"""Which Python runs a project's code, and a managed environment with the code's own dependencies.

`python` at the start of an agent, MCP server or check command means the project's interpreter, found in this order:

1. `python:` in crucible.yaml: an interpreter, or a virtual environment folder;
2. the managed environment AgentCrucible built for this project (`crucible env install`, or Setup → Install);
3. a virtual environment in the repository (.venv, venv, env) that runs on this machine;
4. the interpreter running AgentCrucible.

The managed environment lives outside the repository (CRUCIBLE_ENVS_DIR, default ~/.cache/agentcrucible/envs), sees
AgentCrucible's own packages (so generated adapters import), and gets the repository's requirements on top.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

import agentcrucible

VENV_NAMES = (".venv", "venv", "env")
REQUIREMENTS = ("requirements.txt", "requirements/base.txt", "requirements/prod.txt")


def envs_dir() -> Path:
    return Path(os.environ.get("CRUCIBLE_ENVS_DIR") or Path.home() / ".cache" / "agentcrucible" / "envs")


def managed_env(root: Path) -> Path:
    """The managed environment of the project whose crucible.yaml is in `root`."""
    root = root.resolve()
    slug = re.sub(r"[^\w.-]+", "-", root.parent.name if root.name == "agent-tests" else root.name).strip("-") or "project"
    return envs_dir() / f"{slug}-{hashlib.sha1(str(root).encode()).hexdigest()[:8]}"


def venv_python(venv: Path) -> Path | None:
    """The interpreter of a virtual environment, if it was made for this operating system."""
    for p in ((venv / "Scripts" / "python.exe",) if os.name == "nt" else (venv / "bin" / "python", venv / "bin" / "python3")):
        if p.is_file():
            return p
    return None


def repo_roots(root: Path) -> list[Path]:
    """Where the code lives: the repository an `agent-tests/` folder belongs to, plus each agent's import root."""
    root = root.resolve()
    repo = root.parent if root.name == "agent-tests" else root
    out = [repo]
    f = root / "discovery.json"
    if f.is_file():
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            ids = {fid for a in d.get("agents", []) if a.get("include") for fid in a.get("evidence", [])[:1]}
            for fid in ids:
                ir = ((d.get("facts") or {}).get(fid) or {}).get("attrs", {}).get("import_root")
                if ir and (repo / ir).is_dir() and repo / ir not in out:
                    out.append(repo / ir)
        except (OSError, ValueError):
            pass
    return out


def project_python(cfg: Any) -> tuple[str, str]:
    """(interpreter, where it came from) for a loaded ProjectConfig."""
    root = Path(cfg.root)
    if getattr(cfg, "python", None):
        p = Path(cfg.python)
        p = p if p.is_absolute() else (root / p)
        exe = venv_python(p) if p.is_dir() else p
        if exe and exe.exists():
            return str(exe), "crucible.yaml"
        return str(p), "crucible.yaml (not found)"
    exe = venv_python(managed_env(root))
    if exe:
        return str(exe), "managed environment"
    for base in reversed(repo_roots(root)):  # the most specific folder (a service in a monorepo) first
        for name in VENV_NAMES:
            exe = venv_python(base / name)
            if exe:
                return str(exe), f"{(base / name).as_posix()}"
    return sys.executable, "AgentCrucible's own Python"


def requirements_files(root: Path) -> list[Path]:
    """The dependency files to install: requirements.txt (or pyproject.toml) of each place the agents' code lives."""
    out: list[Path] = []
    for base in reversed(repo_roots(root)):
        hit = next((base / r for r in REQUIREMENTS if (base / r).is_file()), None)
        if hit is None and (base / "pyproject.toml").is_file():
            hit = base / "pyproject.toml"
        if hit and hit not in out:
            out.append(hit)
    return out


def install(root: Path, say: Callable[[str], None] | None = None, files: list[Path] | None = None) -> str:
    """Create (or update) the project's managed environment and install the code's dependencies into it."""
    say = say or (lambda _m: None)
    env = managed_env(root)
    files = files if files is not None else requirements_files(root)
    if not files:
        raise ValueError("No requirements.txt or pyproject.toml found next to the agents' code")
    uv = shutil.which("uv")
    env.parent.mkdir(parents=True, exist_ok=True)
    if venv_python(env) is None:
        say(f"Creating the environment at {env}")
        cmd = [uv, "venv", "--python", sys.executable, str(env)] if uv else [sys.executable, "-m", "venv", str(env)]
        _run(cmd, say)
    exe = venv_python(env)
    if exe is None:
        raise RuntimeError(f"Couldn't create a virtual environment at {env}")
    # AgentCrucible's own packages stay importable (generated adapters use them); the code's pins win, they come first
    site = Path(agentcrucible.__file__).resolve().parent.parent
    sp = next(iter(sorted((env / "lib").glob("python*/site-packages"))), None) if os.name != "nt" else env / "Lib" / "site-packages"
    if sp is not None:
        (sp / "agentcrucible-host.pth").write_text(str(site) + "\n", encoding="utf-8")
    for f in files:
        say(f"Installing {f.name} from {f.parent}")
        if f.name == "pyproject.toml":
            args = ["-e", str(f.parent)]
        else:
            args = ["-r", str(f)]
        cmd = ([uv, "pip", "install", "--python", str(exe), "--index-strategy", "unsafe-best-match", *args] if uv
               else [str(exe), "-m", "pip", "install", *args])
        _run(cmd, say, cwd=f.parent)
    say(f"Ready: {exe}")
    return str(exe)


def _run(cmd: list[str], say: Callable[[str], None], cwd: Path | None = None) -> None:
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            stdin=subprocess.DEVNULL, encoding="utf-8", errors="replace")
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            tail = (tail + [line])[-20:]
            if re.match(r"\s*(Installed|Resolved|Prepared|Successfully|Collecting|error|ERROR)", line):
                say(line[:200])
    if proc.wait() != 0:
        raise RuntimeError("\n".join(tail[-8:]) or f"{cmd[0]} failed")

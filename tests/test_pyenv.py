"""Which Python runs a project's agents, and the managed environment built from the code's requirements."""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from agentcrucible.gateway import split_command
from agentcrucible.pyenv import install, managed_env, project_python, requirements_files

BIN = ("Scripts", "python.exe") if os.name == "nt" else ("bin", "python")


def fake_venv(path: Path) -> Path:
    exe = path.joinpath(*BIN)
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    return exe


def test_interpreter_order(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_ENVS_DIR", str(tmp_path / "envs"))
    repo = tmp_path / "acme"
    tests = repo / "agent-tests"
    tests.mkdir(parents=True)
    cfg = SimpleNamespace(root=tests, python=None)
    assert project_python(cfg) == (sys.executable, "AgentCrucible's own Python")
    repo_venv = fake_venv(repo / ".venv")
    assert project_python(cfg)[0] == str(repo_venv)  # a venv in the repository
    managed = fake_venv(managed_env(tests))
    assert project_python(cfg) == (str(managed), "managed environment")  # beats the repo's
    own = fake_venv(tmp_path / "mine")
    cfg.python = str(tmp_path / "mine")  # crucible.yaml wins, a folder means its venv
    assert project_python(cfg) == (str(own), "crucible.yaml")
    assert split_command("python agent.py", "/x/python")[0] == "/x/python"
    assert split_command("python agent.py")[0] == sys.executable


def test_install_builds_an_environment_that_still_imports_agentcrucible(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_ENVS_DIR", str(tmp_path / "envs"))
    repo = tmp_path / "acme"
    (repo / "agent-tests").mkdir(parents=True)
    (repo / "requirements.txt").write_text("# nothing to install\n")
    assert requirements_files(repo / "agent-tests") == [repo / "requirements.txt"]
    log: list[str] = []
    python = install(repo / "agent-tests", log.append)
    assert Path(python).is_file() and log[-1].startswith("Ready")
    out = subprocess.run([python, "-c", "import sys, agentcrucible.adapters; print(sys.prefix)"],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()).resolve() == managed_env(repo / "agent-tests").resolve()
    assert project_python(SimpleNamespace(root=repo / "agent-tests", python=None))[1] == "managed environment"

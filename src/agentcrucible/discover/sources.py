"""Where the code comes from: a local folder, or a Git URL cloned (shallow, read-only use) into a work folder."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

GIT_URL = re.compile(r"^(https://|http://|ssh://|git@|file://)[^\s]+$")


def is_git_url(s: str) -> bool:
    return bool(GIT_URL.match(s.strip()))


def repo_name(url: str) -> str:
    name = re.sub(r"\.git$", "", url.rstrip("/").split("/")[-1].split(":")[-1])
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name) or "repo"


def clone(url: str, work: Path, ref: str | None = None) -> Path:
    """Shallow-clone `url` into `work/<name>`. Never prompts for credentials; private repos need a configured helper."""
    if not is_git_url(url):
        raise ValueError(f"not a git URL: {url}")
    dest = work / repo_name(url)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--depth", "1", "--quiet"] + (["--branch", ref] if ref else []) + [url, str(dest)]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise RuntimeError(f"git clone failed: {(r.stderr or r.stdout).strip()[:300]}")
    return dest

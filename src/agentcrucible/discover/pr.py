"""Put the approved tests on a branch and open a pull request, instead of leaving them as new files in the working tree.

The commit is built with git plumbing and a temporary index, so the user's working tree, index and current branch are
never touched: `agent-tests/` (and any accepted code changes) go onto a new branch `agentcrucible/tests-<time>` made from
HEAD, which is pushed. With the GitHub CLI (`gh`) logged in, a pull request is opened; otherwise the result carries the
link to open one.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .plan import OUT_DIR
from .schema import Discovery


class PullRequestError(RuntimeError):
    pass


def _repo_top(root: Path) -> Path | None:
    for d in [root, *root.parents]:
        if (d / ".git").exists():
            return d
    return None


def _git(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> str:
    # The repository the user chose may belong to another user (a Docker bind mount, a shared checkout); allow just
    # that one for these commands instead of failing with "dubious ownership". Global git config is not touched.
    top = _repo_top(root)
    safe = ["-c", f"safe.directory={top.as_posix()}"] if top else []
    r = subprocess.run(["git", *safe, *args], cwd=root, capture_output=True, text=True, timeout=120, env=env,
                       stdin=subprocess.DEVNULL)
    if check and r.returncode != 0:
        raise PullRequestError(f"git {args[0]} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def github_repo(url: str) -> str | None:
    """owner/repo for a GitHub remote URL (https or ssh), else None."""
    m = re.match(r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:|ssh://git@github\.com/)([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1) if m else None


def _files(top: Path, out: Path, extra: list[str]) -> list[str]:
    """Repo-relative paths to commit: everything in agent-tests/ except run results, plus changed source files."""
    paths = []
    for p in sorted(out.rglob("*")):
        rel = p.relative_to(out)
        if p.is_file() and rel.parts[0] != ".crucible" and "__pycache__" not in rel.parts:
            paths.append(p.relative_to(top).as_posix())
    for f in extra:
        p = (top / f).resolve()
        if p.is_file() and top in p.parents:
            paths.append(p.relative_to(top).as_posix())
    return sorted(set(paths))


def for_apply(d: Discovery, root: Path, result: dict[str, Any], **kw: Any) -> dict[str, Any]:
    """Open the pull request for what `apply` just wrote (the tests, plus the code changes it applied)."""
    done = set(result.get("code_changes") or [])
    changed = [str(root / fx.file) for p in d.plans for fx in p.fixes if fx.id in done]
    return open_pull_request(root, Path(result["out"]), changed=changed, **kw)


def open_pull_request(root: Path, out: Path | None = None, *, changed: list[str] | None = None, branch: str | None = None,
                      base: str | None = None, remote: str = "origin", push: bool = True, title: str | None = None,
                      body: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    out = (out or root / OUT_DIR).resolve()
    try:
        top = Path(_git(root, "rev-parse", "--show-toplevel")).resolve()
    except (PullRequestError, OSError) as e:
        raise PullRequestError(f"{root} isn't usable as a git repository, so there's nothing to open a pull request on ({e})") from e
    head = _git(top, "rev-parse", "HEAD")
    base = base or _git(top, "rev-parse", "--abbrev-ref", "HEAD")
    if base == "HEAD":
        raise PullRequestError("the repository is on a detached HEAD; check out the branch the pull request should target")
    branch = branch or f"agentcrucible/tests-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}"
    if _git(top, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        raise PullRequestError(f"branch {branch} already exists")
    files = _files(top, out, [str(Path(c)) for c in (changed or [])])
    if not files:
        raise PullRequestError(f"nothing to commit in {out}")

    tmp = Path(tempfile.mkdtemp(prefix="crucible-pr-"))
    env = {**os.environ, "GIT_INDEX_FILE": str(tmp / "index")}
    try:
        _git(top, "read-tree", head, env=env)
        for rel in files:
            blob = _git(top, "hash-object", "-w", "--", rel)
            _git(top, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
        tree = _git(top, "write-tree", env=env)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n_tests = sum(1 for f in files if "/scenarios/" in f)
    title = title or f"Add AgentCrucible tests ({n_tests} scenarios)"
    body = body or (f"Tests drafted by `crucible discover` and approved in review: {len(files)} files under "
                    f"`{out.relative_to(top).as_posix()}/`" + (f" and {len(changed)} accepted code changes" if changed else "")
                    + ".\n\nRun them with `crucible run` from that folder.")
    try:
        commit = _git(top, "commit-tree", tree, "-p", head, "-m", f"{title}\n\n{body}")
    except PullRequestError as e:
        raise PullRequestError(f"{e} (set git user.name and user.email for this repository)") from None
    _git(top, "update-ref", f"refs/heads/{branch}", commit)
    result: dict[str, Any] = {"branch": branch, "base": base, "commit": commit[:12], "files": files, "pushed": False,
                              "pr_url": None, "compare_url": None, "note": None}

    url = _git(top, "remote", "get-url", remote, check=False)
    if not url:
        result["note"] = f"No `{remote}` remote: the branch {branch} is in your local repository; push it to open a pull request."
        return result
    if push:
        r = subprocess.run(["git", "-c", f"safe.directory={top.as_posix()}", "push", remote, f"{branch}:{branch}"], cwd=top,
                           capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            result["note"] = (f"The branch {branch} is ready locally, but pushing it failed: "
                              f"{(r.stderr or r.stdout).strip()[:300]}. Push it yourself: git push {remote} {branch}")
            return result
        result["pushed"] = True
    gh_repo = github_repo(url)
    if gh_repo:
        result["compare_url"] = f"https://github.com/{gh_repo}/compare/{base}...{branch}?expand=1"
        if result["pushed"] and shutil.which("gh"):
            r = subprocess.run(["gh", "pr", "create", "--repo", gh_repo, "--head", branch, "--base", base,
                                "--title", title, "--body", body], cwd=top, capture_output=True, text=True, timeout=120,
                               stdin=subprocess.DEVNULL)
            if r.returncode == 0 and r.stdout.strip().startswith("http"):
                result["pr_url"] = r.stdout.strip().splitlines()[-1]
            else:
                result["note"] = f"`gh pr create` didn't work ({(r.stderr or r.stdout).strip()[:200]}); open it from the link."
        elif result["pushed"]:
            result["note"] = "Open the pull request from the link (install and log in to the GitHub CLI to have it opened for you)."
    elif result["pushed"]:
        result["note"] = f"Pushed {branch} to {remote}; open a pull request there."
    return result

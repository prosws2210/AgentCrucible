"""`crucible discover --apply --pr`: the tests go onto a new pushed branch, the working tree stays as it was."""

import shutil
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from agentcrucible.cli import app as cli
from agentcrucible.discover.pr import PullRequestError, github_repo, open_pull_request

DEMO = Path(__file__).resolve().parent.parent / "examples" / "import-demo"


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--bare", "-q", str(remote))
    repo = tmp_path / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Test User")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "app")
    git(repo, "remote", "add", "origin", str(remote))
    git(repo, "push", "-q", "origin", "main")
    return repo, remote


def test_apply_with_pr_pushes_a_branch_and_leaves_the_working_tree(tmp_path):
    repo, remote = repo_with_remote(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    r = CliRunner().invoke(cli, ["discover", str(repo), "--no-llm", "--apply", "--yes", "--no-smoke", "--pr"])
    assert r.exit_code == 0, r.output
    assert "Branch agentcrucible/tests-" in r.output and "pushed" in r.output
    branch = next(b for b in git(remote, "branch", "--list", "agentcrucible/*").split() if b.startswith("agentcrucible/"))
    files = git(remote, "ls-tree", "-r", "--name-only", branch).splitlines()
    assert "agent-tests/crucible.yaml" in files and any(f.startswith("agent-tests/scenarios/") for f in files)
    assert not any("/.crucible/" in f for f in files)  # run results stay local
    assert git(remote, "rev-parse", f"{branch}~1") == head  # one commit on top of what was checked out
    # the user's checkout is untouched: same branch, same HEAD, nothing staged
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main" and git(repo, "rev-parse", "HEAD") == head
    assert git(repo, "diff", "--cached", "--name-only") == ""


def test_pr_errors_and_github_links(tmp_path):
    (tmp_path / "plain").mkdir()
    try:
        open_pull_request(tmp_path / "plain")
        raise AssertionError("expected an error")
    except PullRequestError as e:
        assert "isn't usable as a git repository" in str(e)
    assert github_repo("https://github.com/prosws2210/AgentCrucible.git") == "prosws2210/AgentCrucible"
    assert github_repo("git@github.com:acme/agents.git") == "acme/agents"
    assert github_repo("https://gitlab.com/acme/agents.git") is None

    repo, _ = repo_with_remote(tmp_path)
    (repo / "agent-tests").mkdir()
    (repo / "agent-tests" / "crucible.yaml").write_text("version: 1\n", encoding="utf-8")
    git(repo, "remote", "remove", "origin")
    r = open_pull_request(repo)
    assert not r["pushed"] and "No `origin` remote" in r["note"] and r["files"] == ["agent-tests/crucible.yaml"]

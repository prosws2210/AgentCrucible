import asyncio
import subprocess
from pathlib import Path

import httpx
import pytest

from agentcrucible.checks import GradeContext, grade
from agentcrucible.config import HelperModel, ProjectConfig, Scenario
from agentcrucible.runner import Runner, RunOptions, rmtree
from agentcrucible.trajectory import Recorder

CALC = Path(__file__).resolve().parent.parent / "examples" / "coding-agent" / "repos" / "calculator"


def make_runner(tmp_path: Path) -> Runner:
    cfg = ProjectConfig.model_validate({"project": "t", "agent": {"command": "python x.py"}})
    cfg.root = tmp_path
    return Runner(cfg, RunOptions(out_root=tmp_path / ".crucible"))


def scenario(workspace: dict, checks: list) -> Scenario:
    return Scenario.model_validate({"id": "s", "task": "t", "environment": {"workspace": workspace}, "checks": checks})


def run_checks(sc: Scenario, ws: Path) -> list:
    async def go():
        async with httpx.AsyncClient() as http:
            return await grade(sc, Recorder("e", "s", 1), GradeContext(dbs={}, judge=HelperModel(), http=http, workspace=ws))
    return asyncio.run(go())


def test_plain_directory_gets_baseline_commit_and_checks(tmp_path):
    runner = make_runner(tmp_path)
    sc = scenario({"path": str(CALC)}, [
        {"state.command": {"run": "python -m pytest", "expect_exit": 0}},
        {"state.git_diff": {"changed": "calc.py", "not_changed": "tests/**", "max_files": 1}},
        {"state.file": {"path": "calc.py", "contains": "1 - percent / 100"}},
    ])
    ws = runner._build_workspace(sc, tmp_path)
    try:
        # untouched repo: the bug makes the tests fail and nothing has changed yet
        before = run_checks(sc, ws)
        assert [r.passed for r in before] == [False, False, False]
        assert "FAILED" in before[0].detail and "changed nothing" in before[1].detail

        # the fix an agent should make
        f = ws / "calc.py"
        f.write_text(f.read_text().replace("price * percent / 100", "price * (1 - percent / 100)"))
        after = run_checks(sc, ws)
        assert [r.passed for r in after] == [True, True, True], [r.detail for r in after]
    finally:
        rmtree(ws)


def test_git_diff_catches_test_tampering_and_deletion(tmp_path):
    runner = make_runner(tmp_path)
    sc = scenario({"path": str(CALC)}, [
        {"state.git_diff": {"not_changed": "tests/**"}},
        {"state.file": {"path": "tests/test_calc.py", "exists": True}},
        {"state.git_diff": {"max_files": 0}},
    ])
    ws = runner._build_workspace(sc, tmp_path)
    try:
        (ws / "tests" / "test_calc.py").unlink()
        (ws / "new_file.py").write_text("x = 1\n")
        results = run_checks(sc, ws)
        assert [r.passed for r in results] == [False, False, False]
        assert "tests/test_calc.py" in results[0].detail
        assert "2 files changed" in results[2].detail
    finally:
        rmtree(ws)


def test_git_repo_source_and_ref(tmp_path):
    src = tmp_path / "repo"
    src.mkdir()
    def git(*a):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *a], cwd=src, check=True, capture_output=True)
    git("init", "-q")
    (src / "a.txt").write_text("v1\n")
    git("add", "-A")
    git("commit", "-qm", "v1")
    git("tag", "v1")
    (src / "a.txt").write_text("v2\n")
    git("commit", "-qam", "v2")

    runner = make_runner(tmp_path)
    (tmp_path / "out").mkdir()  # the runner always passes an existing per-episode temp dir
    ws = runner._build_workspace(scenario({"path": str(src), "ref": "v1"}, []), tmp_path / "out")
    try:
        assert (ws / "a.txt").read_text() == "v1\n"
        (ws / "a.txt").write_text("changed\n")
        sc = scenario({"path": str(src)}, [{"state.git_diff": {"changed": "a.txt", "max_files": 1}}])
        assert run_checks(sc, ws)[0].passed
    finally:
        rmtree(tmp_path / "out")


def test_file_check_is_confined_to_workspace(tmp_path):
    runner = make_runner(tmp_path)
    sc = scenario({"path": str(CALC)}, [{"state.file": {"path": "../../etc/passwd"}}])
    ws = runner._build_workspace(sc, tmp_path)
    try:
        (r,) = run_checks(sc, ws)
        assert not r.passed and "outside the workspace" in r.detail
    finally:
        rmtree(ws)


def test_workspace_checks_need_a_workspace():
    sc = Scenario.model_validate({"id": "s", "task": "t", "checks": [{"state.command": "echo hi"}]})
    (r,) = run_checks(sc, None)  # type: ignore[arg-type]
    assert not r.passed and "environment.workspace" in r.detail


def test_ref_requires_git_repo(tmp_path):
    runner = make_runner(tmp_path)
    with pytest.raises(ValueError):
        runner._build_workspace(scenario({"path": str(CALC), "ref": "main"}, []), tmp_path)

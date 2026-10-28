"""Example MCP server: file and test tools for a coding agent, confined to one workspace.

AgentCrucible gives every episode a fresh copy of the repo via CRUCIBLE_WORKSPACE.
Unlike the support example's servers, this one is written carefully: every path is resolved and
checked against the workspace root, and destructive tools are annotated.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

mcp = FastMCP("workspace")
ROOT = Path(os.environ.get("CRUCIBLE_WORKSPACE") or tempfile.mkdtemp(prefix="workspace-")).resolve()
SKIP = {".git", "__pycache__", ".pytest_cache"}

RelPath = Annotated[str, Field(description="Path relative to the repository root, e.g. 'calc.py' or 'tests/test_calc.py'")]


def _safe(path: str) -> Path:
    p = (ROOT / path).resolve()
    if p != ROOT and ROOT not in p.parents:
        raise ValueError(f"path {path!r} is outside the workspace")
    return p


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def list_files(
    directory: Annotated[str, Field(description="Directory relative to the repository root")] = ".",
) -> list[str]:
    """List all files under a directory of the repository (recursively), as repository-relative paths."""
    base = _safe(directory)
    return sorted(
        p.relative_to(ROOT).as_posix()
        for p in base.rglob("*")
        if p.is_file() and not (set(p.relative_to(ROOT).parts) & SKIP)
    )


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def read_file(path: RelPath) -> str:
    """Return the full text content of a file in the repository."""
    return _safe(path).read_text(encoding="utf-8")


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def write_file(
    path: RelPath,
    content: Annotated[str, Field(description="The complete new content of the file (not a diff)")],
) -> str:
    """Create or overwrite a file in the repository with the given full content."""
    p = _safe(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {path}"


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
def delete_file(path: RelPath) -> str:
    """Delete a file from the repository. Irreversible."""
    p = _safe(path)
    if not p.is_file():
        raise ValueError(f"{path} is not a file")
    p.unlink()
    return f"deleted {path}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def run_tests() -> str:
    """Run the repository's test suite with pytest and return the exit code and the end of the output."""
    try:
        # stdin=DEVNULL: this process's stdin is the MCP protocol pipe; a child must never inherit it
        r = subprocess.run([sys.executable, "-m", "pytest"], cwd=ROOT, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=120,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return "tests timed out after 120s"
    tail = "\n".join(r.stdout.strip().splitlines()[-40:])
    return f"exit code {r.returncode}\n{tail}"


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
def search_code(
    pattern: Annotated[str, Field(description="Regular expression to search for in repository files")],
) -> list[str]:
    """Search all repository files for a regular expression; returns 'path:line: text' matches."""
    rx = re.compile(pattern)
    hits = []
    for rel in list_files("."):
        for i, line in enumerate(_safe(rel).read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if rx.search(line):
                hits.append(f"{rel}:{i}: {line.strip()}")
    return hits[:100]


if __name__ == "__main__":
    mcp.run()

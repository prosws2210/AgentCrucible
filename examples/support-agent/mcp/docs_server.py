"""Example MCP server: help-center articles.

Deliberately has issues for the MCP audit to find: a path-traversal bug in read_document
and a vaguely described, overlapping `find` tool.
"""

import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("docs")
KB = Path(os.environ.get("CRUCIBLE_KB", Path(__file__).resolve().parent.parent / "kb"))


@mcp.tool()
def list_documents() -> list[str]:
    """List the available help-center articles."""
    return sorted(p.name for p in KB.glob("*.md"))


@mcp.tool()
def read_document(path: str) -> str:
    """Read a help-center article, e.g. 'returns.md'."""
    # PLANTED BUG: no containment check, '../' escapes the knowledge-base folder.
    return (KB / path).read_text(encoding="utf-8")


@mcp.tool()
def find(q: str) -> list[str]:
    # PLANTED ISSUE: no description, cryptic param name, overlaps with read_document.
    return [p.name for p in KB.glob("*.md") if q.lower() in p.read_text(encoding="utf-8").lower()]


if __name__ == "__main__":
    mcp.run()

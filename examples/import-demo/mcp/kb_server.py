"""Knowledge-base MCP server for the support team's internal tools."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("knowledge-base")

ARTICLES = {"shipping": "Standard shipping takes 3-5 business days.", "returns": "Returns are accepted within 30 days."}


@mcp.tool()
def list_articles() -> list[str]:
    """List the knowledge-base articles."""
    return sorted(ARTICLES)


@mcp.tool()
def read_article(slug: str) -> str:
    """Read one article by its slug."""
    return ARTICLES.get(slug, "not found")


if __name__ == "__main__":
    mcp.run()

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
from langchain_core.tools import tool

REPORTS_DIR = Path(os.getenv("REPORTS_DIR", "./reports"))
ATOM = "{http://www.w3.org/2005/Atom}"


@tool
def search_arxiv(query: str, max_results: int = 5) -> list[dict]:
    """Search arXiv and return titles, ids and abstracts."""
    r = httpx.get(
        "http://export.arxiv.org/api/query",
        params={"search_query": f"all:{query}", "start": 0, "max_results": max_results},
        timeout=20,
    )
    root = ET.fromstring(r.text)
    return [
        {
            "id": e.findtext(f"{ATOM}id"),
            "title": e.findtext(f"{ATOM}title"),
            "summary": e.findtext(f"{ATOM}summary"),
        }
        for e in root.findall(f"{ATOM}entry")
    ]


@tool
def fetch_paper(arxiv_id: str) -> str:
    """Fetch the HTML full text of an arXiv paper."""
    r = httpx.get(f"https://arxiv.org/html/{arxiv_id}", follow_redirects=True, timeout=30)
    r.raise_for_status()
    return r.text[:60_000]


@tool
def lookup_citation_count(arxiv_id: str) -> int:
    """Return the Semantic Scholar citation count for a paper."""
    r = httpx.get(
        f"https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}",
        params={"fields": "citationCount"},
        timeout=10,
    )
    return r.json().get("citationCount", 0)


@tool
def save_report(filename: str, markdown: str) -> str:
    """Write the final literature review to the reports directory."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / Path(filename).name
    path.write_text(markdown, encoding="utf-8")
    return str(path)


researcher_tools = [search_arxiv, fetch_paper]
writer_tools = [save_report, lookup_citation_count]

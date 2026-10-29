import os

import httpx

from .index import get_query_engine

JIRA_BASE = os.getenv("JIRA_BASE_URL", "https://acme.atlassian.net")
JIRA_AUTH = (os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"])
GITHUB_REPO = os.getenv("GITHUB_REPO", "acme/platform")


def search_docs(question: str) -> str:
    """Answer a question from the internal product documentation index."""
    response = get_query_engine().query(question)
    sources = ", ".join(n.metadata.get("file_name", "?") for n in response.source_nodes)
    return f"{response}\n\nSources: {sources}"


def create_jira_ticket(summary: str, description: str, project_key: str = "DOCS") -> str:
    """Create a Jira issue when the docs are missing or wrong."""
    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": "Task"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}],
            },
        }
    }
    r = httpx.post(f"{JIRA_BASE}/rest/api/3/issue", json=payload, auth=JIRA_AUTH, timeout=15)
    r.raise_for_status()
    return r.json()["key"]


def fetch_release_notes(tag: str = "latest") -> str:
    """Fetch the GitHub release notes body for a tag (or the latest release)."""
    path = "latest" if tag == "latest" else f"tags/{tag}"
    r = httpx.get(
        f"https://api.github.com/repos/{GITHUB_REPO}/releases/{path}",
        headers={"Accept": "application/vnd.github+json"},
        timeout=15,
    )
    r.raise_for_status()
    return r.json().get("body") or ""

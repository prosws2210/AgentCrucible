import sqlite3

import httpx

from . import config

TOOLS = [
    {
        "name": "search_kb",
        "description": "Full-text search over the internal knowledge base. Returns the top article snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_url",
        "description": "Download a web page the customer linked to and return its text.",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "format": "uri"}},
            "required": ["url"],
        },
    },
    {
        "name": "create_ticket",
        "description": "Open a support ticket for follow-up by a human.",
        "input_schema": {
            "type": "object",
            "properties": {
                "customer_email": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
            },
            "required": ["customer_email", "subject", "body"],
        },
    },
    {
        "name": "notify_oncall",
        "description": "Page the on-call engineer in Slack about an outage.",
        "input_schema": {
            "type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"],
        },
    },
]


def search_kb(query: str, limit: int = 5) -> list[dict]:
    with sqlite3.connect(config.KB_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT a.slug, a.title, snippet(articles_fts, 1, '[', ']', '...', 24) AS snippet "
            "FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid "
            "WHERE articles_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def fetch_url(url: str) -> str:
    resp = httpx.get(url, follow_redirects=True, timeout=15.0, headers={"User-Agent": "helpdesk-bot/1.2"})
    resp.raise_for_status()
    return resp.text[:20_000]


def create_ticket(customer_email: str, subject: str, body: str, priority: str = "normal") -> dict:
    with sqlite3.connect(config.TICKETS_DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO tickets (customer_email, subject, body, priority, status) VALUES (?, ?, ?, ?, 'open')",
            (customer_email, subject, body, priority),
        )
        conn.commit()
        return {"ticket_id": cur.lastrowid}


def notify_oncall(summary: str) -> dict:
    resp = httpx.post(config.SLACK_WEBHOOK_URL, json={"text": f":rotating_light: {summary}"}, timeout=10.0)
    return {"status": resp.status_code}


HANDLERS = {
    "search_kb": search_kb,
    "fetch_url": fetch_url,
    "create_ticket": create_ticket,
    "notify_oncall": notify_oncall,
}

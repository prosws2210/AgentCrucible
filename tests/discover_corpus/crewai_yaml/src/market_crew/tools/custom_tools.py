import os
import sqlite3
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from crewai.tools import tool

SALES_DB = os.getenv("SALES_DB", "data/sales.sqlite3")


@tool("Fetch Competitor Page")
def fetch_competitor_page(url: str) -> str:
    """Download a competitor web page and return its visible text."""
    resp = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (market-crew)"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text(" ", strip=True)[:15000]


@tool("Sales Lookup")
def sales_lookup(segment: str, quarter: str) -> str:
    """Return won/lost deal counts and revenue for a customer segment in a quarter like 2026-Q2."""
    with sqlite3.connect(SALES_DB) as conn:
        rows = conn.execute(
            "SELECT outcome, loss_reason, COUNT(*), SUM(amount_usd) FROM deals "
            "WHERE segment = ? AND fiscal_quarter = ? GROUP BY outcome, loss_reason",
            (segment, quarter),
        ).fetchall()
    return "\n".join(f"{o} | {r or '-'} | {n} deals | ${amt:,.0f}" for o, r, n, amt in rows)


@tool("Save Report")
def save_report(title: str, markdown: str) -> str:
    """Save a markdown report to the shared reports folder."""
    out = Path("output") / f"{date.today():%Y%m%d}-{title.lower().replace(' ', '-')}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(markdown, encoding="utf-8")
    return f"saved to {out}"

import os
import sqlite3

import httpx

ALPHAVANTAGE_KEY = os.environ["ALPHAVANTAGE_API_KEY"]
WATCHLIST_DB = os.getenv("WATCHLIST_DB", "watchlist.db")
SEC_HEADERS = {"User-Agent": "acme-research research@acme.example"}

TOOLS = [
    {
        "type": "function",
        "name": "get_stock_quote",
        "description": "Get the latest price and daily change for a ticker symbol.",
        "parameters": {
            "type": "object",
            "properties": {"symbol": {"type": "string", "description": "e.g. MSFT"}},
            "required": ["symbol"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "fetch_filing",
        "description": "Download the text of the most recent SEC filing of a given form type for a company CIK.",
        "parameters": {
            "type": "object",
            "properties": {
                "cik": {"type": "string"},
                "form": {"type": "string", "enum": ["10-K", "10-Q", "8-K"]},
            },
            "required": ["cik", "form"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "save_watchlist_note",
        "description": "Save an analyst note about a ticker to the team watchlist.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "note": {"type": "string"},
            },
            "required": ["symbol", "note"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def get_stock_quote(symbol: str) -> dict:
    r = httpx.get(
        "https://www.alphavantage.co/query",
        params={"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": ALPHAVANTAGE_KEY},
        timeout=10,
    )
    r.raise_for_status()
    q = r.json().get("Global Quote", {})
    return {"symbol": symbol, "price": q.get("05. price"), "change_pct": q.get("10. change percent")}


def fetch_filing(cik: str, form: str) -> str:
    padded = cik.zfill(10)
    subs = httpx.get(f"https://data.sec.gov/submissions/CIK{padded}.json", headers=SEC_HEADERS, timeout=15).json()
    recent = subs["filings"]["recent"]
    for idx, f in enumerate(recent["form"]):
        if f == form:
            accession = recent["accessionNumber"][idx].replace("-", "")
            doc = recent["primaryDocument"][idx]
            url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession}/{doc}"
            return httpx.get(url, headers=SEC_HEADERS, timeout=30).text[:40_000]
    return f"no {form} filing found for CIK {cik}"


def save_watchlist_note(symbol: str, note: str) -> dict:
    with sqlite3.connect(WATCHLIST_DB) as db:
        db.execute(
            "INSERT INTO notes (symbol, body, created_at) VALUES (?, ?, datetime('now'))",
            (symbol.upper(), note),
        )
    return {"saved": True}


DISPATCH = {
    "get_stock_quote": get_stock_quote,
    "fetch_filing": fetch_filing,
    "save_watchlist_note": save_watchlist_note,
}

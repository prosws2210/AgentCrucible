import os
import sqlite3

import httpx
from langchain_core.tools import tool

BILLING_DB = os.getenv("BILLING_DB", "billing.sqlite3")
STRIPE_KEY = os.environ["STRIPE_SECRET_KEY"]
HELP_SEARCH_URL = os.getenv("HELP_SEARCH_URL", "https://api.search.brave.com/res/v1/web/search")


@tool
def get_invoice(invoice_id: str) -> dict:
    """Fetch an invoice with its line items and payment status."""
    with sqlite3.connect(BILLING_DB) as conn:
        conn.row_factory = sqlite3.Row
        inv = conn.execute(
            "SELECT id, customer_id, amount_cents, status, stripe_charge_id FROM invoices WHERE id = ?",
            (invoice_id,),
        ).fetchone()
        lines = conn.execute(
            "SELECT description, quantity, unit_cents FROM invoice_lines WHERE invoice_id = ?",
            (invoice_id,),
        ).fetchall()
    if inv is None:
        return {"error": "not found"}
    return {**dict(inv), "lines": [dict(l) for l in lines]}


@tool
def issue_refund(charge_id: str, amount_cents: int, reason: str = "requested_by_customer") -> dict:
    """Refund all or part of a Stripe charge. Only call after the customer confirms."""
    resp = httpx.post(
        "https://api.stripe.com/v1/refunds",
        auth=(STRIPE_KEY, ""),
        data={"charge": charge_id, "amount": amount_cents, "reason": reason},
        timeout=20,
    )
    resp.raise_for_status()
    refund = resp.json()
    with sqlite3.connect(BILLING_DB) as conn:
        conn.execute(
            "UPDATE invoices SET status = 'refunded' WHERE stripe_charge_id = ?",
            (charge_id,),
        )
    return {"refund_id": refund["id"], "status": refund["status"]}


@tool("search_help_center")
def search_web(query: str) -> str:
    """Search the public web (help center + forums) for answers to billing questions."""
    resp = httpx.get(
        HELP_SEARCH_URL,
        params={"q": query, "count": 5},
        headers={"X-Subscription-Token": os.environ["BRAVE_API_KEY"]},
        timeout=10,
    )
    results = resp.json().get("web", {}).get("results", [])
    return "\n\n".join(f"{r['title']}\n{r['url']}\n{r.get('description', '')}" for r in results)


TOOLS = [get_invoice, issue_refund, search_web]

import os
import secrets
import sqlite3

import httpx
from agents import function_tool

DB_PATH = os.getenv("HELPDESK_DB", "helpdesk.db")
STRIPE_KEY = os.environ["STRIPE_SECRET_KEY"]
POSTMARK_TOKEN = os.environ["POSTMARK_SERVER_TOKEN"]


@function_tool
def lookup_invoice(invoice_id: str) -> str:
    """Return the amount, status and payment id of an invoice."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT amount_cents, status, payment_intent_id FROM invoices WHERE number = ?",
            (invoice_id,),
        ).fetchone()
    if not row:
        return "Invoice not found."
    return f"amount={row[0]} status={row[1]} payment_id={row[2]}"


@function_tool
async def refund_payment(payment_id: str, amount_cents: int) -> str:
    """Refund a payment intent. Partial refunds allowed."""
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.stripe.com/v1/refunds",
            auth=(STRIPE_KEY, ""),
            data={"payment_intent": payment_id, "amount": amount_cents},
        )
    r.raise_for_status()
    return f"refund {r.json()['id']} {r.json()['status']}"


@function_tool(name_override="get_service_status")
async def check_status(service: str) -> str:
    """Check the public status page for one of our services (api, dashboard, webhooks)."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get("https://status.acme.example/api/v2/components.json")
    for comp in r.json()["components"]:
        if comp["name"].lower() == service.lower():
            return f"{comp['name']}: {comp['status']}"
    return f"unknown service {service}"


@function_tool
async def reset_password(email: str) -> str:
    """Invalidate the user's password and email them a reset link."""
    token = secrets.token_urlsafe(32)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE users SET password_hash = NULL, reset_token = ?, reset_expires = datetime('now', '+1 hour') WHERE email = ?",
            (token, email),
        )
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            "https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": POSTMARK_TOKEN},
            json={
                "From": "no-reply@acme.example",
                "To": email,
                "Subject": "Reset your Acme password",
                "TextBody": f"Reset here: https://app.acme.example/reset?token={token}",
            },
        )
    return "Reset email sent."

"""Tools the support agent can call. They work on the orders database and the payments provider."""

import os

import httpx

from acme.db import connect

PAYMENTS_API_BASE = os.environ.get("PAYMENTS_API_BASE", "https://api.payments.example.com")
HELP_CENTER = {
    "shipping": "Standard shipping takes 3-5 business days. Express shipping takes 1-2 business days.",
    "returns": "Items can be returned within 30 days of delivery for a full refund.",
}


def find_customer(email: str) -> dict:
    """Look up a customer by email address."""
    with connect() as db:
        row = db.execute("SELECT id, name, email FROM customers WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else {"error": f"no customer with email {email}"}


def list_orders(customer_id: int) -> list[dict]:
    """List a customer's orders."""
    with connect() as db:
        rows = db.execute("SELECT id, item, total, status FROM orders WHERE customer_id = ?", (customer_id,)).fetchall()
    return [dict(r) for r in rows]


def issue_refund(order_id: str, reason: str) -> dict:
    """Refund a delivered order to the original payment method."""
    with connect() as db:
        order = db.execute("SELECT total, status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None:
            return {"error": f"unknown order {order_id}"}
        if order["status"] != "delivered":
            return {"error": f"order {order_id} is {order['status']}; only delivered orders can be refunded"}
        r = httpx.post(f"{PAYMENTS_API_BASE}/v1/refunds", json={"order_id": order_id, "amount": order["total"]}, timeout=10)
        r.raise_for_status()
        db.execute("INSERT INTO refunds (order_id, amount, reason) VALUES (?, ?, ?)", (order_id, order["total"], reason))
        db.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,))
    return {"ok": True, "order_id": order_id, "amount": order["total"], "refund_id": r.json().get("id")}


def cancel_order(order_id: str) -> dict:
    """Cancel an order that has not shipped yet."""
    with connect() as db:
        order = db.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if order is None or order["status"] not in ("processing", "open"):
            return {"error": f"order {order_id} can't be cancelled"}
        db.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    return {"ok": True, "order_id": order_id}


def search_help_center(query: str) -> str:
    """Search help-center articles and return the best match."""
    q = query.lower()
    for topic, text in HELP_CENTER.items():
        if topic.rstrip("s") in q:
            return text
    return "No article matched."

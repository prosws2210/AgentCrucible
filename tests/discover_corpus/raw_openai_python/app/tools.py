"""Tool implementations + JSON schemas exposed to the support model."""
import sqlite3
from datetime import datetime, timezone

import httpx
from sqlalchemy import text

from .db import SessionLocal
from .settings import settings


def lookup_order(order_id: str) -> dict:
    with SessionLocal() as session:
        row = session.execute(
            text(
                "SELECT id, status, total_cents, currency, shipping_address, created_at "
                "FROM orders WHERE id = :id"
            ),
            {"id": order_id},
        ).mappings().first()
    if row is None:
        return {"error": f"order {order_id} not found"}
    return dict(row)


def update_shipping_address(order_id: str, address: str) -> dict:
    with SessionLocal.begin() as session:
        result = session.execute(
            text(
                "UPDATE orders SET shipping_address = :addr, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = :id AND status = 'pending'"
            ),
            {"addr": address, "id": order_id},
        )
    return {"updated": result.rowcount == 1}


def cancel_order(order_id: str, reason: str) -> dict:
    with SessionLocal.begin() as session:
        result = session.execute(
            text("UPDATE orders SET status = 'cancelled' WHERE id = :id AND status IN ('pending', 'paid')"),
            {"id": order_id},
        )
        session.execute(
            text("INSERT INTO order_events (order_id, kind, note) VALUES (:id, 'cancelled', :reason)"),
            {"id": order_id, "reason": reason},
        )
    return {"cancelled": result.rowcount == 1}


def get_exchange_rate(base: str, quote: str) -> dict:
    resp = httpx.get(
        f"{settings.fx_api_base}/latest",
        params={"from": base.upper(), "to": quote.upper()},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"base": base, "quote": quote, "rate": data["rates"][quote.upper()]}


def log_feedback(order_id: str, rating: int, comment: str = "") -> dict:
    conn = sqlite3.connect(settings.feedback_db_path)
    try:
        conn.execute(
            "INSERT INTO feedback (order_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
            (order_id, rating, comment, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "Look up an order by its id and return status, total and address.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_shipping_address",
            "description": "Change the shipping address of a pending order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "address": {"type": "string", "description": "Full postal address"},
                },
                "required": ["order_id", "address"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_order",
            "description": "Cancel an order that has not shipped yet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_exchange_rate",
            "description": "Get the current FX rate between two ISO currency codes.",
            "parameters": {
                "type": "object",
                "properties": {"base": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["base", "quote"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_feedback",
            "description": "Record a customer satisfaction rating for an order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "rating": {"type": "integer", "minimum": 1, "maximum": 5},
                    "comment": {"type": "string"},
                },
                "required": ["order_id", "rating"],
            },
        },
    },
]

AVAILABLE_FUNCTIONS = {
    "lookup_order": lookup_order,
    "update_shipping_address": update_shipping_address,
    "cancel_order": cancel_order,
    "get_exchange_rate": get_exchange_rate,
    "log_feedback": log_feedback,
}

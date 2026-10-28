"""Example MCP server: an online shop backed by SQLite.

AgentCrucible gives every episode a fresh copy of the database via CRUCIBLE_DB.
It contains one deliberately planted bug for the MCP audit to find (see get_order).
"""

import os
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("shop")
DB = os.environ.get("CRUCIBLE_DB", "shop.db")


def _q(sql: str, args: tuple = (), write: bool = False) -> list[dict]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
        if write:
            conn.commit()
        return rows
    finally:
        conn.close()


@mcp.tool()
def find_customer(email: str) -> dict:
    """Look up a customer by email address. Returns the customer's id, name and email."""
    rows = _q("SELECT * FROM customers WHERE lower(email) = lower(?)", (email,))
    return rows[0] if rows else {"error": f"no customer with email {email}"}


@mcp.tool()
def list_orders(customer_id: int) -> list[dict]:
    """List all orders of a customer (id, item, total, status, placed_on), newest first."""
    return _q("SELECT * FROM orders WHERE customer_id = ? ORDER BY placed_on DESC", (customer_id,))


@mcp.tool()
def get_order(order_id: str) -> dict:
    """Get one order by its id, e.g. 'A-1042'."""
    # PLANTED BUG: string-formatted SQL (injectable) and no not-found handling.
    rows = _q(f"SELECT * FROM orders WHERE id = '{order_id}'")
    return rows[0]


@mcp.tool()
def issue_refund(order_id: str, reason: str) -> dict:
    """Refund a delivered order in full. Irreversible. Only call after the customer has confirmed."""
    rows = _q("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not rows:
        return {"ok": False, "error": f"order {order_id} not found"}
    order = rows[0]
    if order["status"] == "refunded":
        return {"ok": False, "error": f"order {order_id} was already refunded"}
    if order["status"] != "delivered":
        return {"ok": False, "error": f"order {order_id} is {order['status']}; only delivered orders can be refunded"}
    _q("INSERT INTO refunds (order_id, amount, reason) VALUES (?, ?, ?)", (order_id, order["total"], reason), write=True)
    _q("UPDATE orders SET status = 'refunded' WHERE id = ?", (order_id,), write=True)
    return {"ok": True, "order_id": order_id, "amount": order["total"], "eta": "5-7 business days"}


@mcp.tool()
def cancel_order(order_id: str) -> dict:
    """Cancel an order that has not shipped yet (status 'processing')."""
    rows = _q("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not rows:
        return {"ok": False, "error": f"order {order_id} not found"}
    if rows[0]["status"] != "processing":
        return {"ok": False, "error": f"order {order_id} is {rows[0]['status']} and can no longer be cancelled"}
    _q("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,), write=True)
    return {"ok": True, "order_id": order_id, "status": "cancelled"}


@mcp.tool()
def search_products(query: str) -> list[dict]:
    """Search the product catalog by name or description."""
    like = f"%{query}%"
    return _q("SELECT * FROM products WHERE name LIKE ? OR description LIKE ?", (like, like))


if __name__ == "__main__":
    mcp.run()

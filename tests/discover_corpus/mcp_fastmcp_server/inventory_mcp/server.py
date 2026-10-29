from mcp.server.fastmcp import FastMCP

from .db import connect

mcp = FastMCP("inventory")


@mcp.tool()
def list_products(category: str | None = None, limit: int = 50) -> list[dict]:
    """List products, optionally filtered by category."""
    with connect() as conn:
        if category:
            rows = conn.execute(
                "SELECT sku, name, category, price_cents FROM products WHERE category = ? ORDER BY name LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sku, name, category, price_cents FROM products ORDER BY name LIMIT ?", (limit,)
            ).fetchall()
    return [dict(r) for r in rows]


@mcp.tool()
def get_stock(sku: str) -> dict:
    """Get on-hand and reserved quantity for a SKU across all warehouses."""
    with connect() as conn:
        row = conn.execute(
            "SELECT sku, SUM(on_hand) AS on_hand, SUM(reserved) AS reserved FROM stock WHERE sku = ? GROUP BY sku",
            (sku,),
        ).fetchone()
    return dict(row) if row else {"sku": sku, "on_hand": 0, "reserved": 0}


@mcp.tool()
def adjust_stock(sku: str, warehouse: str, delta: int, reason: str) -> dict:
    """Add or remove units of a SKU in a warehouse and record the movement."""
    with connect() as conn:
        conn.execute(
            "UPDATE stock SET on_hand = on_hand + ? WHERE sku = ? AND warehouse = ?",
            (delta, sku, warehouse),
        )
        conn.execute(
            "INSERT INTO stock_movements (sku, warehouse, delta, reason, created_at) VALUES (?, ?, ?, ?, datetime('now'))",
            (sku, warehouse, delta, reason),
        )
    return {"ok": True, "sku": sku, "delta": delta}


@mcp.tool()
def delete_product(sku: str) -> str:
    """Permanently delete a product and all of its stock rows."""
    with connect() as conn:
        conn.execute("DELETE FROM stock WHERE sku = ?", (sku,))
        cur = conn.execute("DELETE FROM products WHERE sku = ?", (sku,))
    return f"deleted {cur.rowcount} product(s)"


if __name__ == "__main__":
    mcp.run()

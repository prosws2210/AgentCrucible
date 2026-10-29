import { tool } from "ai";
import { sql } from "@vercel/postgres";
import { z } from "zod";

const SHIPPO_TOKEN = process.env.SHIPPO_API_TOKEN!;

export const searchProductsTool = tool({
  description: "Search the product catalog by keyword and optional max price.",
  inputSchema: z.object({
    query: z.string().describe("Search keywords"),
    maxPrice: z.number().optional(),
  }),
  execute: async ({ query, maxPrice }) => {
    const { rows } = await sql`
      SELECT id, name, price_cents, stock
      FROM products
      WHERE to_tsvector('english', name || ' ' || description) @@ plainto_tsquery('english', ${query})
        AND (${maxPrice ?? null}::int IS NULL OR price_cents <= ${maxPrice ? maxPrice * 100 : null})
      LIMIT 10`;
    return rows;
  },
});

export const getOrderStatusTool = tool({
  description: "Get the fulfilment and carrier tracking status of an order.",
  inputSchema: z.object({ orderId: z.string() }),
  execute: async ({ orderId }) => {
    const { rows } = await sql`SELECT status, carrier, tracking_number FROM orders WHERE id = ${orderId}`;
    if (rows.length === 0) return { error: "order not found" };
    const order = rows[0];
    if (!order.tracking_number) return { status: order.status };
    const res = await fetch(
      `https://api.goshippo.com/tracks/${order.carrier}/${order.tracking_number}`,
      { headers: { Authorization: `ShippoToken ${SHIPPO_TOKEN}` } },
    );
    const track = await res.json();
    return { status: order.status, tracking: track.tracking_status };
  },
});

export const applyDiscountTool = tool({
  description: "Apply a percentage discount code to the shopper's open cart.",
  inputSchema: z.object({
    cartId: z.string(),
    code: z.string(),
  }),
  execute: async ({ cartId, code }) => {
    const { rows } = await sql`SELECT percent_off FROM discount_codes WHERE code = ${code} AND expires_at > now()`;
    if (rows.length === 0) return { applied: false, reason: "invalid or expired code" };
    await sql`UPDATE carts SET discount_code = ${code}, discount_percent = ${rows[0].percent_off} WHERE id = ${cartId}`;
    return { applied: true, percentOff: rows[0].percent_off };
  },
});

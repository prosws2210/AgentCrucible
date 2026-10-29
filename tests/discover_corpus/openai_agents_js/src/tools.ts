import { tool } from "@openai/agents";
import Stripe from "stripe";
import { z } from "zod";

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);
const ORDERS_API = process.env.ORDERS_API_URL ?? "https://orders.internal.acme.example";

export const lookupOrder = tool({
  name: "lookup_order",
  description: "Fetch an order with its items, status and payment intent id.",
  parameters: z.object({ orderId: z.string() }),
  execute: async ({ orderId }) => {
    const res = await fetch(`${ORDERS_API}/v1/orders/${encodeURIComponent(orderId)}`, {
      headers: { Authorization: `Bearer ${process.env.ORDERS_API_TOKEN}` },
    });
    if (res.status === 404) return "Order not found.";
    return JSON.stringify(await res.json());
  },
});

export const issueRefund = tool({
  name: "issue_refund",
  description: "Refund an order's payment, fully or partially (amount in cents).",
  parameters: z.object({
    paymentIntentId: z.string(),
    amountCents: z.number().int().positive().nullable(),
  }),
  execute: async ({ paymentIntentId, amountCents }) => {
    const refund = await stripe.refunds.create({
      payment_intent: paymentIntentId,
      ...(amountCents ? { amount: amountCents } : {}),
    });
    return `Refund ${refund.id} is ${refund.status}.`;
  },
});

export const emailCustomer = tool({
  name: "email_customer",
  description: "Send the customer an email confirming what was done.",
  parameters: z.object({ to: z.string(), subject: z.string(), body: z.string() }),
  execute: async ({ to, subject, body }) => {
    const res = await fetch("https://api.postmarkapp.com/email", {
      method: "POST",
      headers: {
        "X-Postmark-Server-Token": process.env.POSTMARK_TOKEN!,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ From: "orders@acme.example", To: to, Subject: subject, TextBody: body }),
    });
    return res.ok ? "sent" : `failed: ${res.status}`;
  },
});

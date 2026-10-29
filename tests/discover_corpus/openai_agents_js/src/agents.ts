import { Agent } from "@openai/agents";
import { emailCustomer, issueRefund, lookupOrder } from "./tools";

export const refundAgent = new Agent({
  name: "Refund Agent",
  handoffDescription: "Handles refund requests once the order has been identified.",
  instructions:
    "Confirm the refund amount with the customer, issue the refund, then email them a confirmation.",
  model: "gpt-4.1",
  tools: [issueRefund, emailCustomer],
});

export const frontDesk = Agent.create({
  name: "Front Desk",
  instructions:
    "Greet the customer and look up their order. If they want money back, hand off to the Refund Agent.",
  model: "gpt-4.1-mini",
  tools: [lookupOrder],
  handoffs: [refundAgent],
});

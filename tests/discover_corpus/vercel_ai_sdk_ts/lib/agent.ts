import { generateText, stepCountIs } from "ai";
import { openai } from "@ai-sdk/openai";
import { applyDiscountTool, getOrderStatusTool, searchProductsTool } from "./tools";

const SYSTEM = `You are the shopping assistant for Lumen Home.
Recommend products from the catalog only. Apply discount codes only when the shopper provides one.`;

export async function answerShopper(question: string, cartId: string) {
  const { text, steps } = await generateText({
    model: openai("gpt-4o"),
    system: SYSTEM,
    prompt: `Cart: ${cartId}\n\n${question}`,
    tools: {
      search_products: searchProductsTool,
      get_order_status: getOrderStatusTool,
      apply_discount: applyDiscountTool,
    },
    stopWhen: stepCountIs(5),
  });
  return { text, toolCalls: steps.flatMap((s) => s.toolCalls) };
}

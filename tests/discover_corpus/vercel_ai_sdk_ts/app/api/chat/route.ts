import { convertToModelMessages, stepCountIs, streamText, type UIMessage } from "ai";
import { openai } from "@ai-sdk/openai";
import { getOrderStatusTool, searchProductsTool } from "@/lib/tools";

export const maxDuration = 30;

export async function POST(req: Request) {
  const { messages }: { messages: UIMessage[] } = await req.json();

  const result = streamText({
    model: openai("gpt-4o-mini"),
    system: "You are Lumen Home's storefront chat. Help shoppers find products and track orders.",
    messages: convertToModelMessages(messages),
    tools: {
      search_products: searchProductsTool,
      get_order_status: getOrderStatusTool,
    },
    stopWhen: stepCountIs(4),
  });

  return result.toUIMessageStreamResponse();
}

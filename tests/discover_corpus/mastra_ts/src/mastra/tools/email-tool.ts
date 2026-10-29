import { createTool } from "@mastra/core/tools";
import { z } from "zod";

export const sendFollowUpEmail = createTool({
  id: "sendFollowUpEmail",
  description: "Send a follow-up email to a prospect from the rep's address.",
  inputSchema: z.object({
    to: z.string().email(),
    subject: z.string(),
    html: z.string(),
  }),
  execute: async ({ context }) => {
    const res = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ from: "sales@acme.example", to: [context.to], subject: context.subject, html: context.html }),
    });
    if (!res.ok) throw new Error(`resend failed: ${res.status}`);
    return { id: (await res.json()).id };
  },
});

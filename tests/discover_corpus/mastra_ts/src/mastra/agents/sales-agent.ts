import { Agent } from "@mastra/core/agent";
import { Memory } from "@mastra/memory";
import { openai } from "@ai-sdk/openai";
import { logActivity, lookupAccount } from "../tools/crm-tools";
import { sendFollowUpEmail } from "../tools/email-tool";

export const salesAgent = new Agent({
  name: "Sales Assistant",
  instructions: `
    You help account executives prepare for and follow up on calls.
    - Always look up the account before drafting anything.
    - Log a CRM note after every call summary.
    - Only send an email when the rep explicitly says "send it".
  `,
  model: openai("gpt-4o-mini"),
  tools: { lookupAccount, logActivity, sendFollowUpEmail },
  memory: new Memory(),
});

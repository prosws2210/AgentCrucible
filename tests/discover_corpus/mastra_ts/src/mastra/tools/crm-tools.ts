import { createTool } from "@mastra/core/tools";
import { z } from "zod";

const HUBSPOT = "https://api.hubapi.com";
const headers = {
  Authorization: `Bearer ${process.env.HUBSPOT_PRIVATE_APP_TOKEN}`,
  "Content-Type": "application/json",
};

export const lookupAccount = createTool({
  id: "lookupAccount",
  description: "Look up a company in the CRM by domain and return owner, stage and ARR.",
  inputSchema: z.object({ domain: z.string() }),
  outputSchema: z.object({ id: z.string(), name: z.string(), stage: z.string().nullable(), arr: z.number().nullable() }),
  execute: async ({ context }) => {
    const res = await fetch(`${HUBSPOT}/crm/v3/objects/companies/search`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        filterGroups: [{ filters: [{ propertyName: "domain", operator: "EQ", value: context.domain }] }],
        properties: ["name", "lifecyclestage", "annualrevenue"],
      }),
    });
    const { results } = await res.json();
    const c = results[0];
    return {
      id: c.id,
      name: c.properties.name,
      stage: c.properties.lifecyclestage ?? null,
      arr: c.properties.annualrevenue ? Number(c.properties.annualrevenue) : null,
    };
  },
});

export const logActivity = createTool({
  id: "logActivity",
  description: "Log a call or meeting note against a CRM company.",
  inputSchema: z.object({ companyId: z.string(), note: z.string() }),
  execute: async ({ context }) => {
    const res = await fetch(`${HUBSPOT}/crm/v3/objects/notes`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        properties: { hs_note_body: context.note, hs_timestamp: new Date().toISOString() },
        associations: [
          { to: { id: context.companyId }, types: [{ associationCategory: "HUBSPOT_DEFINED", associationTypeId: 190 }] },
        ],
      }),
    });
    return { noteId: (await res.json()).id };
  },
});

#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { gh, repoPath } from "./github.js";

const server = new McpServer({ name: "github-helper", version: "0.4.0" });

server.tool(
  "search_issues",
  "Search issues and pull requests in a repository",
  { repo: z.string().describe("owner/name"), query: z.string(), state: z.enum(["open", "closed", "all"]).optional() },
  async ({ repo, query, state }) => {
    const q = encodeURIComponent(`repo:${repo} ${query}${state && state !== "all" ? ` state:${state}` : ""}`);
    const data = await gh(`/search/issues?q=${q}&per_page=20`);
    const text = data.items
      .map((i: any) => `#${i.number} [${i.state}] ${i.title}\n${(i.body ?? "").slice(0, 400)}`)
      .join("\n\n");
    return { content: [{ type: "text", text: text || "No results." }] };
  },
);

server.tool(
  "fetch_readme",
  "Get the README of a repository as markdown",
  { repo: z.string() },
  async ({ repo }) => {
    const data = await gh(`${repoPath(repo)}/readme`);
    const markdown = Buffer.from(data.content, "base64").toString("utf8");
    return { content: [{ type: "text", text: markdown }] };
  },
);

server.registerTool(
  "create_issue",
  {
    title: "Create issue",
    description: "Open a new issue in a repository",
    inputSchema: { repo: z.string(), title: z.string(), body: z.string().optional(), labels: z.array(z.string()).optional() },
  },
  async ({ repo, title, body, labels }) => {
    const issue = await gh(`${repoPath(repo)}/issues`, {
      method: "POST",
      body: JSON.stringify({ title, body, labels }),
    });
    return { content: [{ type: "text", text: `Created #${issue.number}: ${issue.html_url}` }] };
  },
);

server.registerTool(
  "close_issue",
  {
    title: "Close issue",
    description: "Close an issue, optionally as not planned",
    inputSchema: { repo: z.string(), number: z.number().int(), notPlanned: z.boolean().optional() },
  },
  async ({ repo, number, notPlanned }) => {
    await gh(`${repoPath(repo)}/issues/${number}`, {
      method: "PATCH",
      body: JSON.stringify({ state: "closed", state_reason: notPlanned ? "not_planned" : "completed" }),
    });
    return { content: [{ type: "text", text: `Closed #${number}` }] };
  },
);

const transport = new StdioServerTransport();
await server.connect(transport);

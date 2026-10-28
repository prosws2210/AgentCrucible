"use client";

import { useState } from "react";
import { IconChat, IconCode, IconServer } from "./Icons";

const CASES = [
  {
    key: "support",
    icon: IconChat,
    tab: "Support & operations agents",
    title: "Agents that take actions for customers",
    body: "Refunds, cancellations, account changes. A simulated customer plays out the conversation, and AgentCrucible checks the database afterwards, not just what the agent said.",
    checks: [
      "The refund row exists, and only after the customer confirmed",
      "Never touched another customer's order",
      "Ignored instructions hidden in product data",
      "Stayed under the tool-call and token budget",
    ],
    result: "In our example, a one-line prompt change made the agent obey a prompt injection in 5 of 5 runs. The gate failed the build.",
  },
  {
    key: "coding",
    icon: IconCode,
    tab: "Coding agents",
    title: "Agents that change your code",
    body: "Every attempt gets a fresh copy of your repository. AgentCrucible runs your test suite afterwards and diffs exactly which files the agent touched.",
    checks: [
      "The test suite passes after the change",
      "Tests were not edited to make them pass",
      "Only the expected files changed",
      "Refused to delete the test suite when asked",
    ],
    result: "Asked to delete the test suite, a 3B model didn't delete it, but rewrote the test file in one run and added files to the tests folder in another. Only the diff check caught it.",
  },
  {
    key: "mcp",
    icon: IconServer,
    tab: "MCP server builders",
    title: "The tools your agents depend on",
    body: "Point the audit at any MCP server. It checks the protocol, fuzzes every tool, probes for injection and path traversal, and measures whether a model picks the right tool.",
    checks: [
      "Conformance with the MCP specification",
      "Clear tool names and descriptions",
      "SQL injection, path traversal, SSRF",
      "Latency under concurrent calls",
    ],
    result: "Found the SQL injection and path traversal planted in our example servers in about 2.5 seconds each, and graded a well-built server A.",
  },
];

export function UseCases() {
  const [i, setI] = useState(0);
  const c = CASES[i];
  return (
    <div>
      <div className="flex gap-2 overflow-x-auto pb-1" role="tablist">
        {CASES.map((x, j) => {
          const Icon = x.icon;
          return (
            <button key={x.key} role="tab" aria-selected={i === j} onClick={() => setI(j)}
              className={`flex shrink-0 items-center gap-2 rounded-full border px-4 py-2 text-[13.5px] transition-colors ${i === j ? "border-ember/60 bg-ember/10 text-fg" : "border-line text-mute hover:text-fg"}`}>
              <Icon className="h-4 w-4" /> {x.tab}
            </button>
          );
        })}
      </div>
      <div className="card mt-5 grid gap-8 p-6 sm:p-8 lg:grid-cols-2">
        <div>
          <h3 className="text-2xl font-semibold tracking-tight">{c.title}</h3>
          <p className="mt-3 text-[15px] leading-relaxed text-mute">{c.body}</p>
          <div className="mt-6 rounded-xl border border-ember/30 bg-ember/[0.06] p-4">
            <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-ember">Real result</div>
            <p className="mt-1.5 text-[14px] leading-relaxed text-fg/90">{c.result}</p>
          </div>
        </div>
        <div>
          <div className="mb-3 text-[12px] font-medium uppercase tracking-[0.14em] text-dim">What gets checked</div>
          <ul className="space-y-2.5">
            {c.checks.map((x) => (
              <li key={x} className="flex items-start gap-3 rounded-xl border border-line bg-panel-2/50 px-4 py-3 text-[14px]">
                <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ok/15 text-[11px] text-ok">✓</span>
                {x}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

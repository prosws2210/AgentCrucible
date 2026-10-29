# @agentcrucible/adapters

Drive TypeScript and JavaScript agents from AgentCrucible: Vercel AI SDK, Mastra, OpenAI Agents JS, LangGraph JS
or a plain function. The stdio protocol, tool tracing, and the scenario's mocks, blocked tools and injected text.
No dependencies; Node 18+.

```ts
import { instrumentModule, serveAgent } from "@agentcrucible/adapters";
import * as mod from "./src/agents/support";

instrumentModule(mod);                     // trace (and mock / block) the tools the module exports
serveAgent(mod.supportAgent, "mastra");    // or "generic" for a function (message, history) => reply
```

`crucible discover` writes this adapter for you and puts a copy of the runtime next to it (`agent-tests/adapters/
crucible.ts`), so nothing needs installing. Run with `npx tsx agent-tests/adapters/<agent>.ts`.

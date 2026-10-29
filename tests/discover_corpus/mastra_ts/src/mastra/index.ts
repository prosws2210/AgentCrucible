import { Mastra } from "@mastra/core/mastra";
import { PinoLogger } from "@mastra/loggers";
import { salesAgent } from "./agents/sales-agent";

export const mastra = new Mastra({
  agents: { salesAgent },
  logger: new PinoLogger({ name: "sales-copilot", level: "info" }),
});

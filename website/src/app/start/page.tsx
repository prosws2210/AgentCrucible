import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import { Wizard } from "@/components/Wizard";

export const metadata: Metadata = {
  title: "Get started · AgentCrucible",
  description: "Answer six questions and get a ready-to-run AgentCrucible setup for your agent and MCP servers.",
};

export default function StartPage() {
  return (
    <>
      <Nav />
      <main className="relative flex-1">
        <div className="grid-bg pointer-events-none absolute inset-x-0 top-0 h-96" />
        <div className="relative mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
          <div className="max-w-2xl">
            <div className="font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">Get started</div>
            <h1 className="mt-3 text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
              Connect your agent in <span className="font-serif font-normal italic ember-text">five minutes</span>
            </h1>
            <p className="mt-4 text-[17px] leading-relaxed text-mute">
              Answer six questions. We write your config, a small adapter for your agent and your first test
              scenario. Your agent&apos;s own code stays as it is.
            </p>
          </div>
          <Wizard />
        </div>
      </main>
    </>
  );
}

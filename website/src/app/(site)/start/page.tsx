import type { Metadata } from "next";
import { StartPaths } from "@/components/StartPaths";

export const metadata: Metadata = {
  title: "Get started · AgentCrucible",
  description: "Import your codebase and get tests drafted for every agent, or answer six questions to set up one agent by hand.",
};

export default function StartPage() {
  return (
    <div className="relative">
        <div className="grid-bg pointer-events-none absolute inset-x-0 top-0 h-96" />
        <div className="relative mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
          <div className="max-w-2xl">
            <div className="font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">Get started</div>
            <h1 className="mt-3 text-balance text-4xl font-semibold tracking-tight sm:text-5xl">
              Test your agents in <span className="font-serif font-normal italic ember-text">minutes</span>
            </h1>
            <p className="mt-4 text-[17px] leading-relaxed text-mute">
              Already have a codebase? Import it and AgentCrucible drafts tests for every agent in it. Or set up a single
              agent by hand. Either way, your agent&apos;s own code stays as it is.
            </p>
          </div>
          <StartPaths />
        </div>
    </div>
  );
}

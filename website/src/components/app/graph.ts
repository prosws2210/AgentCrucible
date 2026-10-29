"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { agentHref } from "./agents";

/** Messages the embedded viewer sends when you ask to open something it shows. */
export function useGraphLinks() {
  const router = useRouter();
  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      const m = ev.data as { type?: string; kind?: string; id?: string; agent?: string };
      if (m?.type !== "crucible:open" || !m.id) return;
      if (m.kind === "agent") router.push(agentHref(m.agent ?? m.id.replace(/^agent:/, "")));
      else if (m.kind === "mcp_server") router.push("/dashboard/servers/");
      else router.push("/dashboard/agents/");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [router]);
}


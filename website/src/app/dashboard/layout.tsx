import type { Metadata } from "next";
import { AppShell } from "@/components/app/AppShell";

export const metadata: Metadata = {
  title: "Dashboard · AgentCrucible",
  description: "Run regression tests on your AI agent, compare against baselines and audit MCP servers.",
};

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}

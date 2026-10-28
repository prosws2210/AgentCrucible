import type { Metadata } from "next";
import { Dashboard } from "@/components/Dashboard";
import { Nav } from "@/components/Nav";

export const metadata: Metadata = {
  title: "Dashboard · AgentCrucible",
  description: "Start regression runs, compare against baselines and audit MCP servers.",
};

export default function DashboardPage() {
  return (
    <>
      <Nav />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6">
        <Dashboard />
      </main>
    </>
  );
}

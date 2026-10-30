export const GITHUB = "https://github.com/prosws2210/AgentCrucible";
export const blob = (path: string) => `${GITHUB}/blob/main/${path}`;
export const tree = (path: string) => `${GITHUB}/tree/main/${path}`;

/** URL of a file in /public (plain <a> links don't get the GitHub Pages base path automatically). */
export const asset = (path: string) => `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}${path}`;

/** Marketing-site pages, in nav order. */
export const NAV_LINKS: [string, string][] = [
  ["How it works", "/how-it-works/"],
  ["Use cases", "/use-cases/"],
  ["Demo", "/demo/"],
  ["Features", "/features/"],
  ["Docs", "/docs/"],
  ["FAQ", "/faq/"],
];

/** Latest released version, shown in the footer. Keep in step with src/agentcrucible/__init__.py when releasing. */
export const VERSION = "0.2.0";
export const LINKEDIN = "https://www.linkedin.com/in/shakti-swaroop-sahu/";

/** Web3Forms access key for "Report a bug" (public by design; the inbox it delivers to is not). Empty: reports open a GitHub issue. */
export const BUG_REPORT_KEY = process.env.NEXT_PUBLIC_BUG_REPORT_KEY ?? "";

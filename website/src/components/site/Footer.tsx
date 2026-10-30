import Link from "next/link";
import { asset, blob, GITHUB, LINKEDIN, tree, VERSION } from "@/lib/site";
import { BugReport } from "../BugReport";
import { CopyButton } from "../CopyButton";
import { Logo } from "../Logo";
import { GitHubIcon } from "../Nav";

const INSTALL = `git clone ${GITHUB}.git && cd AgentCrucible && docker compose up`;

const COLUMNS: [string, [string, string][]][] = [
  ["Product", [["How it works", "/how-it-works/"], ["Use cases", "/use-cases/"], ["Demo", "/demo/"], ["Features", "/features/"], ["Compare", "/compare/"]]],
  ["Get started", [["Setup wizard", "/start/"], ["Dashboard", "/dashboard/"], ["Documentation", "/docs/"], ["Quickstart", "/docs/#quickstart"], ["FAQ", "/faq/"]]],
  ["Resources", [["Adoption guide", blob("docs/ADOPTION.md")], ["Results", blob("docs/RESULTS.md")], ["Architecture", blob("docs/ARCHITECTURE.md")], ["Sample report", asset("/sample/comparison-report.html")], ["Changelog", blob("CHANGELOG.md")]]],
  ["Examples & deploy", [["Support agent", tree("examples/support-agent")], ["Coding agent", tree("examples/coding-agent")], ["GitHub Action", blob("action.yml")], ["Docker images", `${GITHUB}/pkgs/container/agentcrucible`], ["Helm chart", tree("deploy/helm/agentcrucible")]]],
];

// external pages and static files are plain links; site routes go through next/link
const isPlain = (href: string) => /^https?:|\.html$/.test(href);

export function Footer() {
  return (
    <footer className="relative mt-auto overflow-hidden border-t border-line/70">
      {/* ember hairline + glow along the top edge */}
      <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-[linear-gradient(90deg,transparent,rgba(255,107,53,0.7),transparent)]" />
      <div className="pointer-events-none absolute -top-40 left-1/2 h-64 w-[720px] max-w-full -translate-x-1/2 rounded-full bg-[radial-gradient(closest-side,rgba(255,107,53,0.12),transparent)]" />

      <div className="relative mx-auto max-w-6xl px-4 pt-14 sm:px-6 sm:pt-16">
        <div className="grid grid-cols-[minmax(0,1fr)] gap-12 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1.6fr)]">
          {/* brand */}
          <div className="max-w-md">
            <Link href="/" aria-label="AgentCrucible home" className="inline-block"><Logo /></Link>
            <p className="mt-4 text-[14.5px] leading-relaxed text-mute">
              Regression testing for AI agents and MCP servers. Catch your agent&apos;s mistakes before your users do.
            </p>
            <div className="mt-5 flex flex-wrap gap-2 text-[12px]">
              <a href={`${GITHUB}/releases/tag/v${VERSION}`} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-panel px-2.5 py-1 text-mute transition-colors hover:border-ember/50 hover:text-fg">
                <span className="h-1.5 w-1.5 rounded-full bg-ok" /> v{VERSION} released
              </a>
              <span className="rounded-full border border-line bg-panel px-2.5 py-1 text-mute">FSL-1.1</span>
              <span className="rounded-full border border-line bg-panel px-2.5 py-1 text-mute">Self-hosted</span>
            </div>
            <div className="mt-6">
              <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">Try it</div>
              <div className="flex items-center gap-2 rounded-xl border border-line bg-panel-2/70 py-1.5 pl-3 pr-1.5">
                <span className="select-none font-mono text-[12.5px] text-ember">$</span>
                <code className="min-w-0 flex-1 truncate font-mono text-[12.5px] text-fg/90" title={INSTALL}>{INSTALL}</code>
                <CopyButton text={INSTALL} />
              </div>
            </div>
          </div>

          {/* links */}
          <nav aria-label="Footer" className="grid grid-cols-2 gap-x-6 gap-y-10 sm:grid-cols-4 [&>*]:min-w-0">
            {COLUMNS.map(([heading, links]) => (
              <div key={heading}>
                <div className="mb-4 text-[13px] font-semibold text-fg">{heading}</div>
                <ul className="space-y-2.5 text-[13.5px]">
                  {links.map(([label, href]) => (
                    <li key={label}>
                      {isPlain(href)
                        ? <a href={href} className="text-mute transition-colors hover:text-fg">{label}</a>
                        : <Link href={href} className="text-mute transition-colors hover:text-fg">{label}</Link>}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </nav>
        </div>

        {/* bottom bar */}
        <div className="mt-14 flex flex-col-reverse gap-4 border-t border-line/70 py-6 text-[12.5px] text-dim sm:flex-row sm:items-center sm:justify-between">
          <div>© {new Date().getFullYear()} Shakti Swaroop Sahu · Source available under the <a href={blob("LICENSE")} className="text-mute hover:text-fg">Functional Source License (FSL-1.1-ALv2)</a></div>
          <div className="flex items-center gap-1">
            <BugReport className="mr-2 text-mute transition-colors hover:text-fg" />
            <a href={GITHUB} aria-label="GitHub" className="rounded-lg p-2 text-mute transition-colors hover:bg-white/5 hover:text-fg"><GitHubIcon className="h-[18px] w-[18px]" /></a>
            <a href={LINKEDIN} aria-label="LinkedIn" className="rounded-lg p-2 text-mute transition-colors hover:bg-white/5 hover:text-fg"><LinkedInIcon className="h-[18px] w-[18px]" /></a>
          </div>
        </div>
      </div>

    </footer>
  );
}

function LinkedInIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden>
      <path d="M20.45 20.45h-3.56v-5.57c0-1.33-.03-3.04-1.85-3.04-1.85 0-2.14 1.45-2.14 2.94v5.67H9.35V9h3.41v1.56h.05c.48-.9 1.64-1.85 3.37-1.85 3.6 0 4.27 2.37 4.27 5.46v6.28zM5.34 7.43a2.06 2.06 0 1 1 0-4.13 2.06 2.06 0 0 1 0 4.13zM7.12 20.45H3.56V9h3.56v11.45zM22.22 0H1.77C.79 0 0 .77 0 1.72v20.56C0 23.23.79 24 1.77 24h20.45c.98 0 1.78-.77 1.78-1.72V1.72C24 .77 23.2 0 22.22 0z" />
    </svg>
  );
}

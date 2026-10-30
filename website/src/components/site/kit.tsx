// Building blocks shared by the marketing pages (home, how it works, use cases, demo, features, docs, faq).
import Link from "next/link";
import { GITHUB } from "@/lib/site";
import { IconArrow } from "../Icons";
import { LogoMark } from "../Logo";
import { GitHubIcon } from "../Nav";

export function Section({ id, children, className = "" }: { id?: string; children: React.ReactNode; className?: string }) {
  return <section id={id} className={`mx-auto w-full max-w-6xl px-4 py-16 sm:px-6 sm:py-20 ${className}`}>{children}</section>;
}

export function Heading({ eyebrow, title, lead, center, className = "" }: {
  eyebrow?: string;
  title: React.ReactNode;
  lead?: React.ReactNode;
  center?: boolean;
  className?: string;
}) {
  return (
    <div className={`mb-10 max-w-3xl ${center ? "mx-auto text-center" : ""} ${className}`}>
      {eyebrow && <div className="mb-4 font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">{eyebrow}</div>}
      <h2 className="text-balance text-3xl font-semibold tracking-tight sm:text-[40px] sm:leading-[1.1]">{title}</h2>
      {lead && <p className="mt-5 text-pretty text-[17px] leading-relaxed text-mute">{lead}</p>}
    </div>
  );
}

export function Serif({ children }: { children: React.ReactNode }) {
  return <span className="font-serif text-[1.08em] font-normal italic tracking-normal">{children}</span>;
}

export function Cta({ href, children, primary }: { href: string; children: React.ReactNode; primary?: boolean }) {
  const cls = primary ? "bg-fg text-ink hover:bg-white" : "border border-line bg-panel text-fg hover:border-ember/60";
  const c = `inline-flex items-center gap-2 rounded-full px-5 py-3 text-[14.5px] font-semibold transition-colors ${cls}`;
  return href.startsWith("http") ? <a href={href} className={c}>{children}</a> : <Link href={href} className={c}>{children}</Link>;
}

/** "Read more" style link to another page. */
export function More({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="group inline-flex items-center gap-1.5 text-[14.5px] font-medium text-ember">
      {children} <IconArrow className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
    </Link>
  );
}

/** Compact title block at the top of an inner page. It flows straight into the content (no divider), and with
 *  `toc` shows an "On this page" index on wide screens, so the header doubles as navigation. */
export function PageHero({ eyebrow, title, lead, toc, children }: {
  eyebrow: string;
  title: React.ReactNode;
  lead: React.ReactNode;
  toc?: [string, string][];
  children?: React.ReactNode;
}) {
  return (
    <div className="relative">
      <div className="grid-bg pointer-events-none absolute inset-x-0 top-0 h-72" />
      <div className={`relative mx-auto grid w-full max-w-6xl items-end gap-10 px-4 pb-2 pt-12 sm:px-6 sm:pt-16 ${toc ? "lg:grid-cols-[minmax(0,1fr)_280px]" : ""}`}>
        <div className="max-w-3xl animate-rise">
          <div className="mb-3 font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">{eyebrow}</div>
          <h1 className="text-balance text-[34px] font-semibold leading-[1.08] tracking-[-0.02em] sm:text-[44px]">{title}</h1>
          <p className="mt-4 max-w-2xl text-pretty text-[16.5px] leading-relaxed text-mute">{lead}</p>
          {children && <div className="mt-6 flex flex-wrap gap-3">{children}</div>}
        </div>
        {toc && (
          <nav aria-label="On this page" className="hidden animate-rise rounded-2xl border border-line bg-panel/70 p-4 backdrop-blur [animation-delay:120ms] lg:block">
            <div className="mb-2 px-2 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">On this page</div>
            <ol className="space-y-0.5 text-[13.5px]">
              {toc.map(([id, label], i) => (
                <li key={id}>
                  <a href={`#${id}`} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-mute transition-colors hover:bg-white/[0.05] hover:text-fg">
                    <span className="w-4 font-mono text-[11px] text-ember">{i + 1}</span>{label}
                  </a>
                </li>
              ))}
            </ol>
          </nav>
        )}
      </div>
    </div>
  );
}

/** A small numbered or icon card used in grids. */
export function Tile({ icon, title, children, className = "" }: { icon?: React.ReactNode; title: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <div className={`card p-6 ${className}`}>
      {icon && <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ember/12 text-ember">{icon}</span>}
      <h3 className={`${icon ? "mt-5" : ""} text-[17px] font-semibold leading-snug tracking-tight`}>{title}</h3>
      <div className="mt-2.5 text-[14.5px] leading-relaxed text-mute">{children}</div>
    </div>
  );
}

export function CtaBand({ title = <>Know your agent works <Serif>before</Serif> you ship it</>, sub = "Five minutes to connect. Free for your own team and running on your own machine." }: {
  title?: React.ReactNode;
  sub?: string;
}) {
  return (
    // own padding (not <Section>): it always follows a section, so a full top padding would double the gap
    <section className="mx-auto w-full max-w-6xl px-4 pb-24 pt-6 sm:px-6">
      <div className="card relative overflow-hidden px-6 py-14 text-center sm:px-12">
        <div className="pointer-events-none absolute inset-x-0 -bottom-32 mx-auto h-64 w-[640px] max-w-full rounded-full bg-[radial-gradient(closest-side,rgba(255,107,53,0.3),transparent)]" />
        <LogoMark className="relative mx-auto h-12 w-12" />
        <h2 className="relative mx-auto mt-6 max-w-2xl text-balance text-3xl font-semibold tracking-tight sm:text-[40px] sm:leading-[1.1]">{title}</h2>
        <p className="relative mx-auto mt-4 max-w-xl text-[16px] text-mute">{sub}</p>
        <div className="relative mt-8 flex flex-wrap justify-center gap-3">
          <Cta href="/start/" primary>Get started free <IconArrow /></Cta>
          <Cta href={GITHUB}><GitHubIcon /> Star on GitHub</Cta>
        </div>
      </div>
    </section>
  );
}

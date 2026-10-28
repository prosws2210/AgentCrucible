"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { GITHUB, NAV_LINKS } from "@/lib/site";
import { IconMenu, IconX } from "./Icons";
import { Logo } from "./Logo";

const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);

export function Nav() {
  const pathname = norm(usePathname() || "/");
  const [open, setOpen] = useState(false);
  const menu = useRef<HTMLDivElement>(null);

  // close the phone menu after navigating, on Escape, or on a click outside it
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    const onClick = (e: MouseEvent) => menu.current && !menu.current.contains(e.target as Node) && setOpen(false);
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [open]);

  const isActive = (href: string) => pathname.startsWith(href);

  return (
    <header className="sticky top-0 z-50 border-b border-line/70 bg-ink/80 backdrop-blur-xl">
      <nav className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <Link href="/" aria-label="AgentCrucible home">
          <Logo />
        </Link>
        <div className="hidden items-center gap-1 text-[13.5px] lg:flex">
          {NAV_LINKS.map(([label, href]) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(href) ? "page" : undefined}
              className={`rounded-full px-3 py-1.5 transition-colors ${isActive(href) ? "bg-white/[0.07] text-fg" : "text-mute hover:text-fg"}`}
            >
              {label}
            </Link>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <a href={GITHUB} className="hidden items-center gap-2 rounded-full px-3 py-1.5 text-[13px] text-mute transition-colors hover:text-fg sm:flex">
            <GitHubIcon /> GitHub
          </a>
          <Link href="/dashboard/" className="hidden rounded-full border border-line bg-panel px-3.5 py-1.5 text-[13px] font-medium transition-colors hover:border-ember/60 sm:block">
            Dashboard
          </Link>
          <Link href="/start/" className="rounded-full bg-fg px-3.5 py-1.5 text-[13px] font-semibold text-ink transition-colors hover:bg-white">
            Get started
          </Link>
          <div ref={menu} className="relative lg:hidden">
            <button
              onClick={() => setOpen((o) => !o)}
              aria-expanded={open}
              aria-label={open ? "Close menu" : "Menu"}
              className="flex items-center rounded-lg p-1.5 text-mute hover:text-fg"
            >
              {open ? <IconX className="h-5 w-5" /> : <IconMenu className="h-5 w-5" />}
            </button>
            {open && (
              <div className="absolute right-0 top-11 w-60 rounded-xl border border-line bg-panel p-2 shadow-2xl shadow-black/60">
                {NAV_LINKS.map(([label, href]) => (
                  <Link
                    key={href}
                    href={href}
                    onClick={() => setOpen(false)}
                    aria-current={isActive(href) ? "page" : undefined}
                    className={`block rounded-lg px-3 py-2 text-[14px] hover:bg-white/5 hover:text-fg ${isActive(href) ? "bg-white/[0.06] text-fg" : "text-mute"}`}
                  >
                    {label}
                  </Link>
                ))}
                <div className="my-1.5 border-t border-line" />
                <Link href="/dashboard/" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 text-[14px] text-mute hover:bg-white/5 hover:text-fg">Dashboard</Link>
                <a href={GITHUB} className="block rounded-lg px-3 py-2 text-[14px] text-mute hover:bg-white/5 hover:text-fg">GitHub</a>
              </div>
            )}
          </div>
        </div>
      </nav>
    </header>
  );
}

export function GitHubIcon({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg viewBox="0 0 16 16" className={className} fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
    </svg>
  );
}

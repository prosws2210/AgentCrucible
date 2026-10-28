"use client";

import { useEffect, useState } from "react";

/** Docs sidebar that highlights the section currently on screen. */
export function DocsToc({ groups }: { groups: [string, [string, string][]][] }) {
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const ids = groups.flatMap(([, items]) => items.map(([id]) => id));
    const els = ids.map((id) => document.getElementById(id)).filter((e): e is HTMLElement => !!e);
    const obs = new IntersectionObserver(
      (entries) => {
        const top = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
        if (top) setActive(top.target.id);
      },
      { rootMargin: "-80px 0px -65% 0px" },
    );
    els.forEach((e) => obs.observe(e));
    return () => obs.disconnect();
  }, [groups]);

  return (
    <nav aria-label="Documentation" className="space-y-6 text-[13.5px]">
      {groups.map(([g, items]) => (
        <div key={g}>
          <div className="mb-2 px-3 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">{g}</div>
          <ul className="space-y-0.5">
            {items.map(([id, label]) => (
              <li key={id}>
                <a
                  href={`#${id}`}
                  aria-current={active === id ? "location" : undefined}
                  className={`block rounded-lg px-3 py-1.5 transition-colors ${active === id ? "bg-white/[0.07] text-fg" : "text-mute hover:text-fg"}`}
                >
                  {label}
                </a>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  );
}

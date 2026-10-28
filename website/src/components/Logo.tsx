export function LogoMark({ className = "h-7 w-7" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <defs>
        <linearGradient id="ac-ember" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#ffb547" />
          <stop offset="1" stopColor="#ff4d2e" />
        </linearGradient>
      </defs>
      {/* molten core */}
      <path d="M9 15.5h14c0 4.2-3.1 7.5-7 7.5s-7-3.3-7-7.5Z" fill="url(#ac-ember)" />
      {/* crucible vessel */}
      <path
        d="M5.5 11.5h21l-2.2 11.2A5 5 0 0 1 19.4 27h-6.8a5 5 0 0 1-4.9-4.3Z"
        fill="none"
        stroke="#f4eee8"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
      {/* heat */}
      <path d="M12 8.5c0-1.6 1.4-1.9 1.4-3.5M16 8.5c0-1.6 1.4-1.9 1.4-3.5M20 8.5c0-1.6 1.4-1.9 1.4-3.5"
        fill="none" stroke="#ff8a4c" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function Logo() {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      <span className="text-[15px] font-semibold tracking-tight">
        Agent<span className="ember-text">Crucible</span>
      </span>
    </span>
  );
}

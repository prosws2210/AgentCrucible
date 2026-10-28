import Link from "next/link";
import { CopyButton } from "./CopyButton";

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <div className={`card ${className}`}>{children}</div>;
}

export function CardHeader({ title, sub, action }: { title: React.ReactNode; sub?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4">
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
        {sub && <p className="mt-0.5 text-[13px] text-mute">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

type Tone = "ok" | "bad" | "warn" | "info" | "mute" | "ember";
const TONE: Record<Tone, string> = {
  ok: "bg-ok/12 text-ok",
  bad: "bg-bad/12 text-bad",
  warn: "bg-warn/12 text-warn",
  info: "bg-info/12 text-info",
  mute: "bg-white/5 text-mute",
  ember: "bg-ember/12 text-ember",
};

export function Badge({ tone = "mute", children, className = "" }: { tone?: Tone; children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 font-mono text-[11px] ${TONE[tone]} ${className}`}>
      {children}
    </span>
  );
}

export function Button({
  children, onClick, href, variant = "primary", disabled, type = "button", className = "", external, title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  href?: string;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
  className?: string;
  external?: boolean;
  title?: string;
}) {
  const styles = {
    primary: "bg-fg text-ink hover:bg-white",
    secondary: "border border-line bg-panel-2 text-fg hover:border-ember/60",
    ghost: "text-mute hover:text-fg",
  }[variant];
  const cls = `inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full px-4 py-2 text-[13.5px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`;
  if (href) {
    return external ? (
      <a href={href} target="_blank" rel="noreferrer" className={cls}>{children}</a>
    ) : (
      <Link href={href} className={cls}>{children}</Link>
    );
  }
  return (
    <button type={type} onClick={onClick} disabled={disabled} title={title} className={cls}>
      {children}
    </button>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "ok" | "bad" | "warn" }) {
  const color = tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : tone === "warn" ? "text-warn" : "text-fg";
  return (
    <div className="card p-4">
      <div className="text-[12px] text-mute">{label}</div>
      <div className={`mt-1 text-[26px] font-semibold tracking-tight tabular-nums ${color}`}>{value}</div>
      {sub && <div className="mt-0.5 text-[12px] text-dim">{sub}</div>}
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon?: React.ReactNode; title: string; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {icon && <div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl border border-line bg-panel-2 text-mute">{icon}</div>}
      <div className="text-[15px] font-semibold">{title}</div>
      {children && <div className="mt-1.5 max-w-md text-[13.5px] leading-relaxed text-mute">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return <span className={`inline-block animate-spin rounded-full border-2 border-current border-r-transparent ${className}`} aria-hidden />;
}

export function Dots({ passed, n }: { passed: number; n: number }) {
  return (
    <span className="inline-flex gap-1" aria-label={`${passed} of ${n} passed`}>
      {Array.from({ length: n }, (_, i) => (
        <span key={i} className={`h-2 w-2 rounded-full ${i < passed ? "bg-ok" : "bg-bad/80"}`} />
      ))}
    </span>
  );
}

export function Code({ code, title, copy = true, wrap = false }: { code: string; title?: string; copy?: boolean; wrap?: boolean }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel-2/60">
      {(title || copy) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2">
          <span className="truncate font-mono text-[11.5px] text-dim">{title}</span>
          {copy && <CopyButton text={code} />}
        </div>
      )}
      <pre className={`code px-4 py-3.5 text-fg/90 ${wrap ? "whitespace-pre-wrap break-words text-[12px]" : "overflow-x-auto"}`}>{code}</pre>
    </div>
  );
}

export function PassRate({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-dim">–</span>;
  const tone = value >= 0.9 ? "text-ok" : value >= 0.6 ? "text-warn" : "text-bad";
  return <span className={`font-mono tabular-nums ${tone}`}>{Math.round(value * 100)}%</span>;
}

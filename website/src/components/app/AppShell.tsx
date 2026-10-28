"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, ApiError, UNAUTHORIZED, type AuthStatus, type Health, type Project, type Role } from "@/lib/api";
import { GITHUB } from "@/lib/site";
import { LogoMark } from "../Logo";
import { IconBook, IconExternal, IconOverview, IconRuns, IconScenarios, IconServer, IconSetup } from "../Icons";
import { Code, Spinner } from "../ui";

type Ctx = {
  project: Project;
  health: Health;
  models: string[];
  refresh: () => Promise<void>;
  /** false for a read-only (viewer) session: hide or disable anything that starts runs or audits */
  canWrite: boolean;
};
const ProjectCtx = createContext<Ctx | null>(null);

export function useProject(): Ctx {
  const c = useContext(ProjectCtx);
  if (!c) throw new Error("useProject outside AppShell");
  return c;
}

const NAV = [
  { href: "/dashboard/", label: "Overview", icon: IconOverview },
  { href: "/dashboard/runs/", label: "Runs", icon: IconRuns },
  { href: "/dashboard/scenarios/", label: "Scenarios", icon: IconScenarios },
  { href: "/dashboard/servers/", label: "MCP servers", icon: IconServer },
  { href: "/dashboard/setup/", label: "Setup", icon: IconSetup },
];

const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = norm(usePathname() || "/dashboard/");
  const [state, setState] = useState<"loading" | "offline" | "login" | "ready">("loading");
  const [project, setProject] = useState<Project | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [auth, setAuth] = useState<AuthStatus | null>(null);

  const refresh = useCallback(async () => {
    try {
      const a = await api<AuthStatus>("/api/auth/status");
      setAuth(a);
      if (!a.authenticated) {
        setState("login");
        return;
      }
      const [h, p] = await Promise.all([api<Health>("/api/health"), api<Project>("/api/project")]);
      setHealth(h);
      setProject(p);
      setState("ready");
      api<{ models: string[] }>("/api/models").then((m) => setModels(m.models)).catch(() => setModels([]));
    } catch (e) {
      if (e instanceof ApiError) setState(e.status === 401 ? "login" : "offline");
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load; state is set after the requests resolve
    refresh();
    const expired = () => setState("login");
    window.addEventListener(UNAUTHORIZED, expired);
    return () => window.removeEventListener(UNAUTHORIZED, expired);
  }, [refresh]);

  const signOut = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    setProject(null);
    setState("login");
  }, []);

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <Sidebar pathname={pathname} project={state === "ready" ? project : null} health={health} models={models}
        role={auth?.required && state === "ready" ? auth.role : null} onSignOut={signOut} />
      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
          {state === "loading" && (
            <div className="flex items-center justify-center gap-3 py-40 text-[13px] text-dim">
              <Spinner /> Connecting to your AgentCrucible server…
            </div>
          )}
          {state === "offline" && <Offline onRetry={refresh} />}
          {state === "login" && <Login onDone={refresh} />}
          {state === "ready" && project && health && (
            <ProjectCtx.Provider value={{ project, health, models, refresh, canWrite: auth?.role !== "viewer" }}>
              {children}
            </ProjectCtx.Provider>
          )}
        </div>
      </main>
    </div>
  );
}

function Sidebar({ pathname, project, health, models, role, onSignOut }: {
  pathname: string;
  project: Project | null;
  health: Health | null;
  models: string[];
  role: Role | null;
  onSignOut: () => void;
}) {
  const modelOk = project ? models.some((m) => m === project.model || m === `${project.model}:latest`) : false;
  const { ref: navRef, update: onNavScroll, mask: navMask } = useNavScroll(pathname);
  return (
    <aside className="border-b border-line bg-panel/60 lg:sticky lg:top-0 lg:flex lg:h-screen lg:w-64 lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r">
      <div className="flex items-center justify-between px-4 py-4 lg:px-5 lg:py-5">
        <Link href="/" className="flex items-center gap-2.5" aria-label="AgentCrucible website">
          <LogoMark className="h-7 w-7" />
          <span className="text-[15px] font-semibold tracking-tight">
            Agent<span className="ember-text">Crucible</span>
          </span>
        </Link>
        {role && (
          <button onClick={onSignOut} className="text-[12.5px] text-mute hover:text-fg lg:hidden" title={role === "viewer" ? "Signed in · read-only" : "Signed in · full access"}>
            Sign out
          </button>
        )}
      </div>

      {project && (
        <div className="mx-4 mb-4 hidden rounded-xl border border-line bg-panel-2/70 p-3 lg:mx-5 lg:block">
          <div className="text-[11px] uppercase tracking-[0.14em] text-dim">Project</div>
          <div className="mt-1 truncate text-[14px] font-semibold">{project.project}</div>
          <div className="mt-2 space-y-1 text-[12px] text-mute">
            <Status ok label={`API · ${health?.db ?? "…"}`} />
            <Status ok={modelOk} label={modelOk ? `Model · ${project.model}` : `Model ${project.model} not found`} />
            {health?.busy && <Status ok warn label="A run is in progress" />}
          </div>
          {role && (
            <div className="mt-3 flex items-center justify-between border-t border-line pt-2.5 text-[12px]">
              <span className="text-mute">{role === "viewer" ? "Signed in · read-only" : "Signed in · full access"}</span>
              <button onClick={onSignOut} className="text-dim hover:text-fg">Sign out</button>
            </div>
          )}
        </div>
      )}

      {/* phones: one scrolling row; the edge fades while more tabs are hidden that way */}
      <nav
        ref={navRef}
        onScroll={onNavScroll}
        style={{ maskImage: navMask, WebkitMaskImage: navMask }}
        className="flex gap-1 overflow-x-auto px-3 pb-3 [scrollbar-width:none] lg:flex-1 lg:flex-col lg:overflow-visible lg:px-3 lg:pb-0 lg:![mask-image:none] [&::-webkit-scrollbar]:hidden"
      >
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/dashboard/" ? pathname === href : pathname.startsWith(href) || (href === "/dashboard/runs/" && pathname.startsWith("/dashboard/run/"));
          return (
            <Link
              key={href}
              href={href}
              data-active={active || undefined}
              className={`flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                active ? "bg-white/[0.07] font-medium text-fg" : "text-mute hover:bg-white/[0.04] hover:text-fg"
              }`}
            >
              <Icon className={`h-4 w-4 ${active ? "text-ember" : ""}`} />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="hidden space-y-1 border-t border-line px-3 py-4 lg:block">
        <a href={`${GITHUB}/blob/main/docs/ADOPTION.md`} target="_blank" rel="noreferrer" className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-mute hover:text-fg">
          <IconBook /> Documentation <IconExternal className="ml-auto h-3.5 w-3.5" />
        </a>
        <Link href="/start/" className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-mute hover:text-fg">
          <IconSetup /> Connect another agent
        </Link>
      </div>
    </aside>
  );
}

/** Keeps the active tab visible in the phone tab row and reports which edges have hidden tabs. */
function useNavScroll(pathname: string) {
  const ref = useRef<HTMLElement>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  const update = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setEdges({ left: el.scrollLeft > 4, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 4 });
  }, []);
  useEffect(() => {
    const el = ref.current;
    const active = el?.querySelector<HTMLElement>("[data-active]");
    if (el && active && el.scrollWidth > el.clientWidth) {
      el.scrollLeft = active.offsetLeft - (el.clientWidth - active.offsetWidth) / 2;
    }
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [pathname, update]);
  const fade = "transparent, black 32px";
  const mask = edges.left || edges.right
    ? `linear-gradient(to right, ${edges.left ? fade : "black, black"}, ${edges.right ? "black calc(100% - 32px), transparent" : "black"})`
    : undefined;
  return { ref, update, mask };
}

function Status({ ok, warn, label }: { ok: boolean; warn?: boolean; label: string }) {
  const c = warn ? "bg-warn" : ok ? "bg-ok" : "bg-bad";
  return (
    <div className="flex items-center gap-2">
      <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${c}`} />
      <span className="truncate">{label}</span>
    </div>
  );
}

function Offline({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="mx-auto max-w-2xl py-10">
      <div className="font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">Dashboard</div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Start your AgentCrucible server</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-mute">
        The dashboard runs on your machine and talks to a small AgentCrucible server next to your agent. Nothing is
        sent to us. Start it once, then reload this page.
      </p>
      <div className="mt-7 space-y-5">
        <Step n={1} title="Full stack with Docker (recommended)" sub="Dashboard, API, Postgres and a local model server.">
          <Code title="terminal" code={`git clone ${GITHUB}.git\ncd AgentCrucible\ndocker compose up --build\n# open http://localhost:8080/dashboard/`} />
        </Step>
        <Step n={2} title="Or just the API, next to your own project" sub="Uses SQLite; pair it with this site in dev mode.">
          <Code title="terminal" code={`cd your-agent-tests        # where crucible.yaml lives\ncrucible serve --port 8000`} />
        </Step>
      </div>
      <div className="mt-8 flex flex-wrap gap-3">
        <button onClick={onRetry} className="rounded-full bg-fg px-5 py-2.5 text-[14px] font-semibold text-ink">
          I&apos;ve started it, retry
        </button>
        <Link href="/start/" className="rounded-full border border-line bg-panel px-5 py-2.5 text-[14px] font-medium hover:border-ember/60">
          New here? Set up your agent
        </Link>
      </div>
    </div>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({ token }) });
      setToken("");
      onDone();
    } catch (err) {
      setError((err as ApiError).status === 401 ? "That token isn't valid for this server." : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-md py-16">
      <div className="font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">Dashboard</div>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-3 text-[14.5px] leading-relaxed text-mute">
        This server is protected with an access token. Ask whoever runs it, or use the value of{" "}
        <code className="font-mono text-[13px] text-fg">CRUCIBLE_API_TOKEN</code> (full access) or{" "}
        <code className="font-mono text-[13px] text-fg">CRUCIBLE_VIEWER_TOKEN</code> (read-only).
      </p>
      <form onSubmit={submit} className="mt-7 space-y-3">
        <label className="block text-[13px] font-medium" htmlFor="token">Access token</label>
        <input
          id="token"
          type="password"
          autoComplete="current-password"
          autoFocus
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="w-full rounded-lg border border-line bg-panel-2 px-3.5 py-2.5 font-mono text-[14px] outline-none focus:border-ember/70"
        />
        {error && <p role="alert" className="text-[13px] text-bad">{error}</p>}
        <button type="submit" disabled={!token.trim() || busy}
          className="inline-flex w-full items-center justify-center gap-2 rounded-full bg-fg px-5 py-2.5 text-[14px] font-semibold text-ink disabled:cursor-not-allowed disabled:opacity-50">
          {busy && <Spinner />} Sign in
        </button>
      </form>
      <p className="mt-5 text-[12.5px] leading-relaxed text-dim">
        You stay signed in on this browser for 30 days. The token goes only to this server, and the browser keeps a session cookie instead of the token.
      </p>
    </div>
  );
}

function Step({ n, title, sub, children }: { n: number; title: string; sub: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-4">
      <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ember/15 font-mono text-[12px] text-ember">{n}</span>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold">{title}</div>
        <div className="mb-3 text-[13px] text-mute">{sub}</div>
        {children}
      </div>
    </div>
  );
}

export function PageHeader({ title, sub, actions }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-7 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[26px] font-semibold tracking-tight">{title}</h1>
        {sub && <p className="mt-1 max-w-2xl text-[14px] leading-relaxed text-mute">{sub}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

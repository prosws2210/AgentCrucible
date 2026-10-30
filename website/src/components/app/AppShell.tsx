"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import {
  api, ApiError, setCurrentProject, UNAUTHORIZED,
  type AuthStatus, type Health, type Project, type ProjectSummary, type Role,
} from "@/lib/api";
import { GITHUB } from "@/lib/site";
import { LogoMark } from "../Logo";
import { IconAgents, IconBook, IconGraph, IconExternal, IconImport, IconOverview, IconPlus, IconRuns, IconScenarios, IconServer, IconSetup } from "../Icons";
import { Code, Spinner } from "../ui";

type Ctx = {
  project: Project;
  /** every test project this server shows; the switcher picks one */
  projects: ProjectSummary[];
  health: Health;
  models: string[];
  refresh: () => Promise<void>;
  /** make another project current (and go to `to`, default: stay on this page) */
  switchProject: (id: string, to?: string) => void;
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
  { href: "/dashboard/", label: "Overview", icon: IconOverview, also: [] as string[] },
  { href: "/dashboard/agents/", label: "Agents", icon: IconAgents, also: ["/dashboard/agent/"] },
  { href: "/dashboard/graph/", label: "Knowledge graph", icon: IconGraph, also: [] },
  { href: "/dashboard/runs/", label: "Runs", icon: IconRuns, also: ["/dashboard/run/"] },
  { href: "/dashboard/scenarios/", label: "Scenarios", icon: IconScenarios, also: [] },
  { href: "/dashboard/servers/", label: "MCP servers", icon: IconServer, also: [] },
  { href: "/dashboard/add/", label: "Add agents", icon: IconImport, also: ["/dashboard/import/"] },
  { href: "/dashboard/setup/", label: "Setup", icon: IconSetup, also: [] },
];

const norm = (p: string) => (p.endsWith("/") ? p : `${p}/`);
const STORE_KEY = "crucible.project";

function savedProject(): string {
  try {
    return new URLSearchParams(window.location.search).get("project") || localStorage.getItem(STORE_KEY) || "";
  } catch {
    return "";
  }
}

// what the last successful load saw, kept for this browser tab only, so the next page opens without "Connecting…"
type Boot = { auth: AuthStatus; projects: ProjectSummary[]; health: Health; project: Project };
const BOOT_KEY = "crucible:boot";

function loadBoot(): Boot | null {
  try {
    const b = JSON.parse(sessionStorage.getItem(BOOT_KEY) || "null") as Boot | null;
    return b && b.project?.id && b.auth?.authenticated ? b : null;
  } catch {
    return null;
  }
}

function saveBoot(b: Boot) {
  try { sessionStorage.setItem(BOOT_KEY, JSON.stringify(b)); } catch {}
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = norm(usePathname() || "/dashboard/");
  const [state, setState] = useState<"loading" | "offline" | "login" | "ready">("loading");
  const [project, setProject] = useState<Project | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  // the connection dropped while a page was open: keep the page (and anything typed) and reconnect behind a banner
  const [lost, setLost] = useState(false);
  const shown = useRef(false);

  const refresh = useCallback(async () => {
    try {
      // two round trips, not three: who's asking, the projects and the server's health together, then the project
      const [a, list, h] = await Promise.all([api<AuthStatus>("/api/auth/status"), api<ProjectSummary[]>("/api/projects"),
        api<Health>("/api/health")]);
      setAuth(a);
      if (!a.authenticated) {
        setState("login");
        return;
      }
      const wanted = savedProject();
      const id = list.find((x) => x.id === wanted && !x.error)?.id ?? list.find((x) => x.home)?.id ?? list[0]?.id ?? "";
      setCurrentProject(id);
      const p = await api<Project>("/api/project");
      setProjects(list);
      setHealth(h);
      setProject(p);
      setState("ready");
      shown.current = true;
      setLost(false);
      saveBoot({ auth: a, projects: list, health: h, project: p });
      api<{ models: string[] }>("/api/models").then((m) => setModels(m.models)).catch(() => setModels([]));
    } catch (e) {
      // a server that's restarting fails with a network error, not an API one: offline either way (it retries itself)
      if (e instanceof ApiError && e.status === 401) setState("login");
      else if (shown.current) setLost(true);
      else setState("offline");
    }
  }, []);

  useEffect(() => {  // while the server is unreachable, keep trying, so a restart doesn't need a manual reload
    if (state !== "offline" && !lost) return;
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [state, lost, refresh]);

  useEffect(() => {
    // a reload or a new page in this tab opens at once from what the last load saw; the requests below refresh it
    const boot = loadBoot();
    if (boot && boot.project.id === (savedProject() || boot.project.id)) {
      setCurrentProject(boot.project.id);
      /* eslint-disable react-hooks/set-state-in-effect -- restoring the last session before the network answers */
      setAuth(boot.auth);
      setProjects(boot.projects);
      setHealth(boot.health);
      setProject(boot.project);
      setState("ready");
      /* eslint-enable react-hooks/set-state-in-effect */
      shown.current = true;
    }
    refresh();
    const expired = () => {
      try { sessionStorage.removeItem(BOOT_KEY); } catch {}
      setState("login");
    };
    window.addEventListener(UNAUTHORIZED, expired);
    return () => window.removeEventListener(UNAUTHORIZED, expired);
  }, [refresh]);

  const router = useRouter();
  const switchProject = useCallback((id: string, to?: string) => {
    try { localStorage.setItem(STORE_KEY, id); } catch {}
    setCurrentProject(id);
    if (to) router.push(to);
    else if (new URLSearchParams(window.location.search).has("project")) router.replace(window.location.pathname);
    refresh();
  }, [refresh, router]);

  const signOut = useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    try { sessionStorage.removeItem(BOOT_KEY); } catch {}
    setProject(null);
    setState("login");
  }, []);

  return (
    <div className="flex min-h-screen flex-col lg:flex-row">
      <Sidebar pathname={pathname} project={state === "ready" ? project : null} projects={projects} health={health} models={models}
        role={auth?.required && state === "ready" ? auth.role : null} onSignOut={signOut} onSwitch={switchProject} />
      <main className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
          {state === "loading" && (
            <div className="flex items-center justify-center gap-3 py-40 text-[13px] text-dim">
              <Spinner /> Connecting to your AgentCrucible server…
            </div>
          )}
          {state === "offline" && <Offline onRetry={refresh} />}
          {lost && state === "ready" && (
            <div role="status" className="mb-4 flex items-center gap-2 rounded-lg border border-warn/40 bg-warn/[0.06] px-3 py-2 text-[12.5px] text-mute">
              <Spinner /> Lost the connection to the server. Reconnecting… nothing on this page is lost.
            </div>
          )}
          {state === "login" && <Login onDone={refresh} />}
          {state === "ready" && project && health && (
            <ProjectCtx.Provider value={{ project, projects, health, models, refresh, switchProject, canWrite: auth?.role !== "viewer" }}>
              {/* keyed: switching projects remounts the page, so it reloads that project's data */}
              <div key={project.id}>{children}</div>
            </ProjectCtx.Provider>
          )}
        </div>
      </main>
    </div>
  );
}

function Sidebar({ pathname, project, projects, health, models, role, onSignOut, onSwitch }: {
  pathname: string;
  project: Project | null;
  projects: ProjectSummary[];
  health: Health | null;
  models: string[];
  role: Role | null;
  onSignOut: () => void;
  onSwitch: (id: string, to?: string) => void;
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
        <div className="mx-4 mb-3 rounded-xl border border-line bg-panel-2/70 p-3 lg:mx-5 lg:mb-4">
          <ProjectSwitcher project={project} projects={projects} onSwitch={onSwitch} />
          <div className="mt-2 hidden space-y-1 text-[12px] text-mute lg:block">
            <Status ok label={`API · ${health?.db ?? "…"}`} />
            <Status ok={modelOk} label={modelOk ? `Model · ${project.model}` : `Model ${project.model} not found`} />
            {health?.busy && <Status ok warn label="A run is in progress" />}
          </div>
          {role && (
            <div className="mt-3 hidden items-center justify-between border-t border-line pt-2.5 text-[12px] lg:flex">
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
        {NAV.map(({ href, label, icon: Icon, also }) => {
          const active = href === "/dashboard/" ? pathname === href : [href, ...also].some((h) => pathname.startsWith(h));
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
        <Link href="/dashboard/projects/" className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] text-mute hover:text-fg">
          <IconOverview /> All projects
        </Link>
      </div>
    </aside>
  );
}

export const SOURCE: Record<string, string> = { server: "server project", import: "imported", manual: "added by hand", added: "added" };

function ProjectSwitcher({ project, projects, onSwitch }: { project: Project; projects: ProjectSummary[]; onSwitch: (id: string, to?: string) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  const n = project.agents.length;
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="listbox"
        className="flex w-full items-center gap-2 rounded-lg text-left" title="Switch project">
        <span className="min-w-0 flex-1">
          <span className="block text-[11px] uppercase tracking-[0.14em] text-dim">Project</span>
          <span className="block truncate text-[14px] font-semibold">{project.project}</span>
          <span className="block truncate text-[12px] text-mute">{n} agent{n === 1 ? "" : "s"} · {SOURCE[project.source] ?? project.source}</span>
        </span>
        <svg viewBox="0 0 24 24" className={`h-4 w-4 shrink-0 text-dim transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="2"><path d="m7 10 5 5 5-5" /></svg>
      </button>
      {open && (
        <div role="listbox" className="absolute left-0 right-0 top-full z-30 mt-2 overflow-hidden rounded-xl border border-line bg-panel shadow-2xl shadow-black/40">
          <ul className="max-h-72 overflow-y-auto py-1">
            {projects.map((p) => (
              <li key={p.id}>
                <button role="option" aria-selected={p.id === project.id} disabled={!!p.error}
                  onClick={() => { setOpen(false); if (p.id !== project.id) onSwitch(p.id); }}
                  className={`flex w-full items-start gap-2 px-3 py-2 text-left hover:bg-white/[0.05] disabled:opacity-50 ${p.id === project.id ? "bg-white/[0.04]" : ""}`}>
                  <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${p.id === project.id ? "bg-ember" : "bg-transparent"}`} />
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium">{p.name}</span>
                    <span className="block truncate text-[11.5px] text-dim">
                      {p.error ? "crucible.yaml doesn\u2019t load" : `${p.agents.length} agent${p.agents.length === 1 ? "" : "s"} · ${p.scenarios} scenarios · ${SOURCE[p.source] ?? p.source}`}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="border-t border-line p-1">
            <Link href="/dashboard/add/" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-ember hover:bg-white/[0.04]">
              <IconPlus className="h-3.5 w-3.5" /> Add agents or a codebase
            </Link>
            <Link href="/dashboard/projects/" onClick={() => setOpen(false)} className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-mute hover:bg-white/[0.04] hover:text-fg">
              <IconOverview className="h-3.5 w-3.5" /> All projects
            </Link>
          </div>
        </div>
      )}
    </div>
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
          New here? Get started
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

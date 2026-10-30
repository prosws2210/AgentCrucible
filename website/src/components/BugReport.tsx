"use client";

import { useRef, useState } from "react";
import { BUG_REPORT_KEY, GITHUB, VERSION } from "@/lib/site";

type State = { kind: "idle" | "sending" | "sent" } | { kind: "failed"; message: string };

/** The mail's subject: what the maintainer sees in the inbox. */
export const bugSubject = (project: string) => `BUG REPORTED : ${project.trim() || "AgentCrucible"}`;

/** A prefilled GitHub issue: the fallback when the site was built without a form key (GitHub mails the owner too). */
export const issueUrl = (project: string, what: string) =>
  `${GITHUB}/issues/new?${new URLSearchParams({ title: bugSubject(project), body: what, labels: "bug" })}`;

/**
 * "Report a bug": a button that opens a short form. With NEXT_PUBLIC_BUG_REPORT_KEY set at build time the report is
 * mailed through Web3Forms (the key is meant to be public; the address it delivers to is not in the page); without it
 * the form opens a prefilled GitHub issue instead.
 */
export function BugReport({ project = "", className = "", children }: { project?: string; className?: string; children?: React.ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [name, setName] = useState(project);
  const [what, setWhat] = useState("");
  const [email, setEmail] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });

  const open = () => {
    if (!name.trim()) setName(project);  // the dashboard's current project, unless one was typed already
    if (state.kind === "sent") { setWhat(""); setState({ kind: "idle" }); }
    dialog.current?.showModal();
  };
  const close = () => dialog.current?.close();

  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!BUG_REPORT_KEY) {
      window.open(issueUrl(name, what), "_blank", "noopener");
      setState({ kind: "sent" });
      return;
    }
    if ((new FormData(e.currentTarget).get("botcheck") as string | null)) return;  // filled in by a bot, not a person
    setState({ kind: "sending" });
    try {
      const r = await fetch("https://api.web3forms.com/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({
          access_key: BUG_REPORT_KEY,
          subject: bugSubject(name),
          from_name: "AgentCrucible bug report",
          project: name.trim() || "(not given)",
          bug: what,
          ...(email.trim() ? { email: email.trim(), replyto: email.trim() } : {}),
          page: window.location.pathname,
          version: VERSION,
          browser: navigator.userAgent,
        }),
      });
      const body = await r.json().catch(() => ({}));
      if (r.ok && body.success !== false) setState({ kind: "sent" });
      else setState({ kind: "failed", message: body?.body?.message ?? body?.message ?? `the mail service answered ${r.status}` });
    } catch {
      setState({ kind: "failed", message: "couldn't reach the mail service (offline, or blocked by the network)" });
    }
  };

  const field = "w-full rounded-lg border border-line bg-panel-2 px-3 py-2 text-[14px] text-fg outline-none placeholder:text-dim focus:border-ember/60";
  return (
    <>
      <button type="button" onClick={open} className={className}>{children ?? "Report a bug"}</button>
      <dialog
        ref={dialog}
        aria-labelledby="bug-title"
        onClick={(e) => { if (e.target === dialog.current) close(); }}
        className="m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-line bg-panel p-0 text-fg shadow-2xl shadow-black/60 backdrop:bg-black/60 backdrop:backdrop-blur-[2px]"
      >
        {state.kind === "sent" ? (
          <div className="p-6 text-center">
            <div className="mx-auto flex h-11 w-11 items-center justify-center rounded-full bg-ok/15 text-[20px] text-ok">✓</div>
            <h2 className="mt-3 text-[18px] font-semibold">{BUG_REPORT_KEY ? "Thanks, it's on its way" : "Finish it on GitHub"}</h2>
            <p className="mt-1.5 text-[14px] text-mute">
              {BUG_REPORT_KEY
                ? "The report was sent to the maintainer." + (email.trim() ? " You'll get a reply at the address you gave." : "")
                : "A prefilled issue opened in a new tab. Submit it there and the maintainer is notified."}
            </p>
            <button type="button" onClick={close} className="mt-5 rounded-full bg-fg px-5 py-2 text-[13.5px] font-semibold text-ink hover:bg-white">Close</button>
          </div>
        ) : (
          <form onSubmit={submit} className="p-5 sm:p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 id="bug-title" className="text-[18px] font-semibold">Report a bug</h2>
                <p className="mt-1 text-[13.5px] text-mute">Something broken or confusing? Tell us what happened and it goes straight to the maintainer.</p>
              </div>
              <button type="button" onClick={close} aria-label="Close" className="-mr-1 -mt-1 rounded-lg p-1.5 text-mute hover:bg-white/5 hover:text-fg">
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M6 6l12 12M18 6 6 18" /></svg>
              </button>
            </div>
            <label className="mt-5 block text-[13px] font-medium" htmlFor="bug-project">Project</label>
            <input id="bug-project" value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="Your project, or the page you were on" className={`mt-1.5 ${field}`} />
            <label className="mt-4 block text-[13px] font-medium" htmlFor="bug-what">What happened?</label>
            <textarea id="bug-what" required value={what} onChange={(e) => setWhat(e.target.value)} rows={5} maxLength={5000}
              placeholder="What you did, what you expected, and what happened instead. Error messages help." className={`mt-1.5 resize-y ${field}`} />
            <label className="mt-4 block text-[13px] font-medium" htmlFor="bug-email">Your email <span className="font-normal text-dim">(optional, for a reply)</span></label>
            <input id="bug-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" className={`mt-1.5 ${field}`} />
            <input type="checkbox" name="botcheck" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden />
            <p className="mt-3 text-[12px] text-dim">Don&apos;t paste API keys, passwords or customer data. The page you&apos;re on and your browser version are included.</p>
            {state.kind === "failed" && (
              <p className="mt-3 rounded-lg border border-bad/40 bg-bad/[0.07] px-3 py-2 text-[13px] text-bad">
                Not sent: {state.message}. <a href={issueUrl(name, what)} target="_blank" rel="noreferrer" className="underline">Open a GitHub issue instead</a>.
              </p>
            )}
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <button type="button" onClick={close} className="rounded-full px-4 py-2 text-[13.5px] font-semibold text-mute hover:text-fg">Cancel</button>
              <button type="submit" disabled={state.kind === "sending" || !what.trim()}
                className="rounded-full bg-fg px-5 py-2 text-[13.5px] font-semibold text-ink hover:bg-white disabled:cursor-not-allowed disabled:opacity-50">
                {state.kind === "sending" ? "Sending…" : BUG_REPORT_KEY ? "Send report" : "Continue on GitHub"}
              </button>
            </div>
          </form>
        )}
      </dialog>
    </>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { SCENES } from "./scenes";

const W = 960, H = 540; // design size of the stage; scaled to fit like a video

// start time of each scene on the global timeline
const STARTS = SCENES.reduce<number[]>((acc, s, i) => [...acc, i ? acc[i - 1] + SCENES[i - 1].duration : 0], []);
const TOTAL = STARTS[STARTS.length - 1] + SCENES[SCENES.length - 1].duration;
// every caption with its global start and end, in order
const CUES = SCENES.flatMap((s, i) => s.cues.map((c, j) => ({
  text: c.text,
  start: STARTS[i] + c.at,
  end: j + 1 < s.cues.length ? STARTS[i] + s.cues[j + 1].at : STARTS[i] + s.duration,
})));

const fmt = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
/** index of the last item whose start is <= t (-1 if none) */
const lastAtOrBefore = (starts: number[], t: number) => {
  let i = -1;
  while (i + 1 < starts.length && starts[i + 1] <= t) i++;
  return i;
};
const CUE_STARTS = CUES.map((c) => c.start);
const sceneAt = (t: number) => Math.max(0, lastAtOrBefore(STARTS, t));
const cueAt = (t: number) => lastAtOrBefore(CUE_STARTS, t);

/** A narrated product walkthrough, drawn live in the browser: seekable, captioned, with optional spoken narration. */
export function DemoVideo({ chapters = true }: { chapters?: boolean }) {
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [started, setStarted] = useState(false);
  const [captions, setCaptions] = useState(true);
  const [narrate, setNarrate] = useState(false);
  const [scale, setScale] = useState(1);
  const [canSpeak, setCanSpeak] = useState(false);

  const frame = useRef<HTMLDivElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const tRef = useRef(0);
  const speaking = useRef(false);
  const holdSince = useRef<number | null>(null);

  const scene = sceneAt(t);
  const cue = cueAt(t);

  // fit the 960×540 stage to the frame
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setScale(Math.min(e.contentRect.width / W, e.contentRect.height / H)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    // feature check runs after hydration, so the server and first client render agree
    const id = requestAnimationFrame(() => setCanSpeak(typeof window !== "undefined" && "speechSynthesis" in window));
    return () => cancelAnimationFrame(id);
  }, []);

  // the clock
  useEffect(() => {
    if (!playing) return;
    let last = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      let next = tRef.current + dt;
      // with narration on, wait at the end of a caption until the voice has finished it
      const c = cueAt(tRef.current);
      if (narrate && speaking.current && c >= 0 && next >= CUES[c].end) {
        holdSince.current ??= now;
        // some browsers never report the end of speech (e.g. no voices installed): don't wait forever
        if (now - holdSince.current > 6000) speaking.current = false;
        else next = CUES[c].end - 0.001;
      } else holdSince.current = null;
      if (next >= TOTAL) {
        next = TOTAL;
        setPlaying(false);
      }
      tRef.current = next;
      setT(next);
      if (next < TOTAL) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, narrate]);

  // narration: speak each caption as it starts
  useEffect(() => {
    if (!canSpeak) return;
    const synth = window.speechSynthesis;
    synth.cancel();
    speaking.current = false;
    if (!narrate || !playing || cue < 0) return;
    const u = new SpeechSynthesisUtterance(CUES[cue].text);
    u.rate = 1.04;
    const voice = synth.getVoices().find((v) => /en[-_](US|GB)/i.test(v.lang) && /natural|google|samantha|daniel|aria|jenny/i.test(v.name))
      ?? synth.getVoices().find((v) => v.lang.startsWith("en"));
    if (voice) u.voice = voice;
    u.onend = u.onerror = () => { speaking.current = false; };
    speaking.current = true;
    synth.speak(u);
  }, [cue, narrate, playing, canSpeak]);

  useEffect(() => () => { if (typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel(); }, []);

  const seek = useCallback((to: number) => {
    const v = Math.max(0, Math.min(TOTAL - 0.01, to));
    tRef.current = v;
    setT(v);
  }, []);

  const toggle = useCallback(() => {
    setStarted(true);
    if (tRef.current >= TOTAL) seek(0);
    setPlaying((p) => !p);
  }, [seek]);

  const fullscreen = () => {
    const el = shell.current;
    if (!el) return;
    if (document.fullscreenElement) document.exitFullscreen();
    else el.requestFullscreen?.();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === " " || e.key === "k") { e.preventDefault(); toggle(); }
    else if (e.key === "ArrowRight") { e.preventDefault(); seek(tRef.current + 5); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); seek(tRef.current - 5); }
    else if (e.key === "c") setCaptions((c) => !c);
    else if (e.key === "n" && canSpeak) setNarrate((n) => !n);
    else if (e.key === "f") fullscreen();
  };

  const s = SCENES[scene];

  return (
    <div>
      <div
        ref={shell}
        tabIndex={0}
        onKeyDown={onKey}
        aria-label="Product walkthrough video. Space to play or pause, arrow keys to seek, C for captions, N for narration."
        className="group overflow-hidden rounded-2xl border border-line bg-[#0b0908] shadow-2xl shadow-black/60 outline-none focus-visible:ring-2 focus-visible:ring-ember/60 [&:fullscreen]:flex [&:fullscreen]:flex-col [&:fullscreen]:rounded-none"
      >
        {/* stage */}
        <div ref={frame} className="relative aspect-video w-full overflow-hidden [:fullscreen_&]:aspect-auto [:fullscreen_&]:flex-1" onClick={toggle}>
          <div
            className="absolute left-1/2 top-1/2 origin-center bg-ink text-fg"
            style={{ width: W, height: H, transform: `translate(-50%, -50%) scale(${scale})` }}
            aria-hidden
          >
            <div className="grid-bg pointer-events-none absolute inset-0 opacity-60" />
            <div key={s.id} className="absolute inset-0 animate-[rise_0.5s_ease-out_both]">{/* before the first play, show the intro fully drawn as the poster */}{s.render(started ? t - STARTS[scene] : 4)}</div>
            <div className="absolute left-5 top-4 z-40 rounded-full border border-line bg-ink/80 px-3 py-1 font-mono text-[11px] text-mute">
              <span className="text-ember">{scene + 1}/{SCENES.length}</span> · {s.title}
            </div>
          </div>

          {/* captions: real-size text over the scaled stage, so they stay readable on phones */}
          {captions && started && cue >= 0 && (
            <div className="pointer-events-none absolute inset-x-0 bottom-5 hidden justify-center px-3 sm:flex">
              <p className="max-w-3xl rounded-lg bg-black/80 px-3 py-1.5 text-center text-[16px] leading-snug text-white" aria-live="polite">
                {CUES[cue].text}
              </p>
            </div>
          )}

          {/* poster / paused overlay */}
          {!playing && (
            <div className={`absolute inset-0 flex flex-col items-center justify-center gap-3 ${started ? "bg-black/10" : "bg-black/55 backdrop-blur-[2px]"}`}>
              <span className={`flex items-center justify-center rounded-full text-ink shadow-xl transition-transform group-hover:scale-105 ${started ? "h-12 w-12 bg-fg/75 sm:h-14 sm:w-14" : "h-16 w-16 bg-fg sm:h-20 sm:w-20"}`}>
                <PlayIcon className={started ? "ml-0.5 h-5 w-5" : "ml-1 h-7 w-7 sm:h-8 sm:w-8"} />
              </span>
              {!started && (
                <div className="text-center">
                  <div className="text-[15px] font-semibold sm:text-[19px]">AgentCrucible in {fmt(TOTAL)}</div>
                  <div className="text-[12px] text-mute sm:text-[13.5px]">From download to a gated pull request · captions on · narration optional</div>
                </div>
              )}
              {started && t >= TOTAL && <div className="text-[14px] font-medium">Replay</div>}
            </div>
          )}
        </div>

        {/* phones: captions under the picture, where they don't cover it */}
        {captions && started && cue >= 0 && (
          <p className="min-h-[3.6em] border-t border-line bg-black px-3 py-2 text-center text-[13px] leading-snug text-white sm:hidden">{CUES[cue].text}</p>
        )}

        {/* controls */}
        <div className="border-t border-line bg-panel/80 px-3 pb-2.5 pt-2 sm:px-4">
          <Timeline t={t} onSeek={seek} />
          <div className="mt-2 flex items-center gap-1 text-[12.5px] sm:gap-2">
            <Btn onClick={toggle} label={playing ? "Pause" : "Play"}>{playing ? <PauseIcon className="h-4 w-4" /> : <PlayIcon className="h-4 w-4" />}</Btn>
            <span className="font-mono text-[11.5px] tabular-nums text-mute">{fmt(t)} / {fmt(TOTAL)}</span>
            <span className="ml-2 hidden truncate text-mute sm:inline">{s.title}</span>
            <span className="ml-auto" />
            <Btn onClick={() => setCaptions((c) => !c)} label={captions ? "Hide captions" : "Show captions"} active={captions}>
              <span className="font-mono text-[11px] font-semibold">CC</span>
            </Btn>
            {canSpeak && (
              <Btn onClick={() => setNarrate((n) => !n)} label={narrate ? "Turn narration off" : "Turn narration on (your browser's voice)"} active={narrate}>
                <SpeakerIcon className="h-4 w-4" muted={!narrate} /><span className="hidden sm:inline">Narration</span>
              </Btn>
            )}
            <Btn onClick={fullscreen} label="Full screen"><FullIcon className="h-4 w-4" /></Btn>
          </div>
        </div>
      </div>

      {/* chapters */}
      {chapters && <ol className="mt-4 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-4">
        {SCENES.map((sc, i) => (
          <li key={sc.id}>
            <button
              onClick={() => { setStarted(true); seek(STARTS[i]); }}
              className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left text-[13px] transition-colors ${i === scene && started ? "border-ember/50 bg-ember/[0.07] text-fg" : "border-line text-mute hover:border-ember/40 hover:text-fg"}`}
            >
              <span className="font-mono text-[11px] text-ember">{fmt(STARTS[i])}</span>
              <span className="truncate">{sc.title}</span>
            </button>
          </li>
        ))}
      </ol>}
    </div>
  );
}

/** Progress bar split into chapter segments; click or drag to seek. */
function Timeline({ t, onSeek }: { t: number; onSeek: (t: number) => void }) {
  const bar = useRef<HTMLDivElement>(null);
  const at = (clientX: number) => {
    const r = bar.current!.getBoundingClientRect();
    return ((clientX - r.left) / r.width) * TOTAL;
  };
  return (
    <div
      ref={bar}
      role="slider"
      aria-label="Seek"
      aria-valuemin={0}
      aria-valuemax={Math.round(TOTAL)}
      aria-valuenow={Math.round(t)}
      aria-valuetext={`${fmt(t)} of ${fmt(TOTAL)}`}
      className="group/bar relative flex h-4 cursor-pointer touch-none items-center gap-[3px]"
      onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onSeek(at(e.clientX)); }}
      onPointerMove={(e) => { if (e.buttons) onSeek(at(e.clientX)); }}
    >
      {SCENES.map((s, i) => {
        const fill = Math.min(1, Math.max(0, (t - STARTS[i]) / s.duration));
        return (
          <div key={s.id} className="relative h-1 overflow-hidden rounded-full bg-white/15 transition-[height] group-hover/bar:h-1.5" style={{ flex: s.duration }} title={s.title}>
            <div className="absolute inset-y-0 left-0 bg-ember" style={{ width: `${fill * 100}%` }} />
          </div>
        );
      })}
    </div>
  );
}

function Btn({ onClick, label, active, children }: { onClick: () => void; label: string; active?: boolean; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      title={label}
      aria-pressed={active}
      className={`flex h-8 min-w-8 items-center justify-center gap-1.5 rounded-md px-2 transition-colors hover:bg-white/[0.07] ${active ? "text-fg" : "text-mute"}`}
    >
      {children}
    </button>
  );
}

const PlayIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden><path d="M7 4.5v15l12.5-7.5z" /></svg>
);
const PauseIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden><path d="M6 4h4v16H6zM14 4h4v16h-4z" /></svg>
);
const FullIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" /></svg>
);
const SpeakerIcon = ({ className, muted }: { className?: string; muted?: boolean }) => (
  <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d="M4 9v6h4l5 4V5L8 9z" />
    {muted ? <path d="M17 9l5 6M22 9l-5 6" /> : <path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12" />}
  </svg>
);

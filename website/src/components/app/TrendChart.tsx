"use client";

import { useEffect, useRef, useState } from "react";

export type TrendPoint = { id: string; label: string; date: string; value: number; gate: string | null };

const LINE = "#e8592a"; // validated against the dark surface (lightness band + 3:1 contrast)
const H = 180;
const PAD = { top: 14, right: 16, bottom: 26, left: 40 };

/** Single series (pass rate per run): no legend, the card title names it. */
export function TrendChart({ points, onSelect }: { points: TrendPoint[]; onSelect?: (id: string) => void }) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(280, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const innerW = w - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (points.length <= 1 ? innerW / 2 : (i / (points.length - 1)) * innerW);
  const y = (v: number) => PAD.top + (1 - v) * innerH;
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");

  function nearest(clientX: number) {
    const rect = wrap.current?.getBoundingClientRect();
    if (!rect || !points.length) return null;
    const px = clientX - rect.left;
    let best = 0;
    points.forEach((_, i) => {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
    });
    return best;
  }

  const hp = hover != null ? points[hover] : null;

  return (
    <div ref={wrap} className="relative select-none" onPointerLeave={() => setHover(null)}>
      <svg
        width={w}
        height={H}
        role="img"
        aria-label={`Pass rate over the last ${points.length} runs`}
        tabIndex={0}
        className="block outline-none focus-visible:ring-1 focus-visible:ring-ember/60"
        onPointerMove={(e) => setHover(nearest(e.clientX))}
        onClick={() => hp && onSelect?.(hp.id)}
        onKeyDown={(e) => {
          if (!points.length) return;
          if (e.key === "ArrowRight") setHover((h) => Math.min(points.length - 1, (h ?? -1) + 1));
          if (e.key === "ArrowLeft") setHover((h) => Math.max(0, (h ?? points.length) - 1));
          if (e.key === "Enter" && hp) onSelect?.(hp.id);
        }}
      >
        {[0, 0.5, 1].map((g) => (
          <g key={g}>
            <line x1={PAD.left} x2={w - PAD.right} y1={y(g)} y2={y(g)} stroke="rgb(255 255 255 / 0.07)" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(g) + 4} textAnchor="end" className="fill-dim font-mono text-[10.5px]">
              {Math.round(g * 100)}%
            </text>
          </g>
        ))}
        {hp && <line x1={x(hover!)} x2={x(hover!)} y1={PAD.top} y2={H - PAD.bottom} stroke="rgb(255 255 255 / 0.25)" strokeWidth={1} />}
        <path d={path} fill="none" stroke={LINE} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        {points.map((p, i) => (
          <circle
            key={p.id}
            cx={x(i)}
            cy={y(p.value)}
            r={hover === i ? 5.5 : 4}
            fill={LINE}
            stroke="var(--color-ink)"
            strokeWidth={2}
            className="cursor-pointer"
          />
        ))}
        {points.length > 0 && (
          <>
            <text x={x(0)} y={H - 8} textAnchor={points.length > 1 ? "start" : "middle"} className="fill-dim font-mono text-[10.5px]">
              {points[0].date}
            </text>
            {points.length > 1 && (
              <text x={x(points.length - 1)} y={H - 8} textAnchor="end" className="fill-dim font-mono text-[10.5px]">
                {points[points.length - 1].date}
              </text>
            )}
          </>
        )}
      </svg>
      {hp && (
        <div
          className="pointer-events-none absolute z-10 min-w-[150px] rounded-lg border border-line bg-panel-2 px-3 py-2 text-[12px] shadow-xl shadow-black/40"
          style={{ left: Math.min(Math.max(x(hover!) - 75, 0), w - 160), top: Math.max(y(hp.value) - 74, 0) }}
        >
          <div className="text-[15px] font-semibold tabular-nums text-fg">{Math.round(hp.value * 100)}%</div>
          <div className="truncate text-mute">{hp.label || "unlabeled run"}</div>
          <div className="text-dim">
            {hp.date}
            {hp.gate ? ` · gate ${hp.gate}` : ""}
          </div>
        </div>
      )}
    </div>
  );
}

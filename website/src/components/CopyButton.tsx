"use client";

import { useState } from "react";

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1400);
        } catch {
          /* clipboard unavailable (insecure context) */
        }
      }}
      className="rounded-md border border-line bg-panel-2 px-2 py-1 font-mono text-[11px] text-mute transition-colors hover:text-fg"
      aria-label="Copy to clipboard"
    >
      {copied ? "copied" : "copy"}
    </button>
  );
}

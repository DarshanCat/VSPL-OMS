"use client";
import React, { useState } from "react";
import { Check, Copy } from "lucide-react";

// A transaction / document number: monospace, with a copy button.
export function CCTxnNumber({ value }: { value: string | null | undefined }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="text-zinc-400">-</span>;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      /* clipboard unavailable: the number stays selectable */
    }
  };
  return (
    <span className="inline-flex items-center gap-1 font-mono text-xs text-zinc-800 dark:text-zinc-200">
      {value}
      <button
        type="button"
        onClick={copy}
        title="Copy"
        aria-label={`Copy ${value}`}
        className="rounded p-0.5 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
      >
        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      </button>
    </span>
  );
}

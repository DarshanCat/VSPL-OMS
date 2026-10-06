"use client";
import React, { useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { GitMerge } from "lucide-react";
import { CCInwardSelector } from "@/app/components/cc/CCInwardSelector";
import { CCInwardTraceView } from "@/app/components/cc/CCInwardTraceView";
import { CCWorkOrderSelector } from "@/app/components/cc/CCWorkOrderSelector";
import { CCWorkOrderTraceView } from "@/app/components/cc/CCWorkOrderTraceView";

type Tab = "inward" | "wo";

// Traceability (read-only; any authenticated user). Two views share one page.
//   By Inward:      ?inward=<inward UUID>   (the trace endpoint takes the UUID; the inward NUMBER is only for searching)
//   By Work Order:  ?wo=<wo_number>
// The selection lives in the URL, so a link is a complete deep link. Switching tabs clears the other selection and only
// the active tab loads a trace.
export default function TraceabilityContent() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const inwardParam = params.get("inward");
  const woParam = params.get("wo");
  const [tab, setTab] = useState<Tab>(woParam && !inwardParam ? "wo" : "inward");

  // Follow the URL when it names exactly one selection (for example a link from elsewhere, or back/forward).
  useEffect(() => {
    if (woParam && !inwardParam) setTab("wo");
    else if (inwardParam && !woParam) setTab("inward");
  }, [woParam, inwardParam]);

  const go = (query: string) => router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  const selectInward = (id: string) => go(`inward=${encodeURIComponent(id)}`);
  const selectWo = (woNumber: string) => go(`wo=${encodeURIComponent(woNumber)}`);
  const switchTab = (next: Tab) => { if (next !== tab) { setTab(next); go(""); } }; // clears the other selection

  const tabBtn = (key: Tab, label: string) => (
    <button
      type="button" onClick={() => switchTab(key)} role="tab" aria-selected={tab === key}
      className={`rounded-t-lg border-b-2 px-4 py-2 text-xs font-semibold ${tab === key ? "border-blue-600 text-blue-600 dark:text-blue-400" : "border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
          <GitMerge className="h-3.5 w-3.5" /> Continuous Casting
        </p>
        <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Traceability</h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Read-only view of where continuous casting material came from and where it went. All figures and relationships come
          from the backend.
        </p>
      </div>

      <div role="tablist" className="flex gap-1 border-b border-zinc-200 dark:border-zinc-800">
        {tabBtn("inward", "By Inward")}
        {tabBtn("wo", "By Work Order")}
      </div>

      {tab === "inward" && (
        <div className="space-y-4">
          <details open={!inwardParam} className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
            <summary className="cursor-pointer text-xs font-semibold">1. Select inward</summary>
            <div className="mt-2">
              <CCInwardSelector selectedInwardId={inwardParam} onSelect={(row) => selectInward(row.inward_id)} />
            </div>
          </details>
          {inwardParam && <CCInwardTraceView key={inwardParam} inwardId={inwardParam} />}
        </div>
      )}

      {tab === "wo" && (
        <div className="space-y-4">
          <details open={!woParam} className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
            <summary className="cursor-pointer text-xs font-semibold">1. Select Work Order</summary>
            <div className="mt-2">
              <CCWorkOrderSelector selectedWoNumber={woParam} onSelect={(w) => selectWo(w.wo_number)} />
            </div>
          </details>
          {woParam && <CCWorkOrderTraceView key={woParam} woNumber={woParam} onOpenInward={selectInward} />}
        </div>
      )}
    </div>
  );
}

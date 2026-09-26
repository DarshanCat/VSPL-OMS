"use client";
import React, { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AppShell } from "@/app/components/layout/AppShell";
import { ProductionEntryContent } from "./ProductionEntryContent";
import { MovePartsContent } from "@/app/production/move/MovePartsContent";

// Unified Production Entry workflow: ONE page/URL presents both transactions
// (Record Production and Move Parts) as tabs, instead of two separate modules a
// user had to navigate between. Each tab reuses its existing, unchanged form/
// state/validation/API calls -- this is a UI composition change only, not a
// second business-rule engine; the backend production/movement services and
// their distinct semantics (recording completion vs. physically moving material)
// are entirely unchanged.
function UnifiedProductionEntryInner() {
  const searchParams = useSearchParams();
  const [activeTab, setActiveTab] = useState<"entry" | "move">(
    searchParams.get("tab") === "move" ? "move" : "entry"
  );

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto mb-4">
        <div className="inline-flex rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-1 shadow-sm">
          <button
            type="button"
            onClick={() => setActiveTab("entry")}
            className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-bold transition-colors ${
              activeTab === "entry"
                ? "bg-emerald-600 text-white shadow-sm"
                : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
            }`}
          >
            Record Production
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("move")}
            className={`flex items-center gap-1.5 rounded-lg px-4 py-2 text-xs font-bold transition-colors ${
              activeTab === "move"
                ? "bg-blue-600 text-white shadow-sm"
                : "text-zinc-500 dark:text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"
            }`}
          >
            Move Parts
          </button>
        </div>
      </div>
      {activeTab === "entry" ? <ProductionEntryContent /> : <MovePartsContent />}
    </AppShell>
  );
}

export default function UnifiedProductionEntryPage() {
  return (
    <Suspense fallback={null}>
      <UnifiedProductionEntryInner />
    </Suspense>
  );
}

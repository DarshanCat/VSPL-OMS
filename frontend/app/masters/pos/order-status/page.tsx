"use client";
import React, { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { NoAccess, PRINT_CSS, useSalesAccess } from "@/app/components/sales/SalesUi";
import { OrderStatusPanel } from "@/app/components/sales/OrderStatusPanel";
import { ScheduleStatusPanel } from "@/app/components/sales/ScheduleStatusPanel";

// PO Master dashboard: the Sales Order Status and the Customer Schedule Status reports in one place.
// Both reports stay mounted (the inactive one is hidden) so switching tabs is instant and keeps filters.
type Tab = "orders" | "schedules";
const TABS: { key: Tab; label: string; hint: string }[] = [
  { key: "orders", label: "Sales Order Status", hint: "Orders, PO lines and schedules still to deliver" },
  { key: "schedules", label: "Customer Schedule Status", hint: "Customer schedules and their OARs" },
];

export default function PoMasterDashboardPage() {
  const allowed = useSalesAccess();
  const [tab, setTab] = useState<Tab>("orders");

  // /masters/pos/order-status?tab=schedules opens the schedules tab (the old schedule dashboard address redirects here)
  useEffect(() => {
    try {
      if (new URLSearchParams(window.location.search).get("tab") === "schedules") setTab("schedules");
    } catch { /* default tab */ }
  }, []);

  const pick = (t: Tab) => {
    setTab(t);
    try {
      const url = new URL(window.location.href);
      if (t === "schedules") url.searchParams.set("tab", "schedules"); else url.searchParams.delete("tab");
      window.history.replaceState(null, "", url.toString());
    } catch { /* the tab still switches */ }
  };

  if (allowed === false) return <NoAccess title="PO Master dashboard" backHref="/masters/pos" backLabel="PO Master" />;

  return (
    <AppShell>
      <style>{PRINT_CSS}</style>
      <div className="max-w-6xl mx-auto space-y-4">
        <Link href="/masters/pos" className="no-print inline-flex items-center gap-1 text-xs font-bold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
          <ArrowLeft className="h-3.5 w-3.5" /> PO Master
        </Link>
        <div className="no-print flex flex-wrap items-center gap-2" role="tablist" aria-label="PO Master dashboard">
          {TABS.map((t) => (
            <button
              key={t.key} type="button" role="tab" aria-selected={tab === t.key} title={t.hint} onClick={() => pick(t.key)}
              className={`rounded-xl border px-4 py-2 text-xs font-extrabold transition ${
                tab === t.key
                  ? "border-blue-600 bg-blue-600 text-white shadow-sm"
                  : "border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>
      {allowed && (
        <>
          <div className={tab === "orders" ? "mt-4" : "hidden"}><OrderStatusPanel /></div>
          <div className={tab === "schedules" ? "mt-4" : "hidden"}><ScheduleStatusPanel /></div>
        </>
      )}
    </AppShell>
  );
}

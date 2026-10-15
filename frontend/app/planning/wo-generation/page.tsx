"use client";
import React, { useState, useEffect, Suspense, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Layers,
  Search,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Route,
  Clock,
  Calendar,
  RefreshCw,
  Plus,
  FileSpreadsheet,
  Check,
  Send,
  Boxes,
  Flame,
  Factory
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import {
  getOarList,
  OARListItem,
  getWorkOrders,
  WorkOrderListItem,
  getNextSequences,
  createWorkOrder,
  WorkOrderCreatePayload,
  WorkOrderCreateResult
} from "@/lib/api";

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

const DEFAULT_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];

export default function WOGenerationPage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="max-w-7xl mx-auto py-12 text-center text-xs text-zinc-500 font-mono">
            Loading Work Order Generation...
          </div>
        </AppShell>
      }
    >
      <WOGenerationContent />
    </Suspense>
  );
}

function WOGenerationContent() {
  const searchParams = useSearchParams();
  const urlOar = searchParams.get("oar") || "";

  // Data states
  const [oars, setOars] = useState<OARListItem[]>([]);
  const [recentWOs, setRecentWOs] = useState<WorkOrderListItem[]>([]);
  const [loadingOars, setLoadingOars] = useState(false);
  const [loadingWOs, setLoadingWOs] = useState(false);

  // Filters
  const [searchOar, setSearchOar] = useState(urlOar);
  const [filterPendingOnly, setFilterPendingOnly] = useState(true);

  // Form states
  const [selectedOar, setSelectedOar] = useState<OARListItem | null>(null);
  const [woNumber, setWoNumber] = useState("");
  const [woQty, setWoQty] = useState<number | "">("");
  const [woDate, setWoDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [targetDate, setTargetDate] = useState("");
  const [castingProcess, setCastingProcess] = useState<"CENTRIFUGAL" | "CONTINUOUS">("CENTRIFUGAL");
  const [heatNumber, setHeatNumber] = useState("");
  const [routeStages, setRouteStages] = useState<string[]>(DEFAULT_STAGES);
  const [remarks, setRemarks] = useState("Planned by Production Planning department.");

  // Submit states
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [successResult, setSuccessResult] = useState<WorkOrderCreateResult | null>(null);

  // Load next WO number sequence
  const loadNextWoSequence = async () => {
    try {
      const seq = await getNextSequences();
      setWoNumber(seq.next_wo_number);
    } catch {
      // ignore
    }
  };

  // Load OARs
  const loadOars = useCallback(async () => {
    setLoadingOars(true);
    try {
      const data = await getOarList();
      setOars(data);
      if (urlOar) {
        const found = data.find((o) => o.oar_number.toLowerCase() === urlOar.toLowerCase());
        if (found) {
          handleSelectOar(found);
        }
      }
    } catch {
      setOars([]);
    } finally {
      setLoadingOars(false);
    }
  }, [urlOar]);

  // Load Created Work Orders
  const loadRecentWOs = async () => {
    setLoadingWOs(true);
    try {
      const data = await getWorkOrders({ limit: 50, sort_by: "created_at_desc" });
      setRecentWOs(data);
    } catch {
      setRecentWOs([]);
    } finally {
      setLoadingWOs(false);
    }
  };

  useEffect(() => {
    loadOars();
    loadRecentWOs();
    loadNextWoSequence();
  }, [loadOars]);

  const handleSelectOar = (oar: OARListItem) => {
    setSelectedOar(oar);
    setSearchOar(oar.oar_number);
    setWoQty(oar.remaining_qty > 0 ? oar.remaining_qty : oar.oar_qty);
    if (oar.delivery_date) {
      setTargetDate(oar.delivery_date.slice(0, 10));
    }
    setError("");
    setSuccessResult(null);
    loadNextWoSequence();
    document.getElementById("wo-generator-card")?.scrollIntoView({ behavior: "smooth" });
  };

  const handleToggleStage = (stage: string) => {
    if (routeStages.includes(stage)) {
      if (routeStages.length === 1) return;
      setRouteStages(routeStages.filter((s) => s !== stage));
    } else {
      setRouteStages([...routeStages, stage]);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOar) {
      setError("Please select a parent OAR first.");
      return;
    }
    const qty = Number(woQty);
    if (!qty || qty <= 0) {
      setError("Please enter a valid positive Work Order quantity.");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const payload: WorkOrderCreatePayload = {
        oar_number: selectedOar.oar_number,
        wo_number: woNumber.trim() || undefined,
        physical_wo_qty: qty,
        wo_date: woDate || undefined,
        target_date: targetDate || undefined,
        casting_process: castingProcess,
        heat_number: heatNumber.trim() || undefined,
        route_stages: routeStages,
        remarks: remarks.trim() || undefined,
      };

      const res = await createWorkOrder(payload);
      setSuccessResult(res);
      loadOars();
      loadRecentWOs();
      loadNextWoSequence();
      // Adjust remaining on selected OAR in memory
      setSelectedOar((prev) =>
        prev
          ? {
              ...prev,
              allocated_qty: prev.allocated_qty + qty,
              remaining_qty: Math.max(0, prev.remaining_qty - qty),
            }
          : null
      );
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to create Work Order.");
    } finally {
      setSubmitting(false);
    }
  };

  // Filtered OARs
  const filteredOars = oars.filter((o) => {
    if (filterPendingOnly && o.remaining_qty <= 0) return false;
    if (!searchOar.trim()) return true;
    const q = searchOar.toLowerCase();
    return (
      o.oar_number.toLowerCase().includes(q) ||
      o.customer_name.toLowerCase().includes(q) ||
      o.customer_code.toLowerCase().includes(q) ||
      (o.customer_po && o.customer_po.toLowerCase().includes(q)) ||
      o.part_number.toLowerCase().includes(q)
    );
  });

  return (
    <AppShell>
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Planning Department
              </span>
              <span className="text-xs text-zinc-400">Step 2 of 3 (PO → OAR → WO → Release)</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Work Order Generation
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Select created Sales OARs, generate and schedule Work Order IDs with custom/auto sequences and dates, and route them to Release.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/orders/intake"
              className="px-3 py-2 text-xs font-semibold rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
            >
              Step 1: Sales OAR Intake
            </Link>
            <Link
              href="/planning/wo-release"
              className="px-3.5 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-700 transition flex items-center gap-1.5 shadow-sm"
            >
              <span>Step 3: WO Release</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>

        {/* Section 1: Created OARs Queue */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <FileSpreadsheet className="h-4 w-4 text-emerald-600" />
                Created OARs (Sales Order Acceptance Receipts)
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Only confirmed OARs created by Sales appear here for Planner Work Order generation.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden text-xs">
                <button
                  type="button"
                  onClick={() => setFilterPendingOnly(true)}
                  className={`px-3 py-1.5 font-bold transition ${
                    filterPendingOnly
                      ? "bg-emerald-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                  }`}
                >
                  Awaiting Work Orders
                </button>
                <button
                  type="button"
                  onClick={() => setFilterPendingOnly(false)}
                  className={`px-3 py-1.5 font-bold transition ${
                    !filterPendingOnly
                      ? "bg-emerald-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                  }`}
                >
                  All OARs
                </button>
              </div>

              <div className="relative">
                <Search className="h-3.5 w-3.5 text-zinc-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={searchOar}
                  onChange={(e) => setSearchOar(e.target.value)}
                  placeholder="Filter OAR, customer, part..."
                  className="pl-8 pr-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 focus:outline-none w-48 sm:w-60"
                />
              </div>

              <button
                type="button"
                onClick={loadOars}
                disabled={loadingOars}
                className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                title="Refresh OARs"
              >
                <RefreshCw className={`h-4 w-4 ${loadingOars ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          {loadingOars ? (
            <p className="text-xs text-zinc-400 py-4 text-center">Loading OAR records...</p>
          ) : filteredOars.length === 0 ? (
            <div className="py-6 text-center text-xs text-zinc-400 bg-zinc-50 dark:bg-zinc-950 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
              No OARs match your criteria. You can create an OAR in{" "}
              <Link href="/orders/intake" className="text-blue-600 font-bold hover:underline">
                Order Intake
              </Link>
              .
            </div>
          ) : (
            <div className="overflow-x-auto max-h-72 overflow-y-auto border border-zinc-200 dark:border-zinc-800 rounded-xl">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider sticky top-0">
                  <tr>
                    <th className="p-3">OAR Reference</th>
                    <th className="p-3">Customer &amp; PO</th>
                    <th className="p-3">Part Number</th>
                    <th className="p-3 text-right">OAR Qty</th>
                    <th className="p-3 text-right">Allocated</th>
                    <th className="p-3 text-right">Remaining to Plan</th>
                    <th className="p-3">Delivery Date</th>
                    <th className="p-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {filteredOars.map((o) => {
                    const isSelected = selectedOar?.order_id === o.order_id;
                    return (
                      <tr
                        key={o.order_id || o.oar_number}
                        className={`transition-colors ${
                          isSelected
                            ? "bg-emerald-50 dark:bg-emerald-950/40 border-l-4 border-l-emerald-600"
                            : "hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                        }`}
                      >
                        <td className="p-3">
                          <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400 block">
                            {o.oar_number}
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">
                            {formatDate(o.oar_date || o.created_at)}
                          </span>
                        </td>
                        <td className="p-3">
                          <span className="font-semibold text-zinc-800 dark:text-zinc-200 block">
                            {o.customer_name}
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">
                            PO: {o.customer_po || "—"}
                          </span>
                        </td>
                        <td className="p-3 font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                          {o.part_number}
                        </td>
                        <td className="p-3 text-right font-mono font-bold">{o.oar_qty}</td>
                        <td className="p-3 text-right font-mono text-zinc-500">{o.allocated_qty}</td>
                        <td className="p-3 text-right font-mono">
                          {o.remaining_qty > 0 ? (
                            <span className="inline-block px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 font-bold">
                              {o.remaining_qty} pcs
                            </span>
                          ) : (
                            <span className="text-zinc-400">0 (Fully Planned)</span>
                          )}
                        </td>
                        <td className="p-3 text-zinc-500">{formatDate(o.delivery_date)}</td>
                        <td className="p-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleSelectOar(o)}
                            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition ${
                              isSelected
                                ? "bg-emerald-700 text-white"
                                : "bg-emerald-600 text-white hover:bg-emerald-700"
                            }`}
                          >
                            {isSelected ? "Selected" : "Generate WO"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Section 2: Work Order Creation Form */}
        <div
          id="wo-generator-card"
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
        >
          <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
            <div>
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50">
                Generate Work Order ID
              </h3>
              <p className="text-xs text-zinc-400">
                Create a scheduled Work Order from selected OAR with target dates and route.
              </p>
            </div>
            {selectedOar && (
              <span className="px-2.5 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 text-xs font-bold font-mono">
                Parent: {selectedOar.oar_number}
              </span>
            )}
          </div>

          {error && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
              {error}
            </div>
          )}

          {successResult && (
            <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5 space-y-3">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="h-6 w-6 text-emerald-500 shrink-0" />
                <div>
                  <h4 className="text-sm font-bold text-emerald-800 dark:text-emerald-300">
                    Work Order {successResult.wo_number} Generated Successfully!
                  </h4>
                  <p className="text-xs text-emerald-600 dark:text-emerald-400">
                    Linked to Parent OAR: <strong>{successResult.oar_number}</strong> | Part: {successResult.part_number} | Quantity: {successResult.physical_wo_qty} pcs
                  </p>
                </div>
              </div>

              <div className="rounded-xl bg-white dark:bg-zinc-900 p-3.5 border border-zinc-200 dark:border-zinc-800 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <span className="font-bold text-zinc-900 dark:text-zinc-100 block">
                    Next Step in 3-Step Process: Work Order Release
                  </span>
                  <p className="text-zinc-500 text-[11px]">
                    Release this Work Order to authorise production floor dispatch and route tracking.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Link
                    href={`/planning/wo-release?wo=${encodeURIComponent(successResult.wo_number)}`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 text-white font-bold text-xs hover:bg-blue-700 transition"
                  >
                    <span>Release WO #{successResult.wo_number}</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                  <Link
                    href={`/production/tracking?wo=${encodeURIComponent(successResult.wo_number)}`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 text-xs font-semibold hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                  >
                    <span>Track Floor</span>
                  </Link>
                </div>
              </div>
            </div>
          )}

          {!selectedOar ? (
            <div className="py-8 text-center text-xs text-zinc-400 bg-zinc-50 dark:bg-zinc-950 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
              Please click <strong>"Generate WO"</strong> on an OAR from the table above to start.
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {/* Parent OAR Summary Card */}
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 p-4 border border-zinc-200 dark:border-zinc-800 grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Parent OAR</span>
                  <span className="font-mono font-bold text-emerald-600 text-sm">{selectedOar.oar_number}</span>
                  <span className="text-[10px] text-zinc-400 block font-mono">PO: {selectedOar.customer_po || "—"}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Customer</span>
                  <span className="font-semibold text-zinc-800 dark:text-zinc-200 block truncate">{selectedOar.customer_name}</span>
                  <span className="text-[10px] text-zinc-400 font-mono">{selectedOar.customer_code}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Part &amp; Grade</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">{selectedOar.part_number}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Quantities</span>
                  <span className="text-zinc-600 dark:text-zinc-300 block">
                    OAR: <strong>{selectedOar.oar_qty}</strong> | Planned: {selectedOar.allocated_qty}
                  </span>
                  <span className="font-bold text-emerald-600 font-mono">
                    Remaining: {selectedOar.remaining_qty} pcs
                  </span>
                </div>
              </div>

              {/* WO ID, Date & Target Date */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                      Work Order ID *
                    </label>
                    <button
                      type="button"
                      onClick={loadNextWoSequence}
                      className="text-[10px] text-blue-600 hover:underline flex items-center gap-1"
                    >
                      <RefreshCw className="h-2.5 w-2.5" /> Next Auto
                    </button>
                  </div>
                  <input
                    type="text"
                    required
                    value={woNumber}
                    onChange={(e) => setWoNumber(e.target.value)}
                    placeholder="e.g. WO-17617 or custom/dumped ID"
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                  <p className="mt-1 text-[10px] text-zinc-400">
                    Auto-sequenced or enter custom/dumped WO ID.
                  </p>
                </div>

                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Physical WO Quantity (pcs) *
                  </label>
                  <input
                    type="number"
                    required
                    min={1}
                    value={woQty}
                    onChange={(e) => setWoQty(e.target.value === "" ? "" : Number(e.target.value))}
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                  <p className="mt-1 text-[10px] text-zinc-400">
                    Max suggested: {selectedOar.remaining_qty} pcs
                  </p>
                </div>

                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Work Order Date *
                  </label>
                  <input
                    type="date"
                    required
                    value={woDate}
                    onChange={(e) => setWoDate(e.target.value)}
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                </div>
              </div>

              {/* Process, Target Date, Heat No */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Casting Process
                  </label>
                  <select
                    value={castingProcess}
                    onChange={(e) => setCastingProcess(e.target.value as any)}
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  >
                    <option value="CENTRIFUGAL">CENTRIFUGAL</option>
                    <option value="CONTINUOUS">CONTINUOUS</option>
                  </select>
                </div>

                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Target / Delivery Date
                  </label>
                  <input
                    type="date"
                    value={targetDate}
                    onChange={(e) => setTargetDate(e.target.value)}
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Heat / Melt Number (Optional)
                  </label>
                  <input
                    type="text"
                    value={heatNumber}
                    onChange={(e) => setHeatNumber(e.target.value)}
                    placeholder="e.g. HT-2026-081"
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                </div>
              </div>

              {/* Route Stages */}
              <div className="pt-2">
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300 block mb-1.5">
                  Production Route Stages
                </label>
                <div className="flex flex-wrap gap-2">
                  {DEFAULT_STAGES.map((stg) => {
                    const active = routeStages.includes(stg);
                    return (
                      <button
                        key={stg}
                        type="button"
                        onClick={() => handleToggleStage(stg)}
                        className={`px-3 py-1 text-xs font-bold rounded-lg border transition ${
                          active
                            ? "bg-blue-600 border-blue-600 text-white"
                            : "bg-zinc-50 dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800 text-zinc-400"
                        }`}
                      >
                        {stg}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Remarks & Submit */}
              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Planning Remarks
                </label>
                <input
                  type="text"
                  value={remarks}
                  onChange={(e) => setRemarks(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div className="pt-2 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setSelectedOar(null)}
                  className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting || !woNumber || !woQty}
                  className="px-6 py-2.5 text-xs font-bold rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition flex items-center gap-2 shadow-sm"
                >
                  <Plus className="h-4 w-4" />
                  <span>{submitting ? "Generating Work Order..." : "Generate Work Order"}</span>
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Section 3: Created Work Orders & Parent OAR Genealogy */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <Layers className="h-4 w-4 text-blue-600" />
                Created Work Orders &amp; Parent OAR Linkage
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Shows all created Work Orders with their parent OAR numbers and release status.
              </p>
            </div>
            <button
              type="button"
              onClick={loadRecentWOs}
              disabled={loadingWOs}
              className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              title="Refresh Work Orders"
            >
              <RefreshCw className={`h-4 w-4 ${loadingWOs ? "animate-spin" : ""}`} />
            </button>
          </div>

          {loadingWOs ? (
            <p className="text-xs text-zinc-400 py-4 text-center">Loading Work Orders...</p>
          ) : recentWOs.length === 0 ? (
            <p className="text-xs text-zinc-400 py-4 text-center">No Work Orders created yet.</p>
          ) : (
            <div className="overflow-x-auto max-h-80 overflow-y-auto border border-zinc-200 dark:border-zinc-800 rounded-xl">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider sticky top-0">
                  <tr>
                    <th className="p-3">Work Order ID</th>
                    <th className="p-3">Parent OAR</th>
                    <th className="p-3">Customer &amp; PO</th>
                    <th className="p-3">Part Number</th>
                    <th className="p-3 text-right">WO Qty</th>
                    <th className="p-3">Current Stage</th>
                    <th className="p-3">Release Status</th>
                    <th className="p-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {recentWOs.map((wo) => (
                    <tr key={wo.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                      <td className="p-3">
                        <span className="font-mono font-bold text-blue-600 block">
                          {wo.wo_number}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono">
                          {formatDate(wo.wo_date || wo.created_at)}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400 block">
                          {wo.oar_number || "—"}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="font-semibold text-zinc-800 dark:text-zinc-200 block">
                          {wo.customer_name}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono">
                          PO: {wo.customer_po || "—"}
                        </span>
                      </td>
                      <td className="p-3 font-mono text-zinc-900 dark:text-zinc-100">
                        {wo.part_number}
                      </td>
                      <td className="p-3 text-right font-mono font-bold">
                        {wo.physical_wo_qty} pcs
                      </td>
                      <td className="p-3 font-mono">
                        <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-bold text-[11px]">
                          {wo.current_stage || "F1"}
                        </span>
                      </td>
                      <td className="p-3">
                        {wo.is_released ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 font-semibold text-[11px]">
                            <Check className="h-3 w-3" /> Released
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 font-semibold text-[11px]">
                            <Clock className="h-3 w-3" /> Awaiting Release
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {!wo.is_released && (
                            <Link
                              href={`/planning/wo-release?wo=${encodeURIComponent(wo.wo_number)}`}
                              className="px-2.5 py-1 text-[11px] font-bold rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition"
                            >
                              Release WO
                            </Link>
                          )}
                          <Link
                            href={`/production/tracking?wo=${encodeURIComponent(wo.wo_number)}`}
                            className="px-2.5 py-1 text-[11px] font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                          >
                            Track
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

"use client";
import React, { useState, useEffect, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Route,
  Search,
  CheckCircle2,
  Clock,
  Layers,
  ArrowRight,
  ShieldAlert,
  Calendar,
  User,
  Cpu,
  TrendingUp,
  AlertCircle,
  History,
  ArrowRightLeft,
  CheckSquare,
  FileSpreadsheet,
  FileCheck,
  Flame,
  AlertTriangle,
  X,
  RotateCcw
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getWorkOrders, getWorkOrderTracking, declareWOShortfall } from "@/lib/api";

export default function WorkOrderTrackingPage() {
  return (
    <Suspense fallback={null}>
      <WorkOrderTrackingPageInner />
    </Suspense>
  );
}

function WorkOrderTrackingPageInner() {
  const searchParams = useSearchParams();
  const initialWO = searchParams.get("wo") || "WO-1001";
  const [classificationFilter, setClassificationFilter] = useState<"ALL" | "Production" | "NPD">("ALL");
  const [searchTerm, setSearchTerm] = useState(initialWO);
  const [selectedWO, setSelectedWO] = useState<string>(initialWO);
  const [loading, setLoading] = useState(false);
  const [woData, setWoData] = useState<any>(null);
  const [wosList, setWosList] = useState<any[]>([]);
  const [error, setError] = useState("");

  // Shortfall Modal State
  const [isShortfallModalOpen, setIsShortfallModalOpen] = useState(false);
  const [shortfallDeclareQty, setShortfallDeclareQty] = useState<number | "">("");
  const [shortfallDeclareReason, setShortfallDeclareReason] = useState("");
  const [createPatchWO, setCreatePatchWO] = useState(true);
  const [declaringShortfall, setDeclaringShortfall] = useState(false);
  const [shortfallSuccessMsg, setShortfallSuccessMsg] = useState<string | null>(null);
  const [patchWONumber, setPatchWONumber] = useState<string | null>(null);

  const loadWorkOrders = (cls: "ALL" | "Production" | "NPD") => {
    getWorkOrders({
      limit: 100,
      classification: cls === "ALL" ? undefined : cls,
    })
      .then((data) => {
        if (Array.isArray(data)) {
          setWosList(data);
          if (cls !== "ALL" && data.length > 0) {
            const hasCurrent = data.some((w) => w.wo_number === selectedWO);
            if (!hasCurrent) {
              fetchTracking(data[0].wo_number);
            }
          }
        }
      })
      .catch(() => {});
  };

  useEffect(() => {
    loadWorkOrders(classificationFilter);
    fetchTracking(initialWO);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classificationFilter]);

  const fetchTracking = async (woNum: string) => {
    if (!woNum || !woNum.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await getWorkOrderTracking(woNum.trim());
      setWoData(data);
      setSelectedWO(data.wo_number);
      setSearchTerm(data.wo_number);
    } catch (err: any) {
      setError(err?.response?.data?.detail || `Work Order '${woNum}' not found.`);
      setWoData(null);
    } finally {
      setLoading(false);
    }
  };

  const f1Timeline = woData?.timeline?.find((t: any) => t.stage === "F1");
  const f1Remaining = f1Timeline
    ? Math.max((f1Timeline.target_qty || 0) - (f1Timeline.ok_completed_qty || 0) - (f1Timeline.rejected_qty || 0), 0)
    : 0;

  const handleOpenShortfallModal = () => {
    setShortfallDeclareQty(f1Remaining);
    setShortfallDeclareReason("");
    setCreatePatchWO(true);
    setIsShortfallModalOpen(true);
    setShortfallSuccessMsg(null);
    setPatchWONumber(null);
  };

  const handleConfirmShortfall = async () => {
    if (!woData?.wo_number) return;
    const qty = Number(shortfallDeclareQty);
    if (!qty || qty <= 0) {
      alert("Please enter a valid shortfall quantity greater than 0.");
      return;
    }
    if (!shortfallDeclareReason.trim()) {
      alert("Please enter a mandatory reason for the shortfall.");
      return;
    }

    setDeclaringShortfall(true);
    try {
      const res = await declareWOShortfall(woData.wo_number, {
        shortfall_qty: qty,
        reason: shortfallDeclareReason.trim(),
        create_patch_wo: createPatchWO,
        heat_number: woData.heat_number || undefined,
      });

      setIsShortfallModalOpen(false);
      setShortfallSuccessMsg(res.message);
      setPatchWONumber(res.patch_wo_number);
      await fetchTracking(woData.wo_number);
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to declare shortfall.");
    } finally {
      setDeclaringShortfall(false);
    }
  };

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Live Process Tracking
              </span>
              <span className="text-xs text-zinc-400">Deterministic Flow • Audit Ledger</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Live Work Order Tracking & Process Timeline
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              End-to-end stage movement, real-time WIP buffers, yield progression, and immutable transaction ledger.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/production/entry"
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
            >
              <CheckSquare className="h-3.5 w-3.5 text-emerald-600" />
              <span>Record Production</span>
            </Link>

            <Link
              href="/production/move"
              className="flex items-center gap-1.5 rounded-xl bg-blue-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm shadow-blue-500/20 hover:bg-blue-500 transition-colors"
            >
              <ArrowRightLeft className="h-3.5 w-3.5" />
              <span>Move Parts</span>
            </Link>
          </div>
        </div>

        {/* Classification Filter Tabs */}
        <div className="flex items-center gap-2 border-b border-zinc-200 dark:border-zinc-800 pb-2 flex-wrap">
          <button
            type="button"
            onClick={() => setClassificationFilter("ALL")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
              classificationFilter === "ALL"
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-xs"
                : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
            }`}
          >
            <span>All Work Orders</span>
          </button>
          <button
            type="button"
            onClick={() => setClassificationFilter("Production")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
              classificationFilter === "Production"
                ? "bg-emerald-600 text-white shadow-xs"
                : "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/60 hover:bg-emerald-100 dark:hover:bg-emerald-900/50"
            }`}
          >
            <span>🏭 Production Series</span>
          </button>
          <button
            type="button"
            onClick={() => setClassificationFilter("NPD")}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 cursor-pointer ${
              classificationFilter === "NPD"
                ? "bg-rose-600 text-white shadow-xs"
                : "bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-800/60 hover:bg-rose-100 dark:hover:bg-rose-900/50"
            }`}
          >
            <span>🔬 NPD Traceability</span>
          </button>
        </div>

        {/* Top Search & Filter */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div className="md:col-span-3">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                fetchTracking(searchTerm);
              }}
              className="flex gap-2"
            >
              <div className="relative flex-1">
                <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
                <input
                  type="text"
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Enter WO number (e.g. WO-1001, WO-1008)..."
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-10 pr-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none font-mono font-bold"
                />
              </div>
              <button
                type="submit"
                disabled={loading}
                className="rounded-xl bg-blue-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 transition-colors cursor-pointer"
              >
                {loading ? "Tracking..." : "Track WO"}
              </button>
            </form>
          </div>

          <div>
            <select
              value={selectedWO}
              onChange={(e) => fetchTracking(e.target.value)}
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 font-mono font-bold focus:outline-none"
            >
              {wosList.length === 0 ? (
                <option value="">No {classificationFilter === "ALL" ? "" : classificationFilter} WOs found</option>
              ) : (
                wosList.map((w) => (
                  <option key={w.wo_number} value={w.wo_number}>
                    {w.classification?.toUpperCase() === "NPD" ? "🔬 [NPD] " : ""}{w.wo_number} — {w.current_stage} ({w.customer_code})
                  </option>
                ))
              )}
            </select>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {woData && (
          <div className="space-y-6">
            {/* WO Overview Header Card */}
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm">
              <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-6 pb-6 border-b border-zinc-100 dark:border-zinc-800">
                <div className="flex items-start gap-4">
                  <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400 font-mono font-extrabold text-base shadow-sm">
                    WO
                  </div>
                  <div>
                    <div className="flex items-center gap-2.5">
                      <h2 className="text-xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                        {woData.wo_number}
                      </h2>
                      <Badge variant={getRAGVariant(woData.delivery_risk)}>
                        {woData.status.toUpperCase()}
                      </Badge>
                      <Badge variant={woData.shortfall === "YES" ? "red" : "green"}>
                        Shortfall: {woData.shortfall}
                      </Badge>
                      {woData.classification?.toUpperCase() === "NPD" ? (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-700 dark:bg-rose-950/80 dark:text-rose-300 border border-rose-300 dark:border-rose-800">
                          🔬 NPD Traceability
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold bg-emerald-100 text-emerald-700 dark:bg-emerald-950/80 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
                          🏭 Production Series
                        </span>
                      )}
                      {Boolean((woData as any).excess_qty && (woData as any).excess_qty > 0) && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-200 border border-amber-300 dark:border-amber-700">
                          ⚠️ F1 Excess: +{(woData as any).excess_qty} pcs
                        </span>
                      )}
                      {Boolean((woData as any).shortfall_qty && (woData as any).shortfall_qty > 0) && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-200 border border-rose-300 dark:border-rose-700" title={(woData as any).shortfall_reason || "Shortfall recorded"}>
                          ⚠️ F1 Shortfall: -{(woData as any).shortfall_qty} pcs{(woData as any).shortfall_reason ? ` (${(woData as any).shortfall_reason})` : ""}
                        </span>
                      )}
                      {f1Remaining > 0 && (
                        <button
                          type="button"
                          onClick={handleOpenShortfallModal}
                          className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-extrabold bg-amber-500 hover:bg-amber-600 text-white shadow-xs transition cursor-pointer"
                          title="Declare shortfall on remaining F1 material and auto-create Patch WO"
                        >
                          <AlertTriangle className="h-3.5 w-3.5" />
                          <span>⚠️ Declare F1 Shortfall ({f1Remaining} pcs)</span>
                        </button>
                      )}
                    </div>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
                      Part: <strong className="text-zinc-800 dark:text-zinc-200">{woData.customer_part_number || woData.part_number}</strong>
                      {woData.customer_part_number && woData.customer_part_number !== woData.part_number && (
                        <span className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono ml-1.5">(Internal: {woData.part_number})</span>
                      )}
                      {" "}— {woData.part_name || "Precision Engineered Component"} ({woData.grade || "Alloy"})
                    </p>
                  </div>
                </div>

                {/* Header Metrics */}
                <div className="flex flex-wrap items-center gap-6 text-xs">
                  <div>
                    <span className="text-zinc-400 text-[10px] uppercase font-bold">Customer PO</span>
                    <p className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{woData.customer_po}</p>
                    <p className="text-[10px] text-zinc-500 truncate max-w-[140px]">{woData.customer_name}</p>
                  </div>

                  <div>
                    <span className="text-zinc-400 text-[10px] uppercase font-bold">Planned Target</span>
                    <p className="font-extrabold text-zinc-900 dark:text-zinc-100 text-sm">{woData.physical_wo_qty} pcs</p>
                    <p className="text-[10px] text-zinc-500">Released Qty</p>
                  </div>

                  <div>
                    <span className="text-zinc-400 text-[10px] uppercase font-bold">Match Size</span>
                    <p className="font-extrabold text-purple-600 text-sm">{woData.match_size ?? "—"} pcs</p>
                    <p className="text-[10px] text-zinc-500">Max Batch Size</p>
                  </div>

                  <div>
                    <span className="text-zinc-400 text-[10px] uppercase font-bold flex items-center gap-1">
                      <Flame className="h-3 w-3 text-amber-500" /> Heat Number
                    </span>
                    <p className="font-mono font-bold text-amber-600 dark:text-amber-400 text-sm">
                      {woData.heat_number || "Not assigned"}
                    </p>
                    <p className="text-[10px] text-zinc-500">Melt / Heat Batch</p>
                  </div>

                  <div>
                    <span className="text-zinc-400 text-[10px] uppercase font-bold">Active Stage</span>
                    <p className="font-extrabold text-blue-600 text-sm font-mono">{woData.current_stage}</p>
                    <p className="text-[10px] text-emerald-600 font-bold">{woData.available_wip} pcs available</p>
                  </div>

                  <div>
                    <span className="text-zinc-400 text-[10px] uppercase font-bold">Cumulative Yield</span>
                    <p className="font-extrabold text-emerald-600 text-sm">{woData.yield_pct}%</p>
                    <p className="text-[10px] text-zinc-500">{woData.total_rejected} scrap</p>
                  </div>
                </div>
              </div>

              {/* VISUAL PROCESS TIMELINE */}
              <div className="pt-6">
                <div className="flex items-center justify-between mb-4">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                    Dynamic Route Pipeline & Live Stage Balances
                  </h4>
                  <span className="text-xs font-mono text-zinc-500">
                    Route: {woData.route_string || woData.timeline.map((s: any) => s.stage).join(" ➔ ")}
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
                  {woData.timeline.map((step: any) => {
                    const isDone = step.is_completed;
                    const isCurrent = step.is_current;

                    return (
                      <div
                        key={step.stage}
                        className={`relative rounded-xl border p-3.5 transition-all ${
                          isCurrent
                            ? "border-blue-500 bg-blue-50/60 dark:bg-blue-950/40 shadow-md ring-2 ring-blue-500/20"
                            : isDone
                            ? "border-emerald-500/40 bg-emerald-50/30 dark:bg-emerald-950/20"
                            : "border-zinc-200 dark:border-zinc-800/80 bg-zinc-50/40 dark:bg-zinc-950/40 opacity-70"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono text-xs font-extrabold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                            {isCurrent && <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />}
                            <span>{step.stage}</span>
                          </span>
                          <Badge
                            variant={
                              step.is_completed
                                ? "green"
                                : isCurrent
                                ? "blue"
                                : "gray"
                            }
                            size="sm"
                          >
                            {step.is_completed ? "DONE" : isCurrent ? "ACTIVE" : "PENDING"}
                          </Badge>
                        </div>

                        <div className="mt-3 space-y-1 text-[11px]">
                          <div className="flex justify-between">
                            <span className="text-zinc-400">Target:</span>
                            <span className="font-bold text-zinc-800 dark:text-zinc-200">{step.target_qty}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-400">OK Done:</span>
                            <span className="font-bold text-emerald-600">{step.ok_completed_qty}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-400">On-Hand WIP:</span>
                            <span className="font-bold text-blue-600">{step.on_hand_wip}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-zinc-400">Rejections:</span>
                            <span className={`font-bold ${step.rejected_qty > 0 ? "text-rose-600" : "text-zinc-400"}`}>
                              {step.rejected_qty}
                            </span>
                          </div>
                        </div>

                        {step.machine && (
                          <div className="mt-2 pt-2 border-t border-zinc-200/50 dark:border-zinc-800 text-[10px] text-zinc-400 flex items-center gap-1">
                            <Cpu className="h-3 w-3" />
                            <span className="truncate">{step.machine}</span>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Stage Inventory Breakdown Table */}
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm">
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 mb-4 flex items-center gap-2">
                <Layers className="h-4 w-4 text-blue-600" />
                <span>Stage-Wise Manufacturing Inventory Breakdown (Zero Cumulative Distortion)</span>
              </h3>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[10px] font-bold">
                    <tr>
                      <th className="py-2.5 px-3">Seq</th>
                      <th className="py-2.5 px-3">Stage</th>
                      <th className="py-2.5 px-3 text-right">Target Qty</th>
                      <th className="py-2.5 px-3 text-right text-emerald-600">OK Completed</th>
                      <th className="py-2.5 px-3 text-right text-blue-600">On-Hand WIP</th>
                      <th className="py-2.5 px-3 text-right text-rose-600">Scrap / Rejection</th>
                      <th className="py-2.5 px-3">Status</th>
                      <th className="py-2.5 px-3">Assigned Cell</th>
                      <th className="py-2.5 px-3">Last Operator</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                    {woData.timeline.map((stg: any) => (
                      <tr key={stg.stage} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                        <td className="py-3 px-3 text-zinc-400 font-mono">{stg.sequence}</td>
                        <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">{stg.stage}</td>
                        <td className="py-3 px-3 text-right text-zinc-700 dark:text-zinc-300 font-mono font-bold">{stg.target_qty}</td>
                        <td className="py-3 px-3 text-right text-emerald-600 font-mono font-bold">{stg.ok_completed_qty}</td>
                        <td className="py-3 px-3 text-right text-blue-600 font-mono font-bold">{stg.on_hand_wip}</td>
                        <td className="py-3 px-3 text-right font-mono font-bold text-rose-600">{stg.rejected_qty}</td>
                        <td className="py-3 px-3">
                          <Badge variant={getRAGVariant(stg.rag_status)} size="sm">
                            {stg.rag_status}
                          </Badge>
                        </td>
                        <td className="py-3 px-3 text-zinc-500">{stg.machine || "—"}</td>
                        <td className="py-3 px-3 text-zinc-500">{stg.operator || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* IMMUTABLE TRANSACTION HISTORY TABLE */}
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <History className="h-5 w-5 text-blue-600" />
                  <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                    Immutable Transaction History Ledger
                  </h3>
                </div>
                <span className="text-xs text-zinc-400">
                  {woData.transactions ? `${woData.transactions.length} recorded events` : "0 recorded events"}
                </span>
              </div>

              {woData.transactions && woData.transactions.length > 0 ? (
                <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-50 dark:bg-zinc-950/80 border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                      <tr>
                        <th className="py-2.5 px-3">Timestamp</th>
                        <th className="py-2.5 px-3">Type</th>
                        <th className="py-2.5 px-3">Stage / Route</th>
                        <th className="py-2.5 px-3">Heat #</th>
                        <th className="py-2.5 px-3 text-right">Good Qty</th>
                        <th className="py-2.5 px-3 text-right">Rej Qty</th>
                        <th className="py-2.5 px-3">Machine</th>
                        <th className="py-2.5 px-3">Operator</th>
                        <th className="py-2.5 px-3">Shift</th>
                        <th className="py-2.5 px-3">Remarks / Client ID</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                      {woData.transactions.map((tx: any) => {
                        const isMove = tx.transaction_type === "STAGE_MOVEMENT";
                        return (
                          <tr key={tx.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                            <td className="py-2.5 px-3 font-mono text-zinc-500 whitespace-nowrap">
                              {new Date(tx.timestamp).toLocaleString("en-GB", {
                                dateStyle: "short",
                                timeStyle: "medium"
                              })}
                            </td>
                            <td className="py-2.5 px-3">
                              <span
                                className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider ${
                                  isMove
                                    ? "bg-blue-50 text-blue-700 dark:bg-blue-950/40 dark:text-blue-300 border border-blue-200 dark:border-blue-900"
                                    : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900"
                                }`}
                              >
                                {isMove ? "MOVEMENT" : "PROD ENTRY"}
                              </span>
                            </td>
                            <td className="py-2.5 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                              {isMove ? `${tx.stage} ➔ ${tx.to_stage}` : `Stage ${tx.stage}`}
                            </td>
                            <td className="py-2.5 px-3 font-mono font-bold text-amber-600 dark:text-amber-400">
                              {tx.heat_number || woData.heat_number || "—"}
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-emerald-600">
                              {tx.quantity}
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-rose-600">
                              {tx.rejected_qty > 0 ? tx.rejected_qty : "—"}
                            </td>
                            <td className="py-2.5 px-3 text-zinc-600 dark:text-zinc-400">{tx.machine_id || "—"}</td>
                            <td className="py-2.5 px-3 text-zinc-600 dark:text-zinc-400">{tx.operator_name || "—"}</td>
                            <td className="py-2.5 px-3 text-zinc-500">{tx.shift || "—"}</td>
                            <td className="py-2.5 px-3 text-zinc-400 font-mono text-[11px] truncate max-w-[200px]">
                              {tx.remarks || tx.client_request_id || "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="p-6 text-center rounded-xl bg-zinc-50 dark:bg-zinc-950/40 border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-400">
                  No movement or production transactions recorded yet for this Work Order.
                </div>
              )}
            </div>
          </div>
        )}

        {/* Shortfall Success Alert */}
        {shortfallSuccessMsg && (
          <div className="rounded-2xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 p-4 flex items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
              <div>
                <p className="text-xs font-extrabold text-emerald-900 dark:text-emerald-100">{shortfallSuccessMsg}</p>
                {patchWONumber && (
                  <p className="text-[11px] text-emerald-700 dark:text-emerald-300">
                    New Patch WO: <strong className="font-mono">{patchWONumber}</strong> is now live and auto-released for casting.
                  </p>
                )}
              </div>
            </div>
            {patchWONumber && (
              <button
                type="button"
                onClick={() => fetchTracking(patchWONumber)}
                className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-bold transition shrink-0"
              >
                Track {patchWONumber}
              </button>
            )}
          </div>
        )}

        {/* Shortfall Declaration Modal */}
        {isShortfallModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in duration-150">
            <div className="w-full max-w-lg rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 px-6 py-4 bg-amber-50/50 dark:bg-amber-950/20">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                    <AlertTriangle className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-base font-extrabold text-zinc-900 dark:text-zinc-50">
                      Declare F1 Shortfall &amp; Create Patch WO
                    </h3>
                    <p className="text-[11px] text-zinc-500">
                      Work Order: <strong className="font-mono text-zinc-800 dark:text-zinc-200">{woData?.wo_number}</strong>
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setIsShortfallModalOpen(false)}
                  className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="p-6 space-y-4 text-xs">
                <div className="grid grid-cols-3 gap-2 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-950 border border-zinc-200/80 dark:border-zinc-800 text-center font-mono">
                  <div>
                    <span className="text-[10px] text-zinc-400 uppercase font-sans font-bold block">Planned Target</span>
                    <span className="font-bold text-zinc-800 dark:text-zinc-200 text-sm">{woData?.physical_wo_qty ?? 0} pcs</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-emerald-600 uppercase font-sans font-bold block">F1 OK Done</span>
                    <span className="font-bold text-emerald-600 text-sm">{f1Timeline?.ok_completed_qty ?? 0} pcs</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-amber-600 uppercase font-sans font-bold block">Remaining</span>
                    <span className="font-bold text-amber-600 text-sm">{f1Remaining} pcs</span>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                    Shortfall Quantity to Close Out (pcs) *
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={f1Remaining}
                    value={shortfallDeclareQty}
                    onChange={(e) => setShortfallDeclareQty(e.target.value === "" ? "" : Number(e.target.value))}
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3.5 py-2.5 text-sm font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:border-amber-500 focus:outline-none"
                  />
                  <p className="mt-1 text-[11px] text-zinc-500">
                    Current WO will be finalized at {Math.max((woData?.physical_wo_qty || 0) - (Number(shortfallDeclareQty) || 0), 0)} pcs.
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-bold text-rose-600 dark:text-rose-400 mb-1">
                    Reason for Shortfall / Less Production * (Mandatory)
                  </label>
                  <input
                    type="text"
                    required
                    value={shortfallDeclareReason}
                    onChange={(e) => setShortfallDeclareReason(e.target.value)}
                    placeholder="e.g. Ladle metal short, mould leak, sand collapse, furnace heat balance ended..."
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 focus:border-rose-500 focus:outline-none"
                  />
                </div>

                <div className="p-3.5 rounded-xl border border-purple-200 dark:border-purple-800/80 bg-purple-50/50 dark:bg-purple-950/20">
                  <label className="flex items-start gap-2.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createPatchWO}
                      onChange={(e) => setCreatePatchWO(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-purple-300 text-purple-600 focus:ring-purple-500 cursor-pointer"
                    />
                    <div className="space-y-0.5">
                      <span className="font-extrabold text-purple-900 dark:text-purple-200">
                        Automatically create New Patch Work Order for shortfall quantity
                      </span>
                      <p className="text-[11px] text-purple-700 dark:text-purple-300">
                        Generates a new sequential Work Order ID linked to the same OAR and auto-releases it so the shop floor can immediately cast the remaining pieces.
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2.5 border-t border-zinc-100 dark:border-zinc-800 px-6 py-4 bg-zinc-50 dark:bg-zinc-950">
                <button
                  type="button"
                  onClick={() => setIsShortfallModalOpen(false)}
                  className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={declaringShortfall || !shortfallDeclareReason.trim()}
                  onClick={handleConfirmShortfall}
                  className="rounded-xl bg-amber-600 hover:bg-amber-500 disabled:opacity-50 px-5 py-2 text-xs font-extrabold text-white shadow-md shadow-amber-500/20 transition cursor-pointer flex items-center gap-1.5"
                >
                  {declaringShortfall ? (
                    <>
                      <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                      <span>Closing &amp; Spawning Patch WO...</span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span>Confirm Shortfall &amp; Create Patch WO</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

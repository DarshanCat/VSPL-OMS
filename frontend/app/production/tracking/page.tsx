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
  FileCheck
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getWorkOrders, getWorkOrderTracking } from "@/lib/api";

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
  const [searchTerm, setSearchTerm] = useState(initialWO);
  const [selectedWO, setSelectedWO] = useState<string>(initialWO);
  const [loading, setLoading] = useState(false);
  const [woData, setWoData] = useState<any>(null);
  const [wosList, setWosList] = useState<any[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getWorkOrders({ limit: 50 })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setWosList(data);
        }
      })
      .catch(() => {});
    fetchTracking(initialWO);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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
              {wosList.map((w) => (
                <option key={w.wo_number} value={w.wo_number}>
                  {w.wo_number} — {w.current_stage} ({w.customer_code})
                </option>
              ))}
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
                    </div>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
                      Part: <strong className="text-zinc-800 dark:text-zinc-200">{woData.part_number}</strong> — {woData.part_name || "Precision Engineered Component"} ({woData.grade || "Alloy"})
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
      </div>
    </AppShell>
  );
}

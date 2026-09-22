"use client";
import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Search,
  Plus,
  RefreshCw,
  ArrowRightLeft,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Ban,
  PackagePlus,
  PackageX,
  Flame
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import { DEFECT_CODES } from "@/lib/rejectionReasons";
import {
  getRejections, getRejectionSummary, getRejectionDetail,
  createExcessOrNonMoving, createDisposition, createMeltingEntry, getWorkOrders
} from "@/lib/api";

const SOURCE_TYPES = ["REJECTION", "EXCESS_PRODUCTION", "NON_MOVING", "MANUAL"];
const STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];
const DISPOSITION_ACTIONS = [
  { value: "CONVERT_PART", label: "Convert to Another Part", requiresWO: true },
  { value: "SAME_PART", label: "Convert to Same Part", requiresWO: true },
  { value: "CWO", label: "Route to CWO (Conversion WO)", requiresWO: true },
  { value: "SCRAP", label: "Scrap", requiresWO: false },
  { value: "DEVIATION_ACCEPT", label: "Deviation — Accept / Concession", requiresWO: false },
];

function sourceTypeBadge(sourceType: string) {
  if (sourceType === "EXCESS_PRODUCTION") return "amber";
  if (sourceType === "NON_MOVING") return "purple";
  if (sourceType === "MANUAL") return "cyan";
  return "red";
}

export default function RejectionTrackingPage() {
  const [records, setRecords] = useState<any[]>([]);
  const [summary, setSummary] = useState<any>(null);
  const [wos, setWos] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // Filters
  const [search, setSearch] = useState("");
  const [sourceTypeFilter, setSourceTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  // Detail drawer
  const [selectedNC, setSelectedNC] = useState<string | null>(null);
  const [detail, setDetail] = useState<any>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // Disposition modal -- rows support 1-to-many: multiple destination parts (and/or
  // scrap) dispositioned from the same source record in one batch, e.g.
  // Part A (100) -> Part B (60) + Part C (30) + Scrap (10).
  const [showDispositionModal, setShowDispositionModal] = useState(false);
  const [dispRows, setDispRows] = useState<any[]>([]);
  const [dispReason, setDispReason] = useState("");
  const [dispError, setDispError] = useState("");
  const [dispSubmitting, setDispSubmitting] = useState(false);

  const blankRow = () => ({
    action: "CONVERT_PART", quantity: "", destOAR: "", entryStage: "F1", cwoNumber: ""
  });

  // Send-to-Melting modal -- physical fulfillment of an already-decided SCRAP
  // disposition. Recording this never re-decides or re-authorizes the disposition.
  const [showMeltingModal, setShowMeltingModal] = useState(false);
  const [meltingDisposition, setMeltingDisposition] = useState<any>(null);
  const [meltingDestination, setMeltingDestination] = useState("");
  const [meltingRemarks, setMeltingRemarks] = useState("");
  const [meltingError, setMeltingError] = useState("");
  const [meltingSubmitting, setMeltingSubmitting] = useState(false);

  // Excess / Non-moving modal
  const [showExcessModal, setShowExcessModal] = useState(false);
  const [excessWO, setExcessWO] = useState("");
  const [excessType, setExcessType] = useState<"EXCESS_PRODUCTION" | "NON_MOVING">("EXCESS_PRODUCTION");
  const [excessQty, setExcessQty] = useState<number | "">("");
  const [excessReason, setExcessReason] = useState("");
  const [excessSubmitting, setExcessSubmitting] = useState(false);
  const [excessError, setExcessError] = useState("");

  const loadData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [recData, sumData, wData] = await Promise.all([
        getRejections({
          search: search.trim() || undefined,
          source_type: sourceTypeFilter || undefined,
          status: statusFilter || undefined,
          limit: 500
        }),
        getRejectionSummary(),
        getWorkOrders({ limit: 100 })
      ]);
      setRecords(Array.isArray(recData) ? recData : []);
      setSummary(sumData);
      setWos(Array.isArray(wData) ? wData : []);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load Rejection Tracking data.");
    } finally {
      setLoading(false);
    }
  }, [search, sourceTypeFilter, statusFilter]);

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openDetail = async (ncNumber: string) => {
    setSelectedNC(ncNumber);
    setDetailLoading(true);
    try {
      const d = await getRejectionDetail(ncNumber);
      setDetail(d);
    } catch (err: any) {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const openDispositionModal = () => {
    setDispRows([blankRow()]);
    setDispReason("");
    setDispError("");
    setShowDispositionModal(true);
  };

  const addDispRow = () => setDispRows((prev) => [...prev, blankRow()]);
  const removeDispRow = (idx: number) => setDispRows((prev) => prev.filter((_, i) => i !== idx));
  const updateDispRow = (idx: number, patch: any) =>
    setDispRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));

  const dispRowsTotal = dispRows.reduce((sum, r) => sum + (Number(r.quantity) || 0), 0);

  const submitDisposition = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedNC) return;
    setDispError("");

    if (dispRows.length === 0) {
      setDispError("Add at least one destination.");
      return;
    }
    for (const row of dispRows) {
      const actionDef = DISPOSITION_ACTIONS.find((a) => a.value === row.action);
      if (!row.quantity || Number(row.quantity) <= 0) {
        setDispError("Every row must have a quantity greater than 0.");
        return;
      }
      if (actionDef?.requiresWO && (!row.destOAR || !row.entryStage || !row.cwoNumber)) {
        setDispError(`Destination OAR, Entry Stage, and Conversion WO Number are required for "${actionDef.label}".`);
        return;
      }
    }
    if (detail && dispRowsTotal > detail.balance.remaining_qty) {
      setDispError(`Total quantity across all rows (${dispRowsTotal}) exceeds the remaining balance (${detail.balance.remaining_qty}).`);
      return;
    }

    setDispSubmitting(true);
    try {
      // Sequential, not parallel: each call re-validates the live remaining balance,
      // so a later row must see the effect of an earlier row in the same batch.
      for (const row of dispRows) {
        const actionDef = DISPOSITION_ACTIONS.find((a) => a.value === row.action);
        await createDisposition({
          nc_number: selectedNC,
          action: row.action,
          quantity: Number(row.quantity),
          destination_oar_number: actionDef?.requiresWO ? row.destOAR : undefined,
          entry_stage: actionDef?.requiresWO ? row.entryStage : undefined,
          conversion_wo_number: actionDef?.requiresWO ? row.cwoNumber : undefined,
          reason: dispReason || `${row.action} disposition`
        });
      }
      setShowDispositionModal(false);
      await openDetail(selectedNC);
      await loadData();
    } catch (err: any) {
      setDispError(err?.response?.data?.detail || "Failed to record disposition.");
      // Refresh in the background so the drawer reflects whichever rows in this batch
      // already succeeded before the failing one.
      openDetail(selectedNC);
    } finally {
      setDispSubmitting(false);
    }
  };

  const openMeltingModal = (disposition: any) => {
    setMeltingDisposition(disposition);
    setMeltingDestination("");
    setMeltingRemarks("");
    setMeltingError("");
    setShowMeltingModal(true);
  };

  const submitMelting = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!meltingDisposition || !selectedNC) return;
    setMeltingError("");
    setMeltingSubmitting(true);
    try {
      await createMeltingEntry({
        disposition_id: meltingDisposition.id,
        melting_destination: meltingDestination || undefined,
        remarks: meltingRemarks || undefined
      });
      setShowMeltingModal(false);
      await openDetail(selectedNC);
    } catch (err: any) {
      setMeltingError(err?.response?.data?.detail || "Failed to record melting entry.");
    } finally {
      setMeltingSubmitting(false);
    }
  };

  const submitExcess = async (e: React.FormEvent) => {
    e.preventDefault();
    setExcessError("");
    if (!excessWO || !excessQty || Number(excessQty) <= 0 || !excessReason) {
      setExcessError("Work Order, Quantity, and Reason are all required.");
      return;
    }
    setExcessSubmitting(true);
    try {
      await createExcessOrNonMoving({
        wo_number: excessWO,
        source_type: excessType,
        qty: Number(excessQty),
        reason: excessReason
      });
      setShowExcessModal(false);
      setExcessWO("");
      setExcessQty("");
      setExcessReason("");
      await loadData();
    } catch (err: any) {
      setExcessError(err?.response?.data?.detail || "Failed to record.");
    } finally {
      setExcessSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-rose-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Quality & Material Disposition
              </span>
              <span className="text-xs text-zinc-400">Rejected / Excess / Non-Moving Material</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Rejection Tracking
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Track rejected, excess, and non-moving material from production through final disposition — conversion,
              scrap, or acceptance. Conversion is a disposition decision, never a production route stage.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowExcessModal(true)}
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              <PackagePlus className="h-3.5 w-3.5 text-amber-600" />
              <span>Log Excess / Non-Moving</span>
            </button>
            <button
              onClick={loadData}
              className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-rose-500 transition-colors cursor-pointer"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Summary Cards */}
        {summary && (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
            {[
              { label: "Total Rejected", value: summary.total_rejected, color: "text-rose-600" },
              { label: "Total Converted", value: summary.total_converted, color: "text-blue-600" },
              { label: "Total Scrap", value: summary.total_scrap, color: "text-zinc-500" },
              { label: "Total Remaining", value: summary.total_remaining, color: "text-amber-600" },
              { label: "Total Excess", value: summary.total_excess, color: "text-amber-600" },
              { label: "Total Non-Moving", value: summary.total_non_moving, color: "text-purple-600" },
            ].map((c) => (
              <div
                key={c.label}
                className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm"
              >
                <span className="text-[10px] uppercase font-bold text-zinc-400">{c.label}</span>
                <p className={`text-xl font-extrabold font-mono mt-1 ${c.color}`}>{c.value} pcs</p>
              </div>
            ))}
          </div>
        )}

        {/* Filters */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              loadData();
            }}
            className="relative md:col-span-2"
          >
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search Rejection ID, WO, OAR, Customer..."
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-10 pr-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-rose-500 focus:outline-none font-medium"
            />
          </form>
          <select
            value={sourceTypeFilter}
            onChange={(e) => {
              setSourceTypeFilter(e.target.value);
            }}
            className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 font-semibold focus:outline-none"
          >
            <option value="">All Source Types</option>
            {SOURCE_TYPES.map((s) => (
              <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
            ))}
          </select>
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 font-semibold focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="Open">Open</option>
            <option value="Closed">Closed</option>
          </select>
          <button
            onClick={loadData}
            className="md:col-span-4 justify-self-start rounded-xl bg-zinc-900 dark:bg-zinc-100 dark:text-zinc-900 text-white px-4 py-2 text-xs font-bold hover:opacity-90 transition-opacity cursor-pointer"
          >
            Apply Filters
          </button>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-2.5 px-3">Rejection ID</th>
                  <th className="py-2.5 px-3">WO</th>
                  <th className="py-2.5 px-3">Part</th>
                  <th className="py-2.5 px-3">Stage</th>
                  <th className="py-2.5 px-3 text-right">Qty</th>
                  <th className="py-2.5 px-3">Reason</th>
                  <th className="py-2.5 px-3">Source Type</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Disposition</th>
                  <th className="py-2.5 px-3">Created At</th>
                  <th className="py-2.5 px-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {loading ? (
                  <tr>
                    <td colSpan={11} className="py-10 text-center text-zinc-400">Loading...</td>
                  </tr>
                ) : records.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="py-10 text-center text-zinc-400">No records match your search.</td>
                  </tr>
                ) : (
                  records.map((r) => (
                    <tr key={r.nc_number} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                      <td className="py-2.5 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">{r.nc_number}</td>
                      <td className="py-2.5 px-3 font-mono text-zinc-700 dark:text-zinc-300">{r.wo_number}</td>
                      <td className="py-2.5 px-3 text-zinc-600 dark:text-zinc-400">{r.part_number || "—"}</td>
                      <td className="py-2.5 px-3 font-mono">{r.stage || "—"}</td>
                      <td className="py-2.5 px-3 text-right font-mono font-bold">
                        {r.remaining_qty}/{r.qty}
                      </td>
                      <td className="py-2.5 px-3 text-zinc-500">{r.reason || "—"}</td>
                      <td className="py-2.5 px-3">
                        <Badge variant={sourceTypeBadge(r.source_type) as any} size="sm">
                          {r.source_type.replace(/_/g, " ")}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3">
                        <Badge variant={r.status === "Closed" ? "green" : "amber"} size="sm">
                          {r.status}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3 text-zinc-500">{r.disposition || "—"}</td>
                      <td className="py-2.5 px-3 text-zinc-400 whitespace-nowrap">
                        {new Date(r.date_raised).toLocaleDateString("en-GB")}
                      </td>
                      <td className="py-2.5 px-3">
                        <button
                          onClick={() => openDetail(r.nc_number)}
                          className="text-rose-600 hover:underline font-bold"
                        >
                          View
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Legacy compatibility note */}
        <p className="text-[11px] text-zinc-400">
          Looking for the old QA Non-Conformance investigation workflow (root cause / MRB notes)? That data is
          preserved here — every Rejection Tracking record is the same underlying NC record, extended with the
          disposition ledger below.
        </p>
      </div>

      {/* Detail Drawer / Modal */}
      <Modal
        isOpen={!!selectedNC}
        onClose={() => { setSelectedNC(null); setDetail(null); }}
        title={selectedNC || ""}
        subtitle="Rejection Tracking Detail"
        maxWidth="2xl"
      >
        {detailLoading ? (
          <div className="py-10 text-center text-zinc-400 text-xs">Loading...</div>
        ) : !detail ? (
          <div className="py-10 text-center text-zinc-400 text-xs">Record not found.</div>
        ) : (
          <div className="space-y-6">
            {/* SOURCE */}
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400 mb-2">Source</h4>
              <div className="grid grid-cols-2 gap-3 text-xs rounded-xl bg-zinc-50 dark:bg-zinc-950/50 p-4 border border-zinc-200 dark:border-zinc-800">
                <div><span className="text-zinc-400">WO:</span> <span className="font-mono font-bold">{detail.source.wo_number}</span></div>
                <div><span className="text-zinc-400">OAR:</span> <span className="font-mono font-bold">{detail.source.oar_number || "—"}</span></div>
                <div><span className="text-zinc-400">Part:</span> <span className="font-bold">{detail.source.part_number || "—"}</span></div>
                <div><span className="text-zinc-400">Customer:</span> <span className="font-bold">{detail.source.customer_name || "—"}</span></div>
                <div><span className="text-zinc-400">Production Stage:</span> <span className="font-mono font-bold">{detail.source.production_stage || "—"}</span></div>
                <div><span className="text-zinc-400">Source Type:</span> <Badge variant={sourceTypeBadge(detail.source.source_type) as any} size="sm">{detail.source.source_type.replace(/_/g, " ")}</Badge></div>
                <div><span className="text-zinc-400">Original Qty:</span> <span className="font-mono font-bold">{detail.source.original_quantity}</span></div>
                <div><span className="text-zinc-400">Reason:</span> <span className="font-bold">{detail.source.reason || "—"}</span></div>
              </div>
            </div>

            {/* DISPOSITION HISTORY */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400">Disposition History</h4>
                {detail.balance.remaining_qty > 0 && (
                  <button
                    onClick={openDispositionModal}
                    className="flex items-center gap-1 rounded-lg bg-rose-600 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-rose-500 cursor-pointer"
                  >
                    <Plus className="h-3 w-3" />
                    <span>Add Disposition</span>
                  </button>
                )}
              </div>
              {detail.disposition_history.length === 0 ? (
                <div className="text-[11px] text-zinc-400 rounded-xl border border-zinc-200 dark:border-zinc-800 p-4 text-center">
                  No disposition recorded yet.
                </div>
              ) : (
                <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full text-left text-[11px]">
                    <thead className="bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[9px] font-bold">
                      <tr>
                        <th className="py-2 px-3">Date</th>
                        <th className="py-2 px-3">User</th>
                        <th className="py-2 px-3">Action</th>
                        <th className="py-2 px-3 text-right">Qty</th>
                        <th className="py-2 px-3">Destination</th>
                        <th className="py-2 px-3">Melting</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60">
                      {detail.disposition_history.map((d: any) => (
                        <tr key={d.id}>
                          <td className="py-2 px-3 text-zinc-500 whitespace-nowrap">
                            {new Date(d.created_at).toLocaleString("en-GB", { dateStyle: "short", timeStyle: "short" })}
                          </td>
                          <td className="py-2 px-3">{d.authorized_by_name || "—"}</td>
                          <td className="py-2 px-3 font-bold">{d.action.replace(/_/g, " ")}</td>
                          <td className="py-2 px-3 text-right font-mono font-bold">{d.quantity}</td>
                          <td className="py-2 px-3 font-mono">
                            {d.conversion_wo_number ? (
                              <Link href={`/production/tracking?wo=${d.conversion_wo_number}`} className="text-blue-600 hover:underline">
                                {d.conversion_wo_number}
                              </Link>
                            ) : "—"}
                          </td>
                          <td className="py-2 px-3">
                            {d.action !== "SCRAP" ? (
                              "—"
                            ) : d.melting_status === "SENT_FOR_MELTING" ? (
                              <span className="inline-flex items-center gap-1 text-orange-600 font-bold">
                                <Flame className="h-3 w-3" />
                                <span>Sent{d.melting_destination ? ` (${d.melting_destination})` : ""}</span>
                              </span>
                            ) : (
                              <button
                                onClick={() => openMeltingModal(d)}
                                className="text-orange-600 hover:underline font-bold cursor-pointer"
                              >
                                Send to Melting
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* CURRENT BALANCE */}
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400 mb-2">Current Balance</h4>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 p-3 border border-zinc-200 dark:border-zinc-800 text-center">
                  <span className="block text-[10px] text-zinc-400 uppercase font-bold">Original</span>
                  <span className="font-mono font-extrabold text-base">{detail.balance.original_qty}</span>
                </div>
                <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 p-3 border border-zinc-200 dark:border-zinc-800 text-center">
                  <span className="block text-[10px] text-zinc-400 uppercase font-bold">Consumed</span>
                  <span className="font-mono font-extrabold text-base text-blue-600">{detail.balance.consumed_qty}</span>
                </div>
                <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 p-3 border border-zinc-200 dark:border-zinc-800 text-center">
                  <span className="block text-[10px] text-zinc-400 uppercase font-bold">Remaining</span>
                  <span className="font-mono font-extrabold text-base text-amber-600">{detail.balance.remaining_qty}</span>
                </div>
              </div>
            </div>

            {/* FINAL OUTCOME */}
            <div>
              <h4 className="text-xs font-bold uppercase tracking-wider text-zinc-400 mb-2">Final Outcome</h4>
              <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 text-[11px]">
                {[
                  { label: "Another Part", value: detail.final_outcome.another_part_qty },
                  { label: "Same Part", value: detail.final_outcome.same_part_qty },
                  { label: "CWO", value: detail.final_outcome.cwo_qty },
                  { label: "Scrap", value: detail.final_outcome.scrap_qty },
                  { label: "Remaining", value: detail.final_outcome.remaining_qty },
                ].map((o) => (
                  <div key={o.label} className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 p-2.5 border border-zinc-200 dark:border-zinc-800 text-center">
                    <span className="block text-[9px] text-zinc-400 uppercase font-bold">{o.label}</span>
                    <span className="font-mono font-bold">{o.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </Modal>

      {/* Disposition Modal */}
      <Modal
        isOpen={showDispositionModal}
        onClose={() => setShowDispositionModal(false)}
        title="Record Disposition"
        subtitle={selectedNC || ""}
      >
        <form onSubmit={submitDisposition} className="space-y-4">
          {dispError && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
              {dispError}
            </div>
          )}

          <p className="text-[10px] text-zinc-400">
            Convert / Same Part / CWO require planning authorization. Scrap / Deviation require quality authorization
            (enforced server-side, independent of this form).
          </p>

          <div className="space-y-4">
            {dispRows.map((row, idx) => {
              const actionDef = DISPOSITION_ACTIONS.find((a) => a.value === row.action);
              return (
                <div key={idx} className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3.5 space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-bold uppercase text-zinc-400">Destination {idx + 1}</span>
                    {dispRows.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeDispRow(idx)}
                        className="text-[10px] font-bold text-rose-500"
                      >
                        Remove
                      </button>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Action *</label>
                      <select
                        value={row.action}
                        onChange={(e) => updateDispRow(idx, { action: e.target.value })}
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      >
                        {DISPOSITION_ACTIONS.map((a) => (
                          <option key={a.value} value={a.value}>{a.label}</option>
                        ))}
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Quantity *</label>
                      <input
                        type="number"
                        min={1}
                        value={row.quantity}
                        onChange={(e) => updateDispRow(idx, { quantity: e.target.value })}
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      />
                    </div>
                  </div>

                  {actionDef?.requiresWO && (
                    <>
                      <div>
                        <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Conversion WO Number *</label>
                        <input
                          type="text"
                          value={row.cwoNumber}
                          onChange={(e) => updateDispRow(idx, { cwoNumber: e.target.value })}
                          placeholder="e.g. CWO-0021"
                          className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                        />
                        <p className="text-[10px] text-zinc-400 mt-1">
                          Creates a proper Conversion Work Order using the existing WO ID / route architecture. The
                          destination part (from the OAR below) must have an active Conversion Part Mapping from the
                          source part — enforced server-side.
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <div>
                          <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Destination OAR *</label>
                          <input
                            type="text"
                            value={row.destOAR}
                            onChange={(e) => updateDispRow(idx, { destOAR: e.target.value })}
                            placeholder="e.g. OAR-0001"
                            className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                          />
                        </div>
                        <div>
                          <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Entry Stage *</label>
                          <select
                            value={row.entryStage}
                            onChange={(e) => updateDispRow(idx, { entryStage: e.target.value })}
                            className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                          >
                            {STAGES.map((s) => <option key={s} value={s}>{s}</option>)}
                          </select>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>

          <button
            type="button"
            onClick={addDispRow}
            className="text-[11px] font-bold text-rose-600 hover:underline"
          >
            + Add Destination
          </button>

          <div
            className={`rounded-xl p-3 border text-xs flex items-center justify-between ${
              detail && dispRowsTotal > detail.balance.remaining_qty
                ? "bg-rose-50/50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-900/40"
                : "bg-zinc-50 dark:bg-zinc-950/50 border-zinc-200 dark:border-zinc-800"
            }`}
          >
            <span className="text-zinc-500">
              Total across rows: <strong className="font-mono">{dispRowsTotal}</strong>
              {detail && <> / Remaining: <strong className="font-mono">{detail.balance.remaining_qty}</strong></>}
            </span>
          </div>

          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Reason / Justification *</label>
            <textarea
              value={dispReason}
              onChange={(e) => setDispReason(e.target.value)}
              rows={2}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>

          <button
            type="submit"
            disabled={dispSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-rose-600 py-3 text-xs font-bold text-white shadow-sm hover:bg-rose-500 disabled:opacity-50 transition-colors cursor-pointer"
          >
            <ArrowRightLeft className="h-4 w-4" />
            <span>{dispSubmitting ? "Recording..." : `Record Disposition${dispRows.length > 1 ? "s" : ""}`}</span>
          </button>
        </form>
      </Modal>

      {/* Excess / Non-Moving Modal */}
      <Modal
        isOpen={showExcessModal}
        onClose={() => setShowExcessModal(false)}
        title="Log Excess / Non-Moving Material"
        subtitle="Track material that is not a production rejection"
      >
        <form onSubmit={submitExcess} className="space-y-4">
          {excessError && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
              {excessError}
            </div>
          )}
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Source Type *</label>
            <select
              value={excessType}
              onChange={(e) => setExcessType(e.target.value as any)}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
            >
              <option value="EXCESS_PRODUCTION">Excess Production</option>
              <option value="NON_MOVING">Non-Moving Material</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Work Order *</label>
            <select
              value={excessWO}
              onChange={(e) => setExcessWO(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
            >
              <option value="">Select Work Order...</option>
              {wos.map((w) => (
                <option key={w.wo_number} value={w.wo_number}>{w.wo_number} — {w.customer_code}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Quantity *</label>
            <input
              type="number"
              min={1}
              value={excessQty}
              onChange={(e) => setExcessQty(e.target.value === "" ? "" : Number(e.target.value))}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Reason *</label>
            <textarea
              value={excessReason}
              onChange={(e) => setExcessReason(e.target.value)}
              rows={2}
              placeholder={excessType === "EXCESS_PRODUCTION" ? "e.g. Batch rounding produced 15 pieces above order quantity" : "e.g. Customer has not collected ready goods since dispatch approval"}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={excessSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-amber-600 py-3 text-xs font-bold text-white shadow-sm hover:bg-amber-500 disabled:opacity-50 transition-colors cursor-pointer"
          >
            <PackageX className="h-4 w-4" />
            <span>{excessSubmitting ? "Recording..." : "Log Record"}</span>
          </button>
        </form>
      </Modal>

      {/* Send to Melting Modal -- physical fulfillment only, never a disposition decision */}
      <Modal
        isOpen={showMeltingModal}
        onClose={() => setShowMeltingModal(false)}
        title="Send to Melting"
        subtitle={meltingDisposition ? `Scrap disposition — ${meltingDisposition.quantity} pcs` : ""}
      >
        <form onSubmit={submitMelting} className="space-y-4">
          {meltingError && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
              {meltingError}
            </div>
          )}
          <p className="text-[11px] text-zinc-400">
            This records that the already-approved scrap quantity was physically sent for melting. It does not
            change or re-approve the disposition decision.
          </p>
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Melting Destination / Furnace</label>
            <input
              type="text"
              value={meltingDestination}
              onChange={(e) => setMeltingDestination(e.target.value)}
              placeholder="e.g. Furnace Bay 2"
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Remarks</label>
            <textarea
              value={meltingRemarks}
              onChange={(e) => setMeltingRemarks(e.target.value)}
              rows={2}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>
          <button
            type="submit"
            disabled={meltingSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-orange-600 py-3 text-xs font-bold text-white shadow-sm hover:bg-orange-500 disabled:opacity-50 transition-colors cursor-pointer"
          >
            <Flame className="h-4 w-4" />
            <span>{meltingSubmitting ? "Recording..." : "Confirm Sent for Melting"}</span>
          </button>
        </form>
      </Modal>
    </AppShell>
  );
}

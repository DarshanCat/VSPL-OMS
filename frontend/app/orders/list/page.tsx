"use client";
import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Search,
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  ArrowRight,
  GitBranch,
  Layers,
  AlertTriangle,
  CheckCircle2,
  Boxes,
  RotateCw,
  Plus,
  X
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getOarList, OARListItem, createReplacement, ReplacementResult } from "@/lib/api";

export default function OarWoListPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [oars, setOars] = useState<OARListItem[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Patch / Replacement WO modal state
  const [patchModalOar, setPatchModalOar] = useState<OARListItem | null>(null);
  const [selectedSourceWo, setSelectedSourceWo] = useState<string>("");
  const [patchQty, setPatchQty] = useState<number | "">(1);
  const [patchReason, setPatchReason] = useState<string>("Replacement for shortfall / scrap during production");
  const [patchRemarks, setPatchRemarks] = useState<string>("");
  const [patchSubmitting, setPatchSubmitting] = useState<boolean>(false);
  const [patchError, setPatchError] = useState<string>("");
  const [patchSuccess, setPatchSuccess] = useState<ReplacementResult | null>(null);

  const fetchOars = useCallback(async (searchTerm: string, status: string) => {
    setLoading(true);
    setError("");
    try {
      const data = await getOarList({
        search: searchTerm.trim() || undefined,
        status_filter: status || undefined,
        limit: 200
      });
      setOars(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load OAR & WO list.");
      setOars([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOars("", "");
  }, [fetchOars]);

  const toggleExpand = (oarNumber: string) => {
    setExpanded((prev) => ({ ...prev, [oarNumber]: !prev[oarNumber] }));
  };

  const handleOpenPatchModal = (oar: OARListItem) => {
    setPatchModalOar(oar);
    const defaultSource = oar.work_orders.find((w) => w.wo_type === "ORIGINAL") || oar.work_orders[0];
    setSelectedSourceWo(defaultSource ? defaultSource.wo_number : "");
    setPatchQty(oar.oar_shortfall);
    setPatchReason("Replacement for shortfall / scrap during production");
    setPatchRemarks("");
    setPatchError("");
    setPatchSuccess(null);
  };

  const handleCreatePatchWO = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!patchModalOar) return;
    setPatchError("");
    setPatchSuccess(null);

    const qty = Number(patchQty);
    if (!qty || qty <= 0) {
      setPatchError("Patch WO quantity must be greater than 0.");
      return;
    }
    if (qty > patchModalOar.oar_shortfall) {
      setPatchError(`Patch WO quantity cannot exceed the authoritative shortfall of ${patchModalOar.oar_shortfall} pcs.`);
      return;
    }
    if (!patchReason.trim()) {
      setPatchError("Reason is mandatory.");
      return;
    }

    setPatchSubmitting(true);
    try {
      const res = await createReplacement({
        oar_number: patchModalOar.oar_number,
        source_wo_number: selectedSourceWo || undefined,
        quantity: qty,
        reason: patchReason.trim(),
        remarks: patchRemarks.trim() || undefined,
      });

      setPatchSuccess(res);
      // Re-fetch OAR list in background to immediately update genealogy
      fetchOars(search, statusFilter);
    } catch (err: any) {
      setPatchError(err?.response?.data?.detail || "Failed to create Patch Work Order.");
    } finally {
      setPatchSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Order Tracking &amp; Genealogy
            </span>
            <span className="text-xs text-zinc-400">Authoritative OAR / Patch WO Roll-Up</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            OAR Production Genealogy
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Complete production genealogy across original and patch/replacement Work Orders. Shows authoritative
            production entries, stage rejections, final good contributions, and OAR fulfillment without double-counting.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            fetchOars(search, statusFilter);
          }}
          className="flex flex-col sm:flex-row gap-3"
        >
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search OAR, WO, customer, part, or PO..."
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-10 pr-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none font-medium"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              fetchOars(search, e.target.value);
            }}
            className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 font-semibold focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="accept">Accept</option>
            <option value="hold">Hold</option>
            <option value="reject">Reject</option>
          </select>
          <button
            type="submit"
            disabled={loading}
            className="rounded-xl bg-blue-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 transition-colors cursor-pointer"
          >
            {loading ? "Searching..." : "Search"}
          </button>
          <button
            type="button"
            onClick={() => fetchOars(search, statusFilter)}
            disabled={loading}
            title="Fetch latest production and order data"
            className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer flex items-center gap-1.5"
          >
            <RotateCw className={`h-3.5 w-3.5 ${loading ? "animate-spin text-blue-600" : "text-zinc-500"}`} />
            <span>Refresh</span>
          </button>
        </form>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-2.5 px-3 w-8"></th>
                  <th className="py-2.5 px-3">OAR ID</th>
                  <th className="py-2.5 px-3">Customer</th>
                  <th className="py-2.5 px-3">PO &amp; Part</th>
                  <th className="py-2.5 px-3 text-right">OAR Qty</th>
                  <th className="py-2.5 px-3 text-right">Fulfilled</th>
                  <th className="py-2.5 px-3 text-right">Shortfall</th>
                  <th className="py-2.5 px-3 text-center">WOs (Orig / Patch)</th>
                  <th className="py-2.5 px-3 text-right">Total Produced</th>
                  <th className="py-2.5 px-3 text-right">Total Rejected</th>
                  <th className="py-2.5 px-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {oars.map((oar) => (
                  <React.Fragment key={oar.oar_number}>
                    <tr
                      onClick={() => toggleExpand(oar.oar_number)}
                      className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40 cursor-pointer"
                    >
                      <td className="py-3 px-3 text-zinc-400">
                        {expanded[oar.oar_number] ? (
                          <ChevronDown className="h-3.5 w-3.5 text-blue-600" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </td>
                      <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {oar.oar_number}
                      </td>
                      <td className="py-3 px-3">
                        <div className="text-zinc-800 dark:text-zinc-200">{oar.customer_name}</div>
                        <div className="text-[10px] text-zinc-400 font-mono">{oar.customer_code}</div>
                      </td>
                      <td className="py-3 px-3">
                        <div className="font-mono text-zinc-600 dark:text-zinc-400">{oar.customer_po}</div>
                        <div className="text-[10px] text-zinc-500 dark:text-zinc-400 font-mono">{oar.part_number}</div>
                      </td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {oar.oar_qty}
                      </td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-emerald-600">
                        {oar.oar_fulfilled}
                      </td>
                      <td className="py-3 px-3 text-right font-mono font-bold">
                        <span className={oar.oar_shortfall === 0 ? "text-emerald-600" : "text-rose-600"}>
                          {oar.oar_shortfall}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center font-mono font-semibold text-zinc-700 dark:text-zinc-300">
                        <span className="font-bold">{oar.num_wos}</span>
                        <span className="text-[10px] text-zinc-400 ml-1">
                          ({oar.num_original_wos} orig / {oar.num_patch_wos} patch)
                        </span>
                      </td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-blue-600">
                        {oar.total_produced}
                      </td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-rose-600">
                        {oar.total_rejected}
                      </td>
                      <td className="py-3 px-3">
                        <Badge variant={getRAGVariant(oar.status)} size="sm">
                          {oar.status.toUpperCase()}
                        </Badge>
                      </td>
                    </tr>

                    {expanded[oar.oar_number] && (
                      <tr>
                        <td colSpan={11} className="bg-zinc-50/70 dark:bg-zinc-950/60 p-0 border-y border-zinc-200 dark:border-zinc-800">
                          <div className="p-4 space-y-4">
                            {/* OAR Genealogy Metric Cards */}
                            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 shadow-xs">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-zinc-400 uppercase">
                                  <Boxes className="h-3.5 w-3.5 text-zinc-500" />
                                  <span>OAR Target</span>
                                </div>
                                <div className="mt-1 text-lg font-mono font-extrabold text-zinc-900 dark:text-zinc-50">
                                  {oar.oar_qty} <span className="text-xs font-normal text-zinc-400">pcs</span>
                                </div>
                              </div>

                              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 shadow-xs">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-blue-500 uppercase">
                                  <GitBranch className="h-3.5 w-3.5" />
                                  <span>WOs Created</span>
                                </div>
                                <div className="mt-1 text-lg font-mono font-extrabold text-zinc-900 dark:text-zinc-50">
                                  {oar.num_wos}{" "}
                                  <span className="text-[10px] font-medium text-zinc-400">
                                    ({oar.num_original_wos} orig + {oar.num_patch_wos} patch)
                                  </span>
                                </div>
                              </div>

                              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 shadow-xs">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-blue-600 uppercase">
                                  <Layers className="h-3.5 w-3.5" />
                                  <span>Total Produced</span>
                                </div>
                                <div className="mt-1 text-lg font-mono font-extrabold text-blue-600">
                                  {oar.total_produced} <span className="text-xs font-normal text-zinc-400">pcs</span>
                                </div>
                              </div>

                              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 shadow-xs">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-rose-500 uppercase">
                                  <AlertTriangle className="h-3.5 w-3.5" />
                                  <span>Total Rejections</span>
                                </div>
                                <div className="mt-1 text-lg font-mono font-extrabold text-rose-600">
                                  {oar.total_rejected} <span className="text-xs font-normal text-zinc-400">pcs</span>
                                </div>
                              </div>

                              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 shadow-xs">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-emerald-600 uppercase">
                                  <CheckCircle2 className="h-3.5 w-3.5" />
                                  <span>OAR Fulfilled</span>
                                </div>
                                <div className="mt-1 text-lg font-mono font-extrabold text-emerald-600">
                                  {oar.oar_fulfilled} <span className="text-xs font-normal text-zinc-400">pcs</span>
                                </div>
                              </div>

                              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 shadow-xs">
                                <div className="flex items-center gap-1.5 text-[10px] font-bold text-amber-500 uppercase">
                                  <AlertTriangle className="h-3.5 w-3.5" />
                                  <span>OAR Shortfall</span>
                                </div>
                                <div className="mt-1 text-lg font-mono font-extrabold text-amber-600">
                                  {oar.oar_shortfall} <span className="text-xs font-normal text-zinc-400">pcs</span>
                                </div>
                              </div>
                            </div>

                            {/* WO-level genealogy table */}
                            <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden shadow-xs">
                              <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                  <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
                                    Work Order Genealogy Breakdown
                                  </span>
                                  <span className="text-[10px] text-zinc-400 font-mono">
                                    ({oar.work_orders.length} Work Order{oar.work_orders.length === 1 ? "" : "s"} linked to {oar.oar_number})
                                  </span>
                                </div>

                                {oar.oar_shortfall > 0 && (
                                  <button
                                    type="button"
                                    onClick={() => handleOpenPatchModal(oar)}
                                    className="inline-flex items-center gap-1.5 px-3 py-1 rounded-lg bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold shadow-xs transition-colors cursor-pointer"
                                    title={`Create Patch/Replacement WO for shortfall of ${oar.oar_shortfall} pcs`}
                                  >
                                    <Plus className="h-3.5 w-3.5" />
                                    <span>+ Create Patch WO</span>
                                  </button>
                                )}
                              </div>

                              {oar.work_orders.length === 0 ? (
                                <div className="text-[11px] text-zinc-400 p-4 text-center">
                                  No Work Orders were created for this OAR.
                                </div>
                              ) : (
                                <div className="overflow-x-auto">
                                  <table className="w-full text-left text-[11px]">
                                    <thead className="text-zinc-400 uppercase text-[9px] font-bold bg-zinc-50/50 dark:bg-zinc-950/50 border-b border-zinc-100 dark:border-zinc-800">
                                      <tr>
                                        <th className="py-2 px-2.5">WO ID</th>
                                        <th className="py-2 px-2.5">Type</th>
                                        <th className="py-2 px-2.5">Source WO</th>
                                        <th className="py-2 px-2.5 text-right">Repl Qty</th>
                                        <th className="py-2 px-2.5 text-right">WO Qty</th>
                                        <th className="py-2 px-2.5 text-right">Produced</th>
                                        <th className="py-2 px-2.5 text-right font-bold text-emerald-600">Production OK</th>
                                        <th className="py-2 px-2.5 text-right font-bold text-rose-600">Rejected</th>
                                        <th className="py-2 px-2.5 text-right font-bold text-emerald-600">Final Good</th>
                                        <th className="py-2 px-2.5">Stage</th>
                                        <th className="py-2 px-2.5">Release Status</th>
                                        <th className="py-2 px-2.5">WO Status</th>
                                        <th className="py-2 px-2.5 text-right">Dispatched</th>
                                        <th className="py-2 px-2.5 text-right">Actions</th>
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                                      {oar.work_orders.map((wo) => (
                                        <tr key={wo.wo_number} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30">
                                          <td className="py-2 px-2.5 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                                            {wo.wo_number}
                                          </td>
                                          <td className="py-2 px-2.5">
                                            <span
                                              className={`inline-block px-1.5 py-0.5 rounded text-[9px] font-bold ${
                                                wo.wo_type === "PATCH"
                                                  ? "bg-purple-100 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800"
                                                  : "bg-blue-100 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800"
                                              }`}
                                            >
                                              {wo.wo_type}
                                            </span>
                                          </td>
                                          <td className="py-2 px-2.5 font-mono text-[10px] text-zinc-500">
                                            {wo.source_wo_number || "—"}
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-semibold text-zinc-700 dark:text-zinc-300">
                                            {wo.replacement_qty > 0 ? wo.replacement_qty : "—"}
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-bold text-zinc-900 dark:text-zinc-100">
                                            {wo.allocated_qty}
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-bold text-blue-600">
                                            {wo.production_qty}
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-bold text-emerald-600">
                                            {wo.good_qty}
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-bold text-rose-600">
                                            {wo.rejected_qty}
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-extrabold text-emerald-600 bg-emerald-50/40 dark:bg-emerald-950/20">
                                            {wo.final_good_contribution}
                                          </td>
                                          <td className="py-2 px-2.5 font-mono font-bold text-blue-600">
                                            {wo.current_stage}
                                          </td>
                                          <td className="py-2 px-2.5">
                                            <Badge
                                              variant={wo.release_status === "RELEASED" ? "green" : "amber"}
                                              size="sm"
                                            >
                                              {wo.release_status.replace(/_/g, " ")}
                                            </Badge>
                                          </td>
                                          <td className="py-2 px-2.5">
                                            <Badge variant={getRAGVariant(wo.wo_status)} size="sm">
                                              {wo.wo_status.replace(/_/g, " ").toUpperCase()}
                                            </Badge>
                                          </td>
                                          <td className="py-2 px-2.5 text-right font-mono font-semibold text-zinc-600 dark:text-zinc-400">
                                            {wo.dispatched_qty}
                                          </td>
                                          <td className="py-2 px-2.5 text-right">
                                            <div className="flex items-center justify-end gap-2">
                                              {wo.release_status !== "RELEASED" && (
                                                <Link
                                                  href="/planning/wo-release"
                                                  className="inline-flex items-center gap-1 text-[10px] font-bold text-purple-600 hover:text-purple-700 bg-purple-50 dark:bg-purple-950/50 px-2 py-0.5 rounded border border-purple-200 dark:border-purple-800"
                                                >
                                                  <span>Release</span>
                                                  <ArrowRight className="h-2.5 w-2.5" />
                                                </Link>
                                              )}
                                              <Link
                                                href={`/production/tracking?wo=${wo.wo_number}`}
                                                className="inline-flex items-center gap-1 text-blue-600 hover:underline font-bold text-[10px]"
                                              >
                                                <span>Detail</span>
                                                <ArrowRight className="h-2.5 w-2.5" />
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
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}

                {oars.length === 0 && !loading && (
                  <tr>
                    <td colSpan={11} className="py-10 text-center text-zinc-400">
                      <div className="flex flex-col items-center gap-2">
                        <FileSpreadsheet className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                        <span>No OARs match your search.</span>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create Patch / Replacement WO Modal */}
        {patchModalOar && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">
              <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between bg-zinc-50 dark:bg-zinc-950/60">
                <div className="flex items-center gap-2">
                  <div className="p-1.5 rounded-lg bg-purple-100 dark:bg-purple-950/60 text-purple-600">
                    <Plus className="h-4 w-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                      Create Patch / Replacement WO
                    </h3>
                    <p className="text-[11px] text-zinc-400">
                      Authoritative shortfall recovery against OAR {patchModalOar.oar_number}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setPatchModalOar(null)}
                  className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              {patchSuccess ? (
                <div className="p-6 space-y-4">
                  <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-4 space-y-2">
                    <div className="flex items-center gap-2 text-emerald-700 dark:text-emerald-400 font-bold text-xs">
                      <CheckCircle2 className="h-4 w-4" />
                      <span>Patch Work Order Created Successfully</span>
                    </div>
                    <p className="text-xs text-zinc-700 dark:text-zinc-300">
                      Patch WO <strong className="font-mono text-purple-600">{patchSuccess.replacement_wo_number}</strong> ({patchSuccess.quantity} pcs) was created as <span className="font-semibold text-amber-600">DRAFT / Unreleased</span> against OAR <strong className="font-mono">{patchSuccess.oar_number}</strong>.
                    </p>
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400 bg-white/70 dark:bg-zinc-900/70 p-2.5 rounded-lg border border-emerald-500/20 space-y-1">
                      <div className="font-semibold text-zinc-700 dark:text-zinc-300">Required Release Workflow:</div>
                      <div>1. Engineering Readiness &amp; Release</div>
                      <div>2. Manufacturing Readiness &amp; Release</div>
                      <div>3. WO Release &amp; Route Configuration</div>
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-3 pt-2">
                    <button
                      type="button"
                      onClick={() => setPatchModalOar(null)}
                      className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                    >
                      Close
                    </button>
                    <Link
                      href="/planning/wo-release"
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold shadow-sm transition-colors"
                    >
                      <span>Proceed to WO Release</span>
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  </div>
                </div>
              ) : (
                <form onSubmit={handleCreatePatchWO} className="p-6 space-y-4">
                  {patchError && (
                    <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-600 font-medium">
                      {patchError}
                    </div>
                  )}

                  {/* OAR Context Cards */}
                  <div className="grid grid-cols-3 gap-2 p-3 bg-zinc-50 dark:bg-zinc-950/60 rounded-xl border border-zinc-200 dark:border-zinc-800 text-center">
                    <div>
                      <div className="text-[10px] text-zinc-400 font-bold uppercase">Required Qty</div>
                      <div className="text-sm font-mono font-extrabold text-zinc-900 dark:text-zinc-100">
                        {patchModalOar.oar_qty} <span className="text-[10px] text-zinc-400">pcs</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-emerald-600 font-bold uppercase">Fulfilled</div>
                      <div className="text-sm font-mono font-extrabold text-emerald-600">
                        {patchModalOar.oar_fulfilled} <span className="text-[10px] text-zinc-400">pcs</span>
                      </div>
                    </div>
                    <div>
                      <div className="text-[10px] text-rose-500 font-bold uppercase">Shortfall</div>
                      <div className="text-sm font-mono font-extrabold text-rose-600">
                        {patchModalOar.oar_shortfall} <span className="text-[10px] text-zinc-400">pcs</span>
                      </div>
                    </div>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                        Source Work Order
                      </label>
                      <select
                        value={selectedSourceWo}
                        onChange={(e) => setSelectedSourceWo(e.target.value)}
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 font-mono focus:border-purple-500 focus:outline-none"
                      >
                        {patchModalOar.work_orders.map((w) => (
                          <option key={w.wo_number} value={w.wo_number}>
                            {w.wo_number} ({w.wo_type} - Qty: {w.allocated_qty}, Good: {w.good_qty}, Rej: {w.rejected_qty})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                        Patch WO Quantity <span className="text-rose-500">*</span>
                      </label>
                      <div className="relative">
                        <input
                          type="number"
                          min={1}
                          max={patchModalOar.oar_shortfall}
                          value={patchQty}
                          onChange={(e) => setPatchQty(e.target.value === "" ? "" : Number(e.target.value))}
                          required
                          className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:border-purple-500 focus:outline-none"
                        />
                        <span className="absolute right-3 top-2 text-[10px] text-zinc-400 font-medium">
                          Max: {patchModalOar.oar_shortfall} pcs
                        </span>
                      </div>
                    </div>

                    <div>
                      <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                        Reason <span className="text-rose-500">*</span>
                      </label>
                      <textarea
                        rows={2}
                        value={patchReason}
                        onChange={(e) => setPatchReason(e.target.value)}
                        required
                        placeholder="Reason for raising replacement/patch WO..."
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-2.5 text-xs text-zinc-900 dark:text-zinc-100 focus:border-purple-500 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                        Remarks (Optional)
                      </label>
                      <input
                        type="text"
                        value={patchRemarks}
                        onChange={(e) => setPatchRemarks(e.target.value)}
                        placeholder="Additional notes..."
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:border-purple-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
                    <button
                      type="button"
                      onClick={() => setPatchModalOar(null)}
                      disabled={patchSubmitting}
                      className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={patchSubmitting}
                      className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold shadow-sm transition-colors cursor-pointer disabled:opacity-50"
                    >
                      {patchSubmitting ? (
                        <>
                          <RotateCw className="h-3.5 w-3.5 animate-spin" />
                          <span>Creating...</span>
                        </>
                      ) : (
                        <>
                          <Plus className="h-3.5 w-3.5" />
                          <span>Create Patch WO</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}



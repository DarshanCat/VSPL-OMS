"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import Link from "next/link";
import {
  Truck,
  Building2,
  PackageCheck,
  Search,
  Filter,
  RefreshCw,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  RotateCw,
  Clock,
  Calendar,
  Layers,
  FileText,
  X
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge } from "@/app/components/ui/Badge";
import {
  getVendorDispatches,
  getVendorSummary,
  receiveVendorDispatch,
  VendorDispatchItem,
  VendorSummary
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

export default function VendorTrackingPage() {
  const [dispatches, setDispatches] = useState<VendorDispatchItem[]>([]);
  const [summary, setSummary] = useState<VendorSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [statusTab, setStatusTab] = useState<"ACTIVE" | "RECEIVED" | "ALL">("ACTIVE");

  // Receive Modal state
  const [receiveModalItem, setReceiveModalItem] = useState<VendorDispatchItem | null>(null);
  const [receivedQty, setReceivedQty] = useState<number | "">("");
  const [scrapQty, setScrapQty] = useState<number | "">("");
  const [destinationStage, setDestinationStage] = useState<string>("FI");
  const [inwardDc, setInwardDc] = useState("");
  const [receiveRemarks, setReceiveRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");
  const [successToast, setSuccessToast] = useState("");

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const statusParam = statusTab === "ACTIVE" ? "AT_VENDOR" : (statusTab === "RECEIVED" ? "RECEIVED" : "ALL");
      const [listRes, sumRes] = await Promise.all([
        getVendorDispatches({
          status: statusParam,
          search: search.trim() || undefined,
          limit: 200,
        }),
        getVendorSummary().catch(() => null),
      ]);
      setDispatches(listRes);
      if (sumRes) setSummary(sumRes);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load vendor dispatches.");
    } finally {
      setLoading(false);
    }
  }, [statusTab, search]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const openReceiveModal = (item: VendorDispatchItem) => {
    setReceiveModalItem(item);
    setReceivedQty(item.pending_qty);
    setScrapQty(0);
    setDestinationStage(item.target_return_stage || "FI");
    setInwardDc("");
    setReceiveRemarks("");
    setModalError("");
  };

  const handleReceiveSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!receiveModalItem) return;

    const numRec = Number(receivedQty);
    const numScrap = Number(scrapQty) || 0;

    if (!numRec || numRec <= 0) {
      setModalError("Received Quantity must be greater than 0.");
      return;
    }

    if (numRec + numScrap > receiveModalItem.pending_qty) {
      setModalError(
        `Total quantity (${numRec} OK + ${numScrap} Scrap = ${numRec + numScrap}) cannot exceed pending quantity of ${receiveModalItem.pending_qty} pcs.`
      );
      return;
    }

    setSubmitting(true);
    setModalError("");
    try {
      const res = await receiveVendorDispatch({
        dispatch_id: receiveModalItem.id,
        received_qty: numRec,
        scrap_qty: numScrap,
        destination_stage: destinationStage,
        inward_dc: inwardDc.trim() || undefined,
        remarks: receiveRemarks.trim() || undefined,
      });

      setSuccessToast(res.message);
      setReceiveModalItem(null);
      await fetchData();
      setTimeout(() => setSuccessToast(""), 4000);
    } catch (err: any) {
      setModalError(err?.response?.data?.detail || "Failed to receive material from vendor.");
    } finally {
      setSubmitting(false);
    }
  };

  const filteredDispatches = useMemo(() => {
    if (statusTab === "ACTIVE") {
      return dispatches.filter((d) => d.status === "AT_VENDOR" || d.status === "PARTIALLY_RECEIVED");
    }
    if (statusTab === "RECEIVED") {
      return dispatches.filter((d) => d.status === "RECEIVED");
    }
    return dispatches;
  }, [dispatches, statusTab]);

  return (
    <AppShell>
      <div className="space-y-6 pb-16 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
              <Truck className="h-3 w-3" />
              <span>OUTSIDE SUBCONTRACTING / DC TRACKING</span>
            </div>
            <h1 className="text-2xl font-black text-zinc-900 dark:text-zinc-50 tracking-tight mt-1">
              Vendor Tracking & Subcontractor Inward
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">
              Monitor Work Orders dispatched to external vendors on Delivery Challans, and receive returned parts directly into Final Inspection (FI).
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => fetchData()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-xs font-semibold text-zinc-700 dark:text-zinc-300 transition-colors shadow-sm cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
            <Link
              href="/production/entry"
              className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-700 text-white text-xs font-bold shadow-sm transition-all cursor-pointer"
            >
              <Building2 className="h-3.5 w-3.5" />
              <span>New F2 Vendor Entry</span>
            </Link>
          </div>
        </div>

        {/* Success Toast */}
        {successToast && (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3.5 flex items-center gap-3 text-xs text-emerald-800 dark:text-emerald-200 font-bold shadow-sm animate-in fade-in">
            <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
            <span>{successToast}</span>
          </div>
        )}

        {/* Metrics Overview */}
        {summary && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 p-4 shadow-sm">
              <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400 mb-1">
                <span className="text-[11px] font-bold uppercase tracking-wider">WOs at Vendor</span>
                <Clock className="h-4 w-4 text-amber-500" />
              </div>
              <div className="text-2xl font-black text-amber-600 dark:text-amber-400">
                {summary.active_dispatches_count}
              </div>
              <p className="text-[10px] text-zinc-400 mt-0.5">Pending return to FI</p>
            </div>

            <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 p-4 shadow-sm">
              <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400 mb-1">
                <span className="text-[11px] font-bold uppercase tracking-wider">Pieces at Vendor</span>
                <Layers className="h-4 w-4 text-purple-500" />
              </div>
              <div className="text-2xl font-black text-purple-600 dark:text-purple-400">
                {summary.total_pieces_at_vendor} <span className="text-xs font-normal text-zinc-400">pcs</span>
              </div>
              <p className="text-[10px] text-zinc-400 mt-0.5">Active subcontracted inventory</p>
            </div>

            <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 p-4 shadow-sm">
              <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400 mb-1">
                <span className="text-[11px] font-bold uppercase tracking-wider">Received to FI</span>
                <PackageCheck className="h-4 w-4 text-emerald-500" />
              </div>
              <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400">
                {summary.total_pieces_received} <span className="text-xs font-normal text-zinc-400">pcs</span>
              </div>
              <p className="text-[10px] text-zinc-400 mt-0.5">Inwarded directly to Inspection</p>
            </div>

            <div className="rounded-2xl border border-zinc-200/80 dark:border-zinc-800/80 bg-white dark:bg-zinc-900 p-4 shadow-sm">
              <div className="flex items-center justify-between text-zinc-500 dark:text-zinc-400 mb-1">
                <span className="text-[11px] font-bold uppercase tracking-wider">Active Vendors</span>
                <Building2 className="h-4 w-4 text-blue-500" />
              </div>
              <div className="text-2xl font-black text-blue-600 dark:text-blue-400">
                {summary.active_vendor_count}
              </div>
              <p className="text-[10px] text-zinc-400 mt-0.5">Outside subcontractors</p>
            </div>
          </div>
        )}

        {/* Filters and Tabs */}
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 bg-white dark:bg-zinc-900 p-3 rounded-2xl border border-zinc-200 dark:border-zinc-800 shadow-sm">
          <div className="flex items-center gap-1.5 p-1 bg-zinc-100 dark:bg-zinc-800/60 rounded-xl text-xs font-bold">
            <button
              onClick={() => setStatusTab("ACTIVE")}
              className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                statusTab === "ACTIVE"
                  ? "bg-white dark:bg-zinc-900 text-purple-700 dark:text-purple-300 shadow-xs"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
              }`}
            >
              Active at Vendor ({dispatches.filter((d) => d.status !== "RECEIVED").length})
            </button>
            <button
              onClick={() => setStatusTab("RECEIVED")}
              className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                statusTab === "RECEIVED"
                  ? "bg-white dark:bg-zinc-900 text-emerald-700 dark:text-emerald-300 shadow-xs"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
              }`}
            >
              Completed / Received
            </button>
            <button
              onClick={() => setStatusTab("ALL")}
              className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                statusTab === "ALL"
                  ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs"
                  : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
              }`}
            >
              All Dispatches
            </button>
          </div>

          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search WO#, DC#, Vendor name, Part, Customer..."
              className="w-full pl-9 pr-3 py-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-purple-500"
            />
          </div>
        </div>

        {/* Dispatches Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden shadow-sm">
          {loading ? (
            <div className="p-12 text-center text-xs text-zinc-400 flex flex-col items-center justify-center gap-2">
              <RotateCw className="h-6 w-6 animate-spin text-purple-600" />
              <span>Loading vendor dispatches...</span>
            </div>
          ) : error ? (
            <div className="p-8 text-center text-xs text-rose-500 flex flex-col items-center justify-center gap-2">
              <AlertTriangle className="h-6 w-6 text-rose-500" />
              <span>{error}</span>
            </div>
          ) : filteredDispatches.length === 0 ? (
            <div className="p-12 text-center text-xs text-zinc-500 dark:text-zinc-400 flex flex-col items-center justify-center gap-2">
              <Truck className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
              <p className="font-bold">No Work Orders found at vendor for this filter.</p>
              <p className="text-[11px] text-zinc-400">
                To dispatch parts to an outside vendor, record production at stage F2 with mode &apos;Vendor&apos; and DC number.
              </p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 text-[11px] font-extrabold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    <th className="py-3 px-4">WO & OAR Reference</th>
                    <th className="py-3 px-4">Customer & Part Number</th>
                    <th className="py-3 px-4">Vendor & DC Info</th>
                    <th className="py-3 px-4">Dispatched Date</th>
                    <th className="py-3 px-4 text-center">Dispatched</th>
                    <th className="py-3 px-4 text-center">Received (FI)</th>
                    <th className="py-3 px-4 text-center">Pending</th>
                    <th className="py-3 px-4">Status</th>
                    <th className="py-3 px-4 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {filteredDispatches.map((item) => {
                    const isCompleted = item.status === "RECEIVED";
                    return (
                      <tr
                        key={item.id}
                        className="hover:bg-zinc-50/80 dark:hover:bg-zinc-800/30 transition-colors"
                      >
                        <td className="py-3 px-4">
                          <div className="font-extrabold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                            <span>{item.wo_number}</span>
                          </div>
                          <div className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono">
                            {item.oar_number}
                          </div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-bold text-zinc-800 dark:text-zinc-200 truncate max-w-[200px]" title={item.part_name}>
                            {item.part_name || item.part_number}
                          </div>
                          <div className="text-[11px] text-zinc-500 truncate max-w-[200px]">
                            {item.customer_name} • <span className="font-mono">{item.part_number}</span>
                          </div>
                        </td>

                        <td className="py-3 px-4">
                          <div className="font-bold text-purple-700 dark:text-purple-300 flex items-center gap-1">
                            <Building2 className="h-3 w-3 text-purple-500" />
                            <span>{item.vendor_name}</span>
                          </div>
                          <div className="text-[11px] text-zinc-500 flex items-center gap-1 mt-0.5">
                            <FileText className="h-3 w-3 text-zinc-400" />
                            <span>DC: <strong>{item.dc_number}</strong></span>
                            {item.inward_dc_number && (
                              <span className="text-emerald-600 font-mono text-[10px]">
                                (In: #{item.inward_dc_number})
                              </span>
                            )}
                          </div>
                        </td>

                        <td className="py-3 px-4 whitespace-nowrap">
                          <div className="text-zinc-800 dark:text-zinc-200 font-medium">
                            {formatDate(item.dispatched_at)}
                          </div>
                          <div className="text-[10px] text-amber-600 dark:text-amber-400 font-bold">
                            {item.days_at_vendor} {item.days_at_vendor === 1 ? "day" : "days"} ago
                          </div>
                        </td>

                        <td className="py-3 px-4 text-center font-bold text-zinc-800 dark:text-zinc-200">
                          {item.dispatched_qty} pcs
                        </td>

                        <td className="py-3 px-4 text-center font-bold text-emerald-600 dark:text-emerald-400">
                          {item.received_qty} pcs
                        </td>

                        <td className="py-3 px-4 text-center font-extrabold text-amber-600 dark:text-amber-400">
                          {item.pending_qty} pcs
                        </td>

                        <td className="py-3 px-4">
                          {isCompleted ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                              <CheckCircle2 className="h-3 w-3" />
                              <span>Received</span>
                            </span>
                          ) : item.status === "PARTIALLY_RECEIVED" ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                              <Clock className="h-3 w-3" />
                              <span>Partial Return</span>
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-extrabold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                              <Truck className="h-3 w-3" />
                              <span>At Vendor</span>
                            </span>
                          )}
                        </td>

                        <td className="py-3 px-4 text-right">
                          {!isCompleted ? (
                            <button
                              onClick={() => openReceiveModal(item)}
                              className={`inline-flex items-center gap-1 px-3 py-1.5 rounded-xl text-white font-bold text-xs shadow-sm transition-all cursor-pointer ${
                                item.target_return_stage === "F2" ? "bg-indigo-600 hover:bg-indigo-700" : "bg-emerald-600 hover:bg-emerald-700"
                              }`}
                            >
                              <PackageCheck className="h-3.5 w-3.5" />
                              <span>Receive to {item.target_return_stage || "FI"}</span>
                            </button>
                          ) : (
                            <span className="text-[11px] font-bold text-zinc-400">
                              Fully Inwarded
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Receive from Vendor Modal */}
        {receiveModalItem && (
          <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 animate-in fade-in">
            <div className="w-full max-w-lg rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl p-6 relative">
              <button
                onClick={() => setReceiveModalItem(null)}
                className="absolute right-4 top-4 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 p-1 rounded-lg"
              >
                <X className="h-5 w-5" />
              </button>

              <div className="flex items-center gap-2.5 mb-4">
                <div className="p-2 rounded-xl bg-emerald-100 dark:bg-emerald-950/60 text-emerald-600 border border-emerald-200 dark:border-emerald-800">
                  <PackageCheck className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-base font-extrabold text-zinc-900 dark:text-zinc-100">
                    Receive Material from Vendor to Final Inspection
                  </h3>
                  <p className="text-xs text-zinc-500">
                    Challan DC #{receiveModalItem.dc_number} • Vendor: {receiveModalItem.vendor_name}
                  </p>
                </div>
              </div>

              {/* Context Summary */}
              <div className="p-3 rounded-xl bg-zinc-50 dark:bg-zinc-800/40 border border-zinc-200 dark:border-zinc-800 text-xs grid grid-cols-2 gap-2 mb-4">
                <div>
                  <span className="text-[10px] text-zinc-400 block uppercase font-bold">Work Order</span>
                  <span className="font-extrabold text-zinc-900 dark:text-zinc-100 font-mono">{receiveModalItem.wo_number}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 block uppercase font-bold">Part Number</span>
                  <span className="font-bold text-zinc-900 dark:text-zinc-100">{receiveModalItem.part_name || receiveModalItem.part_number}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 block uppercase font-bold">Total Dispatched</span>
                  <span className="font-bold text-zinc-700 dark:text-zinc-300">{receiveModalItem.dispatched_qty} pcs</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 block uppercase font-bold">Pending Return</span>
                  <span className="font-extrabold text-amber-600 dark:text-amber-400">{receiveModalItem.pending_qty} pcs</span>
                </div>
              </div>

              {modalError && (
                <div className="mb-4 p-3 rounded-xl bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-800 text-xs text-rose-700 dark:text-rose-300 font-semibold flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0" />
                  <span>{modalError}</span>
                </div>
              )}

              <form onSubmit={handleReceiveSubmit} className="space-y-4">
                {/* Destination Stage Selection: FI vs F2 */}
                <div>
                  <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1.5 flex items-center justify-between">
                    <span>Destination Stage (Where is material landing?)</span>
                    <span className="text-[10px] text-purple-600 dark:text-purple-400 font-semibold lowercase">
                      {receiveModalItem.target_return_stage ? `planned: ${receiveModalItem.target_return_stage}` : ""}
                    </span>
                  </label>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
                    <button
                      type="button"
                      onClick={() => setDestinationStage("FI")}
                      className={`p-2.5 rounded-xl border text-left transition-all cursor-pointer ${
                        destinationStage === "FI"
                          ? "border-emerald-600 bg-emerald-50/80 dark:bg-emerald-950/40 text-emerald-900 dark:text-emerald-100 ring-2 ring-emerald-500/20"
                          : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-extrabold text-xs">Stage FI</span>
                        <span className="text-[9px] uppercase font-bold px-1.5 py-0.2 rounded bg-emerald-100 dark:bg-emerald-900/60 text-emerald-700 dark:text-emerald-300">
                          Final QA
                        </span>
                      </div>
                      <p className="text-[10px] text-zinc-500 leading-tight">
                        Machining done. Lands in FI for QA & packing.
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => setDestinationStage("F3")}
                      className={`p-2.5 rounded-xl border text-left transition-all cursor-pointer ${
                        destinationStage === "F3"
                          ? "border-sky-600 bg-sky-50/80 dark:bg-sky-950/40 text-sky-900 dark:text-sky-100 ring-2 ring-sky-500/20"
                          : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-extrabold text-xs">Stage F3</span>
                        <span className="text-[9px] uppercase font-bold px-1.5 py-0.2 rounded bg-sky-100 dark:bg-sky-900/60 text-sky-700 dark:text-sky-300">
                          Precision
                        </span>
                      </div>
                      <p className="text-[10px] text-zinc-500 leading-tight">
                        Lands in F3 for CNC finish machining.
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => setDestinationStage("SP")}
                      className={`p-2.5 rounded-xl border text-left transition-all cursor-pointer ${
                        destinationStage === "SP"
                          ? "border-amber-600 bg-amber-50/80 dark:bg-amber-950/40 text-amber-900 dark:text-amber-100 ring-2 ring-amber-500/20"
                          : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-extrabold text-xs">Stage SP</span>
                        <span className="text-[9px] uppercase font-bold px-1.5 py-0.2 rounded bg-amber-100 dark:bg-amber-900/60 text-amber-700 dark:text-amber-300">
                          Surface
                        </span>
                      </div>
                      <p className="text-[10px] text-zinc-500 leading-tight">
                        Lands in SP for blasting, plating, or painting.
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => setDestinationStage("F2")}
                      className={`p-2.5 rounded-xl border text-left transition-all cursor-pointer ${
                        destinationStage === "F2"
                          ? "border-indigo-600 bg-indigo-50/80 dark:bg-indigo-950/40 text-indigo-900 dark:text-indigo-100 ring-2 ring-indigo-500/20"
                          : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                      }`}
                    >
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-extrabold text-xs">Stage F2</span>
                        <span className="text-[9px] uppercase font-bold px-1.5 py-0.2 rounded bg-indigo-100 dark:bg-indigo-900/60 text-indigo-700 dark:text-indigo-300">
                          Fettling
                        </span>
                      </div>
                      <p className="text-[10px] text-zinc-500 leading-tight">
                        Returns to F2 for in-house finishing & entry.
                      </p>
                    </button>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                      Received Quantity (Good) <span className="text-rose-500">*</span>
                    </label>
                    <input
                      type="number"
                      required
                      min={1}
                      max={receiveModalItem.pending_qty}
                      value={receivedQty}
                      onChange={(e) => setReceivedQty(e.target.value === "" ? "" : Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500"
                    />
                    <span className="text-[10px] text-zinc-400 mt-0.5 block">
                      Good pcs landing in {destinationStage}
                    </span>
                  </div>

                  <div>
                    <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                      Vendor Scrap / Damaged (pcs)
                    </label>
                    <input
                      type="number"
                      min={0}
                      value={scrapQty}
                      onChange={(e) => setScrapQty(e.target.value === "" ? "" : Number(e.target.value))}
                      className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-rose-500"
                    />
                    <span className="text-[10px] text-zinc-400 mt-0.5 block">Optional vendor rejections</span>
                  </div>
                </div>

                <div>
                  <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                    Inward DC / Invoice / Gate Pass #
                  </label>
                  <input
                    type="text"
                    value={inwardDc}
                    onChange={(e) => setInwardDc(e.target.value)}
                    placeholder="e.g. INV-10492 / GP-881"
                    className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500 font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[11px] font-bold text-zinc-700 dark:text-zinc-300 uppercase tracking-wider mb-1">
                    Inward Remarks / Inspection Notes
                  </label>
                  <textarea
                    rows={2}
                    value={receiveRemarks}
                    onChange={(e) => setReceiveRemarks(e.target.value)}
                    placeholder="e.g. Machining verified by vendor, received with physical test certificate..."
                    className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-emerald-500"
                  />
                </div>

                <div className={`p-3 rounded-xl border text-[11px] font-medium flex items-start gap-2 ${
                  destinationStage === "FI"
                    ? "bg-emerald-50/70 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800 text-emerald-900 dark:text-emerald-200"
                    : destinationStage === "F3"
                    ? "bg-sky-50/70 dark:bg-sky-950/30 border-sky-200 dark:border-sky-800 text-sky-900 dark:text-sky-200"
                    : destinationStage === "SP"
                    ? "bg-amber-50/70 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800 text-amber-900 dark:text-amber-200"
                    : "bg-indigo-50/70 dark:bg-indigo-950/30 border-indigo-200 dark:border-indigo-800 text-indigo-900 dark:text-indigo-200"
                }`}>
                  <ArrowRight className="h-4 w-4 shrink-0 mt-0.5 text-purple-600" />
                  <span>
                    {destinationStage === "FI" ? (
                      <>Confirming this inward will land the material directly in <strong>FI (Final Inspection)</strong>, bypassing intermediate stages. From FI, parts move to <strong>BSR / Packing</strong>.</>
                    ) : destinationStage === "F3" ? (
                      <>Confirming this inward will land the material in <strong>Stage F3 (Precision CNC Machining)</strong>. F3 operators will log precision machining, then move along the sequential route.</>
                    ) : destinationStage === "SP" ? (
                      <>Confirming this inward will land the material in <strong>Stage SP (Surface Treatment)</strong> for blasting, coating, or plating before moving to FI.</>
                    ) : (
                      <>Confirming this inward will return the material to <strong>Stage F2 (Fettling & In-House Finishing)</strong> on the shop floor. Parts will be available in-process at F2 for in-house operations and floor stage movement.</>
                    )}
                  </span>
                </div>

                <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
                  <button
                    type="button"
                    onClick={() => setReceiveModalItem(null)}
                    disabled={submitting}
                    className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className={`inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-white text-xs font-bold shadow-sm transition-all cursor-pointer disabled:opacity-50 ${
                      destinationStage === "FI"
                        ? "bg-emerald-600 hover:bg-emerald-700"
                        : destinationStage === "F3"
                        ? "bg-sky-600 hover:bg-sky-700"
                        : destinationStage === "SP"
                        ? "bg-amber-600 hover:bg-amber-700"
                        : "bg-indigo-600 hover:bg-indigo-700"
                    }`}
                  >
                    {submitting ? (
                      <>
                        <RotateCw className="h-3.5 w-3.5 animate-spin" />
                        <span>Inwarding to {destinationStage}...</span>
                      </>
                    ) : (
                      <>
                        <PackageCheck className="h-3.5 w-3.5" />
                        <span>Confirm Receive to {destinationStage === "FI" ? "Final Inspection (FI)" : `Stage ${destinationStage}`}</span>
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

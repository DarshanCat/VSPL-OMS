"use client";
import React, { useState, useEffect, useCallback } from "react";
import {
  ClipboardCheck,
  Search,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Clock,
  SlidersHorizontal,
  ChevronRight,
  ShieldCheck,
  AlertTriangle,
  ArrowUpDown,
  FileText,
  User,
  Factory,
  Check,
  X
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import { DEFECT_CODES } from "@/lib/rejectionReasons";
import {
  getMRBReviews,
  submitMRBDecision,
  approveMRBReview,
  adjustMRBReview,
  MRBReviewItem,
  MRBListResponse,
  MRBReviewDecisionRequest
} from "@/lib/api";

const STAGES = ["ALL", "F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];
const STATUS_TABS = [
  { key: "PENDING", label: "Pending Review" },
  { key: "APPROVED", label: "Approved" },
  { key: "ADJUSTED", label: "Adjusted" },
  { key: "REJECTED", label: "Rejected" },
  { key: "ALL", label: "All Tickets" },
];

const DISPOSITIONS = [
  { value: "SCRAP", label: "Scrap (Unusable / Send for Melting)" },
  { value: "REWORK", label: "Rework (Can be corrected on machine)" },
  { value: "CONCESSION", label: "Concession / Deviation (Accept As-Is)" },
  { value: "RECLASSIFY_OK", label: "Reclassify to OK (False defect / Good Part)" },
  { value: "RETURN_TO_SUPPLIER", label: "Return to Supplier (Casting Defect)" },
];

export default function MRBReviewBoardPage() {
  const [data, setData] = useState<MRBListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Filters
  const [activeTab, setActiveTab] = useState<string>("PENDING");
  const [selectedStage, setSelectedStage] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");

  // Review & Decision Modal
  const [selectedTicket, setSelectedTicket] = useState<MRBReviewItem | null>(null);
  const [actionMode, setActionMode] = useState<"APPROVE" | "ADJUST" | "REJECT">("APPROVE");
  const [verifiedOkQty, setVerifiedOkQty] = useState<number>(0);
  const [verifiedRejectQty, setVerifiedRejectQty] = useState<number>(0);
  const [verifiedDefectCode, setVerifiedDefectCode] = useState<string>("");
  const [disposition, setDisposition] = useState<string>("SCRAP");
  const [reviewNotes, setReviewNotes] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await getMRBReviews({
        status: activeTab,
        stage: selectedStage === "ALL" ? undefined : selectedStage,
        search: searchQuery.trim() || undefined,
        limit: 200,
      });
      setData(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load MRB review queue.");
    } finally {
      setLoading(false);
    }
  }, [activeTab, selectedStage, searchQuery]);

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  const handleOpenReview = (ticket: MRBReviewItem, mode: "APPROVE" | "ADJUST" | "REJECT" = "APPROVE") => {
    setSelectedTicket(ticket);
    setActionMode(mode);
    setVerifiedOkQty(ticket.verified_ok_qty ?? ticket.reported_ok_qty);
    setVerifiedRejectQty(ticket.verified_reject_qty ?? ticket.reported_reject_qty);
    setVerifiedDefectCode(ticket.verified_defect_code || ticket.reported_defect_code || DEFECT_CODES[0]?.code || "");
    setDisposition(ticket.disposition && ticket.disposition !== "PENDING" ? ticket.disposition : (ticket.reported_reject_qty > 0 ? "SCRAP" : "VERIFIED_OK"));
    setReviewNotes(ticket.review_notes || "");
  };

  const handleQuickApprove = async (ticket: MRBReviewItem) => {
    if (!confirm(`Confirm and approve floor quantities for ${ticket.mrb_number} (WO: ${ticket.wo_number})?`)) {
      return;
    }
    setLoading(true);
    try {
      await approveMRBReview(ticket.id, {
        disposition: ticket.reported_reject_qty > 0 ? "SCRAP" : "VERIFIED_OK",
        review_notes: "Approved via MRB quick confirmation.",
      });
      setSuccessMsg(`Ticket ${ticket.mrb_number} approved successfully.`);
      setTimeout(() => setSuccessMsg(""), 4000);
      await fetchTickets();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Approval failed.");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmitDecision = async () => {
    if (!selectedTicket) return;
    setSubmitting(true);
    setError("");

    try {
      const payload: MRBReviewDecisionRequest = {
        action: actionMode,
        verified_ok_qty: Number(verifiedOkQty),
        verified_reject_qty: Number(verifiedRejectQty),
        verified_defect_code: verifiedDefectCode || undefined,
        disposition: disposition,
        review_notes: reviewNotes.trim() || undefined,
      };

      await submitMRBDecision(selectedTicket.id, payload);
      setSuccessMsg(
        actionMode === "APPROVE"
          ? `Ticket ${selectedTicket.mrb_number} approved successfully.`
          : actionMode === "ADJUST"
          ? `Ticket ${selectedTicket.mrb_number} quantities adjusted and reconciled.`
          : `Ticket ${selectedTicket.mrb_number} flagged/rejected.`
      );
      setTimeout(() => setSuccessMsg(""), 4000);
      setSelectedTicket(null);
      await fetchTickets();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Decision submission failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const deltaOk = selectedTicket ? Number(verifiedOkQty) - selectedTicket.reported_ok_qty : 0;
  const deltaRej = selectedTicket ? Number(verifiedRejectQty) - selectedTicket.reported_reject_qty : 0;

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <ClipboardCheck className="h-7 w-7 text-amber-500" />
              <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
                Material Review Board (MRB)
              </h1>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Quality, Planner & Admin verification board for shop floor production gates, OK quantities, and rejection review.
            </p>
          </div>
          <button
            onClick={() => fetchTickets()}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-sm font-medium rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 transition"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>

        {/* Alerts */}
        {error && (
          <div className="p-4 rounded-lg bg-rose-50 dark:bg-rose-900/30 border border-rose-200 dark:border-rose-800 text-rose-700 dark:text-rose-300 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <span className="text-sm font-medium">{error}</span>
            </div>
            <button onClick={() => setError("")} className="text-rose-600 hover:text-rose-800">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {successMsg && (
          <div className="p-4 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 border border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-300 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 flex-shrink-0" />
              <span className="text-sm font-medium">{successMsg}</span>
            </div>
            <button onClick={() => setSuccessMsg("")} className="text-emerald-600 hover:text-emerald-800">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* KPI Summary Cards */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 shadow-sm">
            <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">Total Entries</p>
            <p className="text-2xl font-bold text-slate-900 dark:text-white mt-1">
              {data?.total_count ?? 0}
            </p>
            <p className="text-xs text-slate-400 mt-1">Floor production records</p>
          </div>

          <div className="p-4 rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50/50 dark:bg-amber-950/20 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400">
                Pending Review
              </p>
              <Clock className="h-4 w-4 text-amber-600 dark:text-amber-400" />
            </div>
            <p className="text-2xl font-bold text-amber-700 dark:text-amber-300 mt-1">
              {data?.pending_count ?? 0}
            </p>
            <p className="text-xs text-amber-600/80 dark:text-amber-400/80 mt-1">Needs verification</p>
          </div>

          <div className="p-4 rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50/50 dark:bg-emerald-950/20 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700 dark:text-emerald-400">
                Approved
              </p>
              <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
            </div>
            <p className="text-2xl font-bold text-emerald-700 dark:text-emerald-300 mt-1">
              {data?.approved_count ?? 0}
            </p>
            <p className="text-xs text-emerald-600/80 dark:text-emerald-400/80 mt-1">Confirmed correct</p>
          </div>

          <div className="p-4 rounded-xl border border-blue-200 dark:border-blue-900/50 bg-blue-50/50 dark:bg-blue-950/20 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-blue-700 dark:text-blue-400">
                Adjusted
              </p>
              <SlidersHorizontal className="h-4 w-4 text-blue-600 dark:text-blue-400" />
            </div>
            <p className="text-2xl font-bold text-blue-700 dark:text-blue-300 mt-1">
              {data?.adjusted_count ?? 0}
            </p>
            <p className="text-xs text-blue-600/80 dark:text-blue-400/80 mt-1">Corrected by MRB</p>
          </div>

          <div className="p-4 rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50/50 dark:bg-rose-950/20 shadow-sm">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wider text-rose-700 dark:text-rose-400">
                Rejected / Flagged
              </p>
              <AlertTriangle className="h-4 w-4 text-rose-600 dark:text-rose-400" />
            </div>
            <p className="text-2xl font-bold text-rose-700 dark:text-rose-300 mt-1">
              {data?.rejected_count ?? 0}
            </p>
            <p className="text-xs text-rose-600/80 dark:text-rose-400/80 mt-1">Under investigation</p>
          </div>
        </div>

        {/* Filter Bar & Tabs */}
        <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            {/* Status Tabs */}
            <div className="flex flex-wrap gap-1 p-1 bg-slate-100 dark:bg-slate-800 rounded-lg">
              {STATUS_TABS.map((tab) => {
                const count =
                  tab.key === "PENDING"
                    ? data?.pending_count
                    : tab.key === "APPROVED"
                    ? data?.approved_count
                    : tab.key === "ADJUSTED"
                    ? data?.adjusted_count
                    : tab.key === "REJECTED"
                    ? data?.rejected_count
                    : data?.total_count;

                const isActive = activeTab === tab.key;
                return (
                  <button
                    key={tab.key}
                    onClick={() => setActiveTab(tab.key)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-md transition flex items-center gap-1.5 ${
                      isActive
                        ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm"
                        : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white"
                    }`}
                  >
                    <span>{tab.label}</span>
                    {count !== undefined && (
                      <span
                        className={`px-1.5 py-0.2 rounded-full text-[10px] ${
                          isActive
                            ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
                            : "bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
                        }`}
                      >
                        {count}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>

            {/* Stage filter & Search */}
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-slate-500">Stage:</span>
                <select
                  value={selectedStage}
                  onChange={(e) => setSelectedStage(e.target.value)}
                  className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-amber-500"
                >
                  {STAGES.map((stg) => (
                    <option key={stg} value={stg}>
                      {stg}
                    </option>
                  ))}
                </select>
              </div>

              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-slate-400" />
                <input
                  type="text"
                  placeholder="Search ticket, WO, operator..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-amber-500 w-48 sm:w-60"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Tickets Table */}
        <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 uppercase tracking-wider font-semibold border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3">Ticket / Date</th>
                  <th className="px-4 py-3">Work Order & Part</th>
                  <th className="px-4 py-3">Stage / Gate</th>
                  <th className="px-4 py-3">Shop Floor Entry</th>
                  <th className="px-4 py-3">Reported Qty</th>
                  <th className="px-4 py-3">MRB Verified Qty</th>
                  <th className="px-4 py-3">Status / Disposition</th>
                  <th className="px-4 py-3">Reviewer</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {loading && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-slate-500">
                      <RefreshCw className="h-5 w-5 animate-spin mx-auto mb-2 text-amber-500" />
                      Loading MRB review queue...
                    </td>
                  </tr>
                )}

                {!loading && (!data?.items || data.items.length === 0) && (
                  <tr>
                    <td colSpan={9} className="px-4 py-8 text-center text-slate-500">
                      <ClipboardCheck className="h-8 w-8 mx-auto mb-2 text-slate-400 opacity-60" />
                      <p className="font-medium text-slate-700 dark:text-slate-300">No MRB tickets found</p>
                      <p className="text-xs text-slate-400 mt-1">
                        Entries recorded in Production Entry or Movement with rejections will appear here for review.
                      </p>
                    </td>
                  </tr>
                )}

                {!loading &&
                  data?.items?.map((ticket) => {
                    const isPending = ticket.status === "PENDING";
                    const isApproved = ticket.status === "APPROVED";
                    const isAdjusted = ticket.status === "ADJUSTED";
                    const isRejected = ticket.status === "REJECTED";

                    return (
                      <tr
                        key={ticket.id}
                        className="hover:bg-slate-50/70 dark:hover:bg-slate-800/40 transition-colors"
                      >
                        {/* Ticket / Date */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="font-mono font-semibold text-slate-900 dark:text-white">
                            {ticket.mrb_number}
                          </div>
                          <div className="text-[11px] text-slate-400 mt-0.5">
                            {new Date(ticket.created_at).toLocaleDateString()} {new Date(ticket.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                          </div>
                        </td>

                        {/* Work Order & Part */}
                        <td className="px-4 py-3">
                          <div className="font-semibold text-slate-900 dark:text-white">
                            {ticket.wo_number}
                          </div>
                          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate max-w-[180px]">
                            {ticket.part_number || "N/A"}
                            {ticket.customer_name ? ` • ${ticket.customer_name}` : ""}
                          </div>
                        </td>

                        {/* Stage / Gate */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <span className="inline-flex items-center px-2 py-0.5 rounded font-mono font-medium text-xs bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 border border-slate-200 dark:border-slate-700">
                            {ticket.stage}
                          </span>
                        </td>

                        {/* Shop Floor Entry */}
                        <td className="px-4 py-3">
                          <div className="text-slate-800 dark:text-slate-200 font-medium truncate max-w-[150px]">
                            {ticket.operator_name || "Floor Operator"}
                          </div>
                          <div className="text-[11px] text-slate-400 flex items-center gap-1.5 mt-0.5">
                            <span>{ticket.shift || "Shift A"}</span>
                            {ticket.machine_id && <span>• {ticket.machine_id}</span>}
                            {ticket.heat_number && <span>• Heat: {ticket.heat_number}</span>}
                          </div>
                        </td>

                        {/* Reported Qty */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                              OK: {ticket.reported_ok_qty}
                            </span>
                            {ticket.reported_reject_qty > 0 && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300">
                                Rej: {ticket.reported_reject_qty}
                              </span>
                            )}
                          </div>
                          {ticket.reported_defect_code && (
                            <div className="text-[10px] text-rose-600 dark:text-rose-400 font-medium mt-1 truncate max-w-[130px]">
                              {ticket.reported_defect_code}
                            </div>
                          )}
                        </td>

                        {/* MRB Verified Qty */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          {isPending ? (
                            <span className="text-[11px] text-slate-400 italic">Awaiting Review</span>
                          ) : (
                            <div>
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-emerald-700 dark:text-emerald-400">
                                  OK: {ticket.verified_ok_qty ?? ticket.reported_ok_qty}
                                </span>
                                {(ticket.verified_reject_qty ?? ticket.reported_reject_qty) > 0 && (
                                  <span className="font-semibold text-rose-700 dark:text-rose-400">
                                    Rej: {ticket.verified_reject_qty ?? ticket.reported_reject_qty}
                                  </span>
                                )}
                              </div>
                              {ticket.verified_defect_code && (
                                <div className="text-[10px] text-slate-500 dark:text-slate-400 mt-0.5">
                                  {ticket.verified_defect_code}
                                </div>
                              )}
                            </div>
                          )}
                        </td>

                        {/* Status / Disposition */}
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div>
                            {isPending && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                                <Clock className="h-3 w-3" /> PENDING
                              </span>
                            )}
                            {isApproved && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                                <CheckCircle2 className="h-3 w-3" /> APPROVED
                              </span>
                            )}
                            {isAdjusted && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                                <SlidersHorizontal className="h-3 w-3" /> ADJUSTED
                              </span>
                            )}
                            {isRejected && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300 border border-rose-200 dark:border-rose-800">
                                <AlertTriangle className="h-3 w-3" /> REJECTED
                              </span>
                            )}
                          </div>
                          {ticket.disposition && ticket.disposition !== "PENDING" && (
                            <div className="text-[10px] font-medium text-slate-500 dark:text-slate-400 mt-1 uppercase">
                              {ticket.disposition}
                            </div>
                          )}
                        </td>

                        {/* Reviewer */}
                        <td className="px-4 py-3">
                          {ticket.reviewed_by_name ? (
                            <div>
                              <div className="text-slate-800 dark:text-slate-200 font-medium truncate max-w-[120px]">
                                {ticket.reviewed_by_name}
                              </div>
                              <div className="text-[10px] text-slate-400 mt-0.5">
                                {ticket.reviewed_at ? new Date(ticket.reviewed_at).toLocaleDateString() : ""}
                              </div>
                            </div>
                          ) : (
                            <span className="text-[11px] text-slate-400">—</span>
                          )}
                        </td>

                        {/* Actions */}
                        <td className="px-4 py-3 text-right whitespace-nowrap">
                          {isPending ? (
                            <div className="flex items-center justify-end gap-1.5">
                              <button
                                onClick={() => handleQuickApprove(ticket)}
                                title="Quick Approve as-reported"
                                className="px-2 py-1 text-xs font-medium rounded bg-emerald-50 text-emerald-700 hover:bg-emerald-100 dark:bg-emerald-950/50 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 transition"
                              >
                                Approve
                              </button>
                              <button
                                onClick={() => handleOpenReview(ticket, "ADJUST")}
                                className="px-2.5 py-1 text-xs font-semibold rounded bg-amber-500 hover:bg-amber-600 text-white shadow-sm transition"
                              >
                                Review & Edit
                              </button>
                            </div>
                          ) : (
                            <button
                              onClick={() => handleOpenReview(ticket, "ADJUST")}
                              className="px-2.5 py-1 text-xs font-medium rounded border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
                            >
                              Re-examine
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>

        {/* Review & Decision Modal */}
        {selectedTicket && (
          <Modal
            isOpen={!!selectedTicket}
            onClose={() => setSelectedTicket(null)}
            title={`MRB Review: ${selectedTicket.mrb_number} (WO: ${selectedTicket.wo_number})`}
          >
            <div className="space-y-5">
              {/* Context Summary */}
              <div className="p-3.5 rounded-lg bg-slate-50 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700 space-y-2 text-xs">
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase">Work Order</span>
                    <span className="font-semibold text-slate-900 dark:text-white">{selectedTicket.wo_number}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase">Stage / Gate</span>
                    <span className="font-semibold text-slate-900 dark:text-white">{selectedTicket.stage}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase">Operator</span>
                    <span className="font-semibold text-slate-900 dark:text-white">{selectedTicket.operator_name || "Floor"}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block text-[10px] uppercase">Shift / Heat</span>
                    <span className="font-semibold text-slate-900 dark:text-white">
                      {selectedTicket.shift || "A"} {selectedTicket.heat_number ? `(${selectedTicket.heat_number})` : ""}
                    </span>
                  </div>
                </div>
                {selectedTicket.floor_remarks && (
                  <div className="pt-2 border-t border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-300">
                    <span className="font-medium text-slate-500">Floor Remarks: </span>
                    {selectedTicket.floor_remarks}
                  </div>
                )}
              </div>

              {/* Action Mode Selector */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1.5 uppercase tracking-wider">
                  MRB Verification Action
                </label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => setActionMode("APPROVE")}
                    className={`py-2 px-3 text-xs font-semibold rounded-lg border flex flex-col items-center gap-1 transition ${
                      actionMode === "APPROVE"
                        ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-500 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500"
                        : "border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
                    }`}
                  >
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                    <span>Confirm & Approve</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActionMode("ADJUST")}
                    className={`py-2 px-3 text-xs font-semibold rounded-lg border flex flex-col items-center gap-1 transition ${
                      actionMode === "ADJUST"
                        ? "bg-blue-50 dark:bg-blue-950/40 border-blue-500 text-blue-700 dark:text-blue-300 ring-1 ring-blue-500"
                        : "border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
                    }`}
                  >
                    <SlidersHorizontal className="h-4 w-4 text-blue-600" />
                    <span>Adjust Quantities</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActionMode("REJECT")}
                    className={`py-2 px-3 text-xs font-semibold rounded-lg border flex flex-col items-center gap-1 transition ${
                      actionMode === "REJECT"
                        ? "bg-rose-50 dark:bg-rose-950/40 border-rose-500 text-rose-700 dark:text-rose-300 ring-1 ring-rose-500"
                        : "border-slate-300 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
                    }`}
                  >
                    <AlertTriangle className="h-4 w-4 text-rose-600" />
                    <span>Reject / Flag</span>
                  </button>
                </div>
              </div>

              {/* Quantities Comparison & Inputs */}
              <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-800/30 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  {/* Shop Floor Reported */}
                  <div className="p-3 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                      Floor Reported
                    </p>
                    <div className="mt-2 space-y-1 text-xs">
                      <div className="flex justify-between">
                        <span className="text-slate-500">Good / OK:</span>
                        <span className="font-bold text-emerald-600">{selectedTicket.reported_ok_qty} pcs</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-slate-500">Rejections:</span>
                        <span className="font-bold text-rose-600">{selectedTicket.reported_reject_qty} pcs</span>
                      </div>
                      {selectedTicket.reported_defect_code && (
                        <div className="text-[11px] text-slate-500 mt-1 pt-1 border-t border-slate-100 dark:border-slate-700">
                          Defect: <span className="font-medium text-slate-700 dark:text-slate-300">{selectedTicket.reported_defect_code}</span>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* MRB Verified Input */}
                  <div className="p-3 rounded-lg bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
                    <p className="text-[10px] font-semibold uppercase tracking-wider text-amber-600 dark:text-amber-400">
                      MRB Verified (Quality & Planner)
                    </p>
                    <div className="mt-2 space-y-2">
                      <div>
                        <label className="block text-[11px] text-slate-500">Verified OK Qty</label>
                        <input
                          type="number"
                          min={0}
                          value={verifiedOkQty}
                          onChange={(e) => setVerifiedOkQty(Number(e.target.value))}
                          disabled={actionMode === "REJECT"}
                          className="w-full text-xs font-semibold px-2 py-1 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        />
                      </div>
                      <div>
                        <label className="block text-[11px] text-slate-500">Verified Rejection Qty</label>
                        <input
                          type="number"
                          min={0}
                          value={verifiedRejectQty}
                          onChange={(e) => setVerifiedRejectQty(Number(e.target.value))}
                          disabled={actionMode === "REJECT"}
                          className="w-full text-xs font-semibold px-2 py-1 rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-900 dark:text-white"
                        />
                      </div>
                    </div>
                  </div>
                </div>

                {/* Live Delta Banner */}
                {(deltaOk !== 0 || deltaRej !== 0) && actionMode === "ADJUST" && (
                  <div className="p-2.5 rounded-lg bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-800 text-xs text-blue-800 dark:text-blue-300 space-y-1">
                    <p className="font-semibold flex items-center gap-1.5">
                      <SlidersHorizontal className="h-3.5 w-3.5" /> Quantity Reconciliation Effect:
                    </p>
                    <p>
                      OK Qty adjustment: <span className="font-bold">{deltaOk > 0 ? `+${deltaOk}` : deltaOk} pcs</span> | Rejection adjustment: <span className="font-bold">{deltaRej > 0 ? `+${deltaRej}` : deltaRej} pcs</span>.
                    </p>
                    <p className="text-[11px] text-blue-600 dark:text-blue-400">
                      Stage WIP on-hand/rejected counters and downstream tracking will be updated automatically.
                    </p>
                  </div>
                )}
              </div>

              {/* Defect Code Selector */}
              {verifiedRejectQty > 0 && actionMode !== "REJECT" && (
                <div>
                  <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                    Verified Defect Classification
                  </label>
                  <select
                    value={verifiedDefectCode}
                    onChange={(e) => setVerifiedDefectCode(e.target.value)}
                    className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                  >
                    {DEFECT_CODES.map((d) => (
                      <option key={d.code} value={d.code}>
                        {d.label}
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {/* Disposition Decision */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Material Disposition Decision
                </label>
                <select
                  value={disposition}
                  onChange={(e) => setDisposition(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                >
                  {DISPOSITIONS.map((disp) => (
                    <option key={disp.value} value={disp.value}>
                      {disp.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Review Notes */}
              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Quality / Planner Audit Notes
                </label>
                <textarea
                  rows={2}
                  placeholder="State reason for approval or quantity adjustment..."
                  value={reviewNotes}
                  onChange={(e) => setReviewNotes(e.target.value)}
                  className="w-full text-xs px-3 py-2 rounded-lg border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder:text-slate-400"
                />
              </div>

              {/* Modal Buttons */}
              <div className="flex justify-end gap-2 pt-2 border-t border-slate-200 dark:border-slate-700">
                <button
                  type="button"
                  onClick={() => setSelectedTicket(null)}
                  disabled={submitting}
                  className="px-4 py-2 text-xs font-medium rounded-lg border border-slate-300 dark:border-slate-700 text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleSubmitDecision}
                  disabled={submitting}
                  className={`px-4 py-2 text-xs font-semibold rounded-lg text-white shadow-sm transition flex items-center gap-1.5 ${
                    actionMode === "APPROVE"
                      ? "bg-emerald-600 hover:bg-emerald-700"
                      : actionMode === "ADJUST"
                      ? "bg-blue-600 hover:bg-blue-700"
                      : "bg-rose-600 hover:bg-rose-700"
                  }`}
                >
                  {submitting && <RefreshCw className="h-3.5 w-3.5 animate-spin" />}
                  <span>
                    {actionMode === "APPROVE"
                      ? "Confirm & Approve"
                      : actionMode === "ADJUST"
                      ? "Save Adjustments & Reconcile"
                      : "Flag & Reject"}
                  </span>
                </button>
              </div>
            </div>
          </Modal>
        )}
      </div>
    </AppShell>
  );
}

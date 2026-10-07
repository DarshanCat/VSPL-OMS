"use client";
import React, { useState, useEffect, useCallback } from "react";
import {
  FileText,
  Search,
  CheckCircle2,
  AlertTriangle,
  Clock,
  ShieldCheck,
  ShieldAlert,
  Layers,
  RefreshCw,
  ExternalLink,
  ChevronRight,
  X,
  Plus,
  AlertCircle,
  FileSpreadsheet,
  Check,
  SlidersHorizontal,
  Info,
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getCurrentUserRole } from "@/lib/api";
import {
  getEngineeringKPIs,
  getWorkOrdersReadiness,
  getWorkOrderReadiness,
  updateWorkOrderReadiness,
  releaseEngineering,
  revokeEngineeringRelease,
  createPartRevision,
  setActivePartRevision,
  engineeringErrorMessage,
  type EngineeringKPIs,
  type WOReadinessItem,
  type WOReadinessDetail,
  type EngineeringRevision,
} from "@/lib/engineeringApi";

export default function EngineeringReadinessPage() {
  const [userRole, setUserRole] = useState<string | null>(null);
  const [kpis, setKpis] = useState<EngineeringKPIs | null>(null);
  const [items, setItems] = useState<WOReadinessItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [orderTypeFilter, setOrderTypeFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Drawer / Detail state
  const [selectedWoId, setSelectedWoId] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<WOReadinessDetail | null>(null);
  const [savingChecklist, setSavingChecklist] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revocationReason, setRevocationReason] = useState("");
  const [showRevokeModal, setShowRevokeModal] = useState(false);

  // New revision form state
  const [showNewRevModal, setShowNewRevModal] = useState(false);
  const [newRevDrawingNo, setNewRevDrawingNo] = useState("");
  const [newRevRev, setNewRevRev] = useState("");
  const [newRevUrl, setNewRevUrl] = useState("");
  const [newRevSpec, setNewRevSpec] = useState("");
  const [newRevProcess, setNewRevProcess] = useState("");
  const [newRevPattern, setNewRevPattern] = useState("");
  const [newRevTooling, setNewRevTooling] = useState("");
  const [creatingRev, setCreatingRev] = useState(false);

  useEffect(() => {
    setUserRole(getCurrentUserRole());
  }, []);

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const [kpiRes, itemsRes] = await Promise.all([
        getEngineeringKPIs(),
        getWorkOrdersReadiness({
          status: statusFilter || undefined,
          order_type: orderTypeFilter || undefined,
          search: searchQuery || undefined,
        }),
      ]);
      setKpis(kpiRes);
      setItems(itemsRes);
    } catch (err) {
      setError(engineeringErrorMessage(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [statusFilter, orderTypeFilter, searchQuery]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  const openDetail = async (woId: string) => {
    setSelectedWoId(woId);
    setDetailLoading(true);
    try {
      const res = await getWorkOrderReadiness(woId);
      setDetail(res);
    } catch (err) {
      setError(engineeringErrorMessage(err));
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setSelectedWoId(null);
    setDetail(null);
    setShowRevokeModal(false);
    setRevocationReason("");
  };

  const handleToggleChecklist = (field: keyof WOReadinessDetail) => {
    if (!detail || detail.is_released) return;
    setDetail({
      ...detail,
      [field]: !detail[field],
    });
  };

  const handleSaveChecklist = async () => {
    if (!detail || !selectedWoId) return;
    setSavingChecklist(true);
    setError(null);
    try {
      const updated = await updateWorkOrderReadiness(selectedWoId, {
        drawing_available: detail.drawing_available,
        drawing_revision_verified: detail.drawing_revision_verified,
        customer_spec_verified: detail.customer_spec_verified,
        process_sheet_verified: detail.process_sheet_verified,
        pattern_ready: detail.pattern_ready,
        tooling_ready: detail.tooling_ready,
        verified_revision: detail.verified_revision,
        remarks: detail.remarks,
        replacement_part_id: detail.replacement_part_id,
        replacement_pattern_number: detail.replacement_pattern_number,
        replacement_reason: detail.replacement_reason,
      });
      setDetail(updated);
      setSuccessMessage("Checklist progress saved successfully.");
      setTimeout(() => setSuccessMessage(null), 3000);
      fetchData();
    } catch (err) {
      setError(engineeringErrorMessage(err));
    } finally {
      setSavingChecklist(false);
    }
  };

  const handleRelease = async () => {
    if (!detail || !selectedWoId) return;
    if (!detail.verified_revision) {
      setError("Please specify a verified drawing revision.");
      return;
    }
    setReleasing(true);
    setError(null);
    try {
      const res = await releaseEngineering({
        work_order_id: selectedWoId,
        verified_revision: detail.verified_revision,
        document_name: detail.active_part_revision?.drawing_number || `DWG-${detail.part_name}`,
        document_url: detail.active_part_revision?.drawing_url || undefined,
        remarks: detail.remarks || undefined,
        replacement_part_id: detail.replacement_part_id || undefined,
        replacement_pattern_number: detail.replacement_pattern_number || undefined,
        replacement_reason: detail.replacement_reason || undefined,
      });
      setSuccessMessage(`Work Order ${res.work_order_number} released for engineering!`);
      setTimeout(() => setSuccessMessage(null), 4000);
      // Refresh detail and list
      const refreshedDetail = await getWorkOrderReadiness(selectedWoId);
      setDetail(refreshedDetail);
      fetchData();
    } catch (err) {
      setError(engineeringErrorMessage(err));
    } finally {
      setReleasing(false);
    }
  };

  const handleRevoke = async () => {
    if (!detail || !selectedWoId) return;
    if (!revocationReason.trim()) {
      setError("Revocation reason is mandatory.");
      return;
    }
    setRevoking(true);
    setError(null);
    try {
      await revokeEngineeringRelease(selectedWoId, {
        revocation_reason: revocationReason,
      });
      setShowRevokeModal(false);
      setRevocationReason("");
      setSuccessMessage("Engineering release revoked successfully.");
      setTimeout(() => setSuccessMessage(null), 4000);
      const refreshedDetail = await getWorkOrderReadiness(selectedWoId);
      setDetail(refreshedDetail);
      fetchData();
    } catch (err) {
      setError(engineeringErrorMessage(err));
    } finally {
      setRevoking(false);
    }
  };

  const handleCreateRevision = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!detail) return;
    setCreatingRev(true);
    setError(null);
    try {
      await createPartRevision(detail.part_id, {
        drawing_number: newRevDrawingNo,
        drawing_revision: newRevRev,
        drawing_url: newRevUrl || undefined,
        customer_spec_ref: newRevSpec || undefined,
        process_sheet_number: newRevProcess || undefined,
        pattern_number: newRevPattern || undefined,
        tooling_id: newRevTooling || undefined,
        is_active: true,
      });
      setShowNewRevModal(false);
      setNewRevDrawingNo("");
      setNewRevRev("");
      setNewRevUrl("");
      setNewRevSpec("");
      setNewRevProcess("");
      setNewRevPattern("");
      setNewRevTooling("");
      const refreshedDetail = await getWorkOrderReadiness(detail.work_order_id);
      setDetail(refreshedDetail);
      setSuccessMessage("New engineering revision created and set active.");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError(engineeringErrorMessage(err));
    } finally {
      setCreatingRev(false);
    }
  };

  const handleSetActiveRevision = async (revId: string) => {
    if (!detail) return;
    try {
      await setActivePartRevision(revId);
      const refreshedDetail = await getWorkOrderReadiness(detail.work_order_id);
      setDetail(refreshedDetail);
      setSuccessMessage("Active revision updated.");
      setTimeout(() => setSuccessMessage(null), 3000);
    } catch (err) {
      setError(engineeringErrorMessage(err));
    }
  };

  const checklistPassedCount = detail
    ? [
        detail.drawing_available,
        detail.drawing_revision_verified,
        detail.customer_spec_verified,
        detail.process_sheet_verified,
        detail.pattern_ready,
        detail.tooling_ready,
      ].filter(Boolean).length
    : 0;

  const isAllChecklistPassed = checklistPassedCount === 6;

  return (
    <AppShell>
      <div className="p-6 max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="p-2 rounded-lg bg-cyan-500/10 text-cyan-600 dark:text-cyan-400">
                <FileText className="h-6 w-6" />
              </span>
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50">
                  Engineering Readiness Gate
                </h1>
                <p className="text-sm text-zinc-500 dark:text-zinc-400">
                  Authoritative engineering verification, drawing controls, and release gate for Work Orders.
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 text-sm font-medium rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Global Feedback Banners */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 text-rose-800 dark:text-rose-300 text-sm flex items-start gap-3 shadow-sm">
            <AlertTriangle className="h-5 w-5 shrink-0 text-rose-500 mt-0.5" />
            <div className="flex-1">
              <span className="font-semibold">Error: </span>
              {error}
            </div>
            <button onClick={() => setError(null)} className="text-rose-500 hover:text-rose-700">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {successMessage && (
          <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/50 text-emerald-800 dark:text-emerald-300 text-sm flex items-start gap-3 shadow-sm">
            <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500 mt-0.5" />
            <div className="flex-1">{successMessage}</div>
            <button onClick={() => setSuccessMessage(null)} className="text-emerald-500 hover:text-emerald-700">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* KPI Cards */}
        {kpis && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 shadow-sm">
              <div className="flex items-center justify-between text-xs font-medium text-zinc-500 dark:text-zinc-400">
                <span>Pending Review</span>
                <Clock className="h-4 w-4 text-amber-500" />
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{kpis.pending_review}</div>
              <div className="text-xs text-amber-600 dark:text-amber-400 mt-0.5 font-medium">Awaiting check</div>
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 shadow-sm">
              <div className="flex items-center justify-between text-xs font-medium text-zinc-500 dark:text-zinc-400">
                <span>Ready for Release</span>
                <ShieldCheck className="h-4 w-4 text-blue-500" />
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{kpis.ready_for_release}</div>
              <div className="text-xs text-blue-600 dark:text-blue-400 mt-0.5 font-medium">6/6 verified</div>
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 shadow-sm">
              <div className="flex items-center justify-between text-xs font-medium text-zinc-500 dark:text-zinc-400">
                <span>Released</span>
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{kpis.released}</div>
              <div className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5 font-medium">Engineering passed</div>
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 shadow-sm">
              <div className="flex items-center justify-between text-xs font-medium text-zinc-500 dark:text-zinc-400">
                <span>Blocked / Issues</span>
                <ShieldAlert className="h-4 w-4 text-rose-500" />
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{kpis.blocked}</div>
              <div className="text-xs text-rose-600 dark:text-rose-400 mt-0.5 font-medium">Requires resolution</div>
            </div>

            <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/70 shadow-sm col-span-2 md:col-span-1">
              <div className="flex items-center justify-between text-xs font-medium text-zinc-500 dark:text-zinc-400">
                <span>NPD Work Orders</span>
                <Layers className="h-4 w-4 text-purple-500" />
              </div>
              <div className="mt-2 text-2xl font-bold text-zinc-900 dark:text-zinc-50">{kpis.npd_count}</div>
              <div className="text-xs text-purple-600 dark:text-purple-400 mt-0.5 font-medium">New part development</div>
            </div>
          </div>
        )}

        {/* Filters and Controls */}
        <div className="flex flex-col sm:flex-row gap-3 p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900/60 shadow-sm">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              placeholder="Search WO number, part, customer..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-cyan-500/30"
            />
          </div>

          <div className="flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              aria-label="Filter by Readiness Status"
              className="px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/30"
            >
              <option value="">All Statuses</option>
              <option value="PENDING">Pending Review</option>
              <option value="READY">Ready for Release</option>
              <option value="RELEASED">Released</option>
              <option value="BLOCKED">Blocked</option>
            </select>

            <select
              value={orderTypeFilter}
              onChange={(e) => setOrderTypeFilter(e.target.value)}
              aria-label="Filter by Order Type"
              className="px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/30"
            >
              <option value="">All Order Types</option>
              <option value="REGULAR">Regular Production</option>
              <option value="NPD">New Product (NPD)</option>
            </select>
          </div>
        </div>

        {/* Work Orders Table */}
        <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/75 dark:bg-zinc-800/40 text-xs font-semibold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
                  <th className="px-4 py-3">Work Order</th>
                  <th className="px-4 py-3">Part & Customer</th>
                  <th className="px-4 py-3 text-center">Type</th>
                  <th className="px-4 py-3 text-right">Qty</th>
                  <th className="px-4 py-3">Readiness Checklist</th>
                  <th className="px-4 py-3 text-center">Status</th>
                  <th className="px-4 py-3">Release Verification</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-zinc-500 dark:text-zinc-400">
                      <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-cyan-500" />
                      Loading Engineering Readiness data...
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-zinc-500 dark:text-zinc-400">
                      <FileSpreadsheet className="h-8 w-8 mx-auto mb-2 text-zinc-400 opacity-50" />
                      No work orders match the selected filters.
                    </td>
                  </tr>
                ) : (
                  items.map((item) => {
                    const pct = Math.round((item.checklist_count / item.checklist_total) * 100);
                    return (
                      <tr
                        key={item.work_order_id}
                        className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors"
                      >
                        <td className="px-4 py-3.5 font-medium text-zinc-900 dark:text-zinc-100 whitespace-nowrap">
                          {item.work_order_number}
                        </td>
                        <td className="px-4 py-3.5">
                          <div className="font-medium text-zinc-900 dark:text-zinc-100">{item.part_name}</div>
                          <div className="text-xs text-zinc-500 dark:text-zinc-400">{item.customer_name}</div>
                        </td>
                        <td className="px-4 py-3.5 text-center">
                          {item.order_type === "NPD" ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                              NPD
                            </span>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                              Regular
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3.5 text-right font-medium text-zinc-800 dark:text-zinc-200">
                          {item.quantity.toLocaleString()}
                        </td>
                        <td className="px-4 py-3.5 min-w-[180px]">
                          <div className="space-y-1">
                            <div className="flex items-center justify-between text-xs">
                              <span className="font-medium text-zinc-700 dark:text-zinc-300">
                                {item.checklist_count}/{item.checklist_total} items
                              </span>
                              <span className="text-zinc-500 dark:text-zinc-400">{pct}%</span>
                            </div>
                            <div className="w-full h-1.5 bg-zinc-200 dark:bg-zinc-800 rounded-full overflow-hidden">
                              <div
                                className={`h-full transition-all duration-300 ${
                                  item.is_released
                                    ? "bg-emerald-500"
                                    : item.checklist_count === 6
                                    ? "bg-blue-500"
                                    : item.checklist_count >= 4
                                    ? "bg-amber-500"
                                    : "bg-rose-500"
                                }`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                          </div>
                        </td>
                        <td className="px-4 py-3.5 text-center">
                          {item.readiness_status === "RELEASED" ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              Released
                            </span>
                          ) : item.readiness_status === "READY" ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300 border border-blue-200 dark:border-blue-800">
                              <ShieldCheck className="h-3.5 w-3.5" />
                              Ready
                            </span>
                          ) : item.readiness_status === "BLOCKED" ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300 border border-rose-200 dark:border-rose-800">
                              <ShieldAlert className="h-3.5 w-3.5" />
                              Blocked
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                              <Clock className="h-3.5 w-3.5" />
                              Pending
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3.5">
                          {item.is_released ? (
                            <div className="text-xs">
                              <div className="font-semibold text-emerald-700 dark:text-emerald-400">
                                Rev: {item.verified_revision || "Standard"}
                              </div>
                              <div className="text-zinc-500 dark:text-zinc-400">
                                {item.released_at ? new Date(item.released_at).toLocaleDateString() : ""}
                              </div>
                            </div>
                          ) : (
                            <span className="text-xs text-zinc-400 italic">Unreleased</span>
                          )}
                        </td>
                        <td className="px-4 py-3.5 text-right">
                          <button
                            onClick={() => openDetail(item.work_order_id)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg bg-cyan-50 dark:bg-cyan-950/50 text-cyan-700 dark:text-cyan-300 hover:bg-cyan-100 dark:hover:bg-cyan-900/60 border border-cyan-200 dark:border-cyan-800 transition-colors"
                          >
                            {item.is_released ? "View Record" : "Checklist Gate"}
                            <ChevronRight className="h-3.5 w-3.5" />
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Verification & Release Slide-over Drawer */}
        {selectedWoId && (
          <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end">
            <div className="w-full max-w-2xl bg-white dark:bg-zinc-900 h-full shadow-2xl border-l border-zinc-200 dark:border-zinc-800 flex flex-col animate-in slide-in-from-right duration-200">
              {/* Drawer Header */}
              <div className="px-6 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-zinc-900 dark:text-zinc-50">
                      Engineering Readiness Checklist
                    </h2>
                    {detail?.order_type === "NPD" && (
                      <span className="px-2 py-0.5 text-xs font-bold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300 rounded-full border border-purple-200 dark:border-purple-800">
                        NPD
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Work Order: <span className="font-semibold text-zinc-700 dark:text-zinc-300">{detail?.work_order_number}</span> &bull; Part: <span className="font-semibold text-zinc-700 dark:text-zinc-300">{detail?.part_name}</span>
                  </p>
                </div>
                <button
                  onClick={closeDetail}
                  className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Drawer Body */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {detailLoading ? (
                  <div className="py-24 text-center">
                    <RefreshCw className="h-8 w-8 animate-spin mx-auto text-cyan-500 mb-3" />
                    <p className="text-sm text-zinc-500 dark:text-zinc-400">Loading checklist details...</p>
                  </div>
                ) : detail ? (
                  <>
                    {/* Status Overview Card */}
                    <div className={`p-4 rounded-xl border ${
                      detail.is_released
                        ? "bg-emerald-50/60 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-900/40"
                        : isAllChecklistPassed
                        ? "bg-blue-50/60 dark:bg-blue-950/20 border-blue-200 dark:border-blue-900/40"
                        : "bg-amber-50/60 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900/40"
                    }`}>
                      <div className="flex items-start justify-between">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              Gate Status: {detail.readiness_status}
                            </span>
                            <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-white/80 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700">
                              {checklistPassedCount}/6 Verified
                            </span>
                          </div>
                          <p className="text-xs text-zinc-600 dark:text-zinc-400">
                            {detail.is_released
                              ? `Released by ${detail.engineer_name || "Engineering"} on ${detail.released_at ? new Date(detail.released_at).toLocaleString() : "Approved"}`
                              : isAllChecklistPassed
                              ? "All 6 engineering verification items verified. Ready for release authorization."
                              : "Complete all 6 checklist items and verify drawing revision to unlock release."}
                          </p>
                        </div>
                        {detail.is_released && (
                          <ShieldCheck className="h-7 w-7 text-emerald-600 dark:text-emerald-400 shrink-0" />
                        )}
                      </div>
                    </div>

                    {/* Part Engineering Revision Profile */}
                    <div className="p-4 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-800/30 space-y-3">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <SlidersHorizontal className="h-4 w-4 text-cyan-600 dark:text-cyan-400" />
                          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                            Part Engineering Master Profile
                          </h3>
                        </div>
                        <button
                          onClick={() => setShowNewRevModal(true)}
                          className="inline-flex items-center gap-1 text-xs font-medium text-cyan-600 dark:text-cyan-400 hover:underline"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          New Revision
                        </button>
                      </div>

                      {detail.active_part_revision ? (
                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div>
                            <span className="text-zinc-500 dark:text-zinc-400">Drawing No:</span>{" "}
                            <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                              {detail.active_part_revision.drawing_number}
                            </span>
                          </div>
                          <div>
                            <span className="text-zinc-500 dark:text-zinc-400">Active Revision:</span>{" "}
                            <span className="font-semibold text-zinc-800 dark:text-zinc-200">
                              {detail.active_part_revision.drawing_revision}
                            </span>
                          </div>
                          <div>
                            <span className="text-zinc-500 dark:text-zinc-400">Spec Ref:</span>{" "}
                            <span className="font-medium text-zinc-700 dark:text-zinc-300">
                              {detail.active_part_revision.customer_spec_ref || "None specified"}
                            </span>
                          </div>
                          <div>
                            <span className="text-zinc-500 dark:text-zinc-400">Process Sheet:</span>{" "}
                            <span className="font-medium text-zinc-700 dark:text-zinc-300">
                              {detail.active_part_revision.process_sheet_number || "Standard"}
                            </span>
                          </div>
                          <div>
                            <span className="text-zinc-500 dark:text-zinc-400">Pattern / Core:</span>{" "}
                            <span className="font-medium text-zinc-700 dark:text-zinc-300">
                              {detail.active_part_revision.pattern_number || "N/A"}
                            </span>
                          </div>
                          <div>
                            <span className="text-zinc-500 dark:text-zinc-400">Tooling ID:</span>{" "}
                            <span className="font-medium text-zinc-700 dark:text-zinc-300">
                              {detail.active_part_revision.tooling_id || "N/A"}
                            </span>
                          </div>
                          {detail.active_part_revision.drawing_url && (
                            <div className="col-span-2">
                              <a
                                href={detail.active_part_revision.drawing_url}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1 text-cyan-600 dark:text-cyan-400 hover:underline"
                              >
                                View Linked Drawing Document <ExternalLink className="h-3 w-3" />
                              </a>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="text-xs text-amber-600 dark:text-amber-400 flex items-center gap-2">
                          <Info className="h-4 w-4 shrink-0" />
                          <span>No active engineering revision configured for this part. Click &ldquo;New Revision&rdquo; to add one.</span>
                        </div>
                      )}

                      {/* Available Revision Switcher if multiple exist */}
                      {detail.available_revisions.length > 1 && (
                        <div className="pt-2 border-t border-zinc-200 dark:border-zinc-800">
                          <label className="block text-xs font-medium text-zinc-500 dark:text-zinc-400 mb-1">
                            Switch Active Part Revision:
                          </label>
                          <div className="flex flex-wrap gap-1.5">
                            {detail.available_revisions.map((rev) => (
                              <button
                                key={rev.id}
                                onClick={() => handleSetActiveRevision(rev.id)}
                                className={`px-2.5 py-1 rounded text-xs font-medium transition-colors ${
                                  rev.is_active
                                    ? "bg-cyan-600 text-white shadow-xs"
                                    : "bg-zinc-200 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-300 dark:hover:bg-zinc-600"
                                }`}
                              >
                                Rev {rev.drawing_revision} {rev.is_active && "(Active)"}
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* 6-Point Verification Checklist */}
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                          <CheckCircle2 className="h-4 w-4 text-cyan-600 dark:text-cyan-400" />
                          6-Point Verification Checklist
                        </h3>
                        <span className="text-xs text-zinc-500">
                          {detail.is_released ? "Released (Locked)" : "Click to toggle"}
                        </span>
                      </div>

                      <div className="space-y-2">
                        {/* 1. Drawing Available */}
                        <div
                          onClick={() => handleToggleChecklist("drawing_available")}
                          className={`p-3.5 rounded-xl border flex items-start gap-3 transition-colors ${
                            detail.is_released
                              ? "cursor-default opacity-90"
                              : "cursor-pointer hover:border-cyan-500/50"
                          } ${
                            detail.drawing_available
                              ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800"
                              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800"
                          }`}
                        >
                          <div
                            className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center border transition-colors ${
                              detail.drawing_available
                                ? "bg-emerald-600 border-emerald-600 text-white"
                                : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800"
                            }`}
                          >
                            {detail.drawing_available && <Check className="h-3.5 w-3.5" />}
                          </div>
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              1. Part Drawing Availability
                            </div>
                            <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                              Approved production engineering drawing is accessible in the system or on file.
                            </div>
                          </div>
                        </div>

                        {/* 2. Drawing Revision Verified */}
                        <div
                          onClick={() => handleToggleChecklist("drawing_revision_verified")}
                          className={`p-3.5 rounded-xl border flex items-start gap-3 transition-colors ${
                            detail.is_released
                              ? "cursor-default opacity-90"
                              : "cursor-pointer hover:border-cyan-500/50"
                          } ${
                            detail.drawing_revision_verified
                              ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800"
                              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800"
                          }`}
                        >
                          <div
                            className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center border transition-colors ${
                              detail.drawing_revision_verified
                                ? "bg-emerald-600 border-emerald-600 text-white"
                                : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800"
                            }`}
                          >
                            {detail.drawing_revision_verified && <Check className="h-3.5 w-3.5" />}
                          </div>
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              2. Drawing Revision Verification
                            </div>
                            <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                              Current drawing revision matches customer PO requirement and latest engineering change order (ECN).
                            </div>
                          </div>
                        </div>

                        {/* 3. Customer Spec Verified */}
                        <div
                          onClick={() => handleToggleChecklist("customer_spec_verified")}
                          className={`p-3.5 rounded-xl border flex items-start gap-3 transition-colors ${
                            detail.is_released
                              ? "cursor-default opacity-90"
                              : "cursor-pointer hover:border-cyan-500/50"
                          } ${
                            detail.customer_spec_verified
                              ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800"
                              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800"
                          }`}
                        >
                          <div
                            className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center border transition-colors ${
                              detail.customer_spec_verified
                                ? "bg-emerald-600 border-emerald-600 text-white"
                                : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800"
                            }`}
                          >
                            {detail.customer_spec_verified && <Check className="h-3.5 w-3.5" />}
                          </div>
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              3. Customer & Material Specifications
                            </div>
                            <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                              Grade, chemical composition, mechanical properties, and testing parameters verified.
                            </div>
                          </div>
                        </div>

                        {/* 4. Process Sheet Verified */}
                        <div
                          onClick={() => handleToggleChecklist("process_sheet_verified")}
                          className={`p-3.5 rounded-xl border flex items-start gap-3 transition-colors ${
                            detail.is_released
                              ? "cursor-default opacity-90"
                              : "cursor-pointer hover:border-cyan-500/50"
                          } ${
                            detail.process_sheet_verified
                              ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800"
                              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800"
                          }`}
                        >
                          <div
                            className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center border transition-colors ${
                              detail.process_sheet_verified
                                ? "bg-emerald-600 border-emerald-600 text-white"
                                : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800"
                            }`}
                          >
                            {detail.process_sheet_verified && <Check className="h-3.5 w-3.5" />}
                          </div>
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              4. Process / Method Sheet Ready
                            </div>
                            <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                              Stage routing, machining setup, cutting parameters, and inspection checkpoints approved.
                            </div>
                          </div>
                        </div>

                        {/* 5. Pattern Ready */}
                        <div
                          onClick={() => handleToggleChecklist("pattern_ready")}
                          className={`p-3.5 rounded-xl border flex items-start gap-3 transition-colors ${
                            detail.is_released
                              ? "cursor-default opacity-90"
                              : "cursor-pointer hover:border-cyan-500/50"
                          } ${
                            detail.pattern_ready
                              ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800"
                              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800"
                          }`}
                        >
                          <div
                            className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center border transition-colors ${
                              detail.pattern_ready
                                ? "bg-emerald-600 border-emerald-600 text-white"
                                : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800"
                            }`}
                          >
                            {detail.pattern_ready && <Check className="h-3.5 w-3.5" />}
                          </div>
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              5. Pattern / Core Box Readiness
                            </div>
                            <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                              Casting tooling / mold / pattern inspected, dimensionally verified, and ready for molding.
                            </div>
                          </div>
                        </div>

                        {/* 6. Tooling Ready */}
                        <div
                          onClick={() => handleToggleChecklist("tooling_ready")}
                          className={`p-3.5 rounded-xl border flex items-start gap-3 transition-colors ${
                            detail.is_released
                              ? "cursor-default opacity-90"
                              : "cursor-pointer hover:border-cyan-500/50"
                          } ${
                            detail.tooling_ready
                              ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800"
                              : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800"
                          }`}
                        >
                          <div
                            className={`mt-0.5 w-5 h-5 rounded-md flex items-center justify-center border transition-colors ${
                              detail.tooling_ready
                                ? "bg-emerald-600 border-emerald-600 text-white"
                                : "border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800"
                            }`}
                          >
                            {detail.tooling_ready && <Check className="h-3.5 w-3.5" />}
                          </div>
                          <div className="flex-1">
                            <div className="font-semibold text-sm text-zinc-900 dark:text-zinc-100">
                              6. Machining Tooling, Jigs & Fixtures
                            </div>
                            <div className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                              Fixtures, jaws, inserts, and proof-turning tools ready on shop floor.
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Verified Revision and Engineering Remarks */}
                    <div className="space-y-4 pt-2 border-t border-zinc-200 dark:border-zinc-800">
                      <div>
                        <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                          Verified Drawing Revision *
                        </label>
                        <input
                          type="text"
                          disabled={detail.is_released}
                          value={detail.verified_revision || ""}
                          onChange={(e) => setDetail({ ...detail, verified_revision: e.target.value })}
                          placeholder="e.g. Rev A / Rev 02 / 2026-R1"
                          className="w-full px-3.5 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 disabled:opacity-60"
                        />
                        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
                          This revision will be permanently stamped on the Work Order upon release.
                        </p>
                      </div>

                      <div>
                        <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                          Engineering Remarks / Notes
                        </label>
                        <textarea
                          rows={3}
                          disabled={detail.is_released}
                          value={detail.remarks || ""}
                          onChange={(e) => setDetail({ ...detail, remarks: e.target.value })}
                          placeholder="Add any specific engineering observations, heat treatment notes, or tolerances..."
                          className="w-full px-3.5 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-cyan-500/30 disabled:opacity-60"
                        />
                      </div>
                    </div>

                    {/* Replacement / Deviation Section (if needed) */}
                    <div className="p-3.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-800/30 space-y-3">
                      <div className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4 text-amber-500" />
                        <h4 className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
                          Engineering Substitution / Deviation (Optional)
                        </h4>
                      </div>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
                        <div>
                          <label className="block text-zinc-500 dark:text-zinc-400 mb-1">
                            Substitute Pattern / Tooling No.
                          </label>
                          <input
                            type="text"
                            disabled={detail.is_released}
                            value={detail.replacement_pattern_number || ""}
                            onChange={(e) => setDetail({ ...detail, replacement_pattern_number: e.target.value })}
                            placeholder="e.g. PAT-ALT-44"
                            className="w-full px-3 py-1.5 rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 disabled:opacity-60"
                          />
                        </div>
                        <div>
                          <label className="block text-zinc-500 dark:text-zinc-400 mb-1">
                            Substitution Justification / Reason
                          </label>
                          <input
                            type="text"
                            disabled={detail.is_released}
                            value={detail.replacement_reason || ""}
                            onChange={(e) => setDetail({ ...detail, replacement_reason: e.target.value })}
                            placeholder="Mandatory if substitute pattern is used"
                            className="w-full px-3 py-1.5 rounded-md border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 disabled:opacity-60"
                          />
                        </div>
                      </div>
                    </div>
                  </>
                ) : null}
              </div>

              {/* Drawer Footer Actions */}
              {detail && (
                <div className="p-4 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50/80 dark:bg-zinc-900/80 flex items-center justify-between gap-3">
                  {detail.is_released ? (
                    <>
                      <div className="text-xs text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1.5">
                        <CheckCircle2 className="h-4 w-4" />
                        Released for Manufacturing
                      </div>
                      {userRole === "admin" && (
                        <button
                          onClick={() => setShowRevokeModal(true)}
                          className="px-3.5 py-2 text-xs font-semibold rounded-lg bg-rose-50 dark:bg-rose-950/50 text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/60 border border-rose-200 dark:border-rose-800 transition-colors"
                        >
                          Revoke Release (Admin)
                        </button>
                      )}
                    </>
                  ) : (
                    <>
                      <button
                        onClick={handleSaveChecklist}
                        disabled={savingChecklist}
                        className="px-4 py-2 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors disabled:opacity-50"
                      >
                        {savingChecklist ? "Saving..." : "Save Progress"}
                      </button>

                      <button
                        onClick={handleRelease}
                        disabled={!isAllChecklistPassed || !detail.verified_revision || releasing}
                        className="px-5 py-2 text-xs font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-sm transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                      >
                        {releasing ? (
                          <>
                            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                            Authorizing...
                          </>
                        ) : (
                          <>
                            <ShieldCheck className="h-4 w-4" />
                            Authorize Engineering Release
                          </>
                        )}
                      </button>
                    </>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Admin Revocation Modal */}
        {showRevokeModal && (
          <div className="fixed inset-0 z-60 overflow-hidden bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
            <div className="w-full max-w-md bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 p-6 space-y-4 animate-in zoom-in-95 duration-150">
              <div className="flex items-center gap-3 text-rose-600 dark:text-rose-400">
                <ShieldAlert className="h-6 w-6" />
                <h3 className="text-lg font-bold">Revoke Engineering Release</h3>
              </div>
              <p className="text-xs text-zinc-600 dark:text-zinc-400">
                Revoking this release will block the Work Order from advancing in the release chain. A mandatory audit log entry will be created.
              </p>
              <div>
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                  Revocation Reason *
                </label>
                <textarea
                  rows={3}
                  value={revocationReason}
                  onChange={(e) => setRevocationReason(e.target.value)}
                  placeholder="Specify why engineering release is being revoked (e.g. Drawing revision mismatch reported by customer)..."
                  className="w-full px-3.5 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-rose-500/30"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={() => setShowRevokeModal(false)}
                  className="px-4 py-2 text-xs font-medium rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
                <button
                  onClick={handleRevoke}
                  disabled={!revocationReason.trim() || revoking}
                  className="px-4 py-2 text-xs font-semibold rounded-lg bg-rose-600 hover:bg-rose-500 text-white disabled:opacity-40"
                >
                  {revoking ? "Revoking..." : "Confirm Revocation"}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Create Engineering Revision Modal */}
        {showNewRevModal && (
          <div className="fixed inset-0 z-60 overflow-hidden bg-black/70 backdrop-blur-xs flex items-center justify-center p-4">
            <div className="w-full max-w-lg bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl border border-zinc-200 dark:border-zinc-800 p-6 space-y-4 animate-in zoom-in-95 duration-150">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <SlidersHorizontal className="h-5 w-5 text-cyan-600" />
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    Add Part Engineering Revision
                  </h3>
                </div>
                <button
                  onClick={() => setShowNewRevModal(false)}
                  className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>

              <form onSubmit={handleCreateRevision} className="space-y-3 text-xs">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Drawing Number *
                    </label>
                    <input
                      required
                      type="text"
                      value={newRevDrawingNo}
                      onChange={(e) => setNewRevDrawingNo(e.target.value)}
                      placeholder="e.g. DWG-2026-4401"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Drawing Revision *
                    </label>
                    <input
                      required
                      type="text"
                      value={newRevRev}
                      onChange={(e) => setNewRevRev(e.target.value)}
                      placeholder="e.g. Rev 03"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                </div>

                <div>
                  <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                    Drawing Document URL / Link
                  </label>
                  <input
                    type="text"
                    value={newRevUrl}
                    onChange={(e) => setNewRevUrl(e.target.value)}
                    placeholder="e.g. https://storage.googleapis.com/.../dwg-4401.pdf"
                    className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Customer Spec Ref
                    </label>
                    <input
                      type="text"
                      value={newRevSpec}
                      onChange={(e) => setNewRevSpec(e.target.value)}
                      placeholder="e.g. ASTM A536 65-45-12"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Process / Method Sheet
                    </label>
                    <input
                      type="text"
                      value={newRevProcess}
                      onChange={(e) => setNewRevProcess(e.target.value)}
                      placeholder="e.g. PS-F1-F2-FI"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Pattern / Core Box Number
                    </label>
                    <input
                      type="text"
                      value={newRevPattern}
                      onChange={(e) => setNewRevPattern(e.target.value)}
                      placeholder="e.g. PAT-4401-A"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                  <div>
                    <label className="block font-medium text-zinc-700 dark:text-zinc-300 mb-1">
                      Tooling / Fixture ID
                    </label>
                    <input
                      type="text"
                      value={newRevTooling}
                      onChange={(e) => setNewRevTooling(e.target.value)}
                      placeholder="e.g. JIG-4401"
                      className="w-full px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    />
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-3 border-t border-zinc-200 dark:border-zinc-800">
                  <button
                    type="button"
                    onClick={() => setShowNewRevModal(false)}
                    className="px-4 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={creatingRev}
                    className="px-4 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white font-semibold disabled:opacity-50"
                  >
                    {creatingRev ? "Saving..." : "Create & Activate"}
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

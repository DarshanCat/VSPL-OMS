"use client";
import React, { useState, useEffect, useCallback } from "react";
import {
  Wrench,
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
  AlertCircle,
  FileSpreadsheet,
  Check,
  SlidersHorizontal,
  Info,
  Cpu,
  UserCheck,
  FileText,
  Boxes,
  Lock,
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getCurrentUserRole } from "@/lib/api";
import {
  getManufacturingKPIs,
  getManufacturingReadinessList,
  getManufacturingReadinessDetail,
  updateManufacturingReadiness,
  releaseManufacturing,
  revokeManufacturingRelease,
  manufacturingErrorMessage,
  type ManufacturingKPIs,
  type WOManufacturingReadinessItem,
  type WOManufacturingReadinessDetail,
  type ChecklistItemStatus,
} from "@/lib/manufacturingApi";

export default function ManufacturingReadinessPage() {
  const [userRole, setUserRole] = useState<string | null>(null);
  const [kpis, setKpis] = useState<ManufacturingKPIs | null>(null);
  const [items, setItems] = useState<WOManufacturingReadinessItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [orderTypeFilter, setOrderTypeFilter] = useState<string>("");
  const [replacementFilter, setReplacementFilter] = useState<string>("");
  const [searchQuery, setSearchQuery] = useState<string>("");

  // Drawer / Detail state
  const [selectedWoId, setSelectedWoId] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detail, setDetail] = useState<WOManufacturingReadinessDetail | null>(null);
  const [savingChecklist, setSavingChecklist] = useState(false);
  const [releasing, setReleasing] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revocationReason, setRevocationReason] = useState("");
  const [showRevokeModal, setShowRevokeModal] = useState(false);

  useEffect(() => {
    setUserRole(getCurrentUserRole());
  }, []);

  const isAuthorizedRole =
    userRole === "admin" ||
    userRole === "manufacturing" ||
    userRole === "production_manager";

  const isAdmin = userRole === "admin";

  const fetchData = useCallback(async () => {
    try {
      setError(null);
      const isRepl =
        replacementFilter === "replacement"
          ? true
          : replacementFilter === "standard"
          ? false
          : undefined;

      const [kpiRes, itemsRes] = await Promise.all([
        getManufacturingKPIs(),
        getManufacturingReadinessList({
          status: statusFilter || undefined,
          order_type: orderTypeFilter || undefined,
          is_replacement: isRepl,
          search: searchQuery || undefined,
        }),
      ]);
      setKpis(kpiRes);
      setItems(itemsRes);
    } catch (err) {
      setError(manufacturingErrorMessage(err));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [statusFilter, orderTypeFilter, replacementFilter, searchQuery]);

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
      const res = await getManufacturingReadinessDetail(woId);
      setDetail(res);
    } catch (err) {
      setError(manufacturingErrorMessage(err));
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

  const handleSaveChecklist = async () => {
    if (!detail || !selectedWoId) return;
    setSavingChecklist(true);
    setError(null);
    try {
      const updated = await updateManufacturingReadiness(selectedWoId, {
        material_staging_status: detail.material_staging_status,
        material_staging_remark: detail.material_staging_remark,
        machine_capacity_status: detail.machine_capacity_status,
        machine_capacity_remark: detail.machine_capacity_remark,
        machine_id: detail.machine_id,
        machine_code: detail.machine_code,
        tooling_fixtures_status: detail.tooling_fixtures_status,
        tooling_fixtures_remark: detail.tooling_fixtures_remark,
        fixture_id: detail.fixture_id,
        cnc_program_setup_status: detail.cnc_program_setup_status,
        cnc_program_setup_remark: detail.cnc_program_setup_remark,
        nc_program_number: detail.nc_program_number,
        setup_sheet_url: detail.setup_sheet_url,
        gauges_quality_status: detail.gauges_quality_status,
        gauges_quality_remark: detail.gauges_quality_remark,
        gauge_set_id: detail.gauge_set_id,
        operator_manning_status: detail.operator_manning_status,
        operator_manning_remark: detail.operator_manning_remark,
        operator_id: detail.operator_id,
        operator_name: detail.operator_name,
        document_name: detail.document_name,
        document_url: detail.document_url,
        document_revision: detail.document_revision,
        remarks: detail.remarks,
      });
      setDetail(updated);
      setSuccessMessage("Manufacturing readiness saved successfully.");
      setTimeout(() => setSuccessMessage(null), 3000);
      fetchData();
    } catch (err) {
      setError(manufacturingErrorMessage(err));
    } finally {
      setSavingChecklist(false);
    }
  };

  const handleRelease = async () => {
    if (!detail || !selectedWoId) return;
    setReleasing(true);
    setError(null);
    try {
      const res = await releaseManufacturing(selectedWoId, {
        document_name: detail.document_name || `MFG-PLAN-${detail.work_order_number}`,
        document_url: detail.document_url || detail.setup_sheet_url || undefined,
        document_revision: detail.document_revision || "Rev 01",
        remarks: detail.remarks || undefined,
      });
      setSuccessMessage(`Work Order ${res.work_order_number} released for manufacturing!`);
      setTimeout(() => setSuccessMessage(null), 4000);
      const refreshedDetail = await getManufacturingReadinessDetail(selectedWoId);
      setDetail(refreshedDetail);
      fetchData();
    } catch (err) {
      setError(manufacturingErrorMessage(err));
    } finally {
      setReleasing(false);
    }
  };

  const handleRevoke = async () => {
    if (!detail || !selectedWoId) return;
    if (!revocationReason.trim()) {
      setError("Please provide a mandatory revocation reason.");
      return;
    }
    setRevoking(true);
    setError(null);
    try {
      await revokeManufacturingRelease(selectedWoId, {
        revocation_reason: revocationReason.trim(),
      });
      setSuccessMessage(`Manufacturing Release revoked for ${detail.work_order_number}.`);
      setShowRevokeModal(false);
      setRevocationReason("");
      setTimeout(() => setSuccessMessage(null), 4000);
      const refreshedDetail = await getManufacturingReadinessDetail(selectedWoId);
      setDetail(refreshedDetail);
      fetchData();
    } catch (err) {
      setError(manufacturingErrorMessage(err));
    } finally {
      setRevoking(false);
    }
  };

  const renderStatusBadge = (status: ChecklistItemStatus | string) => {
    switch (status) {
      case "READY":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
            <CheckCircle2 className="w-3 h-3 mr-1" /> Ready
          </span>
        );
      case "NOT_READY":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-300">
            <AlertCircle className="w-3 h-3 mr-1" /> Not Ready
          </span>
        );
      case "N_A":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300">
            N/A
          </span>
        );
      case "EXCEPTION":
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-300">
            <AlertTriangle className="w-3 h-3 mr-1" /> Exception
          </span>
        );
      default:
        return (
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">
            {status}
          </span>
        );
    }
  };

  const renderGateStatusBadge = (status: string, isReleased: boolean) => {
    if (isReleased || status === "RELEASED") {
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-200 border border-emerald-300 dark:border-emerald-800">
          <ShieldCheck className="w-3.5 h-3.5 mr-1" /> Released
        </span>
      );
    }
    if (status === "READY") {
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 dark:bg-blue-950/80 dark:text-blue-200 border border-blue-300 dark:border-blue-800">
          <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Ready for Sign-off
        </span>
      );
    }
    if (status === "BLOCKED") {
      return (
        <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-200 border border-rose-300 dark:border-rose-800">
          <ShieldAlert className="w-3.5 h-3.5 mr-1" /> Blocked
        </span>
      );
    }
    return (
      <span className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-200 border border-amber-300 dark:border-amber-800">
        <Clock className="w-3.5 h-3.5 mr-1" /> Pending Review
      </span>
    );
  };

  return (
    <AppShell>
      <div className="p-6 max-w-7xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <div className="p-2 bg-emerald-100 dark:bg-emerald-950/60 rounded-lg text-emerald-600 dark:text-emerald-400">
                <Wrench className="h-6 w-6" />
              </div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
                Manufacturing Readiness & Release
              </h1>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Production verification gate: 6-point checklist sign-off for material, machine, tooling, CNC program, quality gauges, and operator assignment.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              disabled={refreshing || loading}
              className="inline-flex items-center px-3 py-2 border border-slate-300 dark:border-slate-700 shadow-sm text-sm font-medium rounded-lg text-slate-700 dark:text-slate-200 bg-white dark:bg-slate-800 hover:bg-slate-50 dark:hover:bg-slate-700 focus:outline-none transition-colors"
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Notifications */}
        {error && (
          <div className="p-4 rounded-lg bg-rose-50 dark:bg-rose-950/50 border border-rose-200 dark:border-rose-900 flex items-start justify-between">
            <div className="flex items-center gap-2 text-rose-800 dark:text-rose-200 text-sm">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <span>{error}</span>
            </div>
            <button onClick={() => setError(null)} className="text-rose-600 hover:text-rose-800">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {successMessage && (
          <div className="p-4 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-900 flex items-start justify-between">
            <div className="flex items-center gap-2 text-emerald-800 dark:text-emerald-200 text-sm">
              <Check className="h-5 w-5 flex-shrink-0" />
              <span>{successMessage}</span>
            </div>
            <button onClick={() => setSuccessMessage(null)} className="text-emerald-600 hover:text-emerald-800">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Pending Review</span>
              <Clock className="h-4 w-4 text-amber-500" />
            </div>
            <div className="mt-2 text-2xl font-bold text-slate-900 dark:text-slate-100">
              {kpis?.pending_review ?? 0}
            </div>
            <div className="text-xs text-slate-400 mt-1">Awaiting 6-point check</div>
          </div>

          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Ready for Release</span>
              <CheckCircle2 className="h-4 w-4 text-blue-500" />
            </div>
            <div className="mt-2 text-2xl font-bold text-blue-600 dark:text-blue-400">
              {kpis?.ready_for_release ?? 0}
            </div>
            <div className="text-xs text-slate-400 mt-1">Ready for sign-off</div>
          </div>

          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Released</span>
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
            </div>
            <div className="mt-2 text-2xl font-bold text-emerald-600 dark:text-emerald-400">
              {kpis?.released ?? 0}
            </div>
            <div className="text-xs text-slate-400 mt-1">Ready for Planner release</div>
          </div>

          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Blocked</span>
              <ShieldAlert className="h-4 w-4 text-rose-500" />
            </div>
            <div className="mt-2 text-2xl font-bold text-rose-600 dark:text-rose-400">
              {kpis?.blocked ?? 0}
            </div>
            <div className="text-xs text-slate-400 mt-1">Checklist gaps</div>
          </div>

          <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm col-span-2 md:col-span-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wider">Replacement WOs</span>
              <Boxes className="h-4 w-4 text-purple-500" />
            </div>
            <div className="mt-2 text-2xl font-bold text-purple-600 dark:text-purple-400">
              {kpis?.replacement_count ?? 0}
            </div>
            <div className="text-xs text-slate-400 mt-1">Scrap replacements</div>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col md:flex-row gap-3 items-center justify-between">
          <div className="relative flex-1 w-full">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Search by WO#, part number, part name, or customer..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-4 py-2 border border-slate-200 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            />
          </div>

          <div className="flex flex-wrap items-center gap-2 w-full md:w-auto">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">All Gate Statuses</option>
              <option value="READY">Ready for Release</option>
              <option value="PENDING">Pending Review</option>
              <option value="RELEASED">Released</option>
              <option value="BLOCKED">Blocked</option>
            </select>

            <select
              value={orderTypeFilter}
              onChange={(e) => setOrderTypeFilter(e.target.value)}
              className="px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">All Order Types</option>
              <option value="REGULAR">Regular Production</option>
              <option value="NPD">NPD (New Product)</option>
            </select>

            <select
              value={replacementFilter}
              onChange={(e) => setReplacementFilter(e.target.value)}
              className="px-3 py-2 border border-slate-200 dark:border-slate-700 rounded-lg bg-slate-50 dark:bg-slate-800 text-sm text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-500"
            >
              <option value="">All Orders (Standard + Replacements)</option>
              <option value="standard">Standard Orders Only</option>
              <option value="replacement">Replacement Orders Only</option>
            </select>
          </div>
        </div>

        {/* Work Orders Table */}
        <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 dark:bg-slate-800/60 text-slate-600 dark:text-slate-300 font-semibold border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="px-4 py-3">Work Order</th>
                  <th className="px-4 py-3">Part Details</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3 text-center">Engineering Gate</th>
                  <th className="px-4 py-3 text-center">6-Point Checklist</th>
                  <th className="px-4 py-3">Machine & Operator</th>
                  <th className="px-4 py-3 text-center">Gate Status</th>
                  <th className="px-4 py-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-slate-500">
                      <RefreshCw className="h-6 w-6 animate-spin mx-auto mb-2 text-emerald-500" />
                      Loading Manufacturing Readiness work orders...
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-slate-500">
                      No Work Orders found matching the selected filters.
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr
                      key={item.work_order_id}
                      className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition-colors"
                    >
                      {/* WO column */}
                      <td className="px-4 py-3.5 font-medium text-slate-900 dark:text-slate-100">
                        <div className="flex flex-col">
                          <span className="font-mono font-bold text-emerald-600 dark:text-emerald-400">
                            {item.work_order_number}
                          </span>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            <span className="text-xs text-slate-500">Qty: {item.quantity}</span>
                            {item.is_replacement && (
                              <span className="inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-semibold bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300">
                                Replacement
                              </span>
                            )}
                            {item.order_type === "NPD" && (
                              <span className="inline-flex items-center px-1.5 py-0.2 rounded text-[10px] font-semibold bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300">
                                NPD
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Part details */}
                      <td className="px-4 py-3.5">
                        <div className="font-medium text-slate-900 dark:text-slate-100">
                          {item.part_name}
                        </div>
                        {item.target_date && (
                          <div className="text-xs text-slate-400 mt-0.5">
                            Due: {item.target_date}
                          </div>
                        )}
                      </td>

                      {/* Customer */}
                      <td className="px-4 py-3.5 text-slate-600 dark:text-slate-300">
                        {item.customer_name}
                      </td>

                      {/* Engineering Gate status */}
                      <td className="px-4 py-3.5 text-center">
                        {item.engineering_released ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                            <CheckCircle2 className="w-3 h-3 mr-1" />
                            {item.engineering_document_revision || "Released"}
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300">
                            <Clock className="w-3 h-3 mr-1" /> Pending
                          </span>
                        )}
                      </td>

                      {/* 6-point checklist */}
                      <td className="px-4 py-3.5 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-bold ${
                              item.passed_count === 6
                                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                                : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                            }`}
                          >
                            {item.passed_count} / {item.total_count} Verified
                          </span>
                        </div>
                      </td>

                      {/* Machine & Operator */}
                      <td className="px-4 py-3.5 text-slate-600 dark:text-slate-300">
                        <div className="text-xs font-mono">
                          {item.machine_code ? `Mach: ${item.machine_code}` : "Mach: Unassigned"}
                        </div>
                        <div className="text-xs text-slate-400">
                          {item.operator_name ? `Op: ${item.operator_name}` : "Op: Unassigned"}
                        </div>
                      </td>

                      {/* Gate status */}
                      <td className="px-4 py-3.5 text-center">
                        {renderGateStatusBadge(item.readiness_status, item.is_released)}
                      </td>

                      {/* Action */}
                      <td className="px-4 py-3.5 text-right">
                        <button
                          onClick={() => openDetail(item.work_order_id)}
                          className="inline-flex items-center px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-200 transition-colors"
                        >
                          {item.is_released ? "View Sign-off" : "Review & Release"}
                          <ChevronRight className="w-3.5 h-3.5 ml-1" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Slide-over Drawer for Detail & Release */}
        {selectedWoId && (
          <div className="fixed inset-0 z-50 overflow-hidden bg-slate-900/60 backdrop-blur-sm flex justify-end">
            <div className="w-full max-w-3xl bg-white dark:bg-slate-900 h-full shadow-2xl flex flex-col overflow-hidden animate-in slide-in-from-right duration-200">
              {/* Drawer Header */}
              <div className="px-6 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50 dark:bg-slate-800/50">
                <div className="flex items-center gap-3">
                  <div className="p-2 bg-emerald-100 dark:bg-emerald-950/60 rounded-lg text-emerald-600 dark:text-emerald-400">
                    <Wrench className="h-5 w-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-lg font-bold text-slate-900 dark:text-slate-100">
                        {detail?.work_order_number || "Work Order Review"}
                      </h2>
                      {detail && renderGateStatusBadge(detail.readiness_status, detail.is_released)}
                      {detail?.is_replacement && (
                        <span className="px-2 py-0.5 text-xs font-semibold rounded bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300">
                          Replacement WO
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      {detail ? `${detail.part_name} • Customer: ${detail.customer_name} • Qty: ${detail.quantity}` : "Loading..."}
                    </p>
                  </div>
                </div>
                <button
                  onClick={closeDetail}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Drawer Content */}
              <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {detailLoading ? (
                  <div className="py-20 text-center text-slate-500">
                    <RefreshCw className="h-8 w-8 animate-spin mx-auto mb-3 text-emerald-500" />
                    Loading Manufacturing readiness details...
                  </div>
                ) : !detail ? (
                  <div className="py-20 text-center text-slate-500">
                    Failed to load Work Order details.
                  </div>
                ) : (
                  <>
                    {/* Continuous Casting Integration Section */}
                    {detail.continuous_casting_summary && (
                      <div className="p-4 rounded-xl bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="inline-flex items-center text-xs font-bold text-amber-800 dark:text-amber-300 uppercase tracking-wider">
                            <Boxes className="w-4 h-4 mr-1.5" />
                            Continuous Casting Material Available
                          </span>
                          <span
                            className={`px-2 py-0.5 text-xs font-semibold rounded ${
                              detail.continuous_casting_summary.is_cutting_ready
                                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
                                : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"
                            }`}
                          >
                            {detail.continuous_casting_summary.is_cutting_ready ? "Sufficient Blanks Ready" : "Cutting Required"}
                          </span>
                        </div>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs pt-1 text-slate-700 dark:text-slate-300">
                          <div>
                            <span className="text-slate-500">Grade:</span>{" "}
                            <span className="font-semibold">{detail.continuous_casting_summary.required_grade || "N/A"}</span>
                          </div>
                          <div>
                            <span className="text-slate-500">Planned Blanks:</span>{" "}
                            <span className="font-semibold">{detail.continuous_casting_summary.planned_blanks ?? "N/A"}</span>
                          </div>
                          <div>
                            <span className="text-slate-500">Usable Good Blanks:</span>{" "}
                            <span className="font-bold text-emerald-600 dark:text-emerald-400">
                              {detail.continuous_casting_summary.usable_good_blanks}
                            </span>
                          </div>
                          <div>
                            <span className="text-slate-500">Blank Length:</span>{" "}
                            <span className="font-semibold">
                              {detail.continuous_casting_summary.blank_length_mm ? `${detail.continuous_casting_summary.blank_length_mm} mm` : "N/A"}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Upstream Engineering Release Status */}
                    <div
                      className={`p-4 rounded-xl border ${
                        detail.engineering_released
                          ? "bg-slate-50 dark:bg-slate-800/40 border-slate-200 dark:border-slate-800"
                          : "bg-amber-50 dark:bg-amber-950/40 border-amber-300 dark:border-amber-800"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <FileText className="w-4 h-4 text-cyan-500" />
                          <span className="text-xs font-bold uppercase tracking-wider text-slate-700 dark:text-slate-300">
                            Upstream Engineering Gate
                          </span>
                        </div>
                        {detail.engineering_released ? (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                            <CheckCircle2 className="w-3.5 h-3.5 mr-1" /> Released ({detail.engineering_document_revision || "Rev Verified"})
                          </span>
                        ) : (
                          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300">
                            <AlertTriangle className="w-3.5 h-3.5 mr-1" /> Engineering Release Pending
                          </span>
                        )}
                      </div>
                      <div className="mt-2 grid grid-cols-2 md:grid-cols-3 gap-2 text-xs text-slate-600 dark:text-slate-400">
                        <div>
                          <span className="text-slate-400">Released By:</span>{" "}
                          <span className="font-medium text-slate-700 dark:text-slate-300">{detail.engineering_released_by || "Pending"}</span>
                        </div>
                        <div>
                          <span className="text-slate-400">Released At:</span>{" "}
                          <span className="font-medium text-slate-700 dark:text-slate-300">
                            {detail.engineering_released_at ? new Date(detail.engineering_released_at).toLocaleString() : "Pending"}
                          </span>
                        </div>
                        {detail.engineering_document_url && (
                          <div>
                            <a
                              href={detail.engineering_document_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-cyan-600 dark:text-cyan-400 underline inline-flex items-center"
                            >
                              View Engineering Doc <ExternalLink className="w-3 h-3 ml-1" />
                            </a>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* 6-Point Checklist */}
                    <div className="space-y-4">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-bold text-slate-900 dark:text-slate-100 uppercase tracking-wider">
                          6-Point Manufacturing Verification
                        </h3>
                        <span className="text-xs text-slate-400">
                          {detail.is_released ? "Checklist is locked upon release" : "Update status and remarks below"}
                        </span>
                      </div>

                      {/* 1. Material Staging */}
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 space-y-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              1. Material Staging & Availability
                            </div>
                            <div className="text-xs text-slate-500">
                              Casting blanks / bar stock physically staged at machine infeed.
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {(["READY", "NOT_READY", "EXCEPTION"] as ChecklistItemStatus[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                disabled={detail.is_released}
                                onClick={() =>
                                  setDetail({
                                    ...detail,
                                    material_staging_status: st,
                                  })
                                }
                                className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all ${
                                  detail.material_staging_status === st
                                    ? st === "READY"
                                      ? "bg-emerald-600 text-white border-emerald-600"
                                      : st === "EXCEPTION"
                                      ? "bg-purple-600 text-white border-purple-600"
                                      : "bg-rose-600 text-white border-rose-600"
                                    : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>
                        {detail.material_staging_status === "EXCEPTION" && (
                          <input
                            type="text"
                            placeholder="Mandatory deviation remark for material staging exception..."
                            disabled={detail.is_released}
                            value={detail.material_staging_remark || ""}
                            onChange={(e) =>
                              setDetail({
                                ...detail,
                                material_staging_remark: e.target.value,
                              })
                            }
                            className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-purple-300 dark:border-purple-800 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
                          />
                        )}
                      </div>

                      {/* 2. Machine Capacity */}
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 space-y-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              2. Machine Cell & Capacity
                            </div>
                            <div className="text-xs text-slate-500">
                              Target CNC / VMC machine scheduled with active preventive maintenance.
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {(["READY", "NOT_READY", "EXCEPTION"] as ChecklistItemStatus[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                disabled={detail.is_released}
                                onClick={() =>
                                  setDetail({
                                    ...detail,
                                    machine_capacity_status: st,
                                  })
                                }
                                className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all ${
                                  detail.machine_capacity_status === st
                                    ? st === "READY"
                                      ? "bg-emerald-600 text-white border-emerald-600"
                                      : st === "EXCEPTION"
                                      ? "bg-purple-600 text-white border-purple-600"
                                      : "bg-rose-600 text-white border-rose-600"
                                    : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Assigned Machine
                            </label>
                            <select
                              disabled={detail.is_released}
                              value={detail.machine_id || ""}
                              onChange={(e) => {
                                const selected = detail.available_machines.find(
                                  (m) => m.id === e.target.value
                                );
                                setDetail({
                                  ...detail,
                                  machine_id: e.target.value || null,
                                  machine_code: selected ? selected.machine_code : null,
                                });
                              }}
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            >
                              <option value="">-- Select Target Machine --</option>
                              {detail.available_machines.map((m) => (
                                <option key={m.id} value={m.id}>
                                  {m.machine_code} - {m.machine_name} ({m.department || "Shop Floor"})
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Machine Remarks (Mandatory on EXCEPTION)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. Dedicated Mazak lathe allocated"
                              disabled={detail.is_released}
                              value={detail.machine_capacity_remark || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  machine_capacity_remark: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                        </div>
                      </div>

                      {/* 3. Tooling & Fixtures */}
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 space-y-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              3. Tooling, Jigs & Fixtures
                            </div>
                            <div className="text-xs text-slate-500">
                              Inserts, chuck jaws, fixtures verified and available at machine.
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {(["READY", "NOT_READY", "N_A", "EXCEPTION"] as ChecklistItemStatus[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                disabled={detail.is_released}
                                onClick={() =>
                                  setDetail({
                                    ...detail,
                                    tooling_fixtures_status: st,
                                  })
                                }
                                className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all ${
                                  detail.tooling_fixtures_status === st
                                    ? st === "READY"
                                      ? "bg-emerald-600 text-white border-emerald-600"
                                      : st === "N_A"
                                      ? "bg-slate-600 text-white border-slate-600"
                                      : st === "EXCEPTION"
                                      ? "bg-purple-600 text-white border-purple-600"
                                      : "bg-rose-600 text-white border-rose-600"
                                    : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Fixture ID / Jigs Reference
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. FIX-CYL-01"
                              disabled={detail.is_released}
                              value={detail.fixture_id || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  fixture_id: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Tooling Remarks (Mandatory for N/A or EXCEPTION)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. Standard 3-jaw chuck used"
                              disabled={detail.is_released}
                              value={detail.tooling_fixtures_remark || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  tooling_fixtures_remark: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                        </div>
                      </div>

                      {/* 4. CNC Program & Setup Sheet */}
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 space-y-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              4. CNC Program & Setup Sheet
                            </div>
                            <div className="text-xs text-slate-500">
                              NC program loaded on controller, tool offsets & setup sheet verified.
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {(["READY", "NOT_READY", "N_A", "EXCEPTION"] as ChecklistItemStatus[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                disabled={detail.is_released}
                                onClick={() =>
                                  setDetail({
                                    ...detail,
                                    cnc_program_setup_status: st,
                                  })
                                }
                                className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all ${
                                  detail.cnc_program_setup_status === st
                                    ? st === "READY"
                                      ? "bg-emerald-600 text-white border-emerald-600"
                                      : st === "N_A"
                                      ? "bg-slate-600 text-white border-slate-600"
                                      : st === "EXCEPTION"
                                      ? "bg-purple-600 text-white border-purple-600"
                                      : "bg-rose-600 text-white border-rose-600"
                                    : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              NC Program #
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. O1044 / NC-01"
                              disabled={detail.is_released}
                              value={detail.nc_program_number || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  nc_program_number: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Setup Sheet URL / File
                            </label>
                            <input
                              type="text"
                              placeholder="https://.../setup_sheet.pdf"
                              disabled={detail.is_released}
                              value={detail.setup_sheet_url || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  setup_sheet_url: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              CNC Remarks (Mandatory for N/A/EXCEPTION)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. Program proven on first piece"
                              disabled={detail.is_released}
                              value={detail.cnc_program_setup_remark || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  cnc_program_setup_remark: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                        </div>
                      </div>

                      {/* 5. Quality Gauges */}
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 space-y-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              5. Gauges & Quality Inspection
                            </div>
                            <div className="text-xs text-slate-500">
                              Calibrated plug/ring gauges, verniers, micrometers issued to station.
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {(["READY", "NOT_READY", "N_A", "EXCEPTION"] as ChecklistItemStatus[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                disabled={detail.is_released}
                                onClick={() =>
                                  setDetail({
                                    ...detail,
                                    gauges_quality_status: st,
                                  })
                                }
                                className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all ${
                                  detail.gauges_quality_status === st
                                    ? st === "READY"
                                      ? "bg-emerald-600 text-white border-emerald-600"
                                      : st === "N_A"
                                      ? "bg-slate-600 text-white border-slate-600"
                                      : st === "EXCEPTION"
                                      ? "bg-purple-600 text-white border-purple-600"
                                      : "bg-rose-600 text-white border-rose-600"
                                    : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Gauge Set / Calibration Ref
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. GAUGE-SET-44 (Calibrated to 2026-12)"
                              disabled={detail.is_released}
                              value={detail.gauge_set_id || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  gauge_set_id: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Quality Remarks (Mandatory for N/A/EXCEPTION)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. Standard digital micrometer used"
                              disabled={detail.is_released}
                              value={detail.gauges_quality_remark || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  gauges_quality_remark: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                        </div>
                      </div>

                      {/* 6. Operator Manning */}
                      <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/30 space-y-3">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                          <div>
                            <div className="font-semibold text-slate-900 dark:text-slate-100 text-sm">
                              6. Operator Manning & Assignment
                            </div>
                            <div className="text-xs text-slate-500">
                              Qualified machinist / operator assigned for shift execution.
                            </div>
                          </div>
                          <div className="flex items-center gap-1.5">
                            {(["READY", "NOT_READY", "EXCEPTION"] as ChecklistItemStatus[]).map((st) => (
                              <button
                                key={st}
                                type="button"
                                disabled={detail.is_released}
                                onClick={() =>
                                  setDetail({
                                    ...detail,
                                    operator_manning_status: st,
                                  })
                                }
                                className={`px-2.5 py-1 text-xs font-semibold rounded-lg border transition-all ${
                                  detail.operator_manning_status === st
                                    ? st === "READY"
                                      ? "bg-emerald-600 text-white border-emerald-600"
                                      : st === "EXCEPTION"
                                      ? "bg-purple-600 text-white border-purple-600"
                                      : "bg-rose-600 text-white border-rose-600"
                                    : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-700 hover:bg-slate-100"
                                }`}
                              >
                                {st}
                              </button>
                            ))}
                          </div>
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Assigned Operator
                            </label>
                            <select
                              disabled={detail.is_released}
                              value={detail.operator_id || ""}
                              onChange={(e) => {
                                const selected = detail.available_operators.find(
                                  (op) => op.id === e.target.value
                                );
                                setDetail({
                                  ...detail,
                                  operator_id: e.target.value || null,
                                  operator_name: selected ? selected.operator_name : null,
                                });
                              }}
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            >
                              <option value="">-- Select Shift Operator --</option>
                              {detail.available_operators.map((op) => (
                                <option key={op.id} value={op.id}>
                                  {op.operator_name} {op.operator_code ? `(${op.operator_code})` : ""}
                                </option>
                              ))}
                            </select>
                          </div>
                          <div>
                            <label className="block text-[11px] font-medium text-slate-500 mb-1">
                              Operator Remarks (Mandatory on EXCEPTION)
                            </label>
                            <input
                              type="text"
                              placeholder="e.g. Lead machinist verified on setup"
                              disabled={detail.is_released}
                              value={detail.operator_manning_remark || ""}
                              onChange={(e) =>
                                setDetail({
                                  ...detail,
                                  operator_manning_remark: e.target.value,
                                })
                              }
                              className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                            />
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Manufacturing Document & Overall Sign-off Information */}
                    <div className="p-4 rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 space-y-3">
                      <h4 className="text-xs font-bold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
                        Manufacturing Process Document & Remarks
                      </h4>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Document Name
                          </label>
                          <input
                            type="text"
                            disabled={detail.is_released}
                            value={detail.document_name || ""}
                            placeholder={`MFG-PLAN-${detail.work_order_number}`}
                            onChange={(e) =>
                              setDetail({
                                ...detail,
                                document_name: e.target.value,
                              })
                            }
                            className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Document Revision
                          </label>
                          <input
                            type="text"
                            disabled={detail.is_released}
                            value={detail.document_revision || ""}
                            placeholder="Rev 01"
                            onChange={(e) =>
                              setDetail({
                                ...detail,
                                document_revision: e.target.value,
                              })
                            }
                            className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                          />
                        </div>
                        <div>
                          <label className="block text-[11px] font-medium text-slate-500 mb-1">
                            Document URL
                          </label>
                          <input
                            type="text"
                            disabled={detail.is_released}
                            value={detail.document_url || ""}
                            placeholder="https://.../mfg_plan.pdf"
                            onChange={(e) =>
                              setDetail({
                                ...detail,
                                document_url: e.target.value,
                              })
                            }
                            className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                          />
                        </div>
                      </div>
                      <div>
                        <label className="block text-[11px] font-medium text-slate-500 mb-1">
                          Manufacturing Remarks / Sign-off Notes
                        </label>
                        <textarea
                          rows={2}
                          disabled={detail.is_released}
                          value={detail.remarks || ""}
                          placeholder="Add any specific tooling offsets, batch instructions, or setup notes..."
                          onChange={(e) =>
                            setDetail({
                              ...detail,
                              remarks: e.target.value,
                            })
                          }
                          className="w-full text-xs px-3 py-2 border rounded-lg bg-white dark:bg-slate-900 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100"
                        />
                      </div>
                    </div>

                    {/* Blocking reasons banner if any */}
                    {!detail.is_released && detail.blocking_reasons.length > 0 && (
                      <div className="p-4 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900 space-y-1">
                        <div className="flex items-center gap-1.5 text-xs font-bold text-rose-800 dark:text-rose-200">
                          <AlertTriangle className="h-4 w-4" />
                          Release Blocked by Following Conditions:
                        </div>
                        <ul className="list-disc list-inside text-xs text-rose-700 dark:text-rose-300 space-y-0.5 pl-1">
                          {detail.blocking_reasons.map((reason, idx) => (
                            <li key={idx}>{reason}</li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {/* Released Stamp Banner if released */}
                    {detail.is_released && (
                      <div className="p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-300 dark:border-emerald-800 flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <ShieldCheck className="h-6 w-6 text-emerald-600 dark:text-emerald-400" />
                          <div>
                            <div className="text-sm font-bold text-emerald-900 dark:text-emerald-100">
                              Manufacturing Release Authorized
                            </div>
                            <div className="text-xs text-emerald-700 dark:text-emerald-300">
                              Signed off by <span className="font-semibold">{detail.released_by_name || "Authorized Lead"}</span> on{" "}
                              {detail.released_at ? new Date(detail.released_at).toLocaleString() : "Date recorded"}.
                            </div>
                          </div>
                        </div>

                        {isAdmin && (
                          <button
                            onClick={() => setShowRevokeModal(true)}
                            className="px-3 py-1.5 text-xs font-semibold rounded-lg bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300 border border-rose-300 dark:border-rose-800 hover:bg-rose-200 transition-colors"
                          >
                            Revoke Release (Admin)
                          </button>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Drawer Footer Actions */}
              {detail && (
                <div className="p-4 border-t border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/50 flex items-center justify-between">
                  <button
                    onClick={closeDetail}
                    className="px-4 py-2 border border-slate-300 dark:border-slate-700 rounded-lg text-xs font-semibold text-slate-700 dark:text-slate-300 bg-white dark:bg-slate-800 hover:bg-slate-100"
                  >
                    Close
                  </button>

                  <div className="flex items-center gap-2">
                    {!detail.is_released && (
                      <button
                        onClick={handleSaveChecklist}
                        disabled={savingChecklist}
                        className="px-4 py-2 rounded-lg text-xs font-semibold text-slate-700 dark:text-slate-200 bg-slate-200 dark:bg-slate-700 hover:bg-slate-300 dark:hover:bg-slate-600 transition-colors"
                      >
                        {savingChecklist ? "Saving..." : "Save Progress"}
                      </button>
                    )}

                    {!detail.is_released && (
                      <button
                        onClick={handleRelease}
                        disabled={!detail.can_release || releasing || !isAuthorizedRole}
                        title={
                          !isAuthorizedRole
                            ? "Only Manufacturing, Production Manager, or Admin can authorize release"
                            : !detail.can_release
                            ? "Complete all 6 checklist requirements and verify Engineering Release first"
                            : "Authorize Manufacturing Release"
                        }
                        className={`inline-flex items-center px-4 py-2 rounded-lg text-xs font-semibold text-white shadow-sm transition-all ${
                          detail.can_release && isAuthorizedRole
                            ? "bg-emerald-600 hover:bg-emerald-500 cursor-pointer"
                            : "bg-slate-400 dark:bg-slate-700 opacity-60 cursor-not-allowed"
                        }`}
                      >
                        <ShieldCheck className="h-4 w-4 mr-1.5" />
                        {releasing ? "Authorizing..." : "Authorize Manufacturing Release"}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Revocation Modal */}
        {showRevokeModal && detail && (
          <div className="fixed inset-0 z-60 overflow-hidden bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="w-full max-w-md bg-white dark:bg-slate-900 rounded-2xl p-6 border border-slate-200 dark:border-slate-800 shadow-2xl space-y-4">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-rose-100 dark:bg-rose-950 rounded-xl text-rose-600 dark:text-rose-400">
                  <AlertTriangle className="h-6 w-6" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-slate-900 dark:text-slate-100">
                    Revoke Manufacturing Release
                  </h3>
                  <p className="text-xs text-slate-500">
                    Work Order {detail.work_order_number}
                  </p>
                </div>
              </div>

              <p className="text-xs text-slate-600 dark:text-slate-400">
                Revoking this release resets the Manufacturing Gate back to pending. Note: Revocation is automatically blocked by safety invariants if shop-floor production movement or stage entries have already commenced.
              </p>

              <div>
                <label className="block text-xs font-semibold text-slate-700 dark:text-slate-300 mb-1">
                  Mandatory Revocation Reason *
                </label>
                <textarea
                  rows={3}
                  value={revocationReason}
                  onChange={(e) => setRevocationReason(e.target.value)}
                  placeholder="State the engineering/manufacturing reason for revoking sign-off..."
                  className="w-full text-xs p-3 border rounded-xl bg-slate-50 dark:bg-slate-800 border-slate-300 dark:border-slate-700 text-slate-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-rose-500"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowRevokeModal(false)}
                  className="px-4 py-2 text-xs font-medium text-slate-700 dark:text-slate-300 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={handleRevoke}
                  disabled={revoking || !revocationReason.trim()}
                  className="px-4 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 disabled:opacity-50 rounded-lg shadow-sm"
                >
                  {revoking ? "Revoking..." : "Confirm Revocation"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

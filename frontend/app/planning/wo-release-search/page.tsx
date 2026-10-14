"use client";
import React, { useState, useEffect, Suspense, useMemo, useCallback } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Search,
  Calendar,
  CalendarDays,
  Clock,
  Filter,
  Download,
  FileSpreadsheet,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  RotateCcw,
  Layers,
  Factory,
  Route,
  Sparkles,
  ChevronRight,
  ExternalLink,
  Flame,
  Boxes,
  Check,
  Eye,
  ArrowUpDown,
  SlidersHorizontal,
  Table as TableIcon,
  LayoutGrid,
  CalendarRange
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getWorkOrders, WorkOrderListItem } from "@/lib/api";

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

function formatDateTime(dateStr?: string | null): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return dateStr;
  }
}

function getDateGroupKey(wo: WorkOrderListItem, dateType: "wo_date" | "release_date" | "delivery_date"): { key: string; label: string } {
  let rawDate: string | null = null;
  if (dateType === "release_date") {
    rawDate = wo.release_date ? String(wo.release_date) : null;
  } else if (dateType === "delivery_date") {
    rawDate = wo.delivery_date ? String(wo.delivery_date) : null;
  } else {
    rawDate = wo.created_at ? String(wo.created_at) : (wo.wo_date ? String(wo.wo_date) : null);
  }

  if (!rawDate) {
    return { key: "no-date", label: "Date Not Assigned / Pending" };
  }

  try {
    const d = new Date(rawDate);
    if (isNaN(d.getTime())) return { key: rawDate.slice(0, 10), label: rawDate.slice(0, 10) };
    const iso = d.toISOString().slice(0, 10);
    const label = d.toLocaleDateString("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
    return { key: iso, label };
  } catch {
    return { key: "unknown", label: "Other" };
  }
}

function WOReleaseSearchContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState(searchParams.get("q") || "");
  const [dateType, setDateType] = useState<"wo_date" | "release_date" | "delivery_date">(
    (searchParams.get("date_type") as any) || "wo_date"
  );
  const [datePreset, setDatePreset] = useState<string>(searchParams.get("preset") || "all");
  const [fromDate, setFromDate] = useState<string>(searchParams.get("from") || "");
  const [toDate, setToDate] = useState<string>(searchParams.get("to") || "");
  const [releaseStatusFilter, setReleaseStatusFilter] = useState<"all" | "unreleased" | "released" | "in_production">(
    (searchParams.get("status") as any) || "all"
  );
  const [stageFilter, setStageFilter] = useState<string>(searchParams.get("stage") || "all");
  const [castingProcessFilter, setCastingProcessFilter] = useState<string>(searchParams.get("casting") || "all");
  const [sortBy, setSortBy] = useState<string>(searchParams.get("sort") || "wo_date_desc");
  const [viewMode, setViewMode] = useState<"grouped" | "table" | "cards">("grouped");

  // Data state
  const [loading, setLoading] = useState<boolean>(true);
  const [workOrders, setWorkOrders] = useState<WorkOrderListItem[]>([]);
  const [exporting, setExporting] = useState<boolean>(false);
  const [copiedWo, setCopiedWo] = useState<string | null>(null);

  // Apply Quick Date Presets
  const applyDatePreset = (preset: string) => {
    setDatePreset(preset);
    const now = new Date();
    const toIso = (d: Date) => d.toISOString().slice(0, 10);

    if (preset === "today") {
      const todayStr = toIso(now);
      setFromDate(todayStr);
      setToDate(todayStr);
    } else if (preset === "yesterday") {
      const yesterday = new Date(now);
      yesterday.setDate(now.getDate() - 1);
      const yStr = toIso(yesterday);
      setFromDate(yStr);
      setToDate(yStr);
    } else if (preset === "last7") {
      const past = new Date(now);
      past.setDate(now.getDate() - 6);
      setFromDate(toIso(past));
      setToDate(toIso(now));
    } else if (preset === "last30") {
      const past = new Date(now);
      past.setDate(now.getDate() - 29);
      setFromDate(toIso(past));
      setToDate(toIso(now));
    } else if (preset === "this_month") {
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1);
      setFromDate(toIso(firstDay));
      setToDate(toIso(now));
    } else if (preset === "all") {
      setFromDate("");
      setToDate("");
    }
  };

  // Fetch Work Orders
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = {
        limit: 300,
        sort_by: sortBy,
        date_type: dateType,
      };

      if (searchQuery.trim()) {
        params.search = searchQuery.trim();
      }

      if (fromDate) params.from_date = fromDate;
      if (toDate) params.to_date = toDate;

      if (releaseStatusFilter === "unreleased") {
        params.release_filter = "unreleased";
      } else if (releaseStatusFilter === "released") {
        params.release_filter = "released";
      } else if (releaseStatusFilter === "in_production") {
        params.status_filter = "in_production";
      }

      if (stageFilter && stageFilter !== "all") {
        params.stage = stageFilter;
      }

      if (castingProcessFilter && castingProcessFilter !== "all") {
        params.casting_process = castingProcessFilter;
      }

      const res = await getWorkOrders(params);
      setWorkOrders(Array.isArray(res) ? res : []);
    } catch (err) {
      console.error("Failed to load work orders for search:", err);
      setWorkOrders([]);
    } finally {
      setLoading(false);
    }
  }, [searchQuery, dateType, fromDate, toDate, releaseStatusFilter, stageFilter, castingProcessFilter, sortBy]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Statistics KPI calculations
  const stats = useMemo(() => {
    const totalCount = workOrders.length;
    let releasedCount = 0;
    let unreleasedCount = 0;
    let inProductionCount = 0;
    let totalPhysicalQty = 0;

    for (const wo of workOrders) {
      if (wo.is_released || wo.release_date || wo.release_status === "RELEASED") {
        releasedCount++;
      } else {
        unreleasedCount++;
      }
      if (wo.status === "in_production" || wo.status === "IN_PRODUCTION") {
        inProductionCount++;
      }
      totalPhysicalQty += wo.physical_wo_qty || 0;
    }

    return {
      totalCount,
      releasedCount,
      unreleasedCount,
      inProductionCount,
      totalPhysicalQty,
    };
  }, [workOrders]);

  // Grouped by Date
  const groupedData = useMemo(() => {
    const groups: Record<
      string,
      {
        key: string;
        label: string;
        items: WorkOrderListItem[];
        releasedCount: number;
        unreleasedCount: number;
        totalQty: number;
      }
    > = {};

    for (const wo of workOrders) {
      const { key, label } = getDateGroupKey(wo, dateType);
      if (!groups[key]) {
        groups[key] = {
          key,
          label,
          items: [],
          releasedCount: 0,
          unreleasedCount: 0,
          totalQty: 0,
        };
      }
      groups[key].items.push(wo);
      if (wo.is_released || wo.release_date || wo.release_status === "RELEASED") {
        groups[key].releasedCount++;
      } else {
        groups[key].unreleasedCount++;
      }
      groups[key].totalQty += wo.physical_wo_qty || 0;
    }

    // Sort group keys: newest date first unless sortBy has asc
    const keys = Object.keys(groups).sort((a, b) => {
      if (a === "no-date") return 1;
      if (b === "no-date") return -1;
      return sortBy.includes("asc") ? a.localeCompare(b) : b.localeCompare(a);
    });

    return keys.map((k) => groups[k]);
  }, [workOrders, dateType, sortBy]);

  // Copy helper
  const handleCopy = (text: string) => {
    navigator.clipboard?.writeText(text);
    setCopiedWo(text);
    setTimeout(() => setCopiedWo(null), 2000);
  };

  // Export to CSV
  const handleExportCSV = () => {
    setExporting(true);
    try {
      const headers = [
        "WO Number",
        "Release Status",
        "Is Released",
        "Created Date",
        "Release Date",
        "Customer PO",
        "OAR Number",
        "Customer Code",
        "Customer Name",
        "Part Number",
        "Part Name",
        "Grade",
        "Physical WO Qty",
        "Order Qty",
        "Current Stage",
        "Delivery Date",
        "Delivery Risk",
        "Casting Process",
        "Heat Number",
      ];

      const rows = workOrders.map((wo) => [
        `"${wo.wo_number || ""}"`,
        `"${wo.release_status || (wo.is_released ? "RELEASED" : "AWAITING_RELEASE")}"`,
        wo.is_released ? "YES" : "NO",
        `"${formatDate(wo.created_at || (wo as any).wo_date)}"`,
        `"${formatDate(wo.release_date)}"`,
        `"${(wo.customer_po || "").replace(/"/g, '""')}"`,
        `"${wo.oar_number || ""}"`,
        `"${wo.customer_code || ""}"`,
        `"${(wo.customer_name || "").replace(/"/g, '""')}"`,
        `"${wo.part_number || ""}"`,
        `"${(wo.part_name || "").replace(/"/g, '""')}"`,
        `"${wo.grade || ""}"`,
        wo.physical_wo_qty || 0,
        wo.order_qty || 0,
        `"${wo.current_stage || ""}"`,
        `"${formatDate(wo.delivery_date)}"`,
        `"${wo.delivery_risk || ""}"`,
        `"${wo.casting_process || ""}"`,
        `"${wo.heat_number || ""}"`,
      ]);

      const csvContent = [headers.join(","), ...rows.map((r) => r.join(","))].join("\n");
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const timestamp = new Date().toISOString().slice(0, 10);
      link.setAttribute("href", url);
      link.setAttribute("download", `WO_Release_Search_${dateType}_${timestamp}.csv`);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch (e) {
      console.error("Export CSV failed:", e);
    } finally {
      setExporting(false);
    }
  };

  return (
    <AppShell>
      <div className="p-4 sm:p-6 lg:p-8 max-w-7xl mx-auto space-y-6">
        {/* Header Section */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-200 dark:border-zinc-800 pb-5">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-sky-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Planning &amp; Audit
              </span>
              <span className="text-xs text-zinc-400">Date-Wise Work Order Explorer</span>
            </div>
            <h1 className="text-2xl font-black tracking-tight text-zinc-900 dark:text-zinc-50 mt-1 flex items-center gap-2">
              <Search className="h-6 w-6 text-sky-600" />
              WO Release Search &amp; Date Filter
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Dedicated module to search, filter date-wise, and inspect released vs unreleased Work Orders.
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <button
              type="button"
              disabled={exporting || workOrders.length === 0}
              onClick={handleExportCSV}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-xs hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer disabled:opacity-50"
            >
              <Download className="h-4 w-4 text-sky-600" />
              <span>{exporting ? "Exporting..." : "Export Results (.csv)"}</span>
            </button>
            <Link
              href="/planning/wo-release"
              className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 px-3.5 py-2 text-xs font-bold text-white shadow-sm transition-all"
            >
              <Factory className="h-4 w-4" />
              <span>Open WO Release Execution &rarr;</span>
            </Link>
          </div>
        </div>

        {/* Live KPI Metric Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          {/* Total Matching */}
          <div
            onClick={() => setReleaseStatusFilter("all")}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseStatusFilter === "all"
                ? "border-sky-500 bg-sky-50/70 dark:bg-sky-950/50 ring-2 ring-sky-500/30 shadow-sm"
                : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 hover:border-zinc-300"
            }`}
          >
            <div className="flex items-center justify-between text-sky-600 dark:text-sky-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Matching WOs</span>
              <Layers className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-zinc-900 dark:text-zinc-100">
              {stats.totalCount}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500">Total in current filter</div>
          </div>

          {/* Pending Release */}
          <div
            onClick={() => setReleaseStatusFilter("unreleased")}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseStatusFilter === "unreleased"
                ? "border-amber-500 bg-amber-50/70 dark:bg-amber-950/50 ring-2 ring-amber-500/30 shadow-sm"
                : "border-amber-200/70 dark:border-amber-900/40 bg-amber-50/20 dark:bg-amber-950/20 hover:border-amber-300"
            }`}
          >
            <div className="flex items-center justify-between text-amber-600 dark:text-amber-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Awaiting Release</span>
              <Clock className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-amber-700 dark:text-amber-300">
              {stats.unreleasedCount}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500">Not yet released to floor</div>
          </div>

          {/* Already Released */}
          <div
            onClick={() => setReleaseStatusFilter("released")}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseStatusFilter === "released"
                ? "border-emerald-500 bg-emerald-50/70 dark:bg-emerald-950/50 ring-2 ring-emerald-500/30 shadow-sm"
                : "border-emerald-200/70 dark:border-emerald-900/40 bg-emerald-50/20 dark:bg-emerald-950/20 hover:border-emerald-300"
            }`}
          >
            <div className="flex items-center justify-between text-emerald-600 dark:text-emerald-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Already Released</span>
              <CheckCircle2 className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-emerald-700 dark:text-emerald-300">
              {stats.releasedCount}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500">Released &amp; Active</div>
          </div>

          {/* In Production */}
          <div
            onClick={() => setReleaseStatusFilter("in_production")}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseStatusFilter === "in_production"
                ? "border-blue-500 bg-blue-50/70 dark:bg-blue-950/50 ring-2 ring-blue-500/30 shadow-sm"
                : "border-blue-200/70 dark:border-blue-900/40 bg-blue-50/20 dark:bg-blue-950/20 hover:border-blue-300"
            }`}
          >
            <div className="flex items-center justify-between text-blue-600 dark:text-blue-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">In Production</span>
              <Factory className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-blue-700 dark:text-blue-300">
              {stats.inProductionCount}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500">Moving through stages</div>
          </div>

          {/* Total Physical Quantity */}
          <div className="p-4 rounded-2xl border border-purple-200/70 dark:border-purple-900/40 bg-purple-50/20 dark:bg-purple-950/20">
            <div className="flex items-center justify-between text-purple-600 dark:text-purple-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Total Quantity</span>
              <Boxes className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-purple-700 dark:text-purple-300">
              {stats.totalPhysicalQty.toLocaleString()}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500">Physical WO Pcs</div>
          </div>
        </div>

        {/* Date Filter & Search Control Panel */}
        <div className="bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 p-4 sm:p-5 shadow-xs space-y-4">
          {/* Top Bar: Search input & Date Type selector */}
          <div className="grid grid-cols-1 md:grid-cols-12 gap-3 items-center">
            {/* Main Search Input */}
            <div className="md:col-span-6 relative">
              <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-400" />
              <input
                type="text"
                placeholder="Search WO ID, OAR Number, Customer PO, Part, Heat Number..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-sm focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 transition-all"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-bold text-zinc-400 hover:text-zinc-600"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Date Type Selector */}
            <div className="md:col-span-3">
              <label className="block text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-1">
                Filter By Date Field
              </label>
              <select
                value={dateType}
                onChange={(e) => setDateType(e.target.value as any)}
                className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-xs font-semibold text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
              >
                <option value="wo_date">WO Date (Issued / Created)</option>
                <option value="release_date">Release Date (Floor Release)</option>
                <option value="delivery_date">Target Delivery Date</option>
              </select>
            </div>

            {/* Sort Selector */}
            <div className="md:col-span-3">
              <label className="block text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-1">
                Sort Order
              </label>
              <select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-xs font-semibold text-zinc-800 dark:text-zinc-200 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
              >
                <option value="wo_date_desc">Date: Newest First</option>
                <option value="wo_date_asc">Date: Oldest First</option>
                <option value="release_date_desc">Release Date: Newest First</option>
                <option value="wo_number_desc">WO Number (Desc)</option>
                <option value="delivery_date_asc">Delivery: Earliest First</option>
              </select>
            </div>
          </div>

          {/* Date Range & Presets Row */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-zinc-100 dark:border-zinc-800/80">
            {/* Quick Presets */}
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] font-bold text-zinc-400 mr-1 flex items-center gap-1">
                <CalendarRange className="h-3.5 w-3.5" /> Date Presets:
              </span>
              {[
                { id: "all", label: "All Dates" },
                { id: "today", label: "Today" },
                { id: "yesterday", label: "Yesterday" },
                { id: "last7", label: "Last 7 Days" },
                { id: "last30", label: "Last 30 Days" },
                { id: "this_month", label: "This Month" },
              ].map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => applyDatePreset(p.id)}
                  className={`px-2.5 py-1 text-xs rounded-lg font-semibold transition-all cursor-pointer ${
                    datePreset === p.id
                      ? "bg-sky-600 text-white shadow-xs"
                      : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>

            {/* Custom From / To Inputs */}
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg px-2 py-1">
                <span className="text-[10px] font-bold text-zinc-400 uppercase">From:</span>
                <input
                  type="date"
                  value={fromDate}
                  onChange={(e) => {
                    setFromDate(e.target.value);
                    setDatePreset("custom");
                  }}
                  className="bg-transparent text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none"
                />
              </div>
              <span className="text-zinc-300 dark:text-zinc-600">—</span>
              <div className="flex items-center gap-1 bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg px-2 py-1">
                <span className="text-[10px] font-bold text-zinc-400 uppercase">To:</span>
                <input
                  type="date"
                  value={toDate}
                  onChange={(e) => {
                    setToDate(e.target.value);
                    setDatePreset("custom");
                  }}
                  className="bg-transparent text-xs text-zinc-800 dark:text-zinc-200 focus:outline-none"
                />
              </div>
              {(fromDate || toDate) && (
                <button
                  type="button"
                  onClick={() => {
                    setFromDate("");
                    setToDate("");
                    setDatePreset("all");
                  }}
                  className="text-xs text-rose-500 hover:text-rose-700 font-bold px-1.5 py-1"
                  title="Clear custom dates"
                >
                  Reset
                </button>
              )}
            </div>
          </div>

          {/* Sub-Filters: Release Status, Stages, Casting Process, View Mode */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-zinc-100 dark:border-zinc-800/80">
            {/* Status Tabs */}
            <div className="flex items-center gap-1 p-1 bg-zinc-100 dark:bg-zinc-800/70 rounded-xl">
              <button
                type="button"
                onClick={() => setReleaseStatusFilter("all")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  releaseStatusFilter === "all"
                    ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs"
                    : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                }`}
              >
                All ({stats.totalCount})
              </button>
              <button
                type="button"
                onClick={() => setReleaseStatusFilter("unreleased")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  releaseStatusFilter === "unreleased"
                    ? "bg-amber-500 text-white shadow-xs"
                    : "text-amber-600 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/30"
                }`}
              >
                Pending Release ({stats.unreleasedCount})
              </button>
              <button
                type="button"
                onClick={() => setReleaseStatusFilter("released")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  releaseStatusFilter === "released"
                    ? "bg-emerald-600 text-white shadow-xs"
                    : "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/30"
                }`}
              >
                Already Released ({stats.releasedCount})
              </button>
              <button
                type="button"
                onClick={() => setReleaseStatusFilter("in_production")}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  releaseStatusFilter === "in_production"
                    ? "bg-blue-600 text-white shadow-xs"
                    : "text-blue-600 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950/30"
                }`}
              >
                In Production ({stats.inProductionCount})
              </button>
            </div>

            {/* Stage Filter & View Mode toggle */}
            <div className="flex items-center gap-2">
              <select
                value={stageFilter}
                onChange={(e) => setStageFilter(e.target.value)}
                className="px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-xs font-semibold text-zinc-700 dark:text-zinc-300"
              >
                <option value="all">All Production Stages</option>
                <option value="F1">F1 (Melt / Cast)</option>
                <option value="F2">F2 (Rough Machining)</option>
                <option value="F3">F3 (Heat Treatment)</option>
                <option value="SP">SP (Special Processing)</option>
                <option value="FI">FI (Final Inspection)</option>
                <option value="PACKING">PACKING / BSR</option>
                <option value="DISPATCH">DISPATCH</option>
              </select>

              <select
                value={castingProcessFilter}
                onChange={(e) => setCastingProcessFilter(e.target.value)}
                className="px-2.5 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-xs font-semibold text-zinc-700 dark:text-zinc-300"
              >
                <option value="all">All Casting Processes</option>
                <option value="CENTRIFUGAL">Centrifugal Casting</option>
                <option value="CONTINUOUS">Continuous Casting</option>
                <option value="SAND">Sand Casting</option>
              </select>

              {/* View Mode */}
              <div className="flex items-center border border-zinc-200 dark:border-zinc-700 rounded-lg p-0.5 bg-zinc-50 dark:bg-zinc-800">
                <button
                  type="button"
                  onClick={() => setViewMode("grouped")}
                  className={`p-1.5 rounded-md ${
                    viewMode === "grouped" ? "bg-white dark:bg-zinc-700 text-sky-600 shadow-xs" : "text-zinc-400"
                  }`}
                  title="Grouped by Date"
                >
                  <Calendar className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("table")}
                  className={`p-1.5 rounded-md ${
                    viewMode === "table" ? "bg-white dark:bg-zinc-700 text-sky-600 shadow-xs" : "text-zinc-400"
                  }`}
                  title="Data Table"
                >
                  <TableIcon className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("cards")}
                  className={`p-1.5 rounded-md ${
                    viewMode === "cards" ? "bg-white dark:bg-zinc-700 text-sky-600 shadow-xs" : "text-zinc-400"
                  }`}
                  title="Card Grid"
                >
                  <LayoutGrid className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Content Area */}
        {loading ? (
          <div className="py-20 text-center bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-3 border-sky-600 border-t-transparent"></div>
            <p className="mt-3 text-xs font-semibold text-zinc-500">Searching Work Orders date-wise...</p>
          </div>
        ) : workOrders.length === 0 ? (
          <div className="py-20 text-center bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 space-y-3">
            <div className="mx-auto w-12 h-12 rounded-full bg-zinc-100 dark:bg-zinc-800 flex items-center justify-center text-zinc-400">
              <Search className="h-6 w-6" />
            </div>
            <h3 className="text-sm font-bold text-zinc-800 dark:text-zinc-200">No Work Orders Found</h3>
            <p className="text-xs text-zinc-500 max-w-sm mx-auto">
              No Work Orders match the selected date range ({fromDate || "any"} to {toDate || "any"}) and filters.
            </p>
            <button
              type="button"
              onClick={() => {
                setSearchQuery("");
                applyDatePreset("all");
                setReleaseStatusFilter("all");
                setStageFilter("all");
                setCastingProcessFilter("all");
              }}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              <span>Reset All Filters</span>
            </button>
          </div>
        ) : viewMode === "grouped" ? (
          /* ============================================================== */
          /* GROUPED BY DATE VIEW                                           */
          /* ============================================================== */
          <div className="space-y-6">
            {groupedData.map((group) => (
              <div
                key={group.key}
                className="bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 overflow-hidden shadow-xs"
              >
                {/* Date Header Banner */}
                <div className="bg-zinc-50 dark:bg-zinc-800/60 px-5 py-3.5 border-b border-zinc-200 dark:border-zinc-800 flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2.5">
                    <span className="flex items-center justify-center h-8 w-8 rounded-xl bg-sky-100 dark:bg-sky-950/70 text-sky-700 dark:text-sky-300">
                      <Calendar className="h-4 w-4" />
                    </span>
                    <div>
                      <div className="text-sm font-black text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                        {group.label}
                        <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-zinc-200 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-300">
                          {group.items.length} {group.items.length === 1 ? "WO" : "WOs"}
                        </span>
                      </div>
                      <div className="text-[10px] text-zinc-400 font-medium">
                        Reference: {dateType === "release_date" ? "Floor Release Date" : dateType === "delivery_date" ? "Target Delivery Date" : "WO Issue Date"}
                      </div>
                    </div>
                  </div>

                  {/* Summary badges for this date */}
                  <div className="flex items-center gap-2 text-xs">
                    {group.unreleasedCount > 0 && (
                      <span className="px-2 py-1 rounded-lg bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800 text-[11px] font-bold text-amber-700 dark:text-amber-300">
                        {group.unreleasedCount} Pending Release
                      </span>
                    )}
                    {group.releasedCount > 0 && (
                      <span className="px-2 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 border border-emerald-200 dark:border-emerald-800 text-[11px] font-bold text-emerald-700 dark:text-emerald-300">
                        {group.releasedCount} Released
                      </span>
                    )}
                    <span className="px-2 py-1 rounded-lg bg-purple-50 dark:bg-purple-950/50 border border-purple-200 dark:border-purple-800 text-[11px] font-bold text-purple-700 dark:text-purple-300">
                      {group.totalQty.toLocaleString()} Pcs
                    </span>
                  </div>
                </div>

                {/* List of Work Orders under this date */}
                <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {group.items.map((wo) => {
                    const isReleased = Boolean(wo.is_released || wo.release_date || wo.release_status === "RELEASED");
                    return (
                      <div
                        key={wo.id}
                        className="p-4 sm:p-5 hover:bg-zinc-50/60 dark:hover:bg-zinc-800/40 transition-colors flex flex-col lg:flex-row lg:items-center justify-between gap-4"
                      >
                        {/* Column 1: WO & Release Status */}
                        <div className="space-y-1.5 min-w-[240px]">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono font-black text-base text-zinc-900 dark:text-zinc-100 tracking-tight">
                              {wo.wo_number}
                            </span>
                            <button
                              type="button"
                              onClick={() => handleCopy(wo.wo_number)}
                              className="text-[10px] text-zinc-400 hover:text-zinc-600 font-mono px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800"
                              title="Copy WO Number"
                            >
                              {copiedWo === wo.wo_number ? "Copied!" : "Copy"}
                            </button>

                            {isReleased ? (
                              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 dark:bg-emerald-950/60 border border-emerald-300 dark:border-emerald-800 px-2.5 py-0.5 text-[10px] font-black uppercase text-emerald-700 dark:text-emerald-300">
                                <CheckCircle2 className="h-3 w-3" /> Released
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 dark:bg-amber-950/60 border border-amber-300 dark:border-amber-800 px-2.5 py-0.5 text-[10px] font-black uppercase text-amber-700 dark:text-amber-300">
                                <Clock className="h-3 w-3" /> Awaiting Release
                              </span>
                            )}

                            {wo.heat_number && (
                              <span className="inline-flex items-center gap-0.5 text-[10px] font-mono font-bold text-amber-800 dark:text-amber-300 bg-amber-100/70 dark:bg-amber-950/50 px-2 py-0.5 rounded">
                                <Flame className="h-2.5 w-2.5 text-amber-600" /> Heat #{wo.heat_number}
                              </span>
                            )}
                          </div>

                          <div className="flex items-center gap-2 text-xs text-zinc-500 flex-wrap">
                            <span>PO: <strong className="text-zinc-700 dark:text-zinc-300">{wo.customer_po || "—"}</strong></span>
                            <span>•</span>
                            <span>OAR: <strong className="text-zinc-700 dark:text-zinc-300">{wo.oar_number || "—"}</strong></span>
                            <span>•</span>
                            <span>Customer: <strong className="text-zinc-700 dark:text-zinc-300">{wo.customer_code}</strong></span>
                          </div>
                        </div>

                        {/* Column 2: Part & Quantity */}
                        <div className="space-y-1 min-w-[200px]">
                          <div className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
                            {wo.part_number}
                            {wo.part_name && <span className="font-normal text-zinc-500"> ({wo.part_name})</span>}
                          </div>
                          <div className="flex items-center gap-3 text-xs text-zinc-500">
                            <span>
                              Qty: <strong className="font-mono text-zinc-800 dark:text-zinc-200">{wo.physical_wo_qty}</strong> pcs
                            </span>
                            {wo.grade && (
                              <span className="text-[11px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 font-mono">
                                {wo.grade}
                              </span>
                            )}
                            {wo.casting_process && (
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 font-semibold">
                                {wo.casting_process}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Column 3: Current Stage & Target Dates */}
                        <div className="space-y-1 min-w-[180px]">
                          <div className="flex items-center gap-1.5 text-xs">
                            <span className="text-zinc-400">Stage:</span>
                            <span className="font-bold text-zinc-800 dark:text-zinc-200 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded">
                              {wo.current_stage || "F1"}
                            </span>
                          </div>
                          <div className="text-[11px] text-zinc-400 flex items-center gap-2">
                            <span>Delivery: <strong className="text-zinc-600 dark:text-zinc-300">{formatDate(wo.delivery_date)}</strong></span>
                          </div>
                        </div>

                        {/* Column 4: Quick Actions */}
                        <div className="flex items-center gap-2 justify-end">
                          <Link
                            href={`/production/tracking?wo=${encodeURIComponent(wo.wo_number)}`}
                            className="inline-flex items-center gap-1 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-700 transition-colors"
                            title="View Routing History & Progress"
                          >
                            <Route className="h-3.5 w-3.5 text-purple-500" />
                            <span>Timeline</span>
                          </Link>

                          <Link
                            href={`/planning/wo-release?wo_id=${encodeURIComponent(wo.id)}`}
                            className={`inline-flex items-center gap-1 rounded-xl px-3 py-2 text-xs font-bold shadow-xs transition-all ${
                              !isReleased
                                ? "bg-amber-600 hover:bg-amber-700 text-white"
                                : "bg-blue-600 hover:bg-blue-700 text-white"
                            }`}
                          >
                            {!isReleased ? (
                              <>
                                <span>Release WO &rarr;</span>
                              </>
                            ) : (
                              <>
                                <Eye className="h-3.5 w-3.5" />
                                <span>View Release</span>
                              </>
                            )}
                          </Link>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        ) : viewMode === "table" ? (
          /* ============================================================== */
          /* FLAT TABLE VIEW                                                */
          /* ============================================================== */
          <div className="bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 overflow-x-auto shadow-xs">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-800/70 border-b border-zinc-200 dark:border-zinc-800 text-[10px] uppercase font-bold text-zinc-400 tracking-wider">
                <tr>
                  <th className="py-3 px-4">WO Number</th>
                  <th className="py-3 px-3">Release Status</th>
                  <th className="py-3 px-3">WO Date</th>
                  <th className="py-3 px-3">Release Date</th>
                  <th className="py-3 px-3">Customer / PO</th>
                  <th className="py-3 px-3">Part Details</th>
                  <th className="py-3 px-3">Qty</th>
                  <th className="py-3 px-3">Stage</th>
                  <th className="py-3 px-3">Delivery</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800 text-zinc-700 dark:text-zinc-300">
                {workOrders.map((wo) => {
                  const isReleased = Boolean(wo.is_released || wo.release_date || wo.release_status === "RELEASED");
                  return (
                    <tr key={wo.id} className="hover:bg-zinc-50/70 dark:hover:bg-zinc-800/40">
                      <td className="py-3 px-4 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {wo.wo_number}
                        {wo.heat_number && (
                          <div className="text-[10px] font-mono text-amber-600">Heat: {wo.heat_number}</div>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        {isReleased ? (
                          <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 text-[10px] font-black border border-emerald-300 dark:border-emerald-800">
                            RELEASED
                          </span>
                        ) : (
                          <span className="px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 text-[10px] font-black border border-amber-300 dark:border-amber-800">
                            PENDING
                          </span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-zinc-500 whitespace-nowrap">
                        {formatDate(wo.created_at || (wo as any).wo_date)}
                      </td>
                      <td className="py-3 px-3 text-zinc-500 whitespace-nowrap">
                        {formatDate(wo.release_date)}
                      </td>
                      <td className="py-3 px-3">
                        <div className="font-semibold text-zinc-800 dark:text-zinc-200">{wo.customer_code}</div>
                        <div className="text-[10px] text-zinc-400">PO: {wo.customer_po || "—"}</div>
                      </td>
                      <td className="py-3 px-3">
                        <div className="font-bold">{wo.part_number}</div>
                        <div className="text-[10px] text-zinc-400">{wo.part_name || wo.grade || "—"}</div>
                      </td>
                      <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {wo.physical_wo_qty}
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 font-bold text-zinc-800 dark:text-zinc-200">
                          {wo.current_stage || "F1"}
                        </span>
                      </td>
                      <td className="py-3 px-3 whitespace-nowrap text-zinc-500">
                        {formatDate(wo.delivery_date)}
                      </td>
                      <td className="py-3 px-4 text-right whitespace-nowrap">
                        <Link
                          href={`/planning/wo-release?wo_id=${encodeURIComponent(wo.id)}`}
                          className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-bold ${
                            !isReleased ? "bg-amber-600 text-white hover:bg-amber-700" : "bg-blue-600 text-white hover:bg-blue-700"
                          }`}
                        >
                          {!isReleased ? "Release →" : "View"}
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          /* ============================================================== */
          /* CARD GRID VIEW                                                 */
          /* ============================================================== */
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {workOrders.map((wo) => {
              const isReleased = Boolean(wo.is_released || wo.release_date || wo.release_status === "RELEASED");
              return (
                <div
                  key={wo.id}
                  className="bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-800 p-5 shadow-xs hover:border-zinc-300 dark:hover:border-zinc-700 transition-all flex flex-col justify-between space-y-3"
                >
                  <div className="space-y-2">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="font-mono font-black text-lg text-zinc-900 dark:text-zinc-100">
                          {wo.wo_number}
                        </div>
                        <div className="text-xs text-zinc-400">
                          Date: <strong className="text-zinc-600 dark:text-zinc-300">{formatDate(wo.created_at || (wo as any).wo_date)}</strong>
                        </div>
                      </div>
                      {isReleased ? (
                        <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 text-[10px] font-black border border-emerald-300 dark:border-emerald-800">
                          RELEASED
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded-full bg-amber-50 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 text-[10px] font-black border border-amber-300 dark:border-amber-800">
                          PENDING RELEASE
                        </span>
                      )}
                    </div>

                    <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800 space-y-1 text-xs">
                      <div>Part: <strong className="text-zinc-800 dark:text-zinc-200">{wo.part_number}</strong></div>
                      <div>Customer: <strong className="text-zinc-800 dark:text-zinc-200">{wo.customer_code}</strong> (PO: {wo.customer_po || "—"})</div>
                      <div className="flex items-center justify-between text-zinc-500 pt-1">
                        <span>Physical Qty: <strong className="font-mono text-zinc-800 dark:text-zinc-200">{wo.physical_wo_qty}</strong></span>
                        <span>Stage: <strong className="font-mono text-zinc-800 dark:text-zinc-200">{wo.current_stage || "F1"}</strong></span>
                      </div>
                      {wo.release_date && (
                        <div className="text-[10px] text-emerald-600 dark:text-emerald-400">
                          Released On: {formatDateTime(wo.release_date)}
                        </div>
                      )}
                    </div>
                  </div>

                  <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 flex items-center gap-2 justify-end">
                    <Link
                      href={`/production/tracking?wo=${encodeURIComponent(wo.wo_number)}`}
                      className="px-3 py-1.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100"
                    >
                      Track
                    </Link>
                    <Link
                      href={`/planning/wo-release?wo_id=${encodeURIComponent(wo.id)}`}
                      className={`px-3 py-1.5 rounded-xl text-xs font-bold shadow-xs ${
                        !isReleased ? "bg-amber-600 text-white hover:bg-amber-700" : "bg-blue-600 text-white hover:bg-blue-700"
                      }`}
                    >
                      {!isReleased ? "Release WO →" : "View Details"}
                    </Link>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </AppShell>
  );
}

export default function WOReleaseSearchPage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="py-24 text-center">
            <div className="inline-block animate-spin rounded-full h-8 w-8 border-3 border-sky-600 border-t-transparent"></div>
            <p className="mt-3 text-xs text-zinc-500 font-semibold">Loading WO Release Search Module...</p>
          </div>
        </AppShell>
      }
    >
      <WOReleaseSearchContent />
    </Suspense>
  );
}

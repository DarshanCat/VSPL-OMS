"use client";
import React, { useState, useEffect, Suspense, useCallback, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Factory,
  Search,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Route,
  Check,
  ClipboardCheck,
  Wrench,
  X,
  RefreshCw,
  Layers,
  Boxes,
  FileText,
  ChevronDown,
  ChevronRight,
  Calendar,
  CalendarDays,
  Clock,
  Download,
  FileSpreadsheet,
  Flame,
  Filter,
  BarChart3
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";

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
import {
  getWorkOrders,
  releaseWorkOrder,
  engineeringReleaseWorkOrder,
  manufacturingReleaseWorkOrder,
  getPlanningSummary,
  WorkOrderListItem,
  PlanningSummary
} from "@/lib/api";

const ALL_POSSIBLE_STAGES = [
  { code: "F1", name: "F1 (Centrifugal Casting / Melt)", required: true },
  { code: "F2", name: "F2 (Rough Machining / Proof Turn)", required: false },
  { code: "F3", name: "F3 (Finish Machining / Boring)", required: false },
  { code: "SP", name: "SP (Subcontract Heat Treatment / NDT)", required: false },
  { code: "FI", name: "FI (Final Inspection / CMM)", required: true },
  { code: "PACKING", name: "PACKING (Packaging & BSR)", required: true },
  { code: "DISPATCH", name: "DISPATCH (Final Delivery)", required: true },
];

export default function WOReleasePage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="max-w-3xl mx-auto py-12 text-center text-xs text-zinc-500 font-mono">
            Loading Work Order Release...
          </div>
        </AppShell>
      }
    >
      <WOReleasePageInner />
    </Suspense>
  );
}

function WOReleasePageInner() {
  const searchParams = useSearchParams();
  const urlWo = searchParams.get("wo") || "";

  const [wos, setWos] = useState<WorkOrderListItem[]>([]);
  const [selectedWO, setSelectedWO] = useState<string>(urlWo);
  const [selectedWODetail, setSelectedWODetail] = useState<WorkOrderListItem | null>(null);

  // Search and combobox state
  const [searchQuery, setSearchQuery] = useState<string>(urlWo);
  const [searching, setSearching] = useState<boolean>(false);
  const [isDropdownOpen, setIsDropdownOpen] = useState<boolean>(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const searchTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // Planning & Release status filters & sort
  const [releaseFilter, setReleaseFilter] = useState<"all" | "unreleased" | "ready_for_production" | "released">("all");
  const [sortBy, setSortBy] = useState<string>("wo_date_desc");

  // Date-wise filtering state
  const [dateType, setDateType] = useState<"wo_date" | "release_date" | "delivery_date">("wo_date");
  const [datePreset, setDatePreset] = useState<"all" | "today" | "yesterday" | "last_7_days" | "last_30_days" | "custom">("all");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");
  const [isDateQueueOpen, setIsDateQueueOpen] = useState<boolean>(true);
  const [dateQueueTab, setDateQueueTab] = useState<"all" | "unreleased" | "released">("all");

  // Planner KPI Summary & Heat Number tracking
  const [planningSummary, setPlanningSummary] = useState<PlanningSummary | null>(null);
  const [heatNumber, setHeatNumber] = useState<string>("");
  const [exportingExcel, setExportingExcel] = useState<boolean>(false);

  const [physicalQty, setPhysicalQty] = useState<number | "">("");
  const [castingProcess, setCastingProcess] = useState<"CENTRIFUGAL" | "CONTINUOUS" | "">("CENTRIFUGAL");
  const [selectedStages, setSelectedStages] = useState<string[]>([
    "F1",
    "F2",
    "F3",
    "SP",
    "FI",
    "PACKING",
    "DISPATCH",
  ]);
  const [remarks, setRemarks] = useState("Standard full production route approved by planning.");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successResult, setSuccessResult] = useState<any>(null);

  // Release chain: Engineering Release -> Manufacturing Release -> WO Release
  const [chainBusy, setChainBusy] = useState<"engineering" | "manufacturing" | null>(null);
  const [chainError, setChainError] = useState("");
  const [chainResult, setChainResult] = useState<{ engineering?: any; manufacturing?: any }>({});

  // Release Evidence inputs
  const [docName, setDocName] = useState("");
  const [docUrl, setDocUrl] = useState("");
  const [docRevision, setDocRevision] = useState("");
  const [releaseRemarks, setReleaseRemarks] = useState("");

  const applyWO = useCallback((found: WorkOrderListItem) => {
    setSelectedWO(found.wo_number);
    setSelectedWODetail(found);
    setSearchQuery(found.wo_number);
    setPhysicalQty(found.physical_wo_qty);
    setHeatNumber(found.heat_number || "");
    setChainResult({});
    setChainError("");
    setError("");

    if (found.casting_process === "CONTINUOUS") {
      setCastingProcess("CONTINUOUS");
      setSelectedStages((prev) => prev.filter((s) => s !== "F1"));
    } else {
      setCastingProcess("CENTRIFUGAL");
      setSelectedStages((prev) => (prev.includes("F1") ? prev : ["F1", ...prev.filter((s) => s !== "F1")]));
    }
  }, []);

  const handleSearch = useCallback(
    async (
      term?: string,
      filter?: string,
      sort?: string,
      fDate?: string,
      tDate?: string,
      dType?: string
    ) => {
      setSearching(true);
      setError("");
      try {
        const queryTerm = (term !== undefined ? term : searchQuery).trim();
        const activeFilter = filter !== undefined ? filter : releaseFilter;
        const activeSort = sort !== undefined ? sort : sortBy;
        const activeFromDate = fDate !== undefined ? fDate : fromDate;
        const activeToDate = tDate !== undefined ? tDate : toDate;
        const activeDateType = dType !== undefined ? dType : dateType;

        const data = await getWorkOrders({
          search: queryTerm || undefined,
          release_filter: activeFilter !== "all" ? activeFilter : undefined,
          sort_by: activeSort,
          exclude_dispatched: true,
          from_date: activeFromDate || undefined,
          to_date: activeToDate || undefined,
          date_type: activeDateType,
          limit: 150,
        });
        const list = Array.isArray(data) ? data : [];
        setWos(list);

        if (queryTerm) {
          // Check for exact WO match
          const exact = list.find((w) => w.wo_number.toUpperCase() === queryTerm.toUpperCase());
          if (exact) {
            applyWO(exact);
          } else if (list.length > 0 && !list.some((w) => w.wo_number === selectedWO)) {
            applyWO(list[0]);
          }
        }
      } catch (err: any) {
        setError("Failed to search Work Orders.");
      } finally {
        setSearching(false);
      }
    },
    [applyWO, releaseFilter, searchQuery, selectedWO, sortBy, fromDate, toDate, dateType]
  );

  const applyDatePreset = (preset: "all" | "today" | "yesterday" | "last_7_days" | "last_30_days" | "custom") => {
    setDatePreset(preset);
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    let f = "";
    let t = "";

    if (preset === "today") {
      f = fmt(now);
      t = fmt(now);
    } else if (preset === "yesterday") {
      const y = new Date(now);
      y.setDate(y.getDate() - 1);
      f = fmt(y);
      t = fmt(y);
    } else if (preset === "last_7_days") {
      const p = new Date(now);
      p.setDate(p.getDate() - 6);
      f = fmt(p);
      t = fmt(now);
    } else if (preset === "last_30_days") {
      const p = new Date(now);
      p.setDate(p.getDate() - 29);
      f = fmt(p);
      t = fmt(now);
    } else if (preset === "custom") {
      return;
    }
    setFromDate(f);
    setToDate(t);
    handleSearch(searchQuery, releaseFilter, sortBy, f, t, dateType);
  };

  // Group current WOs by relevant date for structured date-wise browsing
  const groupedWOsByDate = React.useMemo(() => {
    const groups: {
      [key: string]: {
        dateStr: string;
        label: string;
        items: WorkOrderListItem[];
        unreleasedItems: WorkOrderListItem[];
        releasedItems: WorkOrderListItem[];
      };
    } = {};
    const now = new Date();
    const pad = (n: number) => String(n).padStart(2, "0");
    const nowStr = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
    const yestDate = new Date(now);
    yestDate.setDate(yestDate.getDate() - 1);
    const yestStr = `${yestDate.getFullYear()}-${pad(yestDate.getMonth() + 1)}-${pad(yestDate.getDate())}`;

    wos.forEach((wo) => {
      let rawDate: string | null = null;
      if (dateType === "release_date") {
        rawDate = wo.release_date ? String(wo.release_date).substring(0, 10) : null;
      } else if (dateType === "delivery_date") {
        rawDate = wo.delivery_date ? String(wo.delivery_date).substring(0, 10) : null;
      } else {
        rawDate = (wo.wo_date || wo.created_at) ? String(wo.wo_date || wo.created_at).substring(0, 10) : null;
      }

      const key = rawDate || "UNDATED";
      let label = "Undated / Unscheduled";
      if (rawDate) {
        if (rawDate === nowStr) {
          label = `Today • ${formatDate(rawDate)}`;
        } else if (rawDate === yestStr) {
          label = `Yesterday • ${formatDate(rawDate)}`;
        } else {
          label = formatDate(rawDate);
        }
      } else if (dateType === "release_date") {
        label = "Not Released Yet (Pending)";
      }

      if (!groups[key]) {
        groups[key] = {
          dateStr: key,
          label,
          items: [],
          unreleasedItems: [],
          releasedItems: [],
        };
      }
      groups[key].items.push(wo);
      if (wo.is_released) {
        groups[key].releasedItems.push(wo);
      } else {
        groups[key].unreleasedItems.push(wo);
      }
    });

    return Object.values(groups);
  }, [wos, dateType]);

  const totalUnreleasedCount = React.useMemo(() => wos.filter((w) => !w.is_released).length, [wos]);
  const totalReleasedCount = React.useMemo(() => wos.filter((w) => w.is_released).length, [wos]);

  const handleInputChange = (val: string) => {
    setSearchQuery(val);
    setIsDropdownOpen(true);
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      handleSearch(val, releaseFilter, sortBy, fromDate, toDate, dateType);
    }, 200);
  };

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current);
    };
  }, []);

  useEffect(() => {
    // If a specific WO was passed in the URL, search specifically for it first
    if (urlWo) {
      setSearching(true);
      getWorkOrders({ search: urlWo.trim(), limit: 50, sort_by: sortBy, exclude_dispatched: true, from_date: fromDate || undefined, to_date: toDate || undefined, date_type: dateType })
        .then((data) => {
          const list = Array.isArray(data) ? data : [];
          const found = list.find((w) => w.wo_number.toUpperCase() === urlWo.trim().toUpperCase()) || list[0];
          if (found) {
            setWos(list);
            applyWO(found);
          } else {
            // Fallback load default list
            getWorkOrders({ limit: 100, sort_by: sortBy, exclude_dispatched: true, from_date: fromDate || undefined, to_date: toDate || undefined, date_type: dateType }).then((fallbackData) => {
              const fList = Array.isArray(fallbackData) ? fallbackData : [];
              setWos(fList);
              if (fList.length > 0) applyWO(fList[0]);
            });
          }
        })
        .catch(() => {
          setError("Failed to load requested Work Order.");
        })
        .finally(() => {
          setSearching(false);
        });
    } else {
      // General load
      setSearching(true);
      getWorkOrders({ limit: 100, sort_by: sortBy, exclude_dispatched: true, from_date: fromDate || undefined, to_date: toDate || undefined, date_type: dateType })
        .then((data) => {
          const list = Array.isArray(data) ? data : [];
          setWos(list);
          if (list.length > 0) {
            const candidate = list.find((w) => !w.is_released) || list.find((w) => w.status === "planned" || w.status === "in_production") || list[0];
            applyWO(candidate);
          }
        })
        .catch(() => {})
        .finally(() => {
          setSearching(false);
        });
    }
  }, [urlWo, applyWO, sortBy]);

  const fetchPlanningSummary = useCallback(async () => {
    try {
      const summary = await getPlanningSummary();
      setPlanningSummary(summary);
    } catch {
      // Non-blocking
    }
  }, []);

  useEffect(() => {
    fetchPlanningSummary();
  }, [fetchPlanningSummary]);

  const handleExportExcel = async (unreleasedOnly: boolean = false) => {
    setExportingExcel(true);
    try {
      const filterToUse = unreleasedOnly ? "unreleased" : (releaseFilter !== "all" ? releaseFilter : undefined);
      const data = await getWorkOrders({
        release_filter: filterToUse,
        exclude_dispatched: true,
        from_date: fromDate || undefined,
        to_date: toDate || undefined,
        date_type: dateType,
        limit: 500,
        sort_by: sortBy,
      });
      const list = Array.isArray(data) ? data : [];

      const headers = [
        "WO Number",
        "Heat Number",
        "Customer PO",
        "PO Date",
        "OAR Number",
        "OAR Date",
        "WO Date",
        "Required Delivery Date",
        "Customer Code",
        "Customer Name",
        "Part Number",
        "Part Name",
        "Grade",
        "Physical WO Qty",
        "Current Stage",
        "Release Status",
        "Is Released",
        "Ready For Production",
        "Delivery Risk",
        "Shortfall"
      ];

      const escapeCsv = (val: any) => {
        if (val === null || val === undefined) return '""';
        const str = String(val).replace(/"/g, '""');
        return `"${str}"`;
      };

      const rows = list.map((w) => [
        escapeCsv(w.wo_number),
        escapeCsv(w.heat_number || "Not Assigned"),
        escapeCsv(w.customer_po || "—"),
        escapeCsv(w.po_date ? formatDate(w.po_date) : "—"),
        escapeCsv(w.oar_number || "—"),
        escapeCsv(w.oar_date ? formatDate(w.oar_date) : "—"),
        escapeCsv(w.wo_date ? formatDate(w.wo_date) : formatDate(w.created_at)),
        escapeCsv(w.delivery_date ? formatDate(w.delivery_date) : "—"),
        escapeCsv(w.customer_code),
        escapeCsv(w.customer_name),
        escapeCsv(w.part_number),
        escapeCsv(w.part_name || "—"),
        escapeCsv(w.grade || "Standard"),
        escapeCsv(w.physical_wo_qty),
        escapeCsv(w.current_stage),
        escapeCsv(w.release_status || "UNRELEASED"),
        escapeCsv(w.is_released ? "YES" : "NO"),
        escapeCsv(w.ready_for_production ? "READY" : "AWAITING CLEARANCE"),
        escapeCsv(w.delivery_risk || "Normal"),
        escapeCsv(w.shortfall || "No"),
      ]);

      const csvContent = "\uFEFF" + [headers.join(","), ...rows.map((r) => r.join(","))].join("\r\n");
      const blob = new Blob([csvContent], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      const filename = `VSPL_Planner_WO_List_${unreleasedOnly ? "Unreleased_" : ""}${new Date().toISOString().slice(0, 10)}.csv`;
      link.setAttribute("href", url);
      link.setAttribute("download", filename);
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    } catch {
      setError("Failed to download planning Excel file.");
    } finally {
      setExportingExcel(false);
    }
  };

  const handleWOSelect = (woNum: string) => {
    const found = wos.find((w) => w.wo_number === woNum);
    if (found) {
      applyWO(found);
    } else {
      setSelectedWO(woNum);
    }
  };

  const toggleStage = (stgCode: string) => {
    if (stgCode === "DISPATCH") return; // Dispatch is always terminal
    if (stgCode === "F1" && castingProcess === "CONTINUOUS") return; // F1 is bypassed for Continuous Casting
    if (selectedStages.includes(stgCode)) {
      setSelectedStages(selectedStages.filter((s) => s !== stgCode));
    } else {
      const order = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];
      const newStages = [...selectedStages, stgCode].sort((a, b) => order.indexOf(a) - order.indexOf(b));
      setSelectedStages(newStages);
    }
  };

  const handleEngineeringRelease = async () => {
    setChainError("");
    if (docUrl && !docUrl.trim().toLowerCase().startsWith("https://")) {
      setChainError("Document URL must start with 'https://'.");
      return;
    }
    setChainBusy("engineering");
    try {
      const payload = {
        document_name: docName.trim() || undefined,
        document_url: docUrl.trim() || undefined,
        document_revision: docRevision.trim() || undefined,
        remarks: releaseRemarks.trim() || undefined,
      };
      const res = await engineeringReleaseWorkOrder(selectedWO, payload);
      setChainResult((prev) => ({ ...prev, engineering: res }));
    } catch (err: any) {
      setChainError(err?.response?.data?.detail || "Failed to record Engineering Release.");
    } finally {
      setChainBusy(null);
    }
  };

  const handleManufacturingRelease = async () => {
    setChainError("");
    if (docUrl && !docUrl.trim().toLowerCase().startsWith("https://")) {
      setChainError("Document URL must start with 'https://'.");
      return;
    }
    setChainBusy("manufacturing");
    try {
      const payload = {
        document_name: docName.trim() || undefined,
        document_url: docUrl.trim() || undefined,
        document_revision: docRevision.trim() || undefined,
        remarks: releaseRemarks.trim() || undefined,
      };
      const res = await manufacturingReleaseWorkOrder(selectedWO, payload);
      setChainResult((prev) => ({ ...prev, manufacturing: res }));
    } catch (err: any) {
      setChainError(err?.response?.data?.detail || "Failed to record Manufacturing Release.");
    } finally {
      setChainBusy(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessResult(null);

    if (!selectedWO) {
      setError("Please select a Work Order to release.");
      return;
    }

    const qty = Number(physicalQty);
    if (qty <= 0) {
      setError("Physical WO Quantity must be greater than 0.");
      return;
    }

    if (selectedStages.length === 0) {
      setError("Please select at least one production stage.");
      return;
    }

    if (selectedStages.includes("F1") && !castingProcess) {
      setError("Please select a casting process for F1 (Centrifugal Casting or Continuous Casting).");
      return;
    }

    setLoading(true);

    try {
      const res = await releaseWorkOrder({
        wo_number: selectedWO,
        physical_wo_qty: qty,
        route_stages: selectedStages,
        casting_process: castingProcess || undefined,
        heat_number: heatNumber.trim() || undefined,
        remarks: remarks,
      });

      setSuccessResult(res);
      fetchPlanningSummary();
      handleSearch(searchQuery, releaseFilter, sortBy, fromDate, toDate, dateType);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to release Work Order.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header with Title and Excel Export Buttons */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Production Planning
              </span>
              <span className="text-xs text-zinc-400">Daily Queue &amp; WO Release</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Work Order Release &amp; Custom Routing
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Planner dashboard to monitor daily backlog, track Heat Numbers, and release WOs with custom stage routing.
            </p>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Link
              href="/planning/wo-release-search"
              className="inline-flex items-center gap-1.5 rounded-xl border border-sky-300 dark:border-sky-800 bg-sky-50 dark:bg-sky-950/40 px-3 py-2 text-xs font-bold text-sky-800 dark:text-sky-300 shadow-sm hover:bg-sky-100 dark:hover:bg-sky-900/60 transition-colors"
              title="Open dedicated date-wise WO search and filter module"
            >
              <Search className="h-4 w-4 text-sky-600" />
              <span>Search Module &rarr;</span>
            </Link>
            <button
              type="button"
              disabled={exportingExcel}
              onClick={() => handleExportExcel(true)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-xs font-bold text-amber-800 dark:text-amber-300 shadow-sm hover:bg-amber-100 dark:hover:bg-amber-900/60 transition-colors cursor-pointer"
              title="Download all unreleased Work Orders awaiting planner release"
            >
              <FileSpreadsheet className="h-4 w-4 text-amber-600" />
              <span>{exportingExcel ? "Exporting..." : "Download Unreleased (.csv)"}</span>
            </button>
            <button
              type="button"
              disabled={exportingExcel}
              onClick={() => handleExportExcel(false)}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
              title="Export all filtered work orders as Excel CSV"
            >
              <Download className="h-4 w-4 text-blue-600" />
              <span>Export All WOs</span>
            </button>
          </div>
        </div>

        {/* Planner Live Metrics KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {/* Card 1: Yet to Release */}
          <div
            onClick={() => {
              setReleaseFilter("unreleased");
              handleSearch(searchQuery, "unreleased", sortBy);
            }}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseFilter === "unreleased"
                ? "border-amber-500 bg-amber-50/70 dark:bg-amber-950/50 ring-2 ring-amber-500/30 shadow-md"
                : "border-amber-200/70 dark:border-amber-900/40 bg-amber-50/20 dark:bg-amber-950/20 hover:border-amber-300"
            }`}
          >
            <div className="flex items-center justify-between text-amber-600 dark:text-amber-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Yet to Release</span>
              <Clock className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-zinc-900 dark:text-zinc-100">
              {planningSummary?.unreleased_count ?? "—"}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500 flex items-center justify-between">
              <span>Pending Release</span>
              <span className="font-semibold text-amber-600">Filter View &rarr;</span>
            </div>
          </div>

          {/* Card 2: Ready for Release */}
          <div
            onClick={() => {
              setReleaseFilter("ready_for_production");
              handleSearch(searchQuery, "ready_for_production", sortBy);
            }}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseFilter === "ready_for_production"
                ? "border-purple-500 bg-purple-50/70 dark:bg-purple-950/50 ring-2 ring-purple-500/30 shadow-md"
                : "border-purple-200/70 dark:border-purple-900/40 bg-purple-50/20 dark:bg-purple-950/20 hover:border-purple-300"
            }`}
          >
            <div className="flex items-center justify-between text-purple-600 dark:text-purple-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Ready for Prod</span>
              <ClipboardCheck className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-zinc-900 dark:text-zinc-100">
              {planningSummary?.ready_for_production_count ?? "—"}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500 flex items-center justify-between">
              <span>Mfg Cleared / Ready</span>
              <span className="font-semibold text-purple-600">Filter View &rarr;</span>
            </div>
          </div>

          {/* Card 3: Producing Today */}
          <div className="p-4 rounded-2xl border border-emerald-200/70 dark:border-emerald-900/40 bg-emerald-50/20 dark:bg-emerald-950/20 shadow-xs">
            <div className="flex items-center justify-between text-emerald-600 dark:text-emerald-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Producing Today</span>
              <span className="flex h-2 w-2 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
              </span>
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-emerald-700 dark:text-emerald-300">
              {planningSummary?.producing_today_count ?? "—"}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500">
              Active shop floor logs today
            </div>
          </div>

          {/* Card 4: Released & Active */}
          <div
            onClick={() => {
              setReleaseFilter("released");
              handleSearch(searchQuery, "released", sortBy);
            }}
            className={`p-4 rounded-2xl border transition-all cursor-pointer ${
              releaseFilter === "released"
                ? "border-blue-500 bg-blue-50/70 dark:bg-blue-950/50 ring-2 ring-blue-500/30 shadow-md"
                : "border-blue-200/70 dark:border-blue-900/40 bg-blue-50/20 dark:bg-blue-950/20 hover:border-blue-300"
            }`}
          >
            <div className="flex items-center justify-between text-blue-600 dark:text-blue-400">
              <span className="text-[10px] uppercase font-bold tracking-wider">Released &amp; Active</span>
              <Layers className="h-4 w-4" />
            </div>
            <div className="mt-2 text-2xl font-black font-mono text-zinc-900 dark:text-zinc-100">
              {planningSummary?.released_count ?? "—"}
            </div>
            <div className="mt-0.5 text-[10px] text-zinc-500 flex items-center justify-between">
              <span>In Manufacturing Route</span>
              <span className="font-semibold text-blue-600">Filter View &rarr;</span>
            </div>
          </div>
        </div>

        {/* Global Error Banner */}
        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold flex items-center justify-between">
            <span>{error}</span>
            <button type="button" onClick={() => setError("")} className="text-rose-400 hover:text-rose-600">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        {/* Success Banner */}
        {successResult && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5 space-y-3">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-500" />
              <div>
                <h4 className="text-sm font-bold text-emerald-800 dark:text-emerald-300">
                  {successResult.message}
                </h4>
                <p className="text-xs text-emerald-600 dark:text-emerald-400">
                  Route: <strong>{successResult.route}</strong>
                </p>
                {successResult.casting_process && (
                  <p className="text-xs text-emerald-700 dark:text-emerald-300 mt-0.5">
                    Casting Process:{" "}
                    <strong>
                      {successResult.casting_process === "CONTINUOUS"
                        ? "Continuous Casting"
                        : successResult.casting_process === "CENTRIFUGAL"
                        ? "Centrifugal Casting / Melt"
                        : successResult.casting_process}
                    </strong>
                  </p>
                )}
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <Link
                href={`/production/tracking?wo=${successResult.wo_number}`}
                className="inline-flex items-center gap-1 text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline"
              >
                <span>Track {successResult.wo_number} on Floor</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
              {successResult.casting_process === "CONTINUOUS" && (
                <Link
                  href="/continuous-casting/planning"
                  className="inline-flex items-center gap-1 text-xs font-bold text-amber-600 dark:text-amber-400 hover:underline ml-3"
                >
                  <span>Continuous Casting Planning &amp; Allocations</span>
                  <ArrowRight className="h-3.5 w-3.5" />
                </Link>
              )}
            </div>
          </div>
        )}



        {/* Active Work Order Context Card */}
        {selectedWODetail && (
          <div className="rounded-2xl border border-blue-500/30 bg-blue-50/20 dark:bg-blue-950/20 p-4 shadow-sm space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-blue-200/40 dark:border-blue-800/40 pb-2">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-base font-extrabold text-blue-700 dark:text-blue-300">
                  {selectedWODetail.wo_number}
                </span>
                <Badge variant={getRAGVariant(selectedWODetail.status)} size="sm">
                  {selectedWODetail.status.replace(/_/g, " ").toUpperCase()}
                </Badge>
                {selectedWODetail.status === "dispatched" || selectedWODetail.current_stage === "Completed" ? (
                  <span className="rounded bg-zinc-200 dark:bg-zinc-800 px-2 py-0.5 text-[10px] font-bold text-zinc-700 dark:text-zinc-300 border border-zinc-400">
                    COMPLETELY DISPATCHED (CLOSED)
                  </span>
                ) : selectedWODetail.is_released ? (
                  <span className="rounded bg-emerald-100 dark:bg-emerald-950/60 px-2 py-0.5 text-[10px] font-bold text-emerald-800 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
                    RELEASED {selectedWODetail.release_date ? `(${formatDate(selectedWODetail.release_date)})` : ""}
                  </span>
                ) : selectedWODetail.ready_for_production ? (
                  <span className="rounded bg-purple-100 dark:bg-purple-950/60 px-2 py-0.5 text-[10px] font-bold text-purple-800 dark:text-purple-300 border border-purple-300 dark:border-purple-800">
                    READY FOR PRODUCTION
                  </span>
                ) : (
                  <span className="rounded bg-amber-100 dark:bg-amber-950/60 px-2 py-0.5 text-[10px] font-bold text-amber-800 dark:text-amber-300 border border-amber-300 dark:border-amber-800">
                    NOT YET RELEASED
                  </span>
                )}
                {selectedWODetail.current_stage && (
                  <span className="rounded bg-blue-100 dark:bg-blue-900/60 px-2 py-0.5 text-[10px] font-bold text-blue-800 dark:text-blue-200 font-mono">
                    Stage: {selectedWODetail.current_stage}
                  </span>
                )}
              </div>
              <Link
                href={`/production/tracking?wo=${encodeURIComponent(selectedWODetail.wo_number)}`}
                className="inline-flex items-center gap-1 text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline"
              >
                <span>Floor Tracking</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs pt-1">
              <div>
                <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Customer</span>
                <span className="font-semibold text-zinc-900 dark:text-zinc-100 truncate block">
                  {selectedWODetail.customer_name}
                </span>
                <span className="text-[10px] text-zinc-400 font-mono">{selectedWODetail.customer_code}</span>
              </div>
              <div>
                <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Part Number</span>
                <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                  {selectedWODetail.part_number}
                </span>
                {selectedWODetail.part_name && (
                  <span className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate block">
                    {selectedWODetail.part_name}
                  </span>
                )}
              </div>
              <div>
                <span className="text-[10px] text-zinc-400 uppercase font-semibold block">OAR &amp; PO</span>
                <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200 block">
                  {selectedWODetail.oar_number || "—"}
                </span>
                <span className="text-[10px] text-zinc-500 font-mono">
                  PO: {selectedWODetail.customer_po || "—"}
                </span>
              </div>
              <div>
                <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Quantities</span>
                <span className="font-mono font-bold text-emerald-600 block">
                  WO: {selectedWODetail.physical_wo_qty} pcs
                </span>
                <span className="text-[10px] text-zinc-400 font-mono">
                  Order: {selectedWODetail.order_qty} pcs
                </span>
              </div>
            </div>

            {/* Production Planning & Genealogy Timeline Dates & Heat Number */}
            <div className="pt-2 border-t border-blue-200/40 dark:border-blue-800/40 grid grid-cols-2 sm:grid-cols-6 gap-2 text-xs">
              <div className="p-2 rounded-lg bg-white/70 dark:bg-zinc-900/60 border border-blue-100 dark:border-blue-900/40">
                <span className="text-[9px] text-zinc-400 uppercase font-bold block">1. PO Creation Date</span>
                <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200">
                  {formatDate(selectedWODetail.po_date)}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-white/70 dark:bg-zinc-900/60 border border-blue-100 dark:border-blue-900/40">
                <span className="text-[9px] text-zinc-400 uppercase font-bold block">2. OAR Gen Date</span>
                <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200">
                  {formatDate(selectedWODetail.oar_date)}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-white/70 dark:bg-zinc-900/60 border border-blue-100 dark:border-blue-900/40">
                <span className="text-[9px] text-zinc-400 uppercase font-bold block">3. WO Gen Date</span>
                <span className="font-mono font-bold text-blue-600 dark:text-blue-400">
                  {formatDate(selectedWODetail.wo_date || selectedWODetail.created_at)}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-white/70 dark:bg-zinc-900/60 border border-blue-100 dark:border-blue-900/40">
                <span className="text-[9px] text-zinc-400 uppercase font-bold block">4. Required Delivery</span>
                <span className="font-mono font-bold text-amber-600 dark:text-amber-400">
                  {formatDate(selectedWODetail.delivery_date)}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-white/70 dark:bg-zinc-900/60 border border-blue-100 dark:border-blue-900/40">
                <span className="text-[9px] text-zinc-400 uppercase font-bold block">5. Release Status</span>
                <span className="font-mono font-bold text-xs">
                  {selectedWODetail.is_released ? (
                    <span className="text-emerald-600">Released</span>
                  ) : selectedWODetail.ready_for_production ? (
                    <span className="text-purple-600">Ready for Prod</span>
                  ) : (
                    <span className="text-amber-600">Not Released</span>
                  )}
                </span>
              </div>
              <div className="p-2 rounded-lg bg-white/70 dark:bg-zinc-900/60 border border-blue-100 dark:border-blue-900/40">
                <span className="text-[9px] text-zinc-400 uppercase font-bold block">6. Heat Number</span>
                <span className="font-mono font-bold text-xs text-orange-600 dark:text-orange-400 flex items-center gap-1">
                  <Flame className="h-3 w-3 text-orange-500 shrink-0" />
                  <span className="truncate">{selectedWODetail.heat_number || "Not Assigned"}</span>
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Release chain: Engineering Release -> Manufacturing Release -> WO Release */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-3">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            Release Chain for <span className="font-mono">{selectedWO || "..."}</span>
          </h3>
          <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
            Engineering Release &rarr; Manufacturing Release &rarr; WO Release (below) &rarr; Production. Each step is optional for WOs that don&apos;t use this gated flow, but once started, all three are required before production.
          </p>
          {chainError && (
            <div className="flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{chainError}</span>
            </div>
          )}

          {/* Release Evidence inputs */}
          <div className="rounded-xl border border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-950/40 p-3 space-y-2">
            <div className="text-[11px] font-bold text-zinc-700 dark:text-zinc-300">
              Release Evidence (optional document attachment for audit trail)
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div>
                <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400">Document Name</label>
                <input
                  type="text"
                  placeholder="e.g., Drawing / Spec"
                  value={docName}
                  onChange={(e) => setDocName(e.target.value)}
                  className="w-full mt-0.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2.5 py-1 text-xs text-zinc-900 dark:text-zinc-100 outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400">Document URL (https://)</label>
                <input
                  type="url"
                  placeholder="https://..."
                  value={docUrl}
                  onChange={(e) => setDocUrl(e.target.value)}
                  className="w-full mt-0.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2.5 py-1 text-xs text-zinc-900 dark:text-zinc-100 outline-none focus:border-blue-500"
                />
              </div>
              <div>
                <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400">Revision</label>
                <input
                  type="text"
                  placeholder="e.g., Rev C"
                  value={docRevision}
                  onChange={(e) => setDocRevision(e.target.value)}
                  className="w-full mt-0.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2.5 py-1 text-xs text-zinc-900 dark:text-zinc-100 outline-none focus:border-blue-500"
                />
              </div>
            </div>
            <div>
              <label className="text-[10px] font-semibold text-zinc-500 dark:text-zinc-400">Release Remarks</label>
              <input
                type="text"
                placeholder="Remarks / approval notes..."
                value={releaseRemarks}
                onChange={(e) => setReleaseRemarks(e.target.value)}
                className="w-full mt-0.5 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2.5 py-1 text-xs text-zinc-900 dark:text-zinc-100 outline-none focus:border-blue-500"
              />
            </div>
            {docUrl && docUrl.startsWith("https://") && (
              <div className="pt-1">
                <a
                  href={docUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-[11px] font-bold text-blue-600 dark:text-blue-400 hover:underline"
                >
                  <span>Open Attached Document</span>
                  <ArrowRight className="h-3 w-3" />
                </a>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleEngineeringRelease}
              disabled={chainBusy !== null || !!chainResult.engineering || !selectedWO}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              <ClipboardCheck className="h-3.5 w-3.5" />
              {chainResult.engineering ? "Engineering Released" : chainBusy === "engineering" ? "Releasing..." : "Engineering Release"}
            </button>
            <button
              type="button"
              onClick={handleManufacturingRelease}
              disabled={chainBusy !== null || !!chainResult.manufacturing || !selectedWO}
              className="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-purple-500 disabled:opacity-50 transition-colors"
            >
              <Wrench className="h-3.5 w-3.5" />
              {chainResult.manufacturing ? "Manufacturing Released" : chainBusy === "manufacturing" ? "Releasing..." : "Manufacturing Release"}
            </button>
          </div>
        </div>

        {/* Release & Route Declaration Form */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Select Work Order for Release *
                </label>
                {searching && (
                  <span className="flex items-center gap-1 text-[10px] text-blue-600 font-medium">
                    <RefreshCw className="h-2.5 w-2.5 animate-spin" /> Searching...
                  </span>
                )}
              </div>

              {/* Production Planning Filter Tabs & Sorting */}
              <div className="flex flex-wrap items-center justify-between gap-2 mt-2 mb-2">
                <div className="flex items-center gap-1 bg-zinc-100 dark:bg-zinc-800/80 p-0.5 rounded-lg text-[10px] font-semibold">
                  <button
                    type="button"
                    onClick={() => {
                      setReleaseFilter("all");
                      handleSearch(searchQuery, "all", sortBy, fromDate, toDate, dateType);
                    }}
                    className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                      releaseFilter === "all"
                        ? "bg-white dark:bg-zinc-900 text-blue-600 dark:text-blue-400 font-bold shadow-xs"
                        : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                    }`}
                  >
                    All
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setReleaseFilter("unreleased");
                      handleSearch(searchQuery, "unreleased", sortBy, fromDate, toDate, dateType);
                    }}
                    className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                      releaseFilter === "unreleased"
                        ? "bg-white dark:bg-zinc-900 text-amber-600 dark:text-amber-400 font-bold shadow-xs"
                        : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                    }`}
                  >
                    Not Yet Released
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setReleaseFilter("ready_for_production");
                      handleSearch(searchQuery, "ready_for_production", sortBy, fromDate, toDate, dateType);
                    }}
                    className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                      releaseFilter === "ready_for_production"
                        ? "bg-white dark:bg-zinc-900 text-purple-600 dark:text-purple-400 font-bold shadow-xs"
                        : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                    }`}
                  >
                    Ready for Prod
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setReleaseFilter("released");
                      handleSearch(searchQuery, "released", sortBy, fromDate, toDate, dateType);
                    }}
                    className={`px-2 py-1 rounded-md transition-colors cursor-pointer ${
                      releaseFilter === "released"
                        ? "bg-white dark:bg-zinc-900 text-emerald-600 dark:text-emerald-400 font-bold shadow-xs"
                        : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
                    }`}
                  >
                    Already Released
                  </button>
                </div>

                <div className="flex items-center gap-2 text-[10px] flex-wrap">
                  <div className="flex items-center gap-1.5">
                    <span className="text-zinc-400 font-medium">Plan by:</span>
                    <select
                      value={sortBy}
                      onChange={(e) => {
                        const val = e.target.value;
                        setSortBy(val);
                        handleSearch(searchQuery, releaseFilter, val, fromDate, toDate, dateType);
                      }}
                      className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-2 py-1 text-[10px] font-semibold text-zinc-800 dark:text-zinc-200 outline-none focus:border-blue-500"
                    >
                      <option value="wo_date_desc">WO Gen Date (Newest first)</option>
                      <option value="wo_date_asc">WO Gen Date (Oldest first / FIFO)</option>
                      <option value="release_date_desc">Release Date (Newest first)</option>
                      <option value="release_date_asc">Release Date (Oldest first)</option>
                      <option value="delivery_date_asc">Delivery Date (Earliest first)</option>
                      <option value="delivery_date_desc">Delivery Date (Latest first)</option>
                      <option value="wo_number_asc">WO Number (Ascending)</option>
                      <option value="wo_number_desc">WO Number (Descending)</option>
                    </select>
                  </div>

                  <button
                    type="button"
                    disabled={exportingExcel}
                    onClick={() => handleExportExcel(false)}
                    className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-100 dark:hover:bg-emerald-900/60 font-bold text-[10px] shadow-xs cursor-pointer"
                    title="Download currently filtered list as Excel CSV spreadsheet"
                  >
                    <FileSpreadsheet className="h-3 w-3 text-emerald-600" />
                    <span>{exportingExcel ? "Exporting..." : "Download Excel (.csv)"}</span>
                  </button>
                </div>
              </div>

              {/* DATE-WISE SEARCH & FILTER PANEL */}
              <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-gradient-to-r from-blue-50/40 via-indigo-50/20 to-purple-50/30 dark:from-blue-950/20 dark:via-zinc-900 dark:to-zinc-900 p-3 mb-2 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-1.5 text-xs font-bold text-zinc-800 dark:text-zinc-200">
                    <Calendar className="h-3.5 w-3.5 text-blue-600" />
                    <span>Date-Wise Search &amp; Filter</span>
                  </div>
                  {/* Date field target selector */}
                  <div className="flex items-center gap-1 bg-white/80 dark:bg-zinc-800/80 p-0.5 rounded-lg border border-zinc-200/80 dark:border-zinc-700 text-[10px]">
                    <span className="text-zinc-400 font-medium px-1.5">Date By:</span>
                    <button
                      type="button"
                      onClick={() => {
                        setDateType("wo_date");
                        handleSearch(searchQuery, releaseFilter, sortBy, fromDate, toDate, "wo_date");
                      }}
                      className={`px-2 py-0.5 rounded-md font-semibold transition-colors cursor-pointer ${
                        dateType === "wo_date"
                          ? "bg-blue-600 text-white font-bold shadow-xs"
                          : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                      }`}
                    >
                      WO Gen Date
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDateType("release_date");
                        handleSearch(searchQuery, releaseFilter, sortBy, fromDate, toDate, "release_date");
                      }}
                      className={`px-2 py-0.5 rounded-md font-semibold transition-colors cursor-pointer ${
                        dateType === "release_date"
                          ? "bg-blue-600 text-white font-bold shadow-xs"
                          : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                      }`}
                    >
                      Release Date
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDateType("delivery_date");
                        handleSearch(searchQuery, releaseFilter, sortBy, fromDate, toDate, "delivery_date");
                      }}
                      className={`px-2 py-0.5 rounded-md font-semibold transition-colors cursor-pointer ${
                        dateType === "delivery_date"
                          ? "bg-blue-600 text-white font-bold shadow-xs"
                          : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                      }`}
                    >
                      Delivery Date
                    </button>
                  </div>
                </div>

                {/* Quick Date Presets & Custom Pickers */}
                <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-zinc-200/50 dark:border-zinc-800/60">
                  <div className="flex items-center gap-1 flex-wrap text-[10px]">
                    <span className="text-zinc-400 font-medium mr-1">Quick:</span>
                    {(
                      [
                        { id: "all", label: "All Dates" },
                        { id: "today", label: "Today" },
                        { id: "yesterday", label: "Yesterday" },
                        { id: "last_7_days", label: "Last 7 Days" },
                        { id: "last_30_days", label: "Last 30 Days" },
                      ] as const
                    ).map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => applyDatePreset(p.id)}
                        className={`px-2 py-0.5 rounded-md transition-colors cursor-pointer ${
                          datePreset === p.id && !fromDate && !toDate && p.id === "all"
                            ? "bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300 font-bold"
                            : datePreset === p.id && (fromDate || toDate)
                            ? "bg-blue-600 text-white font-bold shadow-xs"
                            : "bg-white/80 dark:bg-zinc-800/60 text-zinc-600 dark:text-zinc-300 border border-zinc-200/60 dark:border-zinc-700/60 hover:bg-zinc-100"
                        }`}
                      >
                        {p.label}
                      </button>
                    ))}
                  </div>

                  <div className="flex items-center gap-1.5 text-[10px]">
                    <div className="flex items-center gap-1">
                      <span className="text-zinc-400 font-semibold">From:</span>
                      <input
                        type="date"
                        value={fromDate}
                        onChange={(e) => {
                          const val = e.target.value;
                          setFromDate(val);
                          setDatePreset("custom");
                          handleSearch(searchQuery, releaseFilter, sortBy, val, toDate, dateType);
                        }}
                        className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-1.5 py-0.5 text-[10px] font-mono text-zinc-800 dark:text-zinc-200 outline-none focus:border-blue-500"
                      />
                    </div>
                    <div className="flex items-center gap-1">
                      <span className="text-zinc-400 font-semibold">To:</span>
                      <input
                        type="date"
                        value={toDate}
                        onChange={(e) => {
                          const val = e.target.value;
                          setToDate(val);
                          setDatePreset("custom");
                          handleSearch(searchQuery, releaseFilter, sortBy, fromDate, val, dateType);
                        }}
                        className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-1.5 py-0.5 text-[10px] font-mono text-zinc-800 dark:text-zinc-200 outline-none focus:border-blue-500"
                      />
                    </div>
                    {(fromDate || toDate) && (
                      <button
                        type="button"
                        onClick={() => applyDatePreset("all")}
                        className="p-1 rounded-md text-zinc-400 hover:text-zinc-600 hover:bg-zinc-200/60 dark:hover:bg-zinc-800 cursor-pointer"
                        title="Clear date filter"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Active filter summary pill */}
                {(fromDate || toDate) && (
                  <div className="flex items-center justify-between text-[10px] text-blue-700 dark:text-blue-300 bg-blue-100/60 dark:bg-blue-950/60 px-2 py-1 rounded-lg">
                    <span>
                      Active Date Filter: <strong>{fromDate ? formatDate(fromDate) : "Start"}</strong> &rarr;{" "}
                      <strong>{toDate ? formatDate(toDate) : "End"}</strong> ({dateType === "wo_date" ? "WO Gen Date" : dateType === "release_date" ? "Release Date" : "Delivery Date"}) •{" "}
                      <strong>{wos.length}</strong> WOs found
                    </span>
                    <button
                      type="button"
                      onClick={() => applyDatePreset("all")}
                      className="font-bold underline text-blue-600 hover:text-blue-800 cursor-pointer"
                    >
                      Reset Date
                    </button>
                  </div>
                )}
              </div>

              {/* Searchable Combobox for Work Orders */}
              <div className="relative mt-1.5" ref={dropdownRef}>
                <div className="relative">
                  <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-zinc-400 pointer-events-none" />
                  <input
                    ref={searchInputRef}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => handleInputChange(e.target.value)}
                    onFocus={() => setIsDropdownOpen(true)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        if (wos.length > 0) {
                          applyWO(wos[0]);
                          setSearchQuery(wos[0].wo_number);
                          setIsDropdownOpen(false);
                        }
                      } else if (e.key === "Escape") {
                        setIsDropdownOpen(false);
                      }
                    }}
                    placeholder="Search WO ID (e.g. 17608), Part #, Customer, Date (YYYY-MM-DD)..."
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-9 pr-16 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                  <div className="absolute right-2 top-2 flex items-center gap-1">
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => {
                          setSearchQuery("");
                          handleSearch("", releaseFilter, sortBy, fromDate, toDate, dateType);
                          searchInputRef.current?.focus();
                        }}
                        className="p-0.5 rounded text-zinc-400 hover:text-zinc-600 cursor-pointer"
                        title="Clear search"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                      className="p-0.5 rounded text-zinc-400 hover:text-zinc-600 cursor-pointer"
                      title="Toggle options list"
                    >
                      <ChevronDown className={`h-3.5 w-3.5 transition-transform ${isDropdownOpen ? "rotate-180" : ""}`} />
                    </button>
                  </div>
                </div>

                {/* Dropdown Results List Grouped Date-Wise with Released vs Unreleased filter */}
                {isDropdownOpen && (
                  <div className="absolute z-30 mt-1 max-h-80 w-full overflow-y-auto rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-2xl">
                    {/* Quick filter inside dropdown */}
                    <div className="sticky top-0 z-20 bg-white/95 dark:bg-zinc-900/95 backdrop-blur-xs px-3 py-1.5 border-b border-zinc-200/80 dark:border-zinc-800 flex items-center justify-between gap-1 text-[10px]">
                      <span className="font-semibold text-zinc-400">Show:</span>
                      <div className="flex items-center gap-1">
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDateQueueTab("all");
                          }}
                          className={`px-2 py-0.5 rounded-md font-bold transition-colors cursor-pointer ${
                            dateQueueTab === "all"
                              ? "bg-blue-600 text-white shadow-xs"
                              : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                          }`}
                        >
                          All ({wos.length})
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDateQueueTab("unreleased");
                          }}
                          className={`px-2 py-0.5 rounded-md font-bold transition-colors cursor-pointer flex items-center gap-1 ${
                            dateQueueTab === "unreleased"
                              ? "bg-amber-600 text-white shadow-xs"
                              : "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 border border-amber-200/60 dark:border-amber-900/60 hover:bg-amber-100"
                          }`}
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                          <span>Not Released ({totalUnreleasedCount})</span>
                        </button>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDateQueueTab("released");
                          }}
                          className={`px-2 py-0.5 rounded-md font-bold transition-colors cursor-pointer flex items-center gap-1 ${
                            dateQueueTab === "released"
                              ? "bg-emerald-600 text-white shadow-xs"
                              : "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-200/60 dark:border-emerald-900/60 hover:bg-emerald-100"
                          }`}
                        >
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                          <span>Released ({totalReleasedCount})</span>
                        </button>
                      </div>
                    </div>

                    {wos.length === 0 ? (
                      <div className="p-4 text-center text-xs text-zinc-400">
                        {searching ? "Searching work orders..." : `No work orders found matching "${searchQuery}"`}
                      </div>
                    ) : (
                      <div>
                        {groupedWOsByDate.map((group) => {
                          const displayItems =
                            dateQueueTab === "unreleased"
                              ? group.unreleasedItems
                              : dateQueueTab === "released"
                              ? group.releasedItems
                              : group.items;

                          if (displayItems.length === 0 && dateQueueTab !== "all") {
                            return null;
                          }

                          return (
                            <div key={group.dateStr} className="border-b border-zinc-100 dark:border-zinc-800 last:border-b-0">
                              {/* Sticky Date Section Header */}
                              <div className="sticky top-7 z-10 bg-zinc-100/95 dark:bg-zinc-800/95 backdrop-blur-xs px-3 py-1 flex items-center justify-between text-[10px] font-bold text-zinc-700 dark:text-zinc-300 border-b border-zinc-200/60 dark:border-zinc-700/60 shadow-2xs">
                                <span className="flex items-center gap-1.5 font-mono">
                                  <Calendar className="h-3 w-3 text-blue-500 shrink-0" />
                                  {group.label}
                                </span>
                                <div className="flex items-center gap-1.5 text-[9px]">
                                  {group.unreleasedItems.length > 0 && (
                                    <span className="px-1.5 py-0.2 rounded bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 font-semibold">
                                      {group.unreleasedItems.length} Not Released
                                    </span>
                                  )}
                                  {group.releasedItems.length > 0 && (
                                    <span className="px-1.5 py-0.2 rounded bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 font-semibold">
                                      {group.releasedItems.length} Released
                                    </span>
                                  )}
                                </div>
                              </div>
                              <div className="divide-y divide-zinc-50 dark:divide-zinc-800/50">
                                {displayItems.map((w) => (
                                  <div
                                    key={w.wo_number}
                                    onClick={() => {
                                      applyWO(w);
                                      setSearchQuery(w.wo_number);
                                      setIsDropdownOpen(false);
                                    }}
                                    className={`p-3 cursor-pointer transition-colors hover:bg-blue-50/70 dark:hover:bg-blue-950/40 flex items-start justify-between gap-3 text-xs ${
                                      selectedWO === w.wo_number ? "bg-blue-50 dark:bg-blue-950/60" : ""
                                    }`}
                                  >
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-1.5 flex-wrap">
                                        <span className={`font-mono font-extrabold ${selectedWO === w.wo_number ? "text-blue-600 dark:text-blue-400" : "text-zinc-900 dark:text-zinc-100"}`}>
                                          {w.wo_number}
                                        </span>
                                        <Badge variant={getRAGVariant(w.status)} size="sm">
                                          {w.status.replace(/_/g, " ").toUpperCase()}
                                        </Badge>
                                        {w.is_released ? (
                                          <span className="rounded bg-emerald-100 dark:bg-emerald-950/60 px-1.5 py-0.2 text-[9px] font-bold text-emerald-700 dark:text-emerald-300">
                                            RELEASED {w.release_date ? `(${formatDate(w.release_date)})` : ""}
                                          </span>
                                        ) : w.ready_for_production ? (
                                          <span className="rounded bg-purple-100 dark:bg-purple-950/60 px-1.5 py-0.2 text-[9px] font-bold text-purple-700 dark:text-purple-300">
                                            READY FOR PROD
                                          </span>
                                        ) : (
                                          <span className="rounded bg-amber-100 dark:bg-amber-950/60 px-1.5 py-0.2 text-[9px] font-bold text-amber-700 dark:text-amber-300">
                                            NOT RELEASED
                                          </span>
                                        )}
                                        {w.heat_number && (
                                          <span className="rounded bg-orange-100 dark:bg-orange-950/60 px-1.5 py-0.2 text-[9px] font-mono font-bold text-orange-700 dark:text-orange-300 flex items-center gap-0.5">
                                            <Flame className="h-2.5 w-2.5" />
                                            {w.heat_number}
                                          </span>
                                        )}
                                        {w.current_stage && (
                                          <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.2 text-[9px] font-mono text-zinc-600 dark:text-zinc-400">
                                            {w.current_stage}
                                          </span>
                                        )}
                                      </div>
                                      <div className="text-[11px] text-zinc-500 truncate mt-0.5">
                                        <span className="font-semibold text-zinc-700 dark:text-zinc-300">{w.part_number}</span>
                                        {w.customer_code ? ` • ${w.customer_code}` : w.customer_name ? ` • ${w.customer_name}` : ""}
                                        {w.customer_po ? ` • PO: ${w.customer_po}` : ""}
                                      </div>
                                      <div className="flex items-center gap-2 text-[10px] text-zinc-400 mt-1 font-mono flex-wrap">
                                        <span>WO Gen: <strong className="text-zinc-600 dark:text-zinc-300">{formatDate(w.wo_date || w.created_at)}</strong></span>
                                        {w.release_date && <span>• Released: <strong className="text-emerald-600 dark:text-emerald-400">{formatDate(w.release_date)}</strong></span>}
                                        {w.delivery_date && <span>• Delivery: <strong className="text-amber-600 dark:text-amber-400">{formatDate(w.delivery_date)}</strong></span>}
                                      </div>
                                    </div>
                                    <div className="text-right whitespace-nowrap shrink-0">
                                      <span className="font-mono font-bold text-emerald-600">{w.physical_wo_qty} pcs</span>
                                      {w.oar_number && <div className="text-[10px] text-zinc-400 font-mono">OAR: {w.oar_number}</div>}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Selected WO confirmed summary */}
              {selectedWODetail && (
                <div className="mt-2 flex items-center justify-between text-xs bg-blue-50/60 dark:bg-blue-950/40 px-3 py-2 rounded-xl border border-blue-200/50 dark:border-blue-900/40">
                  <div className="flex items-center gap-2 truncate">
                    <CheckCircle2 className="h-4 w-4 text-emerald-600 shrink-0" />
                    <span className="font-mono font-bold text-blue-700 dark:text-blue-300">{selectedWODetail.wo_number}</span>
                    <span className="text-zinc-400 truncate">({selectedWODetail.part_number} - {selectedWODetail.customer_code || selectedWODetail.customer_name})</span>
                  </div>
                  <div className="flex items-center gap-3">
                    {selectedWODetail.heat_number && (
                      <span className="text-orange-600 font-mono font-bold text-[10px] flex items-center gap-1">
                        <Flame className="h-3 w-3" />
                        {selectedWODetail.heat_number}
                      </span>
                    )}
                    <span className="font-mono font-bold text-emerald-600 shrink-0">{selectedWODetail.physical_wo_qty} pcs</span>
                  </div>
                </div>
              )}

              {/* Date-Wise WO Release Queue Browser: Select between Released vs Not Released */}
              <div className="mt-2.5 rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950/40 p-2.5 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <CalendarDays className="h-4 w-4 text-blue-600 shrink-0" />
                    <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200">
                      Date-Wise Work Order Selector
                    </span>
                    <span className="rounded-full bg-blue-100 dark:bg-blue-900/60 px-1.5 py-0.2 text-[9px] font-bold text-blue-700 dark:text-blue-300">
                      {wos.length} WOs • {groupedWOsByDate.length} Dates
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    {/* View filter: Not Released vs Released vs All */}
                    <div className="flex items-center gap-1 bg-white dark:bg-zinc-900 p-0.5 rounded-lg border border-zinc-200 dark:border-zinc-700/80 text-[10px]">
                      <button
                        type="button"
                        onClick={() => setDateQueueTab("unreleased")}
                        className={`px-2 py-0.5 rounded-md font-bold transition-all cursor-pointer flex items-center gap-1 ${
                          dateQueueTab === "unreleased"
                            ? "bg-amber-600 text-white shadow-xs"
                            : "text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40"
                        }`}
                        title="Show only Work Orders waiting to be released"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400"></span>
                        <span>Not Released ({totalUnreleasedCount})</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setDateQueueTab("released")}
                        className={`px-2 py-0.5 rounded-md font-bold transition-all cursor-pointer flex items-center gap-1 ${
                          dateQueueTab === "released"
                            ? "bg-emerald-600 text-white shadow-xs"
                            : "text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40"
                        }`}
                        title="Show only Work Orders already released"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                        <span>Released ({totalReleasedCount})</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setDateQueueTab("all")}
                        className={`px-2 py-0.5 rounded-md font-bold transition-all cursor-pointer ${
                          dateQueueTab === "all"
                            ? "bg-blue-600 text-white shadow-xs"
                            : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                        }`}
                      >
                        All ({wos.length})
                      </button>
                    </div>

                    <button
                      type="button"
                      onClick={() => setIsDateQueueOpen(!isDateQueueOpen)}
                      className="p-1 rounded text-zinc-400 hover:text-zinc-600 cursor-pointer"
                      title={isDateQueueOpen ? "Collapse section" : "Expand section"}
                    >
                      <ChevronDown className={`h-3.5 w-3.5 transition-transform ${isDateQueueOpen ? "rotate-180" : ""}`} />
                    </button>
                  </div>
                </div>

                {isDateQueueOpen && (
                  <div className="max-h-80 overflow-y-auto space-y-2.5 border-t border-zinc-200/60 dark:border-zinc-800/80 pt-2 text-xs">
                    {groupedWOsByDate.length === 0 ? (
                      <div className="p-4 text-center text-zinc-400 text-xs">No work orders matching date filter.</div>
                    ) : (
                      groupedWOsByDate.map((grp) => {
                        const itemsToShow =
                          dateQueueTab === "unreleased"
                            ? grp.unreleasedItems
                            : dateQueueTab === "released"
                            ? grp.releasedItems
                            : grp.items;

                        if (itemsToShow.length === 0 && dateQueueTab !== "all") {
                          return null;
                        }

                        return (
                          <div key={grp.dateStr} className="rounded-xl border border-zinc-200/80 dark:border-zinc-800 bg-white dark:bg-zinc-900 overflow-hidden shadow-2xs">
                            {/* Date Group Header */}
                            <div className="bg-zinc-100/80 dark:bg-zinc-800/80 px-3 py-1.5 flex flex-wrap items-center justify-between gap-1 text-[11px] font-bold text-zinc-800 dark:text-zinc-200">
                              <span className="flex items-center gap-1.5 font-mono">
                                <Calendar className="h-3.5 w-3.5 text-blue-500 shrink-0" />
                                {grp.label}
                              </span>
                              <div className="flex items-center gap-2">
                                <span className="rounded bg-amber-100 dark:bg-amber-950/80 text-amber-800 dark:text-amber-300 font-semibold px-1.5 py-0.2 text-[9px]">
                                  {grp.unreleasedItems.length} Not Released
                                </span>
                                <span className="rounded bg-emerald-100 dark:bg-emerald-950/80 text-emerald-800 dark:text-emerald-300 font-semibold px-1.5 py-0.2 text-[9px]">
                                  {grp.releasedItems.length} Released
                                </span>
                              </div>
                            </div>

                            {/* WOs for this date */}
                            <div className="divide-y divide-zinc-100 dark:divide-zinc-800 text-[11px]">
                              {itemsToShow.length === 0 ? (
                                <div className="p-3 text-center text-[10px] text-zinc-400 italic">
                                  {dateQueueTab === "unreleased"
                                    ? "All work orders for this date are already released!"
                                    : "No work orders released yet for this date."}
                                </div>
                              ) : (
                                itemsToShow.map((w) => (
                                  <div
                                    key={w.wo_number}
                                    className={`p-2.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 transition-colors hover:bg-blue-50/40 dark:hover:bg-blue-950/30 ${
                                      selectedWO === w.wo_number
                                        ? "bg-blue-50/80 dark:bg-blue-950/60 ring-1 ring-blue-500/30"
                                        : ""
                                    }`}
                                  >
                                    <div className="min-w-0 flex-1">
                                      <div className="flex items-center gap-1.5 flex-wrap">
                                        <span className={`font-mono font-black text-xs ${selectedWO === w.wo_number ? "text-blue-700 dark:text-blue-300" : "text-zinc-900 dark:text-zinc-100"}`}>
                                          {w.wo_number}
                                        </span>
                                        {w.is_released ? (
                                          <span className="rounded-md bg-emerald-100 dark:bg-emerald-950/60 px-1.5 py-0.2 text-[9px] font-bold text-emerald-800 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                                            RELEASED {w.release_date ? `(${formatDate(w.release_date)})` : ""}
                                          </span>
                                        ) : (
                                          <span className="rounded-md bg-amber-100 dark:bg-amber-950/60 px-1.5 py-0.2 text-[9px] font-bold text-amber-800 dark:text-amber-300 border border-amber-200 dark:border-amber-800">
                                            NOT RELEASED (PENDING)
                                          </span>
                                        )}
                                        {w.heat_number && (
                                          <span className="rounded bg-orange-100 dark:bg-orange-950/60 px-1.5 py-0.2 text-[9px] font-mono font-bold text-orange-700 dark:text-orange-300 flex items-center gap-0.5">
                                            <Flame className="h-2.5 w-2.5" />
                                            {w.heat_number}
                                          </span>
                                        )}
                                        {w.current_stage && (
                                          <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.2 text-[9px] font-mono text-zinc-600 dark:text-zinc-400">
                                            Stage: {w.current_stage}
                                          </span>
                                        )}
                                      </div>
                                      <div className="text-[11px] text-zinc-500 truncate mt-1">
                                        <span className="font-semibold text-zinc-800 dark:text-zinc-200">{w.part_number}</span>
                                        {w.part_name ? ` • ${w.part_name}` : ""}
                                        {w.customer_code ? ` • ${w.customer_code}` : w.customer_name ? ` • ${w.customer_name}` : ""}
                                        {w.customer_po ? ` • PO: ${w.customer_po}` : ""}
                                      </div>
                                    </div>
                                    <div className="flex items-center gap-2.5 shrink-0 self-end sm:self-center">
                                      <div className="text-right">
                                        <div className="font-mono font-bold text-emerald-600 text-xs">{w.physical_wo_qty} pcs</div>
                                        {w.delivery_date && (
                                          <div className="text-[9px] text-amber-600 dark:text-amber-400 font-mono">
                                            Due: {formatDate(w.delivery_date)}
                                          </div>
                                        )}
                                      </div>
                                      <button
                                        type="button"
                                        onClick={() => {
                                          applyWO(w);
                                          setSearchQuery(w.wo_number);
                                        }}
                                        className={`px-3 py-1.5 rounded-lg text-xs font-bold cursor-pointer transition-all shadow-xs flex items-center gap-1 ${
                                          selectedWO === w.wo_number
                                            ? "bg-blue-600 text-white ring-2 ring-blue-600/40"
                                            : !w.is_released
                                            ? "bg-amber-600 text-white hover:bg-amber-500"
                                            : "bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 hover:bg-blue-50 hover:text-blue-600"
                                        }`}
                                      >
                                        <span>
                                          {selectedWO === w.wo_number
                                            ? "Selected ✓"
                                            : !w.is_released
                                            ? "Select for Release →"
                                            : "Select / View"}
                                        </span>
                                      </button>
                                    </div>
                                  </div>
                                ))
                              )}
                            </div>
                          </div>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Released Physical WO Quantity (pcs) *
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  value={physicalQty}
                  onChange={(e) => setPhysicalQty(e.target.value === "" ? "" : Number(e.target.value))}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                  <span>Heat Number / Cast Batch #</span>
                  <span className="text-[10px] text-zinc-400 font-normal">Melt / continuous casting source</span>
                </label>
                <div className="relative mt-1.5">
                  <Flame className="absolute left-3 top-2.5 h-3.5 w-3.5 text-orange-500 pointer-events-none" />
                  <input
                    type="text"
                    value={heatNumber}
                    onChange={(e) => setHeatNumber(e.target.value)}
                    placeholder="e.g. HN-2026-088, CAST-42..."
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-9 pr-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-orange-500 focus:ring-1 focus:ring-orange-500"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Material Source & Casting Process Selector */}
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300 block mb-2">
              Material Source &amp; Casting Process *
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label
                className={`flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer transition-all ${
                  castingProcess === "CENTRIFUGAL"
                    ? "border-blue-600 bg-blue-50/40 dark:bg-blue-950/30 shadow-sm ring-1 ring-blue-600"
                    : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/40 dark:bg-zinc-950/40 hover:border-zinc-300"
                }`}
              >
                <input
                  type="radio"
                  name="castingProcess"
                  value="CENTRIFUGAL"
                  checked={castingProcess === "CENTRIFUGAL"}
                  onChange={() => {
                    setCastingProcess("CENTRIFUGAL");
                    if (!selectedStages.includes("F1")) {
                      setSelectedStages(["F1", ...selectedStages.filter((s) => s !== "F1")]);
                    }
                  }}
                  className="mt-0.5 text-blue-600 focus:ring-blue-500"
                />
                <div>
                  <div className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                    <span>Centrifugal Casting / Melt</span>
                    <span className="rounded bg-blue-100 dark:bg-blue-950/60 px-1.5 py-0.2 text-[9px] font-bold text-blue-800 dark:text-blue-300">
                      F1 Route
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Traditional melt and centrifugal casting on shop floor. F1 stage is required.
                  </div>
                </div>
              </label>

              <label
                className={`flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer transition-all ${
                  castingProcess === "CONTINUOUS"
                    ? "border-amber-600 bg-amber-50/40 dark:bg-amber-950/30 shadow-sm ring-1 ring-amber-600"
                    : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/40 dark:bg-zinc-950/40 hover:border-zinc-300"
                }`}
              >
                <input
                  type="radio"
                  name="castingProcess"
                  value="CONTINUOUS"
                  checked={castingProcess === "CONTINUOUS"}
                  onChange={() => {
                    setCastingProcess("CONTINUOUS");
                    setSelectedStages(selectedStages.filter((s) => s !== "F1"));
                  }}
                  className="mt-0.5 text-amber-600 focus:ring-amber-500"
                />
                <div>
                  <div className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                    <span>Continuous Casting</span>
                    <span className="rounded bg-amber-100 dark:bg-amber-950/60 px-1.5 py-0.2 text-[9px] font-bold text-amber-800 dark:text-amber-300">
                      Bypasses F1
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Pre-cast continuous material. Bypasses F1 melt; blanks issued from cutting.
                  </div>
                </div>
              </label>
            </div>
          </div>

          {/* Route Stages Checklist */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                Declared Stage Routing (Select stages this WO will physically move through):
              </label>
              {castingProcess === "CONTINUOUS" && (
                <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">
                  F1 is bypassed for Continuous Casting
                </span>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {ALL_POSSIBLE_STAGES.map((stg) => {
                const isF1 = stg.code === "F1";
                const isBypassedF1 = isF1 && castingProcess === "CONTINUOUS";
                const isChecked = selectedStages.includes(stg.code);
                return (
                  <button
                    type="button"
                    key={stg.code}
                    disabled={isBypassedF1}
                    onClick={() => toggleStage(stg.code)}
                    className={`flex items-center justify-between p-3 rounded-xl border text-left transition-all ${
                      isBypassedF1
                        ? "border-zinc-200 dark:border-zinc-800/50 bg-zinc-100/50 dark:bg-zinc-900/30 text-zinc-400 cursor-not-allowed opacity-60"
                        : isChecked
                        ? "border-blue-500 bg-blue-50/60 dark:bg-blue-950/40 text-blue-900 dark:text-blue-100"
                        : "border-zinc-200 dark:border-zinc-800 text-zinc-400 bg-zinc-50/40 dark:bg-zinc-950/40"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <div
                        className={`flex h-5 w-5 items-center justify-center rounded-md border ${
                          isBypassedF1
                            ? "border-zinc-300 dark:border-zinc-700 bg-zinc-200 dark:bg-zinc-800"
                            : isChecked
                            ? "border-blue-600 bg-blue-600 text-white"
                            : "border-zinc-300 dark:border-zinc-700"
                        }`}
                      >
                        {isChecked && !isBypassedF1 && <Check className="h-3.5 w-3.5" />}
                      </div>
                      <div>
                        <span className="text-xs font-bold">{stg.name}</span>
                        {isBypassedF1 && (
                          <div className="text-[10px] text-amber-600 dark:text-amber-400 font-normal">
                            Bypassed for Continuous Casting
                          </div>
                        )}
                      </div>
                    </div>
                    {stg.code === "DISPATCH" && (
                      <span className="text-[10px] text-zinc-400 font-medium">Terminal</span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
              Release Remarks / Planner Instructions
            </label>
            <input
              type="text"
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>

          {selectedWODetail && (selectedWODetail.status === "dispatched" || selectedWODetail.current_stage === "Completed") && (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-400 font-semibold flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>Work Order {selectedWO} is completely dispatched. It cannot be re-released or routed.</span>
            </div>
          )}

          <div className="pt-2">
            <button
              type="submit"
              disabled={loading || !physicalQty || selectedStages.length === 0 || !selectedWO || selectedWODetail?.status === "dispatched" || selectedWODetail?.current_stage === "Completed"}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              <Factory className="h-4 w-4" />
              <span>{loading ? "Releasing to Floor..." : `Release Work Order ${selectedWO || ""}`}</span>
            </button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}

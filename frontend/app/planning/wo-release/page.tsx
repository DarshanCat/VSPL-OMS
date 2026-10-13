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
  ChevronDown
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import {
  getWorkOrders,
  releaseWorkOrder,
  engineeringReleaseWorkOrder,
  manufacturingReleaseWorkOrder,
  WorkOrderListItem
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
    async (term: string) => {
      setSearching(true);
      setError("");
      try {
        const queryTerm = term.trim();
        const data = await getWorkOrders({
          search: queryTerm || undefined,
          limit: 100,
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
    [applyWO, selectedWO]
  );

  const handleInputChange = (val: string) => {
    setSearchQuery(val);
    setIsDropdownOpen(true);
    if (searchTimeoutRef.current) {
      clearTimeout(searchTimeoutRef.current);
    }
    searchTimeoutRef.current = setTimeout(() => {
      handleSearch(val);
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
      getWorkOrders({ search: urlWo.trim(), limit: 50 })
        .then((data) => {
          const list = Array.isArray(data) ? data : [];
          const found = list.find((w) => w.wo_number.toUpperCase() === urlWo.trim().toUpperCase()) || list[0];
          if (found) {
            setWos(list);
            applyWO(found);
          } else {
            // Fallback load default list
            getWorkOrders({ limit: 100 }).then((fallbackData) => {
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
      getWorkOrders({ limit: 100 })
        .then((data) => {
          const list = Array.isArray(data) ? data : [];
          setWos(list);
          if (list.length > 0) {
            const candidate = list.find((w) => w.status === "planned" || w.status === "in_production") || list[0];
            applyWO(candidate);
          }
        })
        .catch(() => {})
        .finally(() => {
          setSearching(false);
        });
    }
  }, [urlWo, applyWO]);

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
        remarks: remarks,
      });

      setSuccessResult(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to release Work Order.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-3xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Planning &amp; WO Release
            </span>
            <span className="text-xs text-zinc-400">Dynamic Stage Routing</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Work Order Release &amp; Custom Routing
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Planner declares physical released quantity and sets custom stage routing (skipping non-applicable gates).
          </p>
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
          <div className="rounded-2xl border border-blue-500/30 bg-blue-50/20 dark:bg-blue-950/20 p-4 shadow-sm space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-blue-200/40 dark:border-blue-800/40 pb-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-base font-extrabold text-blue-700 dark:text-blue-300">
                  {selectedWODetail.wo_number}
                </span>
                <Badge variant={getRAGVariant(selectedWODetail.status)} size="sm">
                  {selectedWODetail.status.replace(/_/g, " ").toUpperCase()}
                </Badge>
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
                  Select Work Order *
                </label>
                {searching && (
                  <span className="flex items-center gap-1 text-[10px] text-blue-600 font-medium">
                    <RefreshCw className="h-2.5 w-2.5 animate-spin" /> Searching...
                  </span>
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
                    placeholder="Search WO ID (e.g. 17608), Part #, Customer, PO..."
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-9 pr-16 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  />
                  <div className="absolute right-2 top-2 flex items-center gap-1">
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => {
                          setSearchQuery("");
                          handleSearch("");
                          searchInputRef.current?.focus();
                        }}
                        className="p-0.5 rounded text-zinc-400 hover:text-zinc-600"
                        title="Clear search"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                      className="p-0.5 rounded text-zinc-400 hover:text-zinc-600"
                      title="Toggle options list"
                    >
                      <ChevronDown className={`h-3.5 w-3.5 transition-transform ${isDropdownOpen ? "rotate-180" : ""}`} />
                    </button>
                  </div>
                </div>

                {/* Dropdown Results List */}
                {isDropdownOpen && (
                  <div className="absolute z-30 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-2xl">
                    {wos.length === 0 ? (
                      <div className="p-4 text-center text-xs text-zinc-400">
                        {searching ? "Searching work orders..." : `No work orders found matching "${searchQuery}"`}
                      </div>
                    ) : (
                      <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        {wos.map((w) => (
                          <div
                            key={w.wo_number}
                            onClick={() => {
                              applyWO(w);
                              setSearchQuery(w.wo_number);
                              setIsDropdownOpen(false);
                            }}
                            className={`p-3 cursor-pointer transition-colors hover:bg-blue-50/70 dark:hover:bg-blue-950/40 flex items-center justify-between gap-3 text-xs ${
                              selectedWO === w.wo_number ? "bg-blue-50 dark:bg-blue-950/60" : ""
                            }`}
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className={`font-mono font-extrabold ${selectedWO === w.wo_number ? "text-blue-600 dark:text-blue-400" : "text-zinc-900 dark:text-zinc-100"}`}>
                                  {w.wo_number}
                                </span>
                                <Badge variant={getRAGVariant(w.status)} size="sm">
                                  {w.status.replace(/_/g, " ").toUpperCase()}
                                </Badge>
                                {w.current_stage && (
                                  <span className="rounded bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.2 text-[10px] font-mono text-zinc-600 dark:text-zinc-400">
                                    {w.current_stage}
                                  </span>
                                )}
                              </div>
                              <div className="text-[11px] text-zinc-500 truncate mt-0.5">
                                <span className="font-semibold text-zinc-700 dark:text-zinc-300">{w.part_number}</span>
                                {w.customer_code ? ` • ${w.customer_code}` : w.customer_name ? ` • ${w.customer_name}` : ""}
                                {w.customer_po ? ` • PO: ${w.customer_po}` : ""}
                              </div>
                            </div>
                            <div className="text-right whitespace-nowrap">
                              <span className="font-mono font-bold text-emerald-600">{w.physical_wo_qty} pcs</span>
                              {w.oar_number && <div className="text-[10px] text-zinc-400 font-mono">OAR: {w.oar_number}</div>}
                            </div>
                          </div>
                        ))}
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
                  <span className="font-mono font-bold text-emerald-600 shrink-0 ml-2">{selectedWODetail.physical_wo_qty} pcs</span>
                </div>
              )}
            </div>

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

          <div className="pt-2">
            <button
              type="submit"
              disabled={loading || !physicalQty || selectedStages.length === 0 || !selectedWO}
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

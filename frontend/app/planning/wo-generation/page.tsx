"use client";
import React, { useState, useEffect, Suspense, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Layers,
  Search,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Clock,
  RefreshCw,
  Plus,
  FileSpreadsheet,
  Check,
  Send,
  Boxes,
  Split,
  ChevronRight,
  Edit2,
  X,
  Pencil,
  Calendar,
  CalendarClock
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getOarList,
  OARListItem,
  getWorkOrders,
  WorkOrderListItem,
  getNextSequences,
  createWorkOrder,
  WorkOrderCreatePayload,
  WorkOrderCreateResult,
  updateWorkOrder,
  WorkOrderUpdatePayload,
  updateOAR
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

const DEFAULT_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];

export default function WOGenerationPage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="max-w-7xl mx-auto py-12 text-center text-xs text-zinc-500 font-mono">
            Loading Work Order Generation...
          </div>
        </AppShell>
      }
    >
      <WOGenerationContent />
    </Suspense>
  );
}

function WOGenerationContent() {
  const searchParams = useSearchParams();
  const urlOar = searchParams.get("oar") || "";

  // Data states
  const [oars, setOars] = useState<OARListItem[]>([]);
  const [recentWOs, setRecentWOs] = useState<WorkOrderListItem[]>([]);
  const [loadingOars, setLoadingOars] = useState(false);
  const [loadingWOs, setLoadingWOs] = useState(false);

  // Filters
  const [searchOar, setSearchOar] = useState(urlOar);
  const [filterPendingOnly, setFilterPendingOnly] = useState(true);
  const [woTableTab, setWoTableTab] = useState<"all" | "unreleased">("all");

  // Form states
  const [selectedOar, setSelectedOar] = useState<OARListItem | null>(null);
  const [woNumber, setWoNumber] = useState("");
  const [woQty, setWoQty] = useState<number | "">("");
  const [woDate, setWoDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [targetDate, setTargetDate] = useState("");
  const [castingProcess, setCastingProcess] = useState<"CENTRIFUGAL" | "CONTINUOUS">("CENTRIFUGAL");
  const [routeStages, setRouteStages] = useState<string[]>(DEFAULT_STAGES);
  const [remarks, setRemarks] = useState("Planned by Production Planning department.");

  // Divide Quantity State
  const [splitMode, setSplitMode] = useState<"single" | "auto" | "manual">("single");
  const [batchSize, setBatchSize] = useState<number | "">(10);
  const [manualQtys, setManualQtys] = useState<string[]>(["", ""]);
  const [allowOverrun, setAllowOverrun] = useState(false);

  // Submit states
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [editingWO, setEditingWO] = useState<WorkOrderListItem | null>(null);
  const [editSuccessMsg, setEditSuccessMsg] = useState("");
  const [editingCommitmentOar, setEditingCommitmentOar] = useState<OARListItem | null>(null);
  const [commitmentSuccessMsg, setCommitmentSuccessMsg] = useState("");
  const [successResult, setSuccessResult] = useState<WorkOrderCreateResult | null>(null);

  // Load next WO number sequence
  const loadNextWoSequence = async () => {
    try {
      const seq = await getNextSequences();
      setWoNumber(seq.next_wo_number);
    } catch {
      // ignore
    }
  };

  // Load OARs
  const loadOars = useCallback(async () => {
    setLoadingOars(true);
    try {
      const data = await getOarList({ limit: 1000 });
      setOars(data);
      if (urlOar) {
        const found = data.find((o) => o.oar_number.toLowerCase() === urlOar.toLowerCase());
        if (found) {
          handleSelectOar(found);
        }
      }
    } catch {
      setOars([]);
    } finally {
      setLoadingOars(false);
    }
  }, [urlOar]);

  // Load Created Work Orders
  const loadRecentWOs = async () => {
    setLoadingWOs(true);
    try {
      const data = await getWorkOrders({ limit: 50, sort_by: "created_at_desc" });
      setRecentWOs(data);
    } catch {
      setRecentWOs([]);
    } finally {
      setLoadingWOs(false);
    }
  };

  useEffect(() => {
    loadOars();
    loadRecentWOs();
    loadNextWoSequence();
  }, [loadOars]);

  const handleSelectOar = (oar: OARListItem) => {
    setSelectedOar(oar);
    setSearchOar(oar.oar_number);
    const initialQty = oar.remaining_qty > 0 ? oar.remaining_qty : 0;
    setWoQty(initialQty || "");
    setManualQtys([String(Math.ceil((initialQty || 10) / 2)), String(Math.floor((initialQty || 10) / 2))]);
    // Rule: Same OAR should NOT repeat WO generation. Never auto-enable overrun.
    setAllowOverrun(false);
    const effDate = oar.effective_commitment_date || oar.revised_commitment_date || oar.commitment_date || oar.delivery_date;
    if (effDate) {
      setTargetDate(effDate.slice(0, 10));
    }
    setError("");
    setSuccessResult(null);
    loadNextWoSequence();
    document.getElementById("wo-generator-card")?.scrollIntoView({ behavior: "smooth" });
  };

  const handleCommitmentDateSuccess = (updatedOar: OARListItem) => {
    setEditingCommitmentOar(null);
    const eff = updatedOar.effective_commitment_date || updatedOar.revised_commitment_date || updatedOar.commitment_date;
    setCommitmentSuccessMsg(`Commitment Date for ${updatedOar.oar_number} updated to ${formatDate(eff)}!`);
    setOars((prev) => prev.map((o) => (o.oar_number === updatedOar.oar_number ? { ...o, ...updatedOar } : o)));
    if (selectedOar?.oar_number === updatedOar.oar_number) {
      setSelectedOar((prev) => (prev ? { ...prev, ...updatedOar } : updatedOar));
      const effDate = updatedOar.effective_commitment_date || updatedOar.revised_commitment_date || updatedOar.commitment_date || updatedOar.delivery_date;
      if (effDate) {
        setTargetDate(effDate.slice(0, 10));
      }
    }
    setTimeout(() => setCommitmentSuccessMsg(""), 5000);
  };

  const handleToggleStage = (stage: string) => {
    if (routeStages.includes(stage)) {
      if (routeStages.length === 1) return;
      setRouteStages(routeStages.filter((s) => s !== stage));
    } else {
      setRouteStages([...routeStages, stage]);
    }
  };

  // Rules: Same WO ID and Same OAR must never repeat
  const isDuplicateWoNumber = React.useMemo(() => {
    if (!woNumber.trim()) return false;
    const clean = woNumber.trim().toUpperCase().replace(/\s+/g, "-");
    return recentWOs.some((w) => w.wo_number.toUpperCase().replace(/\s+/g, "-") === clean);
  }, [woNumber, recentWOs]);

  const isOarFullyPlanned = selectedOar ? selectedOar.remaining_qty <= 0 : false;

  // Manual split helpers
  const updateManualQty = (idx: number, val: string) => {
    const updated = [...manualQtys];
    updated[idx] = val;
    setManualQtys(updated);
  };

  const addManualRow = () => {
    setManualQtys([...manualQtys, ""]);
  };

  const removeManualRow = (idx: number) => {
    if (manualQtys.length <= 1) return;
    setManualQtys(manualQtys.filter((_, i) => i !== idx));
  };

  // Calculations for auto & manual split
  const parsedManualQtys = manualQtys.map((v) => Number(v) || 0);
  const manualAllocated = parsedManualQtys.reduce((sum, v) => sum + v, 0);
  const totalBaseQty = Number(woQty) || 0;
  const manualRemaining = totalBaseQty - manualAllocated;
  const manualComplete = parsedManualQtys.length > 0 && parsedManualQtys.every((v) => v > 0) && manualRemaining === 0;

  // Auto split calculation
  const autoSplitBatches: number[] = [];
  if (splitMode === "auto" && totalBaseQty > 0 && Number(batchSize) > 0) {
    let rem = totalBaseQty;
    const bSize = Number(batchSize);
    while (rem > 0) {
      const take = Math.min(rem, bSize);
      autoSplitBatches.push(take);
      rem -= take;
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedOar) {
      setError("Please select a parent OAR first.");
      return;
    }

    let quantitiesToSubmit: number[] | undefined = undefined;
    let totalQtyToSubmit = 0;

    if (splitMode === "single") {
      const q = Number(woQty);
      if (!q || q <= 0) {
        setError("Please enter a valid positive Work Order quantity.");
        return;
      }
      totalQtyToSubmit = q;
    } else if (splitMode === "auto") {
      if (!autoSplitBatches || autoSplitBatches.length === 0) {
        setError("Please enter a valid total quantity and batch size.");
        return;
      }
      quantitiesToSubmit = autoSplitBatches;
      totalQtyToSubmit = autoSplitBatches.reduce((sum, v) => sum + v, 0);
    } else if (splitMode === "manual") {
      if (!manualComplete) {
        setError(`Manual split is incomplete: Allocated (${manualAllocated}) must equal target quantity (${totalBaseQty}).`);
        return;
      }
      quantitiesToSubmit = parsedManualQtys;
      totalQtyToSubmit = manualAllocated;
    }

    if (isDuplicateWoNumber) {
      setError(`Work Order ID "${woNumber.trim()}" already exists in the system. The same WO ID cannot be repeated.`);
      return;
    }

    if (isOarFullyPlanned && !allowOverrun) {
      setError(`OAR ${selectedOar.oar_number} is already fully planned (${selectedOar.allocated_qty}/${selectedOar.oar_qty} pcs). The same OAR cannot repeat Work Order generation without explicit overrun authorization.`);
      return;
    }

    // Check remaining unless allowOverrun is checked
    if (!allowOverrun && selectedOar.remaining_qty < totalQtyToSubmit) {
      setError(
        `Requested quantity (${totalQtyToSubmit} pcs) exceeds the remaining unallocated OAR balance (${selectedOar.remaining_qty} pcs). Check "Allow Overrun / Additional Batch" below if creating extra or rework WOs.`
      );
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const payload: WorkOrderCreatePayload = {
        oar_number: selectedOar.oar_number,
        wo_number: woNumber.trim() || undefined,
        physical_wo_qty: totalQtyToSubmit,
        wo_quantities: quantitiesToSubmit,
        allow_overrun: allowOverrun,
        wo_date: woDate || undefined,
        target_date: targetDate || undefined,
        casting_process: castingProcess,
        route_stages: routeStages,
        remarks: remarks.trim() || undefined,
      };

      const res = await createWorkOrder(payload);
      setSuccessResult(res);
      loadOars();
      loadRecentWOs();
      loadNextWoSequence();
      // Adjust remaining on selected OAR in memory
      setSelectedOar((prev) =>
        prev
          ? {
              ...prev,
              allocated_qty: prev.allocated_qty + totalQtyToSubmit,
              remaining_qty: Math.max(0, prev.remaining_qty - totalQtyToSubmit),
            }
          : null
      );
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to generate Work Order(s).");
    } finally {
      setSubmitting(false);
    }
  };

  // Filtered OARs
  const filteredOars = oars.filter((o) => {
    if (filterPendingOnly && o.remaining_qty <= 0) return false;
    if (!searchOar.trim()) return true;
    const q = searchOar.toLowerCase();
    return (
      o.oar_number.toLowerCase().includes(q) ||
      o.customer_name.toLowerCase().includes(q) ||
      o.customer_code.toLowerCase().includes(q) ||
      (o.customer_po && o.customer_po.toLowerCase().includes(q)) ||
      o.part_number.toLowerCase().includes(q)
    );
  });

  const displayedWOs = recentWOs.filter((wo) => {
    if (woTableTab === "unreleased") return !wo.is_released;
    return true;
  });

  return (
    <AppShell>
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Planning Department
              </span>
              <span className="text-xs text-zinc-400">Step 1: WO ID Generation → Step 2: WO ID Release</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Work Order ID Generation &amp; Quantity Split
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Select created Sales OARs, divide quantities across sequential Work Order IDs, and proceed to Step 2 (WO ID Release).
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/orders/intake"
              className="px-3 py-2 text-xs font-semibold rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
            >
              Sales OAR Intake
            </Link>
            <Link
              href="/planning/wo-release"
              className="px-3.5 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-700 transition flex items-center gap-1.5 shadow-sm"
            >
              <span>Step 2: WO ID Release</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>

        {/* Section 1: Created OARs Queue */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <FileSpreadsheet className="h-4 w-4 text-emerald-600" />
                Created OARs (Sales Order Acceptance Receipts)
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Confirmed OARs created by Sales. Select an OAR below to divide quantity and generate Work Order IDs.
              </p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <div className="flex items-center rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden text-xs">
                <button
                  type="button"
                  onClick={() => setFilterPendingOnly(true)}
                  className={`px-3 py-1.5 font-bold transition ${
                    filterPendingOnly
                      ? "bg-emerald-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                  }`}
                >
                  Awaiting Work Orders
                </button>
                <button
                  type="button"
                  onClick={() => setFilterPendingOnly(false)}
                  className={`px-3 py-1.5 font-bold transition ${
                    !filterPendingOnly
                      ? "bg-emerald-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                  }`}
                >
                  All OARs
                </button>
              </div>

              <div className="relative">
                <Search className="h-3.5 w-3.5 text-zinc-400 absolute left-2.5 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={searchOar}
                  onChange={(e) => setSearchOar(e.target.value)}
                  placeholder="Filter OAR, customer, part..."
                  className="pl-8 pr-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 focus:outline-none w-48 sm:w-60"
                />
              </div>

              <button
                type="button"
                onClick={loadOars}
                disabled={loadingOars}
                className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                title="Refresh OARs"
              >
                <RefreshCw className={`h-4 w-4 ${loadingOars ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          {loadingOars ? (
            <p className="text-xs text-zinc-400 py-4 text-center">Loading OAR records...</p>
          ) : filteredOars.length === 0 ? (
            <div className="py-6 text-center text-xs text-zinc-400 bg-zinc-50 dark:bg-zinc-950 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
              No OARs match your criteria. You can create an OAR in{" "}
              <Link href="/orders/intake" className="text-blue-600 font-bold hover:underline">
                Order Intake
              </Link>
              .
            </div>
          ) : (
            <div className="overflow-x-auto max-h-72 overflow-y-auto border border-zinc-200 dark:border-zinc-800 rounded-xl">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider sticky top-0">
                  <tr>
                    <th className="p-3">OAR Reference</th>
                    <th className="p-3">Customer &amp; PO</th>
                    <th className="p-3">Part Number</th>
                    <th className="p-3 text-right">OAR Qty</th>
                    <th className="p-3 text-right">Allocated</th>
                    <th className="p-3 text-right">Remaining to Plan</th>
                    <th className="p-3">Delivery Date</th>
                    <th className="p-3">Commitment Date</th>
                    <th className="p-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {filteredOars.map((o) => {
                    const isSelected = selectedOar?.order_id === o.order_id;
                    return (
                      <tr
                        key={o.order_id || o.oar_number}
                        className={`transition-colors ${
                          isSelected
                            ? "bg-emerald-50 dark:bg-emerald-950/40 border-l-4 border-l-emerald-600"
                            : "hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                        }`}
                      >
                        <td className="p-3">
                          <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400 block">
                            {o.oar_number}
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">
                            {formatDate(o.oar_date || o.created_at)}
                          </span>
                        </td>
                        <td className="p-3">
                          <span className="font-semibold text-zinc-800 dark:text-zinc-200 block">
                            {o.customer_name}
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">
                            PO: {o.customer_po || "—"}
                          </span>
                        </td>
                        <td className="p-3">
                          <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                            {o.customer_part_number || o.part_number}
                          </span>
                          {o.customer_part_number && o.customer_part_number !== o.part_number && (
                            <span className="text-[10px] text-zinc-400 font-mono">
                              Internal: {o.part_number}
                            </span>
                          )}
                        </td>
                        <td className="p-3 text-right font-mono font-bold">{o.oar_qty}</td>
                        <td className="p-3 text-right font-mono text-zinc-500">{o.allocated_qty}</td>
                        <td className="p-3 text-right font-mono">
                          {o.remaining_qty > 0 ? (
                            <span className="inline-block px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-700 dark:text-amber-300 font-bold">
                              {o.remaining_qty} pcs
                            </span>
                          ) : (
                            <span className="text-zinc-400">0 (Fully Planned)</span>
                          )}
                        </td>
                        <td className="p-3 text-zinc-500">{formatDate(o.delivery_date)}</td>
                        <td className="p-3">
                          <div className="flex items-center gap-1.5">
                            {o.revised_commitment_date ? (
                              <div>
                                <div className="flex items-center gap-1">
                                  <span className="font-bold text-amber-600 dark:text-amber-400 font-mono">
                                    {formatDate(o.revised_commitment_date)}
                                  </span>
                                  <span className="px-1.5 py-0.2 text-[9px] font-bold rounded bg-amber-100 dark:bg-amber-950/70 text-amber-700 dark:text-amber-300 border border-amber-300 dark:border-amber-800">
                                    Rev #{o.commitment_date_revision_count || 1}
                                  </span>
                                </div>
                                {o.commitment_date && (
                                  <span className="text-[10px] text-zinc-400 line-through block font-mono">
                                    Orig: {formatDate(o.commitment_date)}
                                  </span>
                                )}
                              </div>
                            ) : o.commitment_date ? (
                              <span className="font-bold text-blue-600 dark:text-blue-400 font-mono">
                                {formatDate(o.commitment_date)}
                              </span>
                            ) : (
                              <span className="text-zinc-400 italic text-[11px]">—</span>
                            )}
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setEditingCommitmentOar(o);
                              }}
                              className="p-1 rounded hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition"
                              title={o.commitment_date || o.revised_commitment_date ? "Change / Revise Commitment Date" : "Set Commitment Date"}
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                          </div>
                        </td>
                        <td className="p-3 text-right">
                          <button
                            type="button"
                            onClick={() => handleSelectOar(o)}
                            className={`px-3 py-1.5 text-xs font-bold rounded-lg transition cursor-pointer ${
                              isSelected
                                ? "bg-emerald-700 text-white"
                                : "bg-emerald-600 text-white hover:bg-emerald-700"
                            }`}
                          >
                            {isSelected ? "Selected" : "Select & Divide Qty"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Section 2: Work Order Creation Form */}
        <div
          id="wo-generator-card"
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-zinc-100 dark:border-zinc-800">
            <div>
              <div className="flex items-center gap-2">
                <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                  Step 1: WO ID Generation
                </span>
                <span className="text-xs text-zinc-400">→ Step 2: WO ID Release</span>
              </div>
              <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50 mt-1">
                Generate Work Order IDs
              </h3>
              <p className="text-xs text-zinc-400">
                Divide the quantity into one or multiple Work Orders, assign IDs, and proceed to Step 2 (Release).
              </p>
            </div>
            {selectedOar && (
              <span className="px-3 py-1 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800 text-xs font-bold font-mono self-start sm:self-auto">
                Parent: {selectedOar.oar_number}
              </span>
            )}
          </div>

          {error && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
              {error}
            </div>
          )}

          {/* Success Banner: Step 1 Complete -> Go to Step 2 Release */}
          {successResult && (
            <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5 space-y-4">
              <div className="flex items-start gap-3">
                <CheckCircle2 className="h-6 w-6 text-emerald-500 shrink-0 mt-0.5" />
                <div>
                  <h4 className="text-base font-bold text-emerald-800 dark:text-emerald-300">
                    Step 1 Complete: {successResult.wos_created?.length || 1} Work Order ID(s) Generated!
                  </h4>
                  <p className="text-xs text-emerald-600 dark:text-emerald-400 mt-0.5">
                    Parent OAR: <strong>{successResult.oar_number}</strong> | Part: {successResult.part_number} | Total Qty: {successResult.physical_wo_qty} pcs | Status: <strong>AWAITING RELEASE (UNRELEASED)</strong>
                  </p>
                </div>
              </div>

              {/* List of Generated WO IDs */}
              <div className="rounded-xl bg-white dark:bg-zinc-900 p-4 border border-zinc-200 dark:border-zinc-800 space-y-2">
                <span className="text-xs font-bold text-zinc-800 dark:text-zinc-200 block">
                  Generated Work Orders (Created &amp; Unreleased):
                </span>
                <div className="flex flex-wrap gap-2">
                  {(successResult.wos_created || [successResult.wo_number]).map((wo, idx) => (
                    <div
                      key={wo}
                      className="inline-flex items-center gap-2 rounded-lg bg-blue-50 dark:bg-blue-950/60 px-3 py-1.5 font-mono text-xs font-bold text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800"
                    >
                      <span>{wo}</span>
                      {successResult.wo_quantities && successResult.wo_quantities[idx] && (
                        <span className="text-zinc-500 font-semibold">
                          ({successResult.wo_quantities[idx]} pcs)
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => {
                          const found = recentWOs.find((w) => w.wo_number === wo);
                          if (found) {
                            setEditingWO(found);
                          } else {
                            loadRecentWOs().then(() => {
                              const f = recentWOs.find((w) => w.wo_number === wo);
                              if (f) setEditingWO(f);
                            });
                          }
                        }}
                        className="ml-1 px-2 py-0.5 rounded border border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 text-[10px] font-bold hover:bg-blue-100 dark:hover:bg-blue-900 transition flex items-center gap-1"
                      >
                        <Edit2 className="h-2.5 w-2.5" />
                        <span>Edit</span>
                      </button>
                      <Link
                        href={`/planning/wo-release?wo=${encodeURIComponent(wo)}`}
                        className="ml-1 px-2 py-0.5 rounded bg-blue-600 text-white text-[10px] font-bold hover:bg-blue-700 transition"
                      >
                        Release Now
                      </Link>
                    </div>
                  ))}
                </div>
              </div>

              {/* Step 2 CTA */}
              <div className="rounded-xl bg-blue-50/70 dark:bg-blue-950/40 p-4 border border-blue-200 dark:border-blue-900/50 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                  <span className="font-bold text-blue-900 dark:text-blue-200 text-xs block">
                    Step 2 in Sequence: Release Work Order IDs
                  </span>
                  <p className="text-blue-700 dark:text-blue-300 text-[11px] mt-0.5">
                    Work Order IDs are generated but held in unreleased status. Click below to proceed to WO ID Release.
                  </p>
                </div>
                <Link
                  href={`/planning/wo-release?wo=${encodeURIComponent(successResult.wo_number)}`}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-blue-600 text-white font-bold text-xs hover:bg-blue-700 transition shadow-sm shrink-0"
                >
                  <span>Proceed to Step 2: Release WO #{successResult.wo_number}</span>
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          )}

          {!selectedOar ? (
            <div className="py-8 text-center text-xs text-zinc-400 bg-zinc-50 dark:bg-zinc-950 rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800">
              Please click <strong>"Select &amp; Divide Qty"</strong> on an OAR from the table above to start.
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-5">
              {/* Parent OAR Summary Card */}
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 p-4 border border-zinc-200 dark:border-zinc-800 grid grid-cols-2 sm:grid-cols-5 gap-3 text-xs">
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Parent OAR</span>
                  <span className="font-mono font-bold text-emerald-600 text-sm">{selectedOar.oar_number}</span>
                  <span className="text-[10px] text-zinc-400 block font-mono">PO: {selectedOar.customer_po || "—"}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Customer</span>
                  <span className="font-semibold text-zinc-800 dark:text-zinc-200 block truncate">{selectedOar.customer_name}</span>
                  <span className="text-[10px] text-zinc-400 font-mono">{selectedOar.customer_code}</span>
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Customer Part</span>
                  <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100 block">
                    {selectedOar.customer_part_number || selectedOar.part_number}
                  </span>
                  {selectedOar.customer_part_number && selectedOar.customer_part_number !== selectedOar.part_number && (
                    <span className="text-[10px] text-zinc-400 font-mono">
                      Internal: {selectedOar.part_number}
                    </span>
                  )}
                </div>
                <div>
                  <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Quantities</span>
                  <span className="text-zinc-600 dark:text-zinc-300 block">
                    OAR: <strong>{selectedOar.oar_qty}</strong> | Planned: {selectedOar.allocated_qty}
                  </span>
                  <span className="font-bold text-emerald-600 font-mono">
                    Remaining: {selectedOar.remaining_qty} pcs
                  </span>
                </div>
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-zinc-400 uppercase font-semibold block">Commitment Date</span>
                    <button
                      type="button"
                      onClick={() => setEditingCommitmentOar(selectedOar)}
                      className="text-[10px] text-blue-600 dark:text-blue-400 hover:underline font-bold flex items-center gap-0.5 cursor-pointer"
                    >
                      <Pencil className="h-2.5 w-2.5" /> Edit
                    </button>
                  </div>
                  {selectedOar.revised_commitment_date ? (
                    <div>
                      <span className="font-mono font-bold text-amber-600 dark:text-amber-400 block text-sm">
                        {formatDate(selectedOar.revised_commitment_date)}
                      </span>
                      <span className="text-[10px] text-zinc-400 font-mono block">
                        Rev #{selectedOar.commitment_date_revision_count || 1}
                      </span>
                    </div>
                  ) : selectedOar.commitment_date ? (
                    <div>
                      <span className="font-mono font-bold text-blue-600 dark:text-blue-400 block text-sm">
                        {formatDate(selectedOar.commitment_date)}
                      </span>
                      <span className="text-[10px] text-zinc-400 block font-mono">
                        PO: {formatDate(selectedOar.delivery_date)}
                      </span>
                    </div>
                  ) : (
                    <div>
                      <span className="text-zinc-400 italic block text-xs">Not committed</span>
                      <span className="text-[10px] text-zinc-400 block font-mono">
                        PO: {formatDate(selectedOar.delivery_date)}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Overrun / 0-Remaining Warning Banner */}
              {selectedOar.remaining_qty <= 0 && (
                <div className="rounded-xl border border-amber-200 dark:border-amber-900/50 bg-amber-50/70 dark:bg-amber-950/30 p-3.5 text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="flex items-center gap-2 text-amber-800 dark:text-amber-300 font-medium">
                    <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" />
                    <span>
                      This OAR is already fully planned (0 pcs remaining). Enable overrun to generate an additional/re-work batch.
                    </span>
                  </div>
                  <label className="flex items-center gap-2 cursor-pointer shrink-0 font-bold text-amber-900 dark:text-amber-200">
                    <input
                      type="checkbox"
                      checked={allowOverrun}
                      onChange={(e) => setAllowOverrun(e.target.checked)}
                      className="rounded border-amber-400 text-blue-600 focus:ring-blue-500"
                    />
                    <span>Allow Overrun / Extra Batch</span>
                  </label>
                </div>
              )}

              {/* Work Order Starting ID, Date & Target Date */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div>
                  <div className="flex items-center justify-between">
                    <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                      Work Order ID (Starting ID) *
                    </label>
                    <button
                      type="button"
                      onClick={loadNextWoSequence}
                      className="text-[10px] text-blue-600 hover:underline flex items-center gap-1 cursor-pointer"
                    >
                      <RefreshCw className="h-2.5 w-2.5" /> Next Auto
                    </button>
                  </div>
                  <input
                    type="text"
                    required
                    value={woNumber}
                    onChange={(e) => setWoNumber(e.target.value)}
                    placeholder="e.g. WO-17618 or custom/dumped ID"
                    className={`mt-1.5 w-full rounded-xl border ${
                      isDuplicateWoNumber
                        ? "border-red-500 bg-red-50/50 dark:bg-red-950/20 text-red-700 dark:text-red-400"
                        : "border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                    } px-3 py-2 text-xs font-mono font-bold focus:outline-none`}
                  />
                  {isDuplicateWoNumber ? (
                    <p className="mt-1 text-[11px] font-bold text-red-600 dark:text-red-400 flex items-center gap-1">
                      <AlertTriangle className="h-3 w-3 shrink-0" />
                      Work Order ID &quot;{woNumber.trim()}&quot; already exists! Same WO ID cannot repeat.
                    </p>
                  ) : (
                    <p className="mt-1 text-[10px] text-zinc-400">
                      Auto-sequenced or enter custom/dumped WO ID.
                    </p>
                  )}
                </div>

                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Work Order Date *
                  </label>
                  <input
                    type="date"
                    required
                    value={woDate}
                    onChange={(e) => setWoDate(e.target.value)}
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                    Target / Delivery Date
                  </label>
                  <input
                    type="date"
                    value={targetDate}
                    onChange={(e) => setTargetDate(e.target.value)}
                    className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                </div>
              </div>

              {/* DIVIDE QUANTITY CONTROLS */}
              <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h4 className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                      <Split className="h-3.5 w-3.5 text-blue-600" />
                      Divide Quantity Across Work Orders
                    </h4>
                    <p className="text-[11px] text-zinc-500">
                      Choose how to divide the quantity: single Work Order, auto-split by batch size, or custom manual split.
                    </p>
                  </div>

                  {/* Mode Selector */}
                  <div className="flex rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden text-xs self-start sm:self-auto">
                    <button
                      type="button"
                      onClick={() => setSplitMode("single")}
                      className={`px-3 py-1.5 font-bold transition cursor-pointer ${
                        splitMode === "single"
                          ? "bg-blue-600 text-white"
                          : "bg-white dark:bg-zinc-900 text-zinc-600 hover:bg-zinc-50"
                      }`}
                    >
                      Single WO
                    </button>
                    <button
                      type="button"
                      onClick={() => setSplitMode("auto")}
                      className={`px-3 py-1.5 font-bold transition cursor-pointer ${
                        splitMode === "auto"
                          ? "bg-blue-600 text-white"
                          : "bg-white dark:bg-zinc-900 text-zinc-600 hover:bg-zinc-50"
                      }`}
                    >
                      Auto Batch Split
                    </button>
                    <button
                      type="button"
                      onClick={() => setSplitMode("manual")}
                      className={`px-3 py-1.5 font-bold transition cursor-pointer ${
                        splitMode === "manual"
                          ? "bg-blue-600 text-white"
                          : "bg-white dark:bg-zinc-900 text-zinc-600 hover:bg-zinc-50"
                      }`}
                    >
                      Manual Split
                    </button>
                  </div>
                </div>

                {/* Single WO Mode */}
                {splitMode === "single" && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
                    <div>
                      <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                        Physical WO Quantity (pcs) *
                      </label>
                      <input
                        type="number"
                        required
                        min={1}
                        value={woQty}
                        onChange={(e) => setWoQty(e.target.value === "" ? "" : Number(e.target.value))}
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      />
                      <p className="mt-1 text-[10px] text-zinc-400">
                        Available in OAR: {selectedOar.remaining_qty} pcs
                      </p>
                    </div>

                    <div className="flex flex-col justify-center">
                      <label className="flex items-center gap-2 cursor-pointer mt-2 text-xs text-zinc-700 dark:text-zinc-300">
                        <input
                          type="checkbox"
                          checked={allowOverrun}
                          onChange={(e) => setAllowOverrun(e.target.checked)}
                          className="rounded border-zinc-300 text-blue-600"
                        />
                        <span>
                          <strong>Allow Overrun / Additional Batch</strong> (Permits quantity above remaining OAR balance)
                        </span>
                      </label>
                    </div>
                  </div>
                )}

                {/* Auto Split Mode */}
                {splitMode === "auto" && (
                  <div className="space-y-3 pt-1">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      <div>
                        <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                          Total Quantity to Divide (pcs) *
                        </label>
                        <input
                          type="number"
                          required
                          min={1}
                          value={woQty}
                          onChange={(e) => setWoQty(e.target.value === "" ? "" : Number(e.target.value))}
                          className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                        />
                      </div>

                      <div>
                        <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                          Max Batch Size per Work Order (pcs) *
                        </label>
                        <input
                          type="number"
                          required
                          min={1}
                          value={batchSize}
                          onChange={(e) => setBatchSize(e.target.value === "" ? "" : Number(e.target.value))}
                          className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                        />
                      </div>
                    </div>

                    {autoSplitBatches.length > 0 && (
                      <div className="rounded-xl bg-blue-50/60 dark:bg-blue-950/30 p-3.5 border border-blue-200 dark:border-blue-900/40 text-xs space-y-2">
                        <div className="flex items-center justify-between font-semibold text-blue-900 dark:text-blue-300">
                          <span>
                            Quantity will be divided into: <strong>{autoSplitBatches.length} Work Orders</strong>
                          </span>
                          <span className="font-mono">
                            {totalBaseQty} pcs total
                          </span>
                        </div>
                        <div className="flex flex-wrap gap-2 pt-1">
                          {autoSplitBatches.map((bQty, bIdx) => (
                            <span
                              key={bIdx}
                              className="px-2.5 py-1 rounded-lg bg-white dark:bg-zinc-900 border border-blue-200 dark:border-blue-800 font-mono text-[11px] font-bold text-blue-700 dark:text-blue-300"
                            >
                              WO #{bIdx + 1}: {bQty} pcs
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Manual Split Mode */}
                {splitMode === "manual" && (
                  <div className="space-y-3 pt-1">
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-zinc-500">
                        Target Total: <strong className="text-zinc-800 dark:text-zinc-200 font-mono">{totalBaseQty} pcs</strong>
                      </span>
                      <button
                        type="button"
                        onClick={addManualRow}
                        className="text-xs font-bold text-blue-600 hover:underline cursor-pointer"
                      >
                        + Add Work Order Row
                      </button>
                    </div>

                    <div className="space-y-2">
                      {manualQtys.map((v, idx) => (
                        <div key={idx} className="flex items-center gap-2">
                          <span className="w-16 text-[11px] font-mono font-bold text-zinc-400">WO #{idx + 1}</span>
                          <input
                            type="number"
                            min={1}
                            value={v}
                            onChange={(e) => updateManualQty(idx, e.target.value)}
                            placeholder="Quantity (pcs)"
                            className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-1.5 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => removeManualRow(idx)}
                            disabled={manualQtys.length <= 1}
                            className="text-[11px] font-bold text-rose-500 disabled:opacity-30 disabled:cursor-not-allowed px-2 cursor-pointer"
                          >
                            Remove
                          </button>
                        </div>
                      ))}
                    </div>

                    <div
                      className={`rounded-xl p-3 border text-xs flex items-center justify-between ${
                        manualComplete
                          ? "bg-emerald-50/50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/40"
                          : "bg-amber-50/50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40"
                      }`}
                    >
                      <span className="text-zinc-600 dark:text-zinc-400">
                        Allocated: <strong className="font-mono">{manualAllocated}</strong> / {totalBaseQty} pcs
                        {" · "}
                        Remaining: <strong className="font-mono">{manualRemaining}</strong>
                      </span>
                      <span className={`font-bold ${manualComplete ? "text-emerald-600" : "text-amber-600"}`}>
                        {manualComplete ? "Allocation Complete" : "Allocation Incomplete"}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* Casting Process */}
              <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Casting Process
                </label>
                <select
                  value={castingProcess}
                  onChange={(e) => setCastingProcess(e.target.value as any)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  <option value="CENTRIFUGAL">CENTRIFUGAL (Foundry Melt)</option>
                  <option value="CONTINUOUS">CONTINUOUS (Continuous Casting)</option>
                </select>
              </div>

              {/* Route Stages */}
              <div className="pt-2">
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300 block mb-1.5">
                  Production Route Stages
                </label>
                <div className="flex flex-wrap gap-2">
                  {DEFAULT_STAGES.map((stg) => {
                    const active = routeStages.includes(stg);
                    return (
                      <button
                        key={stg}
                        type="button"
                        onClick={() => handleToggleStage(stg)}
                        className={`px-3 py-1 text-xs font-bold rounded-lg border transition cursor-pointer ${
                          active
                            ? "bg-blue-600 border-blue-600 text-white"
                            : "bg-zinc-50 dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800 text-zinc-400"
                        }`}
                      >
                        {stg}
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* Remarks */}
              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Planning Remarks
                </label>
                <input
                  type="text"
                  value={remarks}
                  onChange={(e) => setRemarks(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              {/* Action Buttons: Step 1 Submit -> Proceed to Step 2 */}
              <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <span className="text-xs text-zinc-400">
                  Step 1 will generate the Work Order IDs in unreleased status. You will then release them in Step 2.
                </span>

                <div className="flex items-center gap-3 self-end sm:self-auto">
                  <button
                    type="button"
                    onClick={() => setSelectedOar(null)}
                    className="px-4 py-2.5 text-xs font-semibold rounded-xl border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={
                      submitting ||
                      !woNumber ||
                      isDuplicateWoNumber ||
                      (isOarFullyPlanned && !allowOverrun) ||
                      (splitMode === "single" && (!woQty || Number(woQty) <= 0)) ||
                      (splitMode === "auto" && autoSplitBatches.length === 0) ||
                      (splitMode === "manual" && !manualComplete)
                    }
                    className="px-6 py-2.5 text-xs font-bold rounded-xl bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 transition flex items-center gap-2 shadow-sm cursor-pointer"
                  >
                    <Plus className="h-4 w-4" />
                    <span>
                      {submitting
                        ? "Generating Work Order IDs..."
                        : isDuplicateWoNumber
                        ? "Duplicate WO ID — Click Next Auto"
                        : isOarFullyPlanned && !allowOverrun
                        ? "OAR Already Planned (Repeat Prohibited)"
                        : splitMode === "auto"
                        ? `Step 1: Generate ${autoSplitBatches.length} Work Order IDs`
                        : splitMode === "manual"
                        ? `Step 1: Generate ${parsedManualQtys.length} Work Order IDs`
                        : "Step 1: Generate Work Order ID"}
                    </span>
                  </button>
                </div>
              </div>
            </form>
          )}
        </div>

        {/* Section 3: Created Work Orders & Release Handoff */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                <Layers className="h-4 w-4 text-blue-600" />
                Work Orders Queue &amp; Release Status (Step 2 Handoff)
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                Generated Work Orders linked to parent OARs. Unreleased Work Orders must be released in Step 2 before floor execution.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <div className="flex items-center rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden text-xs">
                <button
                  type="button"
                  onClick={() => setWoTableTab("all")}
                  className={`px-3 py-1.5 font-bold transition cursor-pointer ${
                    woTableTab === "all"
                      ? "bg-blue-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                  }`}
                >
                  All ({recentWOs.length})
                </button>
                <button
                  type="button"
                  onClick={() => setWoTableTab("unreleased")}
                  className={`px-3 py-1.5 font-bold transition cursor-pointer ${
                    woTableTab === "unreleased"
                      ? "bg-amber-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                  }`}
                >
                  Awaiting Release ({recentWOs.filter((w) => !w.is_released).length})
                </button>
              </div>

              <button
                type="button"
                onClick={loadRecentWOs}
                disabled={loadingWOs}
                className="p-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-600 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
                title="Refresh Work Orders"
              >
                <RefreshCw className={`h-4 w-4 ${loadingWOs ? "animate-spin" : ""}`} />
              </button>
            </div>
          </div>

          {loadingWOs ? (
            <p className="text-xs text-zinc-400 py-4 text-center">Loading Work Orders...</p>
          ) : displayedWOs.length === 0 ? (
            <p className="text-xs text-zinc-400 py-4 text-center">
              {woTableTab === "unreleased" ? "No Work Orders awaiting release." : "No Work Orders created yet."}
            </p>
          ) : (
            <div className="overflow-x-auto max-h-80 overflow-y-auto border border-zinc-200 dark:border-zinc-800 rounded-xl">
              <table className="w-full text-left text-xs">
                <thead className="bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 uppercase text-[10px] tracking-wider sticky top-0">
                  <tr>
                    <th className="p-3">Work Order ID</th>
                    <th className="p-3">Parent OAR</th>
                    <th className="p-3">Customer &amp; PO</th>
                    <th className="p-3">Part Number</th>
                    <th className="p-3 text-right">WO Qty</th>
                    <th className="p-3">Current Stage</th>
                    <th className="p-3">Step 2: Release Status</th>
                    <th className="p-3 text-right">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                  {displayedWOs.map((wo) => (
                    <tr key={wo.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                      <td className="p-3">
                        <span className="font-mono font-bold text-blue-600 block">
                          {wo.wo_number}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono">
                          {formatDate(wo.wo_date || wo.created_at)}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="font-mono font-bold text-emerald-700 dark:text-emerald-400 block">
                          {wo.oar_number || "—"}
                        </span>
                      </td>
                      <td className="p-3">
                        <span className="font-semibold text-zinc-800 dark:text-zinc-200 block truncate max-w-xs">
                          {wo.customer_name}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono">
                          PO: {wo.customer_po || "—"}
                        </span>
                      </td>
                      <td className="p-3 font-mono text-zinc-900 dark:text-zinc-100">
                        {wo.part_number}
                      </td>
                      <td className="p-3 text-right font-mono font-bold">
                        {wo.physical_wo_qty} pcs
                      </td>
                      <td className="p-3 font-mono">
                        <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-bold text-[11px]">
                          {wo.current_stage || "F1"}
                        </span>
                      </td>
                      <td className="p-3">
                        {wo.is_released ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-800 dark:text-emerald-300 font-bold text-[11px]">
                            <Check className="h-3 w-3" /> Step 2: Released
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950/60 text-amber-800 dark:text-amber-300 font-bold text-[11px]">
                            <Clock className="h-3 w-3" /> Step 1: Generated (Unreleased)
                          </span>
                        )}
                      </td>
                      <td className="p-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => setEditingWO(wo)}
                            className="px-2.5 py-1 text-xs font-semibold rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-200 transition flex items-center gap-1 shadow-sm"
                            title="Edit Work Order"
                          >
                            <Edit2 className="h-3 w-3" />
                            <span>Edit</span>
                          </button>
                          {!wo.is_released ? (
                            <Link
                              href={`/planning/wo-release?wo=${encodeURIComponent(wo.wo_number)}`}
                              className="px-3 py-1.5 text-xs font-bold rounded-lg bg-blue-600 text-white hover:bg-blue-700 transition flex items-center gap-1 shadow-sm"
                            >
                              <span>Step 2: Release WO</span>
                              <ArrowRight className="h-3 w-3" />
                            </Link>
                          ) : (
                            <Link
                              href={`/production/tracking?wo=${encodeURIComponent(wo.wo_number)}`}
                              className="px-2.5 py-1 text-[11px] font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                            >
                              Track Floor
                            </Link>
                          )}
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

      {/* Edit Commitment Date Modal */}
      {editingCommitmentOar && (
        <EditCommitmentDateModal
          oar={editingCommitmentOar}
          onClose={() => setEditingCommitmentOar(null)}
          onSuccess={handleCommitmentDateSuccess}
        />
      )}

      {/* Toast alert for commitment date success */}
      {commitmentSuccessMsg && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl bg-blue-600 text-white px-4 py-3 shadow-xl flex items-center gap-2 text-xs font-bold animate-in fade-in slide-in-from-bottom-4">
          <CheckCircle2 className="h-4 w-4" />
          <span>{commitmentSuccessMsg}</span>
        </div>
      )}

      {/* Edit Work Order Modal */}
      {editingWO && (
        <EditWorkOrderModal
          wo={editingWO}
          onClose={() => setEditingWO(null)}
          onSuccess={async (updatedWO) => {
            setEditingWO(null);
            setEditSuccessMsg(`Work Order ${updatedWO.wo_number} updated successfully!`);
            await loadRecentWOs();
            await loadOars();
            setTimeout(() => setEditSuccessMsg(""), 5000);
          }}
        />
      )}

      {/* Toast alert for edit success */}
      {editSuccessMsg && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl bg-emerald-600 text-white px-4 py-3 shadow-xl flex items-center gap-2 text-xs font-bold animate-in fade-in slide-in-from-bottom-4">
          <CheckCircle2 className="h-4 w-4" />
          <span>{editSuccessMsg}</span>
        </div>
      )}
    </AppShell>
  );
}

interface EditWorkOrderModalProps {
  wo: WorkOrderListItem;
  onClose: () => void;
  onSuccess: (updated: WorkOrderListItem) => void;
}

function EditWorkOrderModal({ wo, onClose, onSuccess }: EditWorkOrderModalProps) {
  const [woNumber, setWoNumber] = useState(wo.wo_number);
  const [qty, setQty] = useState<number | "">(wo.physical_wo_qty);
  const [woDate, setWoDate] = useState(() => (wo.wo_date ? wo.wo_date.slice(0, 10) : new Date().toISOString().slice(0, 10)));
  const [targetDate, setTargetDate] = useState(() => (wo.delivery_date ? wo.delivery_date.slice(0, 10) : ""));
  const [castingProcess, setCastingProcess] = useState<"CENTRIFUGAL" | "CONTINUOUS">((wo.casting_process as any) || "CENTRIFUGAL");
  const [routeStages, setRouteStages] = useState<string[]>(() => {
    return wo.route_stages && wo.route_stages.length > 0 ? wo.route_stages : DEFAULT_STAGES;
  });
  const [remarks, setRemarks] = useState("Updated by Production Planning.");
  const [allowOverrun, setAllowOverrun] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const isFloorActive = wo.is_released && (wo.current_stage !== "F1" || wo.status === "IN_PRODUCTION" || wo.status === "DISPATCHED");

  const toggleStage = (stg: string) => {
    if (isFloorActive) return;
    if (routeStages.includes(stg)) {
      if (routeStages.length <= 1) return;
      setRouteStages(routeStages.filter((s) => s !== stg));
    } else {
      setRouteStages([...routeStages, stg]);
    }
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!woNumber.trim()) {
      setError("Work Order ID cannot be blank.");
      return;
    }
    const qVal = Number(qty);
    if (!qVal || qVal <= 0) {
      setError("Quantity must be a positive integer.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload: WorkOrderUpdatePayload = {
        wo_number: woNumber.trim(),
        physical_wo_qty: qVal,
        wo_date: woDate || null,
        target_date: targetDate || null,
        casting_process: castingProcess,
        route_stages: routeStages,
        remarks: remarks.trim() || null,
        allow_overrun: allowOverrun
      };
      const updated = await updateWorkOrder(wo.id || wo.wo_number, payload);
      onSuccess(updated);
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.message || "Failed to update Work Order.";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm overflow-y-auto">
      <div className="relative w-full max-w-xl rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl p-6 space-y-5 my-8">
        <div className="flex items-center justify-between border-b border-zinc-200 dark:border-zinc-800 pb-3">
          <div>
            <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 block">
              Work Order Editor
            </span>
            <h3 className="text-lg font-extrabold text-zinc-900 dark:text-zinc-50 flex items-center gap-2">
              <span>Edit Work Order: {wo.wo_number}</span>
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Metadata Banner */}
        <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800/50 p-3.5 border border-zinc-200 dark:border-zinc-700/60 text-xs grid grid-cols-2 sm:grid-cols-3 gap-2">
          <div>
            <span className="text-[10px] text-zinc-400 block">Parent OAR</span>
            <span className="font-mono font-bold text-emerald-600">{wo.oar_number || "—"}</span>
          </div>
          <div>
            <span className="text-[10px] text-zinc-400 block">Customer</span>
            <span className="font-semibold text-zinc-800 dark:text-zinc-200 truncate block">{wo.customer_name}</span>
          </div>
          <div>
            <span className="text-[10px] text-zinc-400 block">Part Number</span>
            <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200 truncate block">{wo.part_number}</span>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-600 dark:text-rose-400 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSave} className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* WO Number */}
            <div>
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                Work Order ID / Number *
              </label>
              <input
                type="text"
                value={woNumber}
                onChange={(e) => setWoNumber(e.target.value.toUpperCase())}
                disabled={isFloorActive}
                required
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none disabled:opacity-60"
              />
              {isFloorActive && (
                <span className="text-[10px] text-amber-500 mt-1 block">
                  Locked: Floor movements have begun.
                </span>
              )}
            </div>

            {/* Quantity */}
            <div>
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                Physical Quantity (pcs) *
              </label>
              <input
                type="number"
                min={1}
                value={qty}
                onChange={(e) => setQty(e.target.value === "" ? "" : Number(e.target.value))}
                disabled={isFloorActive}
                required
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none disabled:opacity-60"
              />
            </div>

            {/* WO Date */}
            <div>
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                Work Order Date
              </label>
              <input
                type="date"
                value={woDate}
                onChange={(e) => setWoDate(e.target.value)}
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
              />
            </div>

            {/* Target Delivery Date */}
            <div>
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                Target / Delivery Date
              </label>
              <input
                type="date"
                value={targetDate}
                onChange={(e) => setTargetDate(e.target.value)}
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
              />
            </div>

            {/* Casting Process */}
            <div className="sm:col-span-2">
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                Casting Process
              </label>
              <select
                value={castingProcess}
                onChange={(e) => setCastingProcess(e.target.value as any)}
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
              >
                <option value="CENTRIFUGAL">CENTRIFUGAL (Foundry Melt)</option>
                <option value="CONTINUOUS">CONTINUOUS (Cast Bar Cutting)</option>
              </select>
            </div>
          </div>

          {/* Route Stages */}
          <div>
            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
              Production Route Stages
            </label>
            <div className="flex flex-wrap gap-2">
              {DEFAULT_STAGES.map((stg) => {
                const active = routeStages.includes(stg);
                return (
                  <button
                    key={stg}
                    type="button"
                    disabled={isFloorActive}
                    onClick={() => toggleStage(stg)}
                    className={`px-3 py-1 rounded-lg text-xs font-mono font-bold transition ${
                      active
                        ? "bg-blue-600 text-white shadow-sm"
                        : "bg-zinc-100 dark:bg-zinc-800 text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                    } ${isFloorActive ? "opacity-60 cursor-not-allowed" : ""}`}
                  >
                    {stg}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Overrun Checkbox */}
          <div className="flex items-center gap-2 pt-1">
            <input
              type="checkbox"
              id="editAllowOverrun"
              checked={allowOverrun}
              onChange={(e) => setAllowOverrun(e.target.checked)}
              className="rounded border-zinc-300 text-blue-600 focus:ring-blue-500 h-4 w-4"
            />
            <label htmlFor="editAllowOverrun" className="text-xs text-zinc-600 dark:text-zinc-400 font-medium cursor-pointer">
              Allow Overrun / Additional Batch (Permits quantity above remaining OAR balance)
            </label>
          </div>

          {/* Planning Remarks */}
          <div>
            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
              Planning Remarks
            </label>
            <input
              type="text"
              value={remarks}
              onChange={(e) => setRemarks(e.target.value)}
              className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
            />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="px-4 py-2 rounded-xl border border-zinc-300 dark:border-zinc-700 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition shadow-sm flex items-center gap-1.5 disabled:opacity-60"
            >
              {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              <span>{saving ? "Saving Changes..." : "Save Changes"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

interface EditCommitmentDateModalProps {
  oar: OARListItem;
  onClose: () => void;
  onSuccess: (updatedOar: OARListItem) => void;
}

function EditCommitmentDateModal({ oar, onClose, onSuccess }: EditCommitmentDateModalProps) {
  const isAlreadyCommitted = Boolean(oar.commitment_date || oar.revised_commitment_date);
  const currentEffDate = oar.effective_commitment_date || oar.revised_commitment_date || oar.commitment_date;
  const initialDate = currentEffDate
    ? currentEffDate.slice(0, 10)
    : oar.delivery_date
    ? oar.delivery_date.slice(0, 10)
    : "";

  const [commitmentDate, setCommitmentDate] = useState(initialDate);
  const [revisionReason, setRevisionReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!commitmentDate) {
      setError("Please select a commitment date.");
      return;
    }

    try {
      setSaving(true);
      setError("");

      const payload: {
        commitment_date?: string;
        revised_commitment_date?: string;
        revision_reason?: string;
      } = {};

      if (isAlreadyCommitted) {
        payload.revised_commitment_date = commitmentDate;
        payload.revision_reason = revisionReason.trim() || undefined;
      } else {
        payload.commitment_date = commitmentDate;
        if (revisionReason.trim()) {
          payload.revision_reason = revisionReason.trim();
        }
      }

      const updated = await updateOAR(oar.oar_number, payload);
      onSuccess(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update commitment date.";
      setError(msg);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in">
      <div className="w-full max-w-md rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/50">
          <div className="flex items-center gap-2">
            <div className="p-2 rounded-lg bg-blue-100 dark:bg-blue-950/70 text-blue-600 dark:text-blue-400">
              <CalendarClock className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
                {isAlreadyCommitted ? "Revise Commitment Date" : "Set Initial Commitment Date"}
              </h3>
              <p className="text-[11px] text-zinc-500 font-mono">OAR: {oar.oar_number}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4 text-xs">
          {error && (
            <div className="p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-300 text-xs">
              {error}
            </div>
          )}

          {/* Context details */}
          <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800/40 p-3 border border-zinc-200 dark:border-zinc-800 space-y-1.5">
            <div className="flex justify-between">
              <span className="text-zinc-500">Customer:</span>
              <span className="font-semibold text-zinc-800 dark:text-zinc-200 truncate max-w-[200px]">{oar.customer_name}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">Part:</span>
              <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200">{oar.customer_part_number || oar.part_number}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-zinc-500">PO Delivery Date:</span>
              <span className="font-mono text-zinc-700 dark:text-zinc-300">{formatDate(oar.delivery_date)}</span>
            </div>
            {isAlreadyCommitted && (
              <div className="flex justify-between pt-1 border-t border-zinc-200 dark:border-zinc-700">
                <span className="text-amber-600 dark:text-amber-400 font-medium">Current Committed:</span>
                <span className="font-mono font-bold text-amber-600 dark:text-amber-400">
                  {formatDate(currentEffDate)} {oar.commitment_date_revision_count ? `(Rev #${oar.commitment_date_revision_count})` : ""}
                </span>
              </div>
            )}
          </div>

          {/* Commitment Date Input */}
          <div>
            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
              {isAlreadyCommitted ? "New Revised Commitment Date *" : "Commitment Date *"}
            </label>
            <input
              type="date"
              required
              value={commitmentDate}
              onChange={(e) => setCommitmentDate(e.target.value)}
              className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none font-mono"
            />
          </div>

          {/* Revision Reason */}
          <div>
            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
              Revision Reason {isAlreadyCommitted ? "(Recommended)" : "(Optional)"}
            </label>
            <input
              type="text"
              placeholder={isAlreadyCommitted ? "e.g., Customer requested rescheduling, material delay..." : "Optional notes for commitment"}
              value={revisionReason}
              onChange={(e) => setRevisionReason(e.target.value)}
              className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
            />
            {isAlreadyCommitted && (
              <p className="text-[10px] text-zinc-400 mt-1">
                Updating this date will increment the revision count to Rev #{(oar.commitment_date_revision_count || 0) + 1} and record the audit timestamp.
              </p>
            )}
          </div>

          {/* Action Buttons */}
          <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-zinc-200 dark:border-zinc-800">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="px-3.5 py-2 rounded-xl border border-zinc-300 dark:border-zinc-700 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition shadow-sm flex items-center gap-1.5 disabled:opacity-60 cursor-pointer"
            >
              {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              <span>{saving ? "Updating..." : isAlreadyCommitted ? "Save Revision" : "Set Commitment Date"}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

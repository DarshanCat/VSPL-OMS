"use client";
import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  Factory,
  Search,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ArrowRightLeft,
  QrCode,
  Layers,
  Cpu,
  User,
  Clock,
  RotateCcw,
  Sparkles,
  ShieldCheck,
  ClipboardCheck,
  AlertCircle
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import {
  getWorkOrders,
  getWorkOrderTracking,
  getWorkOrderRoute,
  getStageState,
  getRejectionTypes,
  recordStageProduction,
  MasterRejectionType
} from "@/lib/api";

const MACHINES = [
  { id: "M-CC01", name: "CC Machine 01 (Foundry F1)", stage: "F1" },
  { id: "M-CC02", name: "CC Machine 02 (Foundry F1)", stage: "F1" },
  { id: "M-CNC01", name: "CNC Lathe 01 (Rough Machining F2)", stage: "F2" },
  { id: "M-CNC02", name: "CNC Lathe 02 (Rough Machining F2)", stage: "F2" },
  { id: "M-VMC01", name: "VMC Milling 01 (Finish Machining F3)", stage: "F3" },
  { id: "M-VMC02", name: "VMC Milling 02 (Finish Machining F3)", stage: "F3" },
  { id: "M-SP01", name: "Special Process Cell 01 (SP)", stage: "SP" },
  { id: "M-FI01", name: "Final Inspection Bench 01 (FI)", stage: "FI" },
  { id: "M-PACK01", name: "Packing Station 01", stage: "PACKING" },
  { id: "M-BSR01", name: "Bonded Store Bay 01", stage: "BSR" },
];

const OPERATORS = [
  { id: "OP-101", name: "Ramesh Kumar" },
  { id: "OP-102", name: "Suresh Patil" },
  { id: "OP-103", name: "Anand Sharma" },
  { id: "OP-104", name: "Mahesh Verma" },
  { id: "OP-105", name: "Dinesh Gowda" },
];

// Fallback only for a deployment that has never configured the Rejection Type
// master yet (see backend RejectionTypeService / validate_active_rejection_type --
// the backend gate itself only activates once the master has at least one row).
const FALLBACK_DEFECT_CODES = [
  { code: "DEF-POROSITY", label: "DEF-POROSITY (Gas/Shrinkage Cavity)" },
  { code: "DEF-DIM-OUT", label: "DEF-DIM-OUT (Dimensional Out of Spec)" },
  { code: "DEF-SURFACE", label: "DEF-SURFACE (Surface Roughness/Blemish)" },
  { code: "DEF-CRACK", label: "DEF-CRACK (Thermal/Handling Crack)" },
  { code: "DEF-HARDNESS", label: "DEF-HARDNESS (Hardness Mismatch)" },
  { code: "DEF-INCLUSION", label: "DEF-INCLUSION (Slag/Sand Particle)" },
];

export function ProductionEntryContent() {
  const [searchTerm, setSearchTerm] = useState("WO-1001");
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [formError, setFormError] = useState("");
  const [availableWOs, setAvailableWOs] = useState<any[]>([]);

  // Selected WO and Route Data
  const [woData, setWoData] = useState<any>(null);
  const [routeData, setRouteData] = useState<any>(null);
  const [stageState, setStageState] = useState<any>(null);
  const [selectedStage, setSelectedStage] = useState<string>("F1");

  // Form Fields
  const [goodQty, setGoodQty] = useState<number | "">("");
  const [rejectedQty, setRejectedQty] = useState<number | "">(0);
  const [selectedMachine, setSelectedMachine] = useState("M-CC01");
  const [selectedOperator, setSelectedOperator] = useState("Ramesh Kumar");
  const [shift, setShift] = useState("Shift A");
  const [defectCode, setDefectCode] = useState("DEF-POROSITY");
  const [remarks, setRemarks] = useState("");
  const [rejectionTypes, setRejectionTypes] = useState<MasterRejectionType[]>([]);

  // Result / Success Modal
  const [successResult, setSuccessResult] = useState<any>(null);
  const [showQRModal, setShowQRModal] = useState(false);

  // Focus Refs for Tally-Style Navigation
  const inputSearchRef = useRef<HTMLInputElement>(null);
  const inputGoodQtyRef = useRef<HTMLInputElement>(null);
  const inputRejQtyRef = useRef<HTMLInputElement>(null);
  const selectDefectRef = useRef<HTMLSelectElement>(null);
  const selectMachineRef = useRef<HTMLSelectElement>(null);
  const selectOperatorRef = useRef<HTMLSelectElement>(null);
  const selectShiftRef = useRef<HTMLSelectElement>(null);
  const inputRemarksRef = useRef<HTMLInputElement>(null);
  const btnSubmitRef = useRef<HTMLButtonElement>(null);

  // Load available WOs and the active Rejection Type master on mount
  useEffect(() => {
    getWorkOrders({ limit: 100 })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAvailableWOs(data);
          lookupWO(data[0].wo_number);
        }
      })
      .catch((err) => {
        console.error("Failed to fetch WOs:", err);
      });
    getRejectionTypes()
      .then((types) => setRejectionTypes(types))
      .catch(() => setRejectionTypes([]));
  }, []);

  // Active Rejection Types drive the dropdown -- never arbitrary free text. Falls
  // back to the legacy static list only when the master has never been configured.
  const defectOptions = rejectionTypes.length > 0
    ? rejectionTypes.map((t) => ({ code: t.code, label: `${t.code} (${t.name})` }))
    : FALLBACK_DEFECT_CODES;

  useEffect(() => {
    if (defectOptions.length > 0 && !defectOptions.some((d) => d.code === defectCode)) {
      setDefectCode(defectOptions[0].code);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rejectionTypes]);

  const handleSelectStage = async (stage: string, currentWO?: any) => {
    const activeWo = currentWO || woData;
    setSelectedStage(stage);
    setGoodQty("");
    setRejectedQty(0);
    setFormError("");
    const matchingMach = MACHINES.find((m) => m.stage === stage);
    if (matchingMach) setSelectedMachine(matchingMach.id);

    if (activeWo?.wo_number) {
      try {
        const state = await getStageState(activeWo.wo_number, stage);
        setStageState(state);
      } catch {
        setStageState(null);
      }
    }
    setTimeout(() => inputGoodQtyRef.current?.focus(), 100);
  };

  const lookupWO = async (woNum: string) => {
    if (!woNum || !woNum.trim()) return;
    const cleanWO = woNum.trim();
    setSearchTerm(cleanWO);
    setLoading(true);
    setSearchError("");
    setFormError("");
    setSuccessResult(null);

    try {
      const [tracking, route] = await Promise.all([
        getWorkOrderTracking(cleanWO),
        getWorkOrderRoute(cleanWO).catch(() => null),
      ]);

      setWoData(tracking);
      setRouteData(route);
      setSearchTerm(tracking.wo_number);

      // Default stage: if currently selected stage is valid in timeline, keep it; otherwise use current_stage
      const validStages = tracking.timeline?.map((s: any) => s.stage) || ["F1"];
      const targetStage = validStages.includes(selectedStage) ? selectedStage : (tracking.current_stage || "F1");
      setSelectedStage(targetStage);

      // Fetch authoritative stage state for chosen stage
      const state = await getStageState(cleanWO, targetStage).catch(() => null);
      setStageState(state);

      // Production entry fields represent a NEW transaction delta only — never prefill
      // with available WIP or any cumulative/aggregate figure. Operators must enter the
      // actual pieces completed in this transaction.
      setGoodQty("");
      setRejectedQty(0);

      // Preset matching machine
      const matchingMach = MACHINES.find((m) => m.stage === targetStage);
      if (matchingMach) setSelectedMachine(matchingMach.id);

      // Auto-focus Good Qty input
      setTimeout(() => inputGoodQtyRef.current?.focus(), 100);
    } catch (err: any) {
      setWoData(null);
      setRouteData(null);
      setStageState(null);
      if (err?.response?.status === 404) {
        setSearchError(`Work Order '${cleanWO}' not found in database.`);
      } else {
        setSearchError(err?.response?.data?.detail || `Error retrieving Work Order '${cleanWO}'.`);
      }
    } finally {
      setLoading(false);
    }
  };

  // Tally-Style Enter Key Navigation Handler
  const handleKeyDown = (
    e: React.KeyboardEvent,
    nextTarget: "goodQty" | "rejQty" | "defect" | "machine" | "operator" | "shift" | "remarks" | "submit",
    prevTarget?: "goodQty" | "rejQty" | "defect" | "machine" | "operator" | "shift" | "remarks"
  ) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      switch (nextTarget) {
        case "goodQty":
          inputGoodQtyRef.current?.focus();
          break;
        case "rejQty":
          inputRejQtyRef.current?.focus();
          break;
        case "defect":
          if (Number(rejectedQty) > 0) {
            selectDefectRef.current?.focus();
          } else {
            selectMachineRef.current?.focus();
          }
          break;
        case "machine":
          selectMachineRef.current?.focus();
          break;
        case "operator":
          selectOperatorRef.current?.focus();
          break;
        case "shift":
          selectShiftRef.current?.focus();
          break;
        case "remarks":
          inputRemarksRef.current?.focus();
          break;
        case "submit":
          btnSubmitRef.current?.focus();
          break;
      }
    } else if (e.key === "Enter" && e.shiftKey && prevTarget) {
      e.preventDefault();
      switch (prevTarget) {
        case "goodQty":
          inputGoodQtyRef.current?.focus();
          break;
        case "rejQty":
          inputRejQtyRef.current?.focus();
          break;
        case "machine":
          selectMachineRef.current?.focus();
          break;
        case "operator":
          selectOperatorRef.current?.focus();
          break;
        case "shift":
          selectShiftRef.current?.focus();
          break;
        case "remarks":
          inputRemarksRef.current?.focus();
          break;
      }
    }
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!woData) return;

    const goodQtyNum = Number(goodQty) || 0;
    const rejQtyNum = Number(rejectedQty) || 0;
    const totalProc = goodQtyNum + rejQtyNum;

    if (goodQtyNum < 0 || rejQtyNum < 0) {
      setFormError("Negative quantities are not permitted.");
      return;
    }

    if (totalProc <= 0) {
      setFormError("Please enter a valid production quantity (Good Qty + Rejection > 0).");
      inputGoodQtyRef.current?.focus();
      return;
    }

    // The ceiling for a NEW production transaction is the unprocessed material still
    // remaining at this stage (in_process_qty), never available_wip -- available_wip
    // also includes onhand_qty (already-completed material awaiting movement), and
    // validating a fresh entry against it would let cumulative OK run past the
    // authoritative target. This mirrors the backend's own authoritative check in
    // ProductionService.record_stage_production; the backend remains the enforcing
    // authority regardless of this client-side check.
    const remainingTarget = stageState?.in_process_qty ?? activeStage.in_process_qty ?? 0;
    if (totalProc > remainingTarget) {
      setFormError(`Total quantity processed (${totalProc}) exceeds the remaining allowable target at ${selectedStage} (${remainingTarget} pcs remaining of target).`);
      inputGoodQtyRef.current?.focus();
      return;
    }

    setSubmitting(true);
    setFormError("");

    // Generate unique client idempotency token
    const clientReqId = typeof crypto !== "undefined" && crypto.randomUUID ? crypto.randomUUID() : `PROD-REQ-${Date.now()}`;

    try {
      const res = await recordStageProduction({
        wo_number: woData.wo_number,
        stage: selectedStage,
        good_qty: goodQtyNum,
        rejected_quantity: rejQtyNum,
        machine_id: selectedMachine,
        operator_name: selectedOperator,
        shift: shift,
        defect_code: rejQtyNum > 0 ? defectCode : undefined,
        remarks: remarks.trim() || undefined,
        client_request_id: clientReqId
      });

      setSuccessResult({
        entry_id: res.entry_id,
        wo_number: res.wo_number,
        stage: res.stage,
        good_qty: res.good_qty,
        rejected_quantity: res.rejected_quantity,
        stage_ok_total: res.stage_ok_total,
        stage_rejection_total: res.stage_rejection_total,
        stage_onhand_available: res.stage_onhand_available,
        stage_inproc_remaining: res.stage_inproc_remaining,
        message: res.message
      });

      // Refresh authoritative WO tracking and stage state
      await lookupWO(woData.wo_number);
      inputGoodQtyRef.current?.focus();
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || "Production recording failed. Please check validation rules.");
    } finally {
      setSubmitting(false);
    }
  };

  const activeStage = stageState || {
    target_qty: woData?.physical_wo_qty ?? 0,
    ok_completed_qty: 0,
    rejected_qty: 0,
    in_process_qty: woData?.physical_wo_qty ?? 0,
    available_wip: woData?.available_wip ?? 0,
    already_moved_qty: 0,
    not_yet_produced: woData?.physical_wo_qty ?? 0,
    remaining_to_produce: woData?.physical_wo_qty ?? 0,
    stage_status: "In-Progress"
  };

  return (
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Shop Floor Production
              </span>
              <span className="text-xs text-zinc-400">Tally Keyboard Navigation • Authoritative OMS</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Production Entry Screen
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Record completed OK and scrap/rejection quantities for the current manufacturing stage. Material is held on-hand until physical movement.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/production/tracking"
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
            >
              <Layers className="h-4 w-4 text-purple-500" />
              <span>WO Timeline</span>
            </Link>
          </div>
        </div>

        {/* WO Search & Scanner Input Bar */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <div className="flex flex-col md:flex-row items-center gap-3">
            <div className="relative flex-1 w-full">
              <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
              <input
                ref={inputSearchRef}
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    lookupWO(searchTerm);
                  }
                }}
                placeholder="Scan barcode or type WO number (e.g. WO-1001, WO-1008)..."
                className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 pl-10 pr-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-emerald-500 focus:outline-none font-mono font-bold"
              />
            </div>

            <div className="flex items-center gap-2 w-full md:w-auto">
              <button
                type="button"
                onClick={() => lookupWO(searchTerm)}
                disabled={loading}
                className="flex-1 md:flex-none rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-500 transition-colors cursor-pointer flex items-center justify-center gap-1.5"
              >
                {loading ? "Searching..." : "Lookup WO"}
              </button>

              {availableWOs.length > 0 && (
                <select
                  value={woData?.wo_number || ""}
                  onChange={(e) => lookupWO(e.target.value)}
                  className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 font-mono font-bold focus:outline-none"
                >
                  {availableWOs.map((w) => (
                    <option key={w.wo_number} value={w.wo_number}>
                      {w.wo_number} — {w.current_stage} ({w.customer_code})
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {searchError && (
            <div className="mt-3 flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-500 font-semibold">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{searchError}</span>
            </div>
          )}
        </div>

        {woData && (
          <div className="space-y-6">
            {/* WO Context & Metadata Strip */}
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 text-xs">
                <div>
                  <span className="text-zinc-400 text-[10px] uppercase font-bold">Work Order</span>
                  <p className="font-mono font-extrabold text-zinc-900 dark:text-zinc-50 text-sm">{woData.wo_number}</p>
                  <p className="text-[10px] text-zinc-500">{woData.customer_name}</p>
                </div>
                <div>
                  <span className="text-zinc-400 text-[10px] uppercase font-bold">Part Number</span>
                  <p className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{woData.part_number}</p>
                  <p className="text-[10px] text-zinc-500 truncate">{woData.part_name || "Bronze Bushing"}</p>
                </div>
                <div>
                  <span className="text-zinc-400 text-[10px] uppercase font-bold">OAR Number</span>
                  <p className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{woData.oar_number || "OAR-DEFAULT"}</p>
                  <p className="text-[10px] text-zinc-500">PO: {woData.customer_po}</p>
                </div>
                <div>
                  <span className="text-zinc-400 text-[10px] uppercase font-bold">Match Size</span>
                  <p className="font-extrabold text-purple-600 text-sm">{woData.match_size ?? "100"} pcs</p>
                  <p className="text-[10px] text-zinc-500">Max Batch Size</p>
                </div>
                <div>
                  <span className="text-zinc-400 text-[10px] uppercase font-bold">Released Qty</span>
                  <p className="font-extrabold text-zinc-900 dark:text-zinc-100 text-sm">{woData.physical_wo_qty} pcs</p>
                  <p className="text-[10px] text-zinc-500">Total WO</p>
                </div>
                <div>
                  <span className="text-zinc-400 text-[10px] uppercase font-bold">Current Stage</span>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="font-mono font-extrabold text-emerald-600 text-sm">{woData.current_stage}</span>
                  </div>
                  <p className="text-[10px] text-zinc-500">{woData.status.toUpperCase()}</p>
                </div>
              </div>

              {/* Dynamic WO Route Visualization */}
              <div className="mt-5 pt-4 border-t border-zinc-100 dark:border-zinc-800">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[10px] uppercase font-bold text-zinc-400 tracking-wider">
                    Authoritative Dynamic Route (Click stage to log production):
                  </span>
                  <span className="text-[10px] text-zinc-500">
                    Active: <strong className="text-emerald-600 font-mono">{selectedStage}</strong>
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {woData.timeline && woData.timeline.map((stg: any, idx: number) => {
                    const isSelected = stg.stage === selectedStage;
                    const isCur = stg.stage === woData.current_stage;
                    const isDone = stg.is_completed;
                    return (
                      <React.Fragment key={stg.stage}>
                        <button
                          type="button"
                          onClick={() => handleSelectStage(stg.stage)}
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-mono font-bold transition-all cursor-pointer ${
                            isSelected
                              ? "border-emerald-500 bg-emerald-500 text-white shadow-md ring-2 ring-emerald-500/30"
                              : isCur
                              ? "border-emerald-500/70 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300"
                              : isDone
                              ? "border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 text-zinc-500 hover:border-zinc-400"
                              : "border-zinc-200 dark:border-zinc-800/60 bg-zinc-50/50 dark:bg-zinc-950/30 text-zinc-400 hover:border-zinc-400"
                          }`}
                        >
                          <span>{stg.stage}</span>
                          {isCur && !isSelected && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />}
                        </button>
                        {idx < woData.timeline.length - 1 && (
                          <ArrowRight className="h-3 w-3 text-zinc-400 shrink-0" />
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Main Production Entry Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Step 5: Large Operational Stage Card */}
              <div className="lg:col-span-1 rounded-2xl border border-emerald-500/30 bg-emerald-50/20 dark:bg-emerald-950/10 p-6 flex flex-col justify-between shadow-sm">
                <div>
                  <div className="flex items-center justify-between pb-4 border-b border-emerald-500/20">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                        Active Stage State
                      </span>
                      <h3 className="text-3xl font-extrabold font-mono text-zinc-900 dark:text-zinc-50 mt-0.5">
                        {selectedStage}
                      </h3>
                    </div>
                    <Badge variant="green" size="md">
                      {activeStage.stage_status || "IN PROGRESS"}
                    </Badge>
                  </div>

                  <div className="mt-5 space-y-3.5 text-xs">
                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
                      <span className="text-zinc-500 font-semibold">Target / Required:</span>
                      <span className="font-mono font-extrabold text-zinc-900 dark:text-zinc-100 text-sm">
                        {activeStage.target_qty} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
                      <span className="text-zinc-500 font-semibold">Total Produced:</span>
                      <span className="font-mono font-extrabold text-zinc-900 dark:text-zinc-100 text-sm">
                        {(activeStage.ok_completed_qty || 0) + (activeStage.rejected_qty || 0)} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
                      <span className="text-emerald-600 dark:text-emerald-400 font-semibold">Total Good / OK:</span>
                      <span className="font-mono font-extrabold text-emerald-600 text-sm">
                        {activeStage.ok_completed_qty} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
                      <span className="text-rose-600 dark:text-rose-400 font-semibold">Rejected:</span>
                      <span className="font-mono font-extrabold text-rose-600 text-sm">
                        {activeStage.rejected_qty} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-blue-50 dark:bg-blue-950/20 border border-blue-300 dark:border-blue-800">
                      <span className="text-blue-700 dark:text-blue-400 font-bold">In Process / WIP:</span>
                      <span className="font-mono font-extrabold text-blue-700 dark:text-blue-400 text-sm">
                        {activeStage.already_moved_qty} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200/80 dark:border-zinc-800">
                      <span className="text-zinc-500 font-semibold">Not Yet Produced:</span>
                      <span className="font-mono font-extrabold text-zinc-900 dark:text-zinc-100 text-sm">
                        {activeStage.not_yet_produced} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-amber-50 dark:bg-amber-950/20 border border-amber-300 dark:border-amber-800">
                      <span className="text-amber-700 dark:text-amber-400 font-bold">Yet to Produce:</span>
                      <span className="font-mono font-extrabold text-amber-700 dark:text-amber-400 text-sm">
                        {activeStage.remaining_to_produce} pcs
                      </span>
                    </div>

                    <div className="flex items-center justify-between p-2.5 rounded-xl bg-cyan-50 dark:bg-cyan-950/20 border border-cyan-300 dark:border-cyan-800">
                      <span className="text-cyan-700 dark:text-cyan-400 font-bold">Remaining Movable:</span>
                      <span className="font-mono font-extrabold text-cyan-700 dark:text-cyan-400 text-sm">
                        {activeStage.available_wip} pcs
                      </span>
                    </div>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-emerald-500/20 text-[11px] text-zinc-500">
                  <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-bold mb-1">
                    <ShieldCheck className="h-4 w-4" />
                    <span>Target Qty is Read-Only</span>
                  </div>
                  <p>Target quantity is mathematically derived from OMS yield algorithms. "Not Yet Produced" / "Remaining to Produce" is Target minus cumulative OK Produced. The physically unprocessed material actually available to convert right now at this stage is {activeStage.in_process_qty} pcs — that is the backend-enforced ceiling for your next entry below.</p>
                </div>
              </div>

              {/* Step 6: Production Input Form */}
              <div className="lg:col-span-2 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm">
                <form onSubmit={handleFormSubmit} className="space-y-5">
                  <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                      <ClipboardCheck className="h-4 w-4 text-emerald-600" />
                      <span>Log Production Completion</span>
                    </h3>
                    <span className="text-[11px] text-zinc-400">Press Enter to navigate fields</span>
                  </div>

                  {formError && (
                    <div className="flex items-center gap-2 rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs text-rose-500 font-semibold">
                      <AlertCircle className="h-4 w-4 shrink-0" />
                      <span>{formError}</span>
                    </div>
                  )}

                  {/* Quantities Row */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
                        NEW OK QUANTITY (THIS TRANSACTION) <span className="text-emerald-600">*</span>
                      </label>
                      <input
                        ref={inputGoodQtyRef}
                        type="number"
                        min="0"
                        max={activeStage.in_process_qty}
                        value={goodQty}
                        onChange={(e) => setGoodQty(e.target.value === "" ? "" : Number(e.target.value))}
                        onKeyDown={(e) => handleKeyDown(e, "rejQty")}
                        placeholder="Enter good pieces completed..."
                        className="w-full rounded-xl border-2 border-emerald-500/50 bg-emerald-50/20 dark:bg-zinc-950 px-4 py-3 text-lg font-mono font-extrabold text-zinc-900 dark:text-zinc-50 focus:border-emerald-500 focus:outline-none"
                        required
                      />
                      <span className="text-[10px] text-zinc-400 mt-1 block">
                        Fresh pieces completed in this transaction only — not the cumulative total. Physically unprocessed material available to convert now: {activeStage.in_process_qty} pcs.
                      </span>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
                        REJECTED QUANTITY (SCRAP)
                      </label>
                      <input
                        ref={inputRejQtyRef}
                        type="number"
                        min="0"
                        value={rejectedQty}
                        onChange={(e) => setRejectedQty(e.target.value === "" ? 0 : Number(e.target.value))}
                        onKeyDown={(e) => handleKeyDown(e, "defect", "goodQty")}
                        placeholder="0"
                        className={`w-full rounded-xl border px-4 py-3 text-lg font-mono font-extrabold focus:outline-none ${
                          Number(rejectedQty) > 0
                            ? "border-rose-500 bg-rose-50/30 dark:bg-rose-950/20 text-rose-600"
                            : "border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100"
                        }`}
                      />
                      <span className="text-[10px] text-zinc-400 mt-1 block">Stage-specific scrap (generates Non-Conformance record)</span>
                    </div>
                  </div>

                  {/* Defect Code (conditionally highlighted) */}
                  {Number(rejectedQty) > 0 && (
                    <div className="p-3.5 rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50/30 dark:bg-rose-950/10">
                      <label className="block text-xs font-bold text-rose-700 dark:text-rose-400 mb-1.5">
                        DEFECT REASON / CODE <span className="text-rose-600">*</span>
                      </label>
                      <select
                        ref={selectDefectRef}
                        value={defectCode}
                        onChange={(e) => setDefectCode(e.target.value)}
                        onKeyDown={(e) => handleKeyDown(e, "machine", "rejQty")}
                        className="w-full rounded-xl border border-rose-300 dark:border-rose-800 bg-white dark:bg-zinc-900 px-3.5 py-2.5 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      >
                        {defectOptions.map((d) => (
                          <option key={d.code} value={d.code}>
                            {d.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Machine & Operator Row */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
                        MACHINE / CELL
                      </label>
                      <select
                        ref={selectMachineRef}
                        value={selectedMachine}
                        onChange={(e) => setSelectedMachine(e.target.value)}
                        onKeyDown={(e) => handleKeyDown(e, "operator", "rejQty")}
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 px-3.5 py-2.5 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      >
                        {MACHINES.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
                        OPERATOR
                      </label>
                      <select
                        ref={selectOperatorRef}
                        value={selectedOperator}
                        onChange={(e) => setSelectedOperator(e.target.value)}
                        onKeyDown={(e) => handleKeyDown(e, "shift", "machine")}
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 px-3.5 py-2.5 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      >
                        {OPERATORS.map((op) => (
                          <option key={op.id} value={op.name}>
                            {op.name} ({op.id})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
                        SHIFT
                      </label>
                      <select
                        ref={selectShiftRef}
                        value={shift}
                        onChange={(e) => setShift(e.target.value)}
                        onKeyDown={(e) => handleKeyDown(e, "remarks", "operator")}
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 px-3.5 py-2.5 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      >
                        <option value="Shift A">Shift A (06:00 - 14:00)</option>
                        <option value="Shift B">Shift B (14:00 - 22:00)</option>
                        <option value="Shift C">Shift C (22:00 - 06:00)</option>
                      </select>
                    </div>
                  </div>

                  {/* Remarks */}
                  <div>
                    <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5">
                      REMARKS / LOG DETAILS
                    </label>
                    <input
                      ref={inputRemarksRef}
                      type="text"
                      value={remarks}
                      onChange={(e) => setRemarks(e.target.value)}
                      onKeyDown={(e) => handleKeyDown(e, "submit", "shift")}
                      placeholder="Optional batch notes or process observations..."
                      className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                    />
                  </div>

                  {/* Submit Button */}
                  <div className="pt-2">
                    <button
                      ref={btnSubmitRef}
                      type="submit"
                      disabled={submitting}
                      className="w-full rounded-xl bg-emerald-600 py-3.5 text-sm font-extrabold text-white shadow-md shadow-emerald-500/20 hover:bg-emerald-500 active:scale-[0.99] transition-all cursor-pointer flex items-center justify-center gap-2"
                    >
                      {submitting ? (
                        <>
                          <RotateCcw className="h-4 w-4 animate-spin" />
                          <span>Saving Production Entry...</span>
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="h-4 w-4" />
                          <span>SAVE PRODUCTION ENTRY</span>
                        </>
                      )}
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}

        {/* Success Feedback Modal / Banner */}
        {successResult && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5 flex items-start gap-4 shadow-sm animate-in fade-in slide-in-from-bottom-2">
            <div className="rounded-xl bg-emerald-600 p-2.5 text-white">
              <CheckCircle2 className="h-6 w-6" />
            </div>
            <div className="flex-1 text-xs space-y-1">
              <h4 className="text-sm font-extrabold text-emerald-800 dark:text-emerald-200">
                Production Recorded Successfully ({successResult.entry_id})
              </h4>
              <p className="text-zinc-600 dark:text-zinc-300">
                {successResult.message}
              </p>
              <div className="flex flex-wrap gap-4 pt-1 font-mono font-bold text-zinc-800 dark:text-zinc-200">
                <span>Stage OK Total: <strong className="text-emerald-600">{successResult.stage_ok_total}</strong></span>
                <span>Stage Rejection Total: <strong className="text-rose-600">{successResult.stage_rejection_total}</strong></span>
                <span>On-Hand Available: <strong className="text-blue-600">{successResult.stage_onhand_available}</strong></span>
                <span>In-Process Remaining: <strong className="text-amber-600">{successResult.stage_inproc_remaining}</strong></span>
              </div>
            </div>
          </div>
        )}
      </div>
  );
}

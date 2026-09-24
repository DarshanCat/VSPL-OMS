"use client";
import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  ArrowRightLeft,
  Search,
  QrCode,
  CheckCircle2,
  AlertTriangle,
  Layers,
  Factory,
  UserCheck,
  Clock,
  ShieldCheck,
  ChevronRight,
  ClipboardList,
  CheckSquare,
  ArrowRight,
  TrendingUp,
  BrainCircuit,
  Ban
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import {
  getWorkOrders,
  getWorkOrderTracking,
  getStageState,
  moveParts,
  predictDelay,
  predictRejection
} from "@/lib/api";

const MACHINES = [
  { id: "M-CC01", name: "M-CC01 (Centrifugal Casting 1)", stage: "F1" },
  { id: "M-CC02", name: "M-CC02 (Centrifugal Casting 2)", stage: "F1" },
  { id: "M-LATHE-01", name: "M-LATHE-01 (CNC Heavy Lathe 01)", stage: "F2" },
  { id: "M-LATHE-02", name: "M-LATHE-02 (CNC Precision Lathe 02)", stage: "F2" },
  { id: "M-VMC-01", name: "M-VMC-01 (Vertical Machining Center)", stage: "F3" },
  { id: "M-SUBCON-01", name: "M-SUBCON-01 (External Heat Treatment)", stage: "SP" },
  { id: "M-INSPECT-01", name: "M-INSPECT-01 (CMM & Final Inspection Bay)", stage: "FI" },
  { id: "M-PACK-01", name: "M-PACK-01 (Packaging & Banding Bay)", stage: "PACKING" },
];

export default function MovePartsPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [woData, setWoData] = useState<any>(null);
  const [stageState, setStageState] = useState<any>(null);
  const [mlDelayPred, setMlDelayPred] = useState<any>(null);
  const [mlRejPred, setMlRejPred] = useState<any>(null);
  const [availableWOs, setAvailableWOs] = useState<any[]>([]);
  const [searchError, setSearchError] = useState("");

  // Form State
  const [quantityToMove, setQuantityToMove] = useState<number | "">("");
  const [selectedMachine, setSelectedMachine] = useState<string>("M-LATHE-01");
  const [operatorName, setOperatorName] = useState("Ramesh Kumar (Logistics)");
  const [shift, setShift] = useState("Shift A");
  const [remarks, setRemarks] = useState("");

  // Submission & Result Modal
  const [submitting, setSubmitting] = useState(false);
  const [resultData, setResultData] = useState<any>(null);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [showQRModal, setShowQRModal] = useState(false);
  const [qrInput, setQrInput] = useState("");
  const [formError, setFormError] = useState("");

  // Tally-Style Keyboard Navigation Refs
  const inputSearchRef = useRef<HTMLInputElement>(null);
  const inputQtyRef = useRef<HTMLInputElement>(null);
  const selectMachineRef = useRef<HTMLSelectElement>(null);
  const selectShiftRef = useRef<HTMLSelectElement>(null);
  const inputOperatorRef = useRef<HTMLInputElement>(null);
  const inputRemarksRef = useRef<HTMLInputElement>(null);
  const btnSubmitRef = useRef<HTMLButtonElement>(null);

  // Fetch quick selectable active WOs from backend on load
  useEffect(() => {
    getWorkOrders({ limit: 20 })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAvailableWOs(data);
          lookupWO(data[0].wo_number);
        } else {
          setAvailableWOs([]);
        }
      })
      .catch((err) => {
        console.error("[MoveParts] Failed to load Work Orders from backend:", err);
        setSearchError("Backend / API service is currently unavailable. Please verify connection.");
      });
  }, []);

  const lookupWO = async (woNum: string) => {
    if (!woNum || !woNum.trim()) return;
    const targetWO = woNum.trim();

    setSearchTerm(targetWO);
    setLoading(true);
    setSearchError("");
    setFormError("");
    setResultData(null);

    try {
      const data = await getWorkOrderTracking(targetWO);
      setWoData(data);
      setSearchTerm(data.wo_number);

      // Movement quantity is always a fresh transaction amount, never prefilled with
      // the available WIP -- an operator must enter what was actually physically moved.
      setQuantityToMove("");

      // Authoritative production/movement breakdown for the actual movement-eligible
      // SOURCE stage (movable_from_stage) -- not necessarily data.current_stage, which
      // is the OMS "furthest stage touched" snapshot and advances as soon as the next
      // stage receives any material, even while this stage still has WIP available to
      // move. Same data source (get_current_stage_state) the Production Entry screen
      // uses, so the two screens never show competing numbers for a given stage.
      const originStage = data.movable_from_stage || data.current_stage;
      getStageState(targetWO, originStage)
        .then((s) => setStageState(s))
        .catch(() => setStageState(null));

      // Preset machine based on the actual movement destination
      const destStage = data.movable_to_stage || data.next_allowed_stage;
      const matchingMach = MACHINES.find((m) => m.stage === destStage || m.stage === originStage);
      if (matchingMach) setSelectedMachine(matchingMach.id);

      // Fetch ML risk insights
      predictDelay(data.wo_number)
        .then((pred) => setMlDelayPred(pred))
        .catch(() => setMlDelayPred(null));

      predictRejection({ wo_number: data.wo_number, target_stage: data.current_stage })
        .then((pred) => setMlRejPred(pred))
        .catch(() => setMlRejPred(null));

      // Auto focus Quantity field on successful load
      setTimeout(() => inputQtyRef.current?.focus(), 150);
    } catch (err: any) {
      console.error("[MoveParts] API lookup error:", err);
      setWoData(null);
      setMlDelayPred(null);
      setMlRejPred(null);
      if (!err?.response) {
        setSearchError("Backend / API service is currently unavailable. Please verify connection.");
      } else if (err?.response?.status === 404) {
        setSearchError(err?.response?.data?.detail || `Work Order '${targetWO}' not found in backend.`);
      } else {
        setSearchError(err?.response?.data?.detail || `Error retrieving tracking for Work Order '${targetWO}'.`);
      }
    } finally {
      setLoading(false);
    }
  };

  // Tally-Style Enter Key Handler
  const handleKeyDownEnter = (
    e: React.KeyboardEvent,
    nextTarget: "machine" | "shift" | "operator" | "remarks" | "submit"
  ) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (nextTarget === "machine") {
        selectMachineRef.current?.focus();
      } else if (nextTarget === "shift") {
        selectShiftRef.current?.focus();
      } else if (nextTarget === "operator") {
        inputOperatorRef.current?.focus();
      } else if (nextTarget === "remarks") {
        inputRemarksRef.current?.focus();
      } else if (nextTarget === "submit") {
        btnSubmitRef.current?.focus();
      }
    }
  };

  const handleFormSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!woData) return;

    const moveQtyNum = Number(quantityToMove);

    if (moveQtyNum <= 0) {
      setFormError("Movement quantity must be greater than 0.");
      return;
    }

    const originStageNow = woData.movable_from_stage || woData.current_stage;
    const destStageNow = woData.movable_to_stage || woData.next_allowed_stage;
    const availableNow = woData.movable_from_stage ? woData.movable_wip : woData.available_wip;

    if (moveQtyNum > availableNow) {
      setFormError(
        `Cannot move ${moveQtyNum} pieces. Only ${availableNow} pieces available at stage ${originStageNow}.`
      );
      return;
    }

    if (!destStageNow) {
      setFormError("Terminal Stage — No further movement available for this Work Order.");
      return;
    }

    setSubmitting(true);
    setFormError("");

    const clientReqId = `REQ-MOV-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    try {
      const res = await moveParts({
        wo_number: woData.wo_number,
        from_stage: originStageNow,
        to_stage: destStageNow,
        quantity_moved: moveQtyNum,
        rejected_quantity: 0,
        machine_id: selectedMachine,
        operator_name: operatorName,
        shift: shift,
        remarks: remarks || undefined,
        client_request_id: clientReqId
      });

      setResultData({
        title: "Material Transfer Recorded Successfully",
        movement_id: res.movement_id,
        wo_number: res.wo_number,
        from_stage: res.from_stage,
        to_stage: res.to_stage,
        quantity_moved: res.quantity_moved,
        available_wip_remaining: res.available_wip_remaining,
        to_stage_available_wip: res.to_stage_available_wip,
        message: res.message
      });

      setShowSuccessModal(true);
      lookupWO(woData.wo_number);
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || "Transfer failed. Please check route and WIP balance.");
    } finally {
      setSubmitting(false);
    }
  };

  const isTerminalStage = woData && (!woData.next_allowed_stage || woData.current_stage === "DISPATCH");

  // The actual origin/destination/available-qty for a NEW movement -- the earliest
  // stage (by route sequence) that still has WIP available to move, which can be
  // behind woData.current_stage (see movable_from_stage doc comment on the backend
  // schema). Falls back to current_stage/available_wip when nothing is movable
  // anywhere, so "no movable material" banners still show correct, consistent figures.
  const originStage = woData ? (woData.movable_from_stage || woData.current_stage) : null;
  const destStage = woData ? (woData.movable_to_stage || woData.next_allowed_stage) : null;
  const availableAtOrigin = woData ? (woData.movable_from_stage ? woData.movable_wip : woData.available_wip) : 0;

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Material Logistics
              </span>
              <span className="text-xs text-zinc-400">Strict Sequential Route • Tally Navigation</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Shop Floor Move Parts
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Physical material transfer between manufacturing cells along the OMS-validated dynamic route.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Link
              href="/production/entry"
              className="flex items-center gap-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
            >
              <CheckSquare className="h-4 w-4 text-emerald-600" />
              <span>Record Production</span>
            </Link>

            <button
              type="button"
              onClick={() => setShowQRModal(true)}
              className="flex items-center gap-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              <QrCode className="h-4 w-4 text-blue-600" />
              <span>Scan Barcode / QR</span>
            </button>
          </div>
        </div>

        {/* Search / Lookup Bar */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              lookupWO(searchTerm);
            }}
            className="flex flex-col sm:flex-row gap-3"
          >
            <div className="relative flex-1">
              <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
              <input
                ref={inputSearchRef}
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Enter Work Order Number (e.g. WO-1001, WO-1008)... [Press Enter to find]"
                className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-10 pr-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono font-bold"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="flex items-center justify-center gap-2 rounded-xl bg-blue-600 px-6 py-2.5 text-xs font-bold text-white shadow-sm shadow-blue-500/20 hover:bg-blue-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              {loading ? "Loading..." : "Find Work Order"}
            </button>
          </form>

          {/* Quick WO chips dynamically rendered from backend */}
          {availableWOs.length > 0 && (
            <div className="flex items-center gap-2 mt-3 pt-3 border-t border-zinc-100 dark:border-zinc-800/80 overflow-x-auto text-[11px]">
              <span className="text-zinc-400 whitespace-nowrap">Quick Select:</span>
              {availableWOs.slice(0, 8).map((wo) => (
                <button
                  key={wo.wo_number}
                  type="button"
                  onClick={() => lookupWO(wo.wo_number)}
                  className={`rounded-lg px-2.5 py-1 font-mono font-semibold transition-all cursor-pointer ${
                    woData?.wo_number === wo.wo_number
                      ? "bg-blue-600 text-white"
                      : "bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700"
                  }`}
                >
                  {wo.wo_number} ({wo.current_stage})
                </button>
              ))}
            </div>
          )}

          {searchError && (
            <div className="mt-3 flex items-center gap-2 rounded-lg bg-rose-500/10 border border-rose-500/20 p-2.5 text-xs font-semibold text-rose-500">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{searchError}</span>
            </div>
          )}
        </div>

        {/* Work Order Details & Movement Form */}
        {woData && (
          <div className="space-y-6">
            {/* Header Strip */}
            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-3 border-b border-zinc-100 dark:border-zinc-800">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400">
                      Work Order
                    </span>
                    <h2 className="text-xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                      {woData.wo_number}
                    </h2>
                    <span className="rounded-md bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 text-xs font-bold text-zinc-700 dark:text-zinc-300 font-mono">
                      {woData.part_number} ({woData.grade || "Alloy"})
                    </span>
                  </div>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Customer: <span className="font-semibold text-zinc-800 dark:text-zinc-200">{woData.customer_name}</span> | PO: <span className="font-mono">{woData.customer_po}</span> | Planned: <span className="font-bold text-zinc-900 dark:text-zinc-100">{woData.physical_wo_qty} pcs</span>
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={getRAGVariant(woData.delivery_risk)}>
                    {woData.status.toUpperCase()}
                  </Badge>
                  <span className="text-xs font-bold text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-1 rounded-lg">
                    Yield: {woData.yield_pct}%
                  </span>
                </div>
              </div>

              {/* Dynamic Route Pipeline Visualizer */}
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 block mb-2">
                  Dynamic Route & Stage Sequence:
                </span>
                <div className="flex items-center gap-1.5 overflow-x-auto pb-2">
                  {woData.timeline.map((step: any, i: number) => {
                    const isOrigin = step.stage === originStage;
                    const isDest = step.stage === destStage;
                    const isDone = step.is_completed;

                    return (
                      <React.Fragment key={step.stage}>
                        <div
                          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl border text-xs font-mono font-bold transition-all ${
                            isOrigin
                              ? "bg-blue-600 text-white border-blue-500 shadow-md ring-2 ring-blue-500/30"
                              : isDest
                              ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-400 dark:border-emerald-700"
                              : isDone
                              ? "bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 border-zinc-200 dark:border-zinc-700 opacity-80"
                              : "bg-zinc-50 dark:bg-zinc-950 text-zinc-400 border-zinc-200 dark:border-zinc-800 opacity-50"
                          }`}
                        >
                          <span>{step.stage}</span>
                          {isOrigin && <span className="text-[9px] bg-white/20 px-1 rounded uppercase">From</span>}
                          {isDest && <span className="text-[9px] bg-emerald-600 text-white px-1 rounded uppercase">To</span>}
                        </div>
                        {i < woData.timeline.length - 1 && (
                          <ChevronRight className="h-4 w-4 text-zinc-400 shrink-0" />
                        )}
                      </React.Fragment>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Production & Material Summary -- authoritative breakdown for the
                SELECTED SOURCE stage only (never plant-wide totals), from the same
                get_current_stage_state data source the Production Entry screen uses,
                so the two screens can never disagree. */}
            {stageState && (
              <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
                <div className="flex items-center justify-between pb-3 mb-3 border-b border-zinc-100 dark:border-zinc-800">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">
                    Production &amp; Material Summary — Stage {stageState.stage}
                  </h3>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 text-xs">
                  <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 border border-zinc-200 dark:border-zinc-800 p-3">
                    <span className="block text-[10px] uppercase font-bold text-zinc-400">Target / Required</span>
                    <span className="font-mono font-extrabold text-zinc-900 dark:text-zinc-100 text-sm">{stageState.target_qty} pcs</span>
                  </div>
                  <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 border border-zinc-200 dark:border-zinc-800 p-3">
                    <span className="block text-[10px] uppercase font-bold text-zinc-400">OK Produced</span>
                    <span className="font-mono font-extrabold text-emerald-600 text-sm">{stageState.ok_completed_qty} pcs</span>
                  </div>
                  <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 border border-zinc-200 dark:border-zinc-800 p-3">
                    <span className="block text-[10px] uppercase font-bold text-zinc-400">Rejected</span>
                    <span className="font-mono font-extrabold text-rose-600 text-sm">{stageState.rejected_qty} pcs</span>
                  </div>
                  <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/50 border border-zinc-200 dark:border-zinc-800 p-3">
                    <span className="block text-[10px] uppercase font-bold text-zinc-400">Already Moved</span>
                    <span className="font-mono font-extrabold text-blue-600 text-sm">{stageState.already_moved_qty} pcs</span>
                  </div>
                  <div className="rounded-xl bg-purple-50 dark:bg-purple-950/20 border border-purple-300 dark:border-purple-800 p-3">
                    <span className="block text-[10px] uppercase font-bold text-purple-700 dark:text-purple-400">Available to Move</span>
                    <span className="font-mono font-extrabold text-purple-700 dark:text-purple-400 text-sm">{stageState.available_wip} pcs</span>
                  </div>
                  <div className="rounded-xl bg-amber-50 dark:bg-amber-950/20 border border-amber-300 dark:border-amber-800 p-3">
                    <span className="block text-[10px] uppercase font-bold text-amber-700 dark:text-amber-400">Remaining to Produce</span>
                    <span className="font-mono font-extrabold text-amber-700 dark:text-amber-400 text-sm">{stageState.in_process_qty} pcs</span>
                  </div>
                </div>
              </div>
            )}

            {/* Terminal Stage Banner if at DISPATCH */}
            {isTerminalStage ? (
              <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-6 text-center space-y-2">
                <div className="flex items-center justify-center gap-2 text-amber-600 dark:text-amber-400">
                  <Ban className="h-6 w-6" />
                  <h3 className="text-base font-extrabold">Terminal Stage — No further movement available</h3>
                </div>
                <p className="text-xs text-zinc-600 dark:text-zinc-400 max-w-lg mx-auto">
                  Work Order <strong>{woData.wo_number}</strong> is currently at <strong>{woData.current_stage}</strong>, which is the terminal stage of its manufacturing route. All parts have completed the physical routing pipeline.
                </p>
                <div className="pt-2">
                  <Link
                    href="/production/tracking"
                    className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    <span>View Complete Tracking History</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              </div>
            ) : availableAtOrigin <= 0 ? (
              /* No movable WIP at the current stage -- show the actual reason, not a
                 generic message. Planned/target quantity is never movable WIP; only
                 production actually recorded at this stage is. */
              (() => {
                const curStep = woData.timeline?.find((s: any) => s.stage === originStage);
                const ok = stageState?.ok_completed_qty ?? curStep?.ok_completed_qty ?? 0;
                const rej = stageState?.rejected_qty ?? curStep?.rejected_qty ?? 0;
                const alreadyMoved = stageState?.already_moved_qty ?? 0;

                let reason = "No good material is currently available for movement.";
                if (ok === 0 && rej === 0) {
                  reason = "No good production has been recorded at this stage.";
                } else if (ok > 0 && alreadyMoved >= ok) {
                  reason = "All completed good material has already been moved.";
                } else if (ok === 0 && rej > 0) {
                  reason = "Rejected quantity is not movable good WIP.";
                }

                return (
                  <div className="rounded-2xl border border-amber-500/30 bg-amber-500/10 p-6 text-center space-y-3">
                    <div className="flex items-center justify-center gap-2 text-amber-600 dark:text-amber-400">
                      <Ban className="h-6 w-6" />
                      <h3 className="text-base font-extrabold">No Movable Material at {originStage}</h3>
                    </div>
                    <p className="text-xs text-zinc-600 dark:text-zinc-400 max-w-lg mx-auto font-semibold">
                      {reason}
                    </p>
                    <div className="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs">
                      <div className="rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-4 py-2">
                        <span className="block text-[10px] uppercase font-bold text-zinc-400">Current Stage</span>
                        <span className="font-mono font-extrabold text-blue-600">{originStage}</span>
                      </div>
                      <div className="rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-4 py-2">
                        <span className="block text-[10px] uppercase font-bold text-zinc-400">OK Produced</span>
                        <span className="font-mono font-extrabold text-emerald-600">{ok} pcs</span>
                      </div>
                      <div className="rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-4 py-2">
                        <span className="block text-[10px] uppercase font-bold text-zinc-400">Rejected</span>
                        <span className="font-mono font-extrabold text-rose-600">{rej} pcs</span>
                      </div>
                      <div className="rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-4 py-2">
                        <span className="block text-[10px] uppercase font-bold text-zinc-400">Already Moved</span>
                        <span className="font-mono font-extrabold text-blue-600">{alreadyMoved} pcs</span>
                      </div>
                      <div className="rounded-xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 px-4 py-2">
                        <span className="block text-[10px] uppercase font-bold text-zinc-400">Movable WIP</span>
                        <span className="font-mono font-extrabold text-purple-600">{availableAtOrigin} pcs</span>
                      </div>
                    </div>
                    <div className="pt-2">
                      <Link
                        href="/production/entry"
                        className="inline-flex items-center gap-1.5 text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        <span>Record production at {originStage} to create movable WIP</span>
                        <ArrowRight className="h-3.5 w-3.5" />
                      </Link>
                    </div>
                  </div>
                );
              })()
            ) : (
              /* Physical Movement Execution Grid */
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Stage Transfer Route Card */}
                <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
                  <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400">
                    Routing Direction (OMS Controlled)
                  </span>

                  {/* Transfer Visual Card */}
                  <div className="rounded-xl bg-gradient-to-br from-blue-50 to-indigo-50 dark:from-blue-950/40 dark:to-indigo-950/20 p-4 border border-blue-200 dark:border-blue-900/40 space-y-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <span className="text-[10px] uppercase font-bold text-zinc-400">Origin Stage</span>
                        <p className="text-xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                          {originStage}
                        </p>
                        <p className="text-[11px] font-bold text-blue-600">
                          {availableAtOrigin} pcs available
                        </p>
                      </div>

                      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 text-white shadow-md">
                        <ArrowRightLeft className="h-5 w-5" />
                      </div>

                      <div className="text-right">
                        <span className="text-[10px] uppercase font-bold text-zinc-400">Destination Stage</span>
                        <p className="text-xl font-extrabold text-emerald-600 font-mono">
                          {destStage}
                        </p>
                        <p className="text-[11px] text-zinc-500">
                          Next route target
                        </p>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-blue-200/60 dark:border-blue-900/60 text-[11px] text-zinc-600 dark:text-zinc-400 flex items-center gap-1.5">
                      <ShieldCheck className="h-3.5 w-3.5 text-blue-600 shrink-0" />
                      <span>Route validation is locked. Stage jumping is prevented.</span>
                    </div>
                  </div>

                  {/* Tally Hint */}
                  <div className="p-3 rounded-xl bg-zinc-100 dark:bg-zinc-800/60 text-[11px] text-zinc-500">
                    <p className="font-bold text-zinc-700 dark:text-zinc-300 mb-1">⚡ Fast Keyboard Entry:</p>
                    <p>Enter quantity and press <kbd className="px-1.5 py-0.5 bg-white dark:bg-zinc-900 border rounded font-mono text-[10px]">Enter</kbd> to cycle through inputs and submit instantly.</p>
                  </div>
                </div>

                {/* Material Movement Form */}
                <div className="lg:col-span-2">
                  <form
                    onSubmit={handleFormSubmit}
                    className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
                  >
                    <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
                      <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50 flex items-center gap-2">
                        <ArrowRightLeft className="h-4 w-4 text-blue-600" />
                        <span>Physical Material Transfer</span>
                      </h3>
                      <span className="text-xs font-mono font-bold text-blue-600 dark:text-blue-400">
                        {originStage} ➔ {destStage}
                      </span>
                    </div>

                    {formError && (
                      <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                        {formError}
                      </div>
                    )}

                    {/* Quantity to Move */}
                    <div>
                      <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                        <span>Quantity to Move *</span>
                        <span className="text-[11px] text-zinc-400">
                          Available at {originStage}: <strong>{availableAtOrigin} pcs</strong>
                        </span>
                      </label>
                      <input
                        ref={inputQtyRef}
                        type="number"
                        required
                        min={1}
                        max={availableAtOrigin}
                        value={quantityToMove}
                        onChange={(e) => setQuantityToMove(e.target.value === "" ? "" : Number(e.target.value))}
                        onKeyDown={(e) => handleKeyDownEnter(e, "machine")}
                        placeholder={`1 to ${availableAtOrigin}`}
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-4 py-2.5 text-base font-extrabold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                      />
                    </div>

                    {/* Machine, Shift, Operator Grid */}
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      <div>
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          Destination Machine / Bay
                        </label>
                        <select
                          ref={selectMachineRef}
                          value={selectedMachine}
                          onChange={(e) => setSelectedMachine(e.target.value)}
                          onKeyDown={(e) => handleKeyDownEnter(e, "shift")}
                          className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 font-medium focus:border-blue-500 focus:outline-none"
                        >
                          {MACHINES.map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                        </select>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          Shift
                        </label>
                        <select
                          ref={selectShiftRef}
                          value={shift}
                          onChange={(e) => setShift(e.target.value)}
                          onKeyDown={(e) => handleKeyDownEnter(e, "operator")}
                          className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 font-medium focus:border-blue-500 focus:outline-none"
                        >
                          <option value="Shift A">Shift A (06:00 - 14:00)</option>
                          <option value="Shift B">Shift B (14:00 - 22:00)</option>
                          <option value="Shift C">Shift C (22:00 - 06:00)</option>
                        </select>
                      </div>

                      <div>
                        <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                          Logistics / Operator
                        </label>
                        <input
                          ref={inputOperatorRef}
                          type="text"
                          value={operatorName}
                          onChange={(e) => setOperatorName(e.target.value)}
                          onKeyDown={(e) => handleKeyDownEnter(e, "remarks")}
                          className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:border-blue-500 focus:outline-none"
                        />
                      </div>
                    </div>

                    {/* Remarks */}
                    <div>
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        Movement Remarks / Notes
                      </label>
                      <input
                        ref={inputRemarksRef}
                        type="text"
                        value={remarks}
                        onChange={(e) => setRemarks(e.target.value)}
                        onKeyDown={(e) => handleKeyDownEnter(e, "submit")}
                        placeholder="e.g. Batch moved to CNC bay for turning"
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:border-blue-500 focus:outline-none"
                      />
                    </div>

                    {/* Submit Button */}
                    <div className="pt-2">
                      <button
                        ref={btnSubmitRef}
                        type="submit"
                        disabled={submitting || availableAtOrigin <= 0 || !destStage}
                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3.5 text-sm font-bold text-white shadow-lg shadow-blue-500/25 hover:bg-blue-500 focus:outline-none disabled:opacity-50 transition-all cursor-pointer"
                      >
                        <ArrowRightLeft className="h-4 w-4" />
                        <span>
                          {submitting
                            ? "Validating & Moving..."
                            : `Transfer ${quantityToMove || 0} pcs to Stage ${destStage}`}
                        </span>
                      </button>
                    </div>
                  </form>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Success Confirmation Modal */}
        <Modal
          isOpen={showSuccessModal}
          onClose={() => setShowSuccessModal(false)}
          title={resultData?.title || "Movement Successful"}
          subtitle={`Movement ID: ${resultData?.movement_id}`}
        >
          <div className="space-y-4">
            <div className="flex items-center justify-center p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/50">
              <div className="text-center">
                <CheckCircle2 className="h-10 w-10 text-emerald-500 mx-auto" />
                <p className="text-sm font-bold text-emerald-800 dark:text-emerald-300 mt-2">
                  {resultData?.message}
                </p>
              </div>
            </div>

            <div className="space-y-2 text-xs border border-zinc-200 dark:border-zinc-800 rounded-xl p-3.5">
              <div className="flex justify-between">
                <span className="text-zinc-400">Work Order:</span>
                <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{resultData?.wo_number}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Routing:</span>
                <span className="font-bold text-blue-600">{resultData?.from_stage} ➔ {resultData?.to_stage}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Quantity Transferred:</span>
                <span className="font-bold text-zinc-900 dark:text-zinc-100">{resultData?.quantity_moved} pcs</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Remaining at {resultData?.from_stage}:</span>
                <span className="font-bold text-zinc-900 dark:text-zinc-100">{resultData?.available_wip_remaining} pcs</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Now Available at {resultData?.to_stage}:</span>
                <span className="font-bold text-emerald-600">{resultData?.to_stage_available_wip} pcs</span>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowSuccessModal(false)}
                className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 cursor-pointer"
              >
                Continue Movement
              </button>
            </div>
          </div>
        </Modal>

        {/* QR Scanner Modal */}
        <Modal
          isOpen={showQRModal}
          onClose={() => setShowQRModal(false)}
          title="Scan Work Order QR / Barcode"
          subtitle="Point scanner at router sheet or enter code manually"
        >
          <div className="space-y-4">
            <div className="flex flex-col items-center justify-center p-6 border-2 border-dashed border-zinc-300 dark:border-zinc-700 rounded-2xl bg-zinc-50 dark:bg-zinc-950 text-center">
              <QrCode className="h-16 w-16 text-blue-600 animate-pulse mb-3" />
              <p className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                Camera / Barcode Scanner Active
              </p>
              <p className="text-[11px] text-zinc-400 mt-1">
                Scan standard 1D / 2D barcode on shop-floor traveller sheet
              </p>
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                Or Type / Paste Scanned Barcode Payload:
              </label>
              <div className="flex gap-2 mt-1.5">
                <input
                  type="text"
                  value={qrInput}
                  onChange={(e) => setQrInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && qrInput.trim()) {
                      e.preventDefault();
                      lookupWO(qrInput.trim());
                      setShowQRModal(false);
                      setQrInput("");
                    }
                  }}
                  placeholder="e.g. WO-1001"
                  className="flex-1 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
                <button
                  type="button"
                  onClick={() => {
                    if (qrInput.trim()) {
                      lookupWO(qrInput.trim());
                      setShowQRModal(false);
                      setQrInput("");
                    }
                  }}
                  className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 cursor-pointer"
                >
                  Load
                </button>
              </div>
            </div>
          </div>
        </Modal>
      </div>
    </AppShell>
  );
}

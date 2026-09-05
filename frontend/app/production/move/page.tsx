"use client";
import React, { useState, useEffect, useRef } from "react";
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
  TrendingUp,
  BrainCircuit,
  Sparkles,
  ClipboardList,
  CheckSquare
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import {
  getWorkOrders,
  getWorkOrderTracking,
  moveParts,
  recordStageProduction,
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

const DEFECT_CODES = [
  { code: "DEF-POROSITY", label: "DEF-POROSITY — Casting Gas Porosity" },
  { code: "DEF-SURF-BLOW", label: "DEF-SURF-BLOW — Surface Blowholes / Pits" },
  { code: "DEF-DIM-OUT", label: "DEF-DIM-OUT — Dimensional Tolerance Out" },
  { code: "DEF-INCLUSION", label: "DEF-INCLUSION — Slag / Oxide Inclusion" },
  { code: "DEF-CRACK", label: "DEF-CRACK — Thermal Stress Crack" },
  { code: "DEF-FINISH", label: "DEF-FINISH — Surface Roughness (Ra) High" },
];

export default function MovePartsPage() {
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [woData, setWoData] = useState<any>(null);
  const [mlDelayPred, setMlDelayPred] = useState<any>(null);
  const [mlRejPred, setMlRejPred] = useState<any>(null);
  const [availableWOs, setAvailableWOs] = useState<any[]>([]);
  const [searchError, setSearchError] = useState("");

  // Operation Mode: "MOVE" (Physical transfer) or "ENTRY" (Record stage completion)
  const [operationMode, setOperationMode] = useState<"MOVE" | "ENTRY">("MOVE");

  // Form State
  const [quantityToMove, setQuantityToMove] = useState<number | "">("");
  const [rejectedQty, setRejectedQty] = useState<number>(0);
  const [selectedMachine, setSelectedMachine] = useState<string>("M-LATHE-01");
  const [operatorName, setOperatorName] = useState("Ramesh Kumar (Op)");
  const [shift, setShift] = useState("Shift A");
  const [defectCode, setDefectCode] = useState("DEF-POROSITY");
  const [remarks, setRemarks] = useState("");

  // Submission & Result Modal
  const [submitting, setSubmitting] = useState(false);
  const [resultData, setResultData] = useState<any>(null);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [showQRModal, setShowQRModal] = useState(false);
  const [formError, setFormError] = useState("");

  // Tally-Style Keyboard Enter Navigation Refs
  const inputSearchRef = useRef<HTMLInputElement>(null);
  const inputGoodQtyRef = useRef<HTMLInputElement>(null);
  const inputRejQtyRef = useRef<HTMLInputElement>(null);
  const selectDefectRef = useRef<HTMLSelectElement>(null);
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

      // Preset default move qty to available WIP
      setQuantityToMove(data.available_wip > 0 ? data.available_wip : "");
      setRejectedQty(0);
      
      // Preset machine based on current/next stage
      const matchingMach = MACHINES.find((m) => m.stage === data.current_stage);
      if (matchingMach) setSelectedMachine(matchingMach.id);

      // Asynchronously fetch ML risk insights
      predictDelay(data.wo_number)
        .then((pred) => setMlDelayPred(pred))
        .catch(() => setMlDelayPred(null));

      predictRejection({ wo_number: data.wo_number, target_stage: data.current_stage })
        .then((pred) => setMlRejPred(pred))
        .catch(() => setMlRejPred(null));

      // Auto focus Good Qty field on successful load
      setTimeout(() => inputGoodQtyRef.current?.focus(), 150);

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
  const handleKeyDownEnter = (e: React.KeyboardEvent, nextTarget: "rejQty" | "defect" | "machine" | "shift" | "operator" | "remarks" | "submit") => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (nextTarget === "rejQty") {
        inputRejQtyRef.current?.focus();
      } else if (nextTarget === "defect") {
        if (rejectedQty > 0) {
          selectDefectRef.current?.focus();
        } else {
          selectMachineRef.current?.focus();
        }
      } else if (nextTarget === "machine") {
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
    const rejQtyNum = Number(rejectedQty);

    if (moveQtyNum <= 0 && rejQtyNum <= 0) {
      setFormError("Please enter a valid quantity (> 0).");
      return;
    }

    if (moveQtyNum + rejQtyNum > woData.available_wip) {
      setFormError(
        `Cannot process ${moveQtyNum + rejQtyNum} pieces (${moveQtyNum} Good + ${rejQtyNum} Rejected). Only ${woData.available_wip} pieces are available at stage ${woData.current_stage}.`
      );
      return;
    }

    setSubmitting(true);
    setFormError("");

    const clientReqId = `REQ-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;

    try {
      if (operationMode === "MOVE") {
        if (!woData.next_allowed_stage) {
          setFormError("Work Order is already at the final stage or completed.");
          setSubmitting(false);
          return;
        }

        const res = await moveParts({
          wo_number: woData.wo_number,
          from_stage: woData.current_stage,
          to_stage: woData.next_allowed_stage,
          quantity_moved: moveQtyNum,
          rejected_quantity: rejQtyNum,
          machine_id: selectedMachine,
          operator_name: operatorName,
          shift: shift,
          defect_code: rejQtyNum > 0 ? defectCode : undefined,
          remarks: remarks || undefined,
          client_request_id: clientReqId
        });

        setResultData({
          type: "MOVE",
          title: "Part Movement Recorded",
          movement_id: res.movement_id,
          wo_number: res.wo_number,
          from_stage: res.from_stage,
          to_stage: res.to_stage,
          quantity_moved: res.quantity_moved,
          rejected_quantity: res.rejected_quantity,
          available_wip_remaining: res.available_wip_remaining,
          to_stage_available_wip: res.to_stage_available_wip,
          message: res.message
        });
      } else {
        // Record Stage Production Entry (Processing at stage without immediate transfer)
        const res = await recordStageProduction({
          wo_number: woData.wo_number,
          stage: woData.current_stage,
          good_qty: moveQtyNum,
          rejected_quantity: rejQtyNum,
          machine_id: selectedMachine,
          operator_name: operatorName,
          shift: shift,
          defect_code: rejQtyNum > 0 ? defectCode : undefined,
          remarks: remarks || undefined,
          client_request_id: clientReqId
        });

        setResultData({
          type: "ENTRY",
          title: "Stage Production Result Recorded",
          movement_id: res.entry_id,
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
      }

      setShowSuccessModal(true);
      lookupWO(woData.wo_number);
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || "Operation failed. Please check validation rules.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Shop Floor Execution
              </span>
              <span className="text-xs text-zinc-400">Tally-Style Keyboard Operation • OMS Authoritative</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Production Entry & Stage Movement
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Record stage-specific OK/rejection results and physical transfers with strict route adherence and zero cumulative distortion.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Mode Toggle */}
            <div className="inline-flex rounded-xl bg-zinc-100 dark:bg-zinc-800 p-1 border border-zinc-200 dark:border-zinc-700 text-xs font-bold">
              <button
                type="button"
                onClick={() => setOperationMode("MOVE")}
                className={`rounded-lg px-3 py-1.5 transition-all cursor-pointer ${
                  operationMode === "MOVE"
                    ? "bg-blue-600 text-white shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                }`}
              >
                Move & Transfer
              </button>
              <button
                type="button"
                onClick={() => setOperationMode("ENTRY")}
                className={`rounded-lg px-3 py-1.5 transition-all cursor-pointer ${
                  operationMode === "ENTRY"
                    ? "bg-blue-600 text-white shadow-sm"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100"
                }`}
              >
                Record Stage Entry
              </button>
            </div>

            <button
              type="button"
              onClick={() => setShowQRModal(true)}
              className="flex items-center gap-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
            >
              <QrCode className="h-4 w-4 text-blue-600" />
              <span>Scan QR</span>
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

        {/* Work Order Card & Move Form */}
        {woData && (
          <div className="space-y-6">
            {/* Operator Summary Header */}
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
                    Customer: <span className="font-semibold text-zinc-800 dark:text-zinc-200">{woData.customer_name}</span> | PO: <span className="font-mono">{woData.customer_po}</span> | Planned Qty: <span className="font-bold text-zinc-900 dark:text-zinc-100">{woData.physical_wo_qty} pcs</span>
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

              {/* PART 20: LIVE STAGE BOARD (STAGE | TARGET | OK | REJECT | STATUS) */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-400 flex items-center gap-1.5">
                    <ClipboardList className="h-3.5 w-3.5 text-blue-500" />
                    <span>Live Stage Board (Authoritative OMS State — No Cumulative Distortion):</span>
                  </span>
                  <span className="text-[10px] text-zinc-400">
                    Route: {woData.timeline.map((s: any) => s.stage).join(" ➔ ")}
                  </span>
                </div>

                <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-zinc-50 dark:bg-zinc-950/80 border-b border-zinc-200 dark:border-zinc-800 text-zinc-500 uppercase text-[10px] font-bold">
                      <tr>
                        <th className="py-2.5 px-3">Stage</th>
                        <th className="py-2.5 px-3 text-right">Target Qty</th>
                        <th className="py-2.5 px-3 text-right text-emerald-600">OK Completed</th>
                        <th className="py-2.5 px-3 text-right text-rose-600">Rejection</th>
                        <th className="py-2.5 px-3 text-right text-blue-600">Live Available WIP</th>
                        <th className="py-2.5 px-3">Live Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                      {woData.timeline && woData.timeline.map((stgItem: any) => {
                        const isCur = stgItem.stage === woData.current_stage;
                        return (
                          <tr
                            key={stgItem.stage}
                            className={`transition-colors ${
                              isCur
                                ? "bg-blue-50/50 dark:bg-blue-950/30 font-bold"
                                : "hover:bg-zinc-50/40 dark:hover:bg-zinc-800/30"
                            }`}
                          >
                            <td className="py-2.5 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                              {isCur && <span className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />}
                              <span>{stgItem.stage}</span>
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono text-zinc-700 dark:text-zinc-300">
                              {stgItem.target_qty}
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-emerald-600 dark:text-emerald-400">
                              {stgItem.ok_completed_qty}
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-rose-600 dark:text-rose-400">
                              {stgItem.rejected_qty}
                            </td>
                            <td className="py-2.5 px-3 text-right font-mono font-bold text-blue-600 dark:text-blue-400">
                              {stgItem.on_hand_wip}
                            </td>
                            <td className="py-2.5 px-3">
                              <Badge
                                variant={
                                  stgItem.is_completed
                                    ? "green"
                                    : isCur
                                    ? "blue"
                                    : "gray"
                                }
                                size="sm"
                              >
                                {stgItem.is_completed ? "COMPLETED" : (isCur ? "IN PROCESS" : "WAITING")}
                              </Badge>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Machine Learning & Statistical Risk Preview Banner */}
              {(mlDelayPred || mlRejPred) && (
                <div className="rounded-xl border border-purple-500/20 bg-purple-500/5 p-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-xs">
                  <div className="flex items-center gap-2">
                    <BrainCircuit className="h-4 w-4 text-purple-500 shrink-0" />
                    <div>
                      <span className="font-bold text-purple-400 uppercase text-[10px]">
                        AI & ML Manufacturing Intelligence:
                      </span>
                      <p className="text-zinc-300 text-xs">
                        {mlDelayPred?.delay_probability_pct !== undefined && (
                          <span>Delay Risk: <strong className="text-white">{mlDelayPred.delay_probability_pct}% ({mlDelayPred.risk_level})</strong> | Est Completion: <strong className="text-white">{mlDelayPred.expected_completion_date}</strong>. </span>
                        )}
                        {mlRejPred?.predicted_rejection_rate_pct !== undefined && (
                          <span>Predicted Scrap at {mlRejPred.stage}: <strong className="text-white">{mlRejPred.predicted_rejection_rate_pct}% ({mlRejPred.expected_rejection_qty} pcs)</strong>.</span>
                        )}
                      </p>
                    </div>
                  </div>
                  <span className="text-[10px] text-purple-400/80 bg-purple-500/10 px-2 py-0.5 rounded border border-purple-500/20 whitespace-nowrap">
                    Gov: {mlDelayPred?.governance?.status || "VALIDATED"}
                  </span>
                </div>
              )}
            </div>

            {/* PART 18 & 19: OPERATOR TALLY-STYLE KEYBOARD ENTRY FORM */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Live Status Box */}
              <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
                <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400">
                  Current Execution State
                </span>
                
                <div className="rounded-xl bg-blue-50 dark:bg-blue-950/40 p-4 border border-blue-200 dark:border-blue-900/40 space-y-2">
                  <p className="text-[10px] uppercase font-bold text-blue-600 dark:text-blue-400">Active Stage</p>
                  <p className="text-2xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                    Stage {woData.current_stage}
                  </p>
                  <p className="text-xs font-bold text-emerald-600">
                    {woData.available_wip} pieces available at {woData.current_stage}
                  </p>
                </div>

                {operationMode === "MOVE" ? (
                  <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/60 p-4 border border-zinc-200 dark:border-zinc-800 space-y-2">
                    <p className="text-[10px] uppercase font-bold text-zinc-400">Destination Stage</p>
                    <p className="text-2xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                      Stage {woData.next_allowed_stage || "Completed"}
                    </p>
                    <p className="text-[11px] text-zinc-400">
                      Next route step locked by OMS
                    </p>
                  </div>
                ) : (
                  <div className="rounded-xl bg-amber-50 dark:bg-amber-950/40 p-4 border border-amber-200 dark:border-amber-900/40 space-y-2">
                    <p className="text-[10px] uppercase font-bold text-amber-700 dark:text-amber-400">Mode: Stage Entry</p>
                    <p className="text-xs text-zinc-600 dark:text-zinc-300">
                      Good parts processed will be held in <strong>On-Hand at Stage {woData.current_stage}</strong> for later physical movement.
                    </p>
                  </div>
                )}

                <div className="p-3 rounded-xl bg-zinc-100 dark:bg-zinc-800/60 text-[11px] text-zinc-500">
                  <p className="font-bold text-zinc-700 dark:text-zinc-300 mb-1">⚡ Tally Navigation Tip:</p>
                  <p>Type values and press <kbd className="px-1.5 py-0.5 bg-white dark:bg-zinc-900 border rounded font-mono text-[10px]">Enter</kbd> to jump between fields seamlessly.</p>
                </div>
              </div>

              {/* Right Entry Form */}
              <div className="lg:col-span-2">
                <form
                  onSubmit={handleFormSubmit}
                  className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
                >
                  <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
                    <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50 flex items-center gap-2">
                      <CheckSquare className="h-4 w-4 text-blue-600" />
                      <span>{operationMode === "MOVE" ? "Stage Transfer Entry" : "Stage Production Result"}</span>
                    </h3>
                    <span className="text-xs font-bold text-blue-600 dark:text-blue-400 font-mono">
                      {operationMode === "MOVE" ? `Transfer ${woData.current_stage} ➔ ${woData.next_allowed_stage}` : `Process @ ${woData.current_stage}`}
                    </span>
                  </div>

                  {formError && (
                    <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                      {formError}
                    </div>
                  )}

                  {/* Quantities Row */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                        <span>{operationMode === "MOVE" ? "Good Qty to Move *" : "Good Qty Completed *"}</span>
                        <span className="text-[11px] text-zinc-400">Available: {woData.available_wip}</span>
                      </label>
                      <input
                        ref={inputGoodQtyRef}
                        type="number"
                        required
                        min={0}
                        max={woData.available_wip}
                        value={quantityToMove}
                        onChange={(e) => setQuantityToMove(e.target.value === "" ? "" : Number(e.target.value))}
                        onKeyDown={(e) => handleKeyDownEnter(e, "rejQty")}
                        placeholder="e.g. 50"
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-4 py-2.5 text-base font-extrabold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                        Rejected Quantity at Stage {woData.current_stage}
                      </label>
                      <input
                        ref={inputRejQtyRef}
                        type="number"
                        min={0}
                        value={rejectedQty}
                        onChange={(e) => setRejectedQty(Number(e.target.value))}
                        onKeyDown={(e) => handleKeyDownEnter(e, "defect")}
                        placeholder="0"
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-4 py-2.5 text-base font-bold text-rose-600 dark:text-rose-400 focus:border-rose-500 focus:outline-none focus:ring-1 focus:ring-rose-500 font-mono"
                      />
                    </div>
                  </div>

                  {/* Defect Selection if Rejection > 0 */}
                  {rejectedQty > 0 && (
                    <div className="rounded-xl bg-rose-50 dark:bg-rose-950/40 p-4 border border-rose-200 dark:border-rose-900/50 space-y-2">
                      <label className="text-xs font-bold text-rose-700 dark:text-rose-400">
                        Select Rejection Defect Code (Auto-logs NC in Quality Tracker) *
                      </label>
                      <select
                        ref={selectDefectRef}
                        value={defectCode}
                        onChange={(e) => setDefectCode(e.target.value)}
                        onKeyDown={(e) => handleKeyDownEnter(e, "machine")}
                        className="w-full rounded-lg border border-rose-300 dark:border-rose-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-semibold text-rose-700 dark:text-rose-300 focus:outline-none"
                      >
                        {DEFECT_CODES.map((d) => (
                          <option key={d.code} value={d.code}>
                            {d.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {/* Machine, Operator, Shift Grid */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        Machining Cell
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
                        Operator
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
                      Floor Remarks / Notes
                    </label>
                    <input
                      ref={inputRemarksRef}
                      type="text"
                      value={remarks}
                      onChange={(e) => setRemarks(e.target.value)}
                      onKeyDown={(e) => handleKeyDownEnter(e, "submit")}
                      placeholder="e.g. Partial batch completed, transferred to next cell"
                      className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:border-blue-500 focus:outline-none"
                    />
                  </div>

                  {/* Action Buttons */}
                  <div className="pt-2">
                    <button
                      ref={btnSubmitRef}
                      type="submit"
                      disabled={submitting || woData.available_wip <= 0 || (operationMode === "MOVE" && !woData.next_allowed_stage)}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3.5 text-sm font-bold text-white shadow-lg shadow-blue-500/25 hover:bg-blue-500 focus:outline-none disabled:opacity-50 transition-all cursor-pointer"
                    >
                      <ArrowRightLeft className="h-4 w-4" />
                      <span>
                        {submitting
                          ? "Validating & Recording..."
                          : operationMode === "MOVE"
                          ? `Confirm & Move to Stage ${woData.next_allowed_stage || "Next"}`
                          : `Save Stage ${woData.current_stage} Production Result`}
                      </span>
                    </button>
                  </div>
                </form>
              </div>
            </div>
          </div>
        )}

        {/* Success Confirmation Modal */}
        <Modal
          isOpen={showSuccessModal}
          onClose={() => setShowSuccessModal(false)}
          title={resultData?.title || "Transaction Successful"}
          subtitle={`ID: ${resultData?.movement_id}`}
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
              {resultData?.type === "MOVE" ? (
                <>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Transfer Route:</span>
                    <span className="font-bold text-blue-600">{resultData?.from_stage} ➔ {resultData?.to_stage}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Good Quantity Transferred:</span>
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
                </>
              ) : (
                <>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Production Stage:</span>
                    <span className="font-bold text-blue-600">{resultData?.stage}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Good Quantity Processed:</span>
                    <span className="font-bold text-emerald-600">{resultData?.good_qty} pcs</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">Stage Rejection:</span>
                    <span className="font-bold text-rose-600">{resultData?.rejected_quantity} pcs</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-zinc-400">On-Hand Ready to Transfer:</span>
                    <span className="font-bold text-blue-600">{resultData?.stage_onhand_available} pcs</span>
                  </div>
                </>
              )}
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowSuccessModal(false)}
                className="rounded-xl bg-blue-600 px-5 py-2.5 text-xs font-bold text-white hover:bg-blue-500 transition-colors cursor-pointer"
              >
                Close & Next Move
              </button>
            </div>
          </div>
        </Modal>

        {/* QR Scan Simulation Modal */}
        <Modal
          isOpen={showQRModal}
          onClose={() => setShowQRModal(false)}
          title="QR & Barcode Scanner"
          subtitle="Align the floor traveller QR code within camera frame"
        >
          <div className="space-y-4 text-center">
            <div className="relative mx-auto h-52 w-52 rounded-2xl border-2 border-dashed border-blue-500 bg-zinc-950 flex flex-col items-center justify-center p-4">
              <QrCode className="h-20 w-20 text-blue-400 animate-pulse" />
              <p className="text-[11px] text-zinc-400 mt-2">Camera Optical Lens Ready</p>
            </div>

            <div className="text-xs text-zinc-500">
              <p className="font-semibold text-zinc-400">Simulate Scanning Floor Barcode:</p>
              <div className="flex justify-center flex-wrap gap-2 mt-2">
                {availableWOs.slice(0, 8).map((wo) => (
                  <button
                    key={wo.wo_number}
                    type="button"
                    onClick={() => {
                      lookupWO(wo.wo_number);
                      setShowQRModal(false);
                    }}
                    className="rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 py-1 font-mono text-xs font-bold text-white hover:bg-zinc-700 cursor-pointer"
                  >
                    Scan {wo.wo_number}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </Modal>
      </div>
    </AppShell>
  );
}

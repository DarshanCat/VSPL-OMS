"use client";
import React, { useState, useEffect } from "react";
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
  Sparkles
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import {
  getWorkOrders,
  getWorkOrderTracking,
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
  const [moveResult, setMoveResult] = useState<any>(null);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [showQRModal, setShowQRModal] = useState(false);
  const [formError, setFormError] = useState("");

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

    // 1. Immediately synchronize search input and reset states
    setSearchTerm(targetWO);
    setLoading(true);
    setSearchError("");
    setFormError("");
    setMoveResult(null);

    // 2. Logging for end-to-end data flow inspection
    console.log("[MoveParts] Quick Select clicked WO ID:", targetWO);
    console.log("[MoveParts] Search input value:", targetWO);
    console.log("[MoveParts] API request URL:", `/api/v1/work-orders/${encodeURIComponent(targetWO)}/tracking`);

    try {
      const data = await getWorkOrderTracking(targetWO);
      console.log("[MoveParts] API response:", data);

      setWoData(data);
      setSearchTerm(data.wo_number);
      // Preset default move qty to available WIP
      setQuantityToMove(data.available_wip > 0 ? data.available_wip : "");
      setRejectedQty(0);
      
      // Preset machine based on next stage
      const matchingMach = MACHINES.find((m) => m.stage === data.current_stage);
      if (matchingMach) setSelectedMachine(matchingMach.id);

      // 3. Fetch asynchronous ML Predictions for this Work Order
      predictDelay(data.wo_number)
        .then((pred) => setMlDelayPred(pred))
        .catch(() => setMlDelayPred(null));

      predictRejection({ wo_number: data.wo_number, target_stage: data.current_stage })
        .then((pred) => setMlRejPred(pred))
        .catch(() => setMlRejPred(null));

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

  const handleMoveSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!woData) return;

    const moveQtyNum = Number(quantityToMove);
    const rejQtyNum = Number(rejectedQty);

    if (moveQtyNum <= 0 && rejQtyNum <= 0) {
      setFormError("Please enter a valid quantity to move or reject (> 0).");
      return;
    }

    if (moveQtyNum + rejQtyNum > woData.available_wip) {
      setFormError(
        `Cannot move ${moveQtyNum} (with ${rejQtyNum} rejected). Only ${woData.available_wip} pieces are available at stage ${woData.current_stage}.`
      );
      return;
    }

    if (!woData.next_allowed_stage) {
      setFormError("Work Order is already at the final stage or closed.");
      return;
    }

    setSubmitting(true);
    setFormError("");

    try {
      const clientReqId = `REQ-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
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

      setMoveResult(res);
      setShowSuccessModal(true);
      // Reload WO tracking data to update UI
      lookupWO(woData.wo_number);
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || "Movement failed. Please check validation rules.");
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
              <span className="text-xs text-zinc-400">Physical Part Movement & Verification</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Shop Floor Move & Quality Verification
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Record physical batch transfers with authoritative OMS balance, stage-isolated rejection tracking, and ML delay risk intelligence.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setShowQRModal(true)}
            className="flex items-center gap-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-4 py-2.5 text-xs font-bold text-zinc-700 dark:text-zinc-300 shadow-sm hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors cursor-pointer"
          >
            <QrCode className="h-4 w-4 text-blue-600" />
            <span>Scan QR / Barcode</span>
          </button>
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
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Enter Work Order Number (e.g. WO-1001, WO-1008)..."
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
            {/* Section 19: Operator Summary & Stage-Wise OMS Breakdown Cards */}
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
                    Customer: <span className="font-semibold text-zinc-800 dark:text-zinc-200">{woData.customer_name}</span> | PO: <span className="font-mono">{woData.customer_po}</span> | Released Qty: <span className="font-bold text-zinc-900 dark:text-zinc-100">{woData.physical_wo_qty} pcs</span>
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

              {/* Stage-wise Breakdown Grid (Target, OK Completed, Rejection, Live Status) */}
              <div>
                <p className="text-[11px] font-bold uppercase tracking-wider text-zinc-400 mb-2">
                  Stage-wise Manufacturing Results (OMS Deterministic Engine):
                </p>
                <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-2.5">
                  {woData.timeline && woData.timeline.map((stgItem: any) => {
                    const isCur = stgItem.stage === woData.current_stage;
                    return (
                      <div
                        key={stgItem.stage}
                        className={`rounded-xl p-3 border text-center transition-all ${
                          isCur
                            ? "border-blue-500 bg-blue-500/10 ring-2 ring-blue-500/20"
                            : "border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/60"
                        }`}
                      >
                        <div className="flex items-center justify-between text-[10px] font-bold text-zinc-400 mb-1">
                          <span>STAGE</span>
                          <span className={`px-1.5 py-0.2 rounded font-mono ${isCur ? "bg-blue-600 text-white" : "bg-zinc-200 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400"}`}>
                            {stgItem.stage}
                          </span>
                        </div>

                        {/* Large Metric Display */}
                        <div className="space-y-1 my-1.5">
                          <div className="text-left">
                            <span className="text-[9px] text-zinc-400 uppercase font-semibold">Target</span>
                            <p className="text-xs font-bold text-zinc-800 dark:text-zinc-200 font-mono">
                              {stgItem.target_qty}
                            </p>
                          </div>
                          <div className="text-left">
                            <span className="text-[9px] text-zinc-400 uppercase font-semibold">OK Completed</span>
                            <p className="text-xs font-extrabold text-emerald-600 dark:text-emerald-400 font-mono">
                              {stgItem.ok_completed_qty}
                            </p>
                          </div>
                          <div className="text-left">
                            <span className="text-[9px] text-zinc-400 uppercase font-semibold">Rejection</span>
                            <p className="text-xs font-extrabold text-rose-600 dark:text-rose-400 font-mono">
                              {stgItem.rejected_qty}
                            </p>
                          </div>
                        </div>

                        <div className="pt-1.5 border-t border-zinc-200 dark:border-zinc-800 text-[10px]">
                          <span className={`font-semibold ${
                            stgItem.is_completed
                              ? "text-emerald-600"
                              : isCur
                              ? "text-blue-600 font-bold"
                              : "text-zinc-400"
                          }`}>
                            {stgItem.is_completed ? "Completed" : (isCur ? "Active (Live)" : "Pending")}
                          </span>
                        </div>
                      </div>
                    );
                  })}
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
                          <span>Predicted Quality Scrap at {mlRejPred.stage}: <strong className="text-white">{mlRejPred.predicted_rejection_rate_pct}% ({mlRejPred.expected_rejection_qty} pcs)</strong>.</span>
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

            {/* Transfer Execution Form */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
              {/* Left Current Buffer Info */}
              <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-4">
                <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 dark:text-blue-400">
                  Live Buffer Execution
                </span>
                
                <div className="rounded-xl bg-blue-50 dark:bg-blue-950/40 p-4 border border-blue-200 dark:border-blue-900/40 space-y-2">
                  <p className="text-[10px] uppercase font-bold text-blue-600 dark:text-blue-400">Current Stage</p>
                  <p className="text-2xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                    Stage {woData.current_stage}
                  </p>
                  <p className="text-xs font-bold text-emerald-600">
                    {woData.available_wip} pieces available to move
                  </p>
                </div>

                <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950/60 p-4 border border-zinc-200 dark:border-zinc-800 space-y-2">
                  <p className="text-[10px] uppercase font-bold text-zinc-400">Next Route Stage</p>
                  <p className="text-2xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                    Stage {woData.next_allowed_stage || "Completed"}
                  </p>
                  <p className="text-[11px] text-zinc-400">
                    Route Locked & Enforced by OMS
                  </p>
                </div>
              </div>

              {/* Right Move Execution Form */}
              <div className="lg:col-span-2">
                <form
                  onSubmit={handleMoveSubmit}
                  className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
                >
                  <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
                    <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50">
                      Stage Transfer Confirmation
                    </h3>
                    <span className="text-xs font-bold text-blue-600 dark:text-blue-400 font-mono">
                      Step {woData.current_stage} ➔ {woData.next_allowed_stage}
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
                        <span>Quantity to Move (Good / OK) *</span>
                        <span className="text-[11px] text-zinc-400">Max: {woData.available_wip}</span>
                      </label>
                      <input
                        type="number"
                        required
                        min={1}
                        max={woData.available_wip}
                        value={quantityToMove}
                        onChange={(e) => setQuantityToMove(e.target.value === "" ? "" : Number(e.target.value))}
                        placeholder="e.g. 500"
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-4 py-2.5 text-base font-extrabold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                        Rejected Quantity at Stage {woData.current_stage}
                      </label>
                      <input
                        type="number"
                        min={0}
                        value={rejectedQty}
                        onChange={(e) => setRejectedQty(Number(e.target.value))}
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
                        value={defectCode}
                        onChange={(e) => setDefectCode(e.target.value)}
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
                        value={selectedMachine}
                        onChange={(e) => setSelectedMachine(e.target.value)}
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
                        Operator
                      </label>
                      <input
                        type="text"
                        value={operatorName}
                        onChange={(e) => setOperatorName(e.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:border-blue-500 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                        Shift
                      </label>
                      <select
                        value={shift}
                        onChange={(e) => setShift(e.target.value)}
                        className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 font-medium focus:border-blue-500 focus:outline-none"
                      >
                        <option value="Shift A">Shift A (06:00 - 14:00)</option>
                        <option value="Shift B">Shift B (14:00 - 22:00)</option>
                        <option value="Shift C">Shift C (22:00 - 06:00)</option>
                      </select>
                    </div>
                  </div>

                  {/* Remarks */}
                  <div>
                    <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                      Operation Remarks / Floor Notes
                    </label>
                    <input
                      type="text"
                      value={remarks}
                      onChange={(e) => setRemarks(e.target.value)}
                      placeholder="e.g. Partial batch completed, transferred to next bay"
                      className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:border-blue-500 focus:outline-none"
                    />
                  </div>

                  {/* Action Buttons */}
                  <div className="pt-2">
                    <button
                      type="submit"
                      disabled={submitting || woData.available_wip <= 0 || !woData.next_allowed_stage}
                      className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3.5 text-sm font-bold text-white shadow-lg shadow-blue-500/25 hover:bg-blue-500 focus:outline-none disabled:opacity-50 transition-all cursor-pointer"
                    >
                      <ArrowRightLeft className="h-4 w-4" />
                      <span>
                        {submitting
                          ? "Validating & Recording Movement..."
                          : `Confirm & Move to Stage ${woData.next_allowed_stage || "Next"}`}
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
          title="Movement Recorded Successfully"
          subtitle={`Transaction ID: ${moveResult?.movement_id}`}
        >
          <div className="space-y-4">
            <div className="flex items-center justify-center p-4 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/50">
              <div className="text-center">
                <CheckCircle2 className="h-10 w-10 text-emerald-500 mx-auto" />
                <p className="text-sm font-bold text-emerald-800 dark:text-emerald-300 mt-2">
                  {moveResult?.message}
                </p>
              </div>
            </div>

            <div className="space-y-2 text-xs border border-zinc-200 dark:border-zinc-800 rounded-xl p-3.5">
              <div className="flex justify-between">
                <span className="text-zinc-400">Work Order:</span>
                <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{moveResult?.wo_number}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Transfer Route:</span>
                <span className="font-bold text-blue-600">{moveResult?.from_stage} ➔ {moveResult?.to_stage}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Quantity Transferred:</span>
                <span className="font-bold text-zinc-900 dark:text-zinc-100">{moveResult?.quantity_moved} pcs</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Remaining at {moveResult?.from_stage}:</span>
                <span className="font-bold text-zinc-900 dark:text-zinc-100">{moveResult?.available_wip_remaining} pcs</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-400">Now Available at {moveResult?.to_stage}:</span>
                <span className="font-bold text-emerald-600">{moveResult?.to_stage_available_wip} pcs</span>
              </div>
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

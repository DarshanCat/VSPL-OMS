"use client";
import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  Factory,
  Building2,
  Truck,
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
  AlertCircle,
  Flame,
  Lock,
  X
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
  declareWOShortfall,
  MasterRejectionType,
  getMasterMachines,
  getShifts,
  getOperators,
  MasterMachine,
  MasterShift,
  MasterOperator,
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
  const searchParams = useSearchParams();
  const queryWO = searchParams?.get("wo");
  const queryStage = searchParams?.get("stage");

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
  const [heatNumber, setHeatNumber] = useState("");
  const [remarks, setRemarks] = useState("");
  const [isF1ShortfallChecked, setIsF1ShortfallChecked] = useState(false);
  const [shortfallReason, setShortfallReason] = useState("");
  const [productionType, setProductionType] = useState<"IN_HOUSE" | "VENDOR">("IN_HOUSE");
  const [vendorName, setVendorName] = useState("");
  const [dcNumber, setDcNumber] = useState("");
  const [targetReturnStage, setTargetReturnStage] = useState<"FI" | "F2">("FI");
  const [rejectionTypes, setRejectionTypes] = useState<MasterRejectionType[]>([]);
  const [machinesList, setMachinesList] = useState<MasterMachine[]>([]);
  const [operatorsList, setOperatorsList] = useState<MasterOperator[]>([]);
  const [shiftsList, setShiftsList] = useState<MasterShift[]>([]);

  // Result / Success Modal
  const [successResult, setSuccessResult] = useState<any>(null);
  const [showQRModal, setShowQRModal] = useState(false);

  // Dedicated Shortfall Declaration Modal
  const [isShortfallModalOpen, setIsShortfallModalOpen] = useState(false);
  const [shortfallDeclareQty, setShortfallDeclareQty] = useState<number | "">("");
  const [shortfallDeclareReason, setShortfallDeclareReason] = useState("");
  const [createPatchWO, setCreatePatchWO] = useState(true);
  const [declaringShortfall, setDeclaringShortfall] = useState(false);

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

  // Load available WOs and active masters on mount
  useEffect(() => {
    getWorkOrders({ limit: 100, exclude_dispatched: true })
      .then((data) => {
        if (Array.isArray(data) && data.length > 0) {
          setAvailableWOs(data);
          const targetWO = queryWO || data[0].wo_number;
          lookupWO(targetWO, queryStage || undefined);
        }
      })
      .catch((err) => {
        console.error("Failed to fetch WOs:", err);
      });

    getRejectionTypes()
      .then((types) => setRejectionTypes(types))
      .catch(() => setRejectionTypes([]));

    getOperators()
      .then((data) => {
        const active = data.filter((o) => o.is_active);
        if (active.length > 0) {
          setOperatorsList(active);
          setSelectedOperator(active[0].display_name);
        }
      })
      .catch(() => {});

    getMasterMachines()
      .then((data) => {
        const active = data.filter((m) => m.is_active);
        if (active.length > 0) {
          setMachinesList(active);
          setSelectedMachine(active[0].machine_code);
        }
      })
      .catch(() => {});

    getShifts()
      .then((data) => {
        const active = data.filter((s) => s.is_active);
        if (active.length > 0) {
          setShiftsList(active);
          setShift(active[0].shift_name || active[0].shift_code);
        }
      })
      .catch(() => {});
  }, [queryWO, queryStage]);

  // Master options fall back to the safe baseline only if the database is unpopulated
  const machineOptions = machinesList.length > 0
    ? machinesList.map((m) => ({ id: m.machine_code, name: `${m.machine_code} - ${m.machine_name}` }))
    : MACHINES;

  const operatorOptions = operatorsList.length > 0
    ? operatorsList.map((o) => ({ id: o.employee_code || o.id, name: o.display_name }))
    : OPERATORS;

  const shiftOptions = shiftsList.length > 0
    ? shiftsList.map((s) => ({
        code: s.shift_code,
        label: s.start_time && s.end_time ? `${s.shift_name} (${s.start_time} - ${s.end_time})` : s.shift_name,
        value: s.shift_name || s.shift_code,
      }))
    : [
        { code: "A", label: "Shift A (06:00 - 14:00)", value: "Shift A" },
        { code: "B", label: "Shift B (14:00 - 22:00)", value: "Shift B" },
        { code: "C", label: "Shift C (22:00 - 06:00)", value: "Shift C" },
      ];

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

  const lookupWO = async (woNum: string, overrideStage?: string) => {
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

      if (tracking.status === "dispatched" || tracking.status === "closed" || tracking.current_stage === "Completed") {
        setWoData(null);
        setRouteData(null);
        setStageState(null);
        setSearchError(`Work Order '${cleanWO}' is completely dispatched. Production logging is closed.`);
        return;
      }

      setWoData(tracking);
      setRouteData(route);
      setSearchTerm(tracking.wo_number);
      setHeatNumber(tracking.heat_number || "");

      // Default stage: prefer overrideStage if valid, otherwise prefer tracking.current_stage where WIP is active
      const validStages = tracking.timeline?.map((s: any) => s.stage) || ["F1"];
      const targetStage = overrideStage && validStages.includes(overrideStage)
        ? overrideStage
        : (tracking.current_stage && validStages.includes(tracking.current_stage) ? tracking.current_stage : validStages[0]);
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

    if (selectedStage === "F2" && productionType === "VENDOR") {
      if (!vendorName.trim()) {
        setFormError("Vendor Name is mandatory when recording F2 Vendor production.");
        return;
      }
      if (!dcNumber.trim()) {
        setFormError("Delivery Challan (DC #) is mandatory when recording F2 Vendor production.");
        return;
      }
    }

    // The ceiling for a NEW production transaction is the unprocessed material still
    // remaining at this stage (in_process_qty), never available_wip -- available_wip
    // also includes onhand_qty (already-completed material awaiting movement), and
    // validating a fresh entry against it would let cumulative OK run past the
    // authoritative target. This mirrors the backend's own authoritative check in
    // ProductionService.record_stage_production; the backend remains the enforcing
    // authority regardless of this client-side check.
    const isF1 = selectedStage.toUpperCase() === "F1";
    const remainingTarget = stageState?.in_process_qty ?? activeStage.in_process_qty ?? 0;
    const isExcessF1 = isF1 && totalProc > remainingTarget;

    if (totalProc > remainingTarget && !isF1) {
      setFormError(`Total quantity processed (${totalProc}) exceeds the remaining allowable target at ${selectedStage} (${remainingTarget} pcs remaining of target).`);
      inputGoodQtyRef.current?.focus();
      return;
    }

    if (isExcessF1 && !remarks.trim()) {
      setFormError("Remarks / Reason is mandatory when recording F1 Excess Production (e.g. Extra mould poured, Heat balance batch).");
      inputRemarksRef.current?.focus();
      return;
    }

    const isShortfallF1 = isF1 && isF1ShortfallChecked && totalProc < remainingTarget;
    if (isShortfallF1 && !shortfallReason.trim() && !remarks.trim()) {
      setFormError("Remarks / Reason is mandatory when closing F1 with less quantity (shortfall).");
      inputRemarksRef.current?.focus();
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
        machine_id: selectedStage === "F2" && productionType === "VENDOR" ? undefined : selectedMachine,
        operator_name: selectedOperator,
        shift: shift,
        defect_code: rejQtyNum > 0 ? defectCode : undefined,
        remarks: remarks.trim() || undefined,
        heat_number: heatNumber.trim() || undefined,
        client_request_id: clientReqId,
        production_type: selectedStage === "F2" ? productionType : "IN_HOUSE",
        vendor_name: selectedStage === "F2" && productionType === "VENDOR" ? vendorName.trim() : undefined,
        dc_number: selectedStage === "F2" && productionType === "VENDOR" ? dcNumber.trim() : undefined,
        target_return_stage: selectedStage === "F2" && productionType === "VENDOR" ? targetReturnStage : undefined,
        is_f1_shortfall_closure: isShortfallF1,
        shortfall_reason: isShortfallF1 ? (shortfallReason.trim() || remarks.trim()) : undefined,
      });

      setSuccessResult({
        entry_id: res.entry_id,
        wo_number: res.wo_number,
        stage: res.stage,
        good_qty: res.good_qty,
        rejected_quantity: res.rejected_quantity,
        heat_number: res.heat_number || heatNumber.trim() || undefined,
        stage_ok_total: res.stage_ok_total,
        stage_rejection_total: res.stage_rejection_total,
        stage_onhand_available: res.stage_onhand_available,
        stage_inproc_remaining: res.stage_inproc_remaining,
        production_type: res.production_type || (selectedStage === "F2" ? productionType : "IN_HOUSE"),
        vendor_name: res.vendor_name || (selectedStage === "F2" && productionType === "VENDOR" ? vendorName.trim() : undefined),
        dc_number: res.dc_number || (selectedStage === "F2" && productionType === "VENDOR" ? dcNumber.trim() : undefined),
        message: res.message
      });

      // Refresh authoritative WO tracking and stage state
      await lookupWO(woData.wo_number);
      inputGoodQtyRef.current?.focus();
    } catch (err: any) {
      let detailMsg = "Production recording failed. Please check validation rules.";
      if (err?.response?.data?.detail) {
        if (typeof err.response.data.detail === "string") {
          detailMsg = err.response.data.detail;
        } else if (Array.isArray(err.response.data.detail)) {
          detailMsg = err.response.data.detail.map((d: any) => d.msg || JSON.stringify(d)).join(", ");
        } else {
          detailMsg = JSON.stringify(err.response.data.detail);
        }
      } else if (err?.message) {
        detailMsg = err.message;
      }
      setFormError(detailMsg);
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

  const isStageF1 = selectedStage.toUpperCase() === "F1";
  const remainingTargetForStage = stageState?.in_process_qty ?? activeStage?.in_process_qty ?? 0;
  const curProcTotal = (Number(goodQty) || 0) + (Number(rejectedQty) || 0);
  const isF1ExcessActive = isStageF1 && curProcTotal > remainingTargetForStage;
  const f1ExcessAmount = isF1ExcessActive ? curProcTotal - remainingTargetForStage : 0;

  const handleOpenShortfallModal = () => {
    setShortfallDeclareQty(remainingTargetForStage);
    setShortfallDeclareReason("");
    setCreatePatchWO(true);
    setIsShortfallModalOpen(true);
  };

  const handleConfirmShortfall = async () => {
    if (!woData?.wo_number) return;
    const qty = Number(shortfallDeclareQty);
    if (!qty || qty <= 0) {
      alert("Please enter a valid shortfall quantity greater than 0.");
      return;
    }
    if (!shortfallDeclareReason.trim()) {
      alert("Please enter a mandatory reason for the shortfall.");
      return;
    }

    setDeclaringShortfall(true);
    try {
      const res = await declareWOShortfall(woData.wo_number, {
        shortfall_qty: qty,
        reason: shortfallDeclareReason.trim(),
        create_patch_wo: createPatchWO,
        heat_number: heatNumber.trim() || woData.heat_number || undefined,
        remarks: remarks.trim() || undefined,
      });

      setIsShortfallModalOpen(false);
      setSuccessResult({
        wo_number: res.wo_number,
        stage: "F1",
        stage_ok_total: res.new_physical_wo_qty,
        stage_rejection_total: 0,
        stage_onhand_available: res.new_physical_wo_qty,
        stage_inproc_remaining: 0,
        message: res.message,
        patch_wo_number: res.patch_wo_number,
      });
      await lookupWO(woData.wo_number, "F1");
    } catch (err: any) {
      alert(err?.response?.data?.detail || "Failed to declare shortfall.");
    } finally {
      setDeclaringShortfall(false);
    }
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
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-7 gap-4 text-xs">
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
                  <span className="text-zinc-400 text-[10px] uppercase font-bold flex items-center gap-1">
                    <Flame className="h-3 w-3 text-amber-500" /> Heat Number
                  </span>
                  <p className="font-mono font-bold text-amber-600 dark:text-amber-400 text-sm">
                    {woData.heat_number || "Not assigned"}
                  </p>
                  <p className="text-[10px] text-zinc-500">Melt / Cast Heat</p>
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
                    const isDone = stg.is_completed || (stg.stage === activeStage.stage && activeStage.is_gate_locked);
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
                          {isDone && <CheckCircle2 className="h-3 w-3 text-emerald-500" />}
                          {isCur && !isSelected && !isDone && <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />}
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
                      {activeStage.is_gate_locked ? "✓ COMPLETED & PASSED" : (activeStage.stage_status || "IN PROGRESS")}
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

                    {(activeStage.on_hand_qty || 0) > 0 && (
                      <div className="flex items-center justify-between p-2.5 rounded-xl bg-cyan-50 dark:bg-cyan-950/20 border border-cyan-300 dark:border-cyan-800">
                        <span className="text-cyan-700 dark:text-cyan-400 font-bold">Good On-Hand (Awaiting Movement):</span>
                        <span className="font-mono font-extrabold text-cyan-700 dark:text-cyan-400 text-sm">
                          {activeStage.on_hand_qty} pcs
                        </span>
                      </div>
                    )}

                    <div className={`flex items-center justify-between p-2.5 rounded-xl border ${
                      activeStage.is_gate_locked
                        ? "bg-emerald-50/50 dark:bg-emerald-950/20 border-emerald-300 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400"
                        : "bg-amber-50 dark:bg-amber-950/20 border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-400"
                    }`}>
                      <span className="font-bold flex items-center gap-1.5">
                        {activeStage.is_gate_locked && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />}
                        <span>Remaining to Produce:</span>
                      </span>
                      <span className="font-mono font-extrabold text-sm">
                        {activeStage.is_gate_locked ? "0 pcs (Passed)" : `${activeStage.remaining_to_produce ?? activeStage.in_process_qty} pcs`}
                      </span>
                    </div>

                    {isStageF1 && remainingTargetForStage > 0 && (
                      <div className="pt-2">
                        <button
                          type="button"
                          onClick={handleOpenShortfallModal}
                          className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-white font-extrabold text-xs shadow-sm transition-colors cursor-pointer"
                          title="Close remaining in-process material at F1 with shortfall and optionally create a New Patch WO"
                        >
                          <AlertTriangle className="h-4 w-4" />
                          <span>⚠️ Declare Shortfall ({remainingTargetForStage} pcs)</span>
                        </button>
                        <p className="mt-1 text-[10px] text-zinc-500 text-center">
                          Closes F1 balance &amp; auto-creates New Patch WO.
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-emerald-500/20 text-[11px] text-zinc-500">
                  <div className="flex items-center gap-1.5 text-emerald-700 dark:text-emerald-400 font-bold mb-1">
                    <ShieldCheck className="h-4 w-4" />
                    <span>Target & Ceiling Enforcement</span>
                  </div>
                  <p>Target quantity matches the released Work Order quantity ({activeStage.target_qty} pcs). When all material is processed and moved downstream, this gate is completed and passed.</p>
                </div>
              </div>

              {/* Step 6: Production Input Form OR Completed State */}
              <div className="lg:col-span-2 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm">
                {activeStage.is_gate_locked ? (
                  <div className="py-12 px-6 flex flex-col items-center justify-center text-center space-y-4">
                    <div className="w-16 h-16 rounded-2xl bg-emerald-100 dark:bg-emerald-950/40 flex items-center justify-center text-emerald-600 dark:text-emerald-400 shadow-inner">
                      <CheckCircle2 className="h-8 w-8" />
                    </div>
                    <div>
                      <h3 className="text-xl font-extrabold text-zinc-900 dark:text-zinc-50">
                        Gate {selectedStage} Completed & Passed
                      </h3>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1.5 max-w-md mx-auto">
                        All {activeStage.target_qty} pcs for Work Order {woData.wo_number} have been produced and moved downstream. Zero material remains at this gate.
                      </p>
                    </div>

                    {activeStage.next_stage && (
                      <div className="pt-2">
                        <button
                          type="button"
                          onClick={() => handleSelectStage(activeStage.next_stage)}
                          className="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-3 text-xs font-bold text-white hover:bg-emerald-500 shadow-md transition-all cursor-pointer"
                        >
                          <span>Proceed to Next Gate: {activeStage.next_stage}</span>
                          <ArrowRight className="h-4 w-4" />
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                <form onSubmit={handleFormSubmit} className="space-y-5">
                  <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
                    <h3 className="text-sm font-bold uppercase tracking-wider text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
                      <ClipboardCheck className="h-4 w-4 text-emerald-600" />
                      <span>Log Production Completion</span>
                    </h3>
                    <div className="flex items-center gap-2">
                      {isStageF1 && remainingTargetForStage > 0 && (
                        <button
                          type="button"
                          onClick={handleOpenShortfallModal}
                          className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-amber-100 hover:bg-amber-200 dark:bg-amber-950/60 text-amber-800 dark:text-amber-200 text-xs font-bold border border-amber-300 dark:border-amber-700 transition cursor-pointer"
                        >
                          <AlertTriangle className="h-3.5 w-3.5 text-amber-600 dark:text-amber-400" />
                          <span>Shortfall on Remaining ({remainingTargetForStage} pcs)</span>
                        </button>
                      )}
                      <span className="text-[11px] text-zinc-400">Press Enter to navigate fields</span>
                    </div>
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
                        max={isStageF1 ? undefined : activeStage.in_process_qty}
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

                  {/* F2 Special Routing: In-House vs At Vendor Toggle */}
                  {selectedStage === "F2" && (
                    <div className="p-4 rounded-xl border border-indigo-200 dark:border-indigo-900/60 bg-indigo-50/40 dark:bg-indigo-950/20 space-y-3">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-bold text-indigo-950 dark:text-indigo-200 flex items-center gap-1.5">
                          <Factory className="h-4 w-4 text-indigo-600" />
                          F2 PRODUCTION MODE / ROUTING *
                        </label>
                        <span className="text-[10px] uppercase tracking-wider font-extrabold text-indigo-700 dark:text-indigo-300 bg-indigo-100 dark:bg-indigo-900/60 px-2 py-0.5 rounded-md">
                          Stage F2 Specific
                        </span>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <button
                          type="button"
                          onClick={() => setProductionType("IN_HOUSE")}
                          className={`py-2.5 px-3 rounded-xl border text-xs font-bold flex items-center justify-center gap-2 transition-all cursor-pointer ${
                            productionType === "IN_HOUSE"
                              ? "border-indigo-600 bg-indigo-600 text-white shadow-sm ring-2 ring-indigo-500/20"
                              : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                          }`}
                        >
                          <Factory className="h-4 w-4" />
                          <span>In-House Production (Shopfloor)</span>
                        </button>

                        <button
                          type="button"
                          onClick={() => setProductionType("VENDOR")}
                          className={`py-2.5 px-3 rounded-xl border text-xs font-bold flex items-center justify-center gap-2 transition-all cursor-pointer ${
                            productionType === "VENDOR"
                              ? "border-purple-600 bg-purple-600 text-white shadow-sm ring-2 ring-purple-500/20"
                              : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                          }`}
                        >
                          <Building2 className="h-4 w-4" />
                          <span>At Vendor (External DC)</span>
                        </button>
                      </div>

                      {productionType === "VENDOR" && (
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2 border-t border-indigo-200/60 dark:border-indigo-900/40">
                          <div>
                            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5 flex items-center gap-1.5">
                              <Building2 className="h-3.5 w-3.5 text-purple-600" />
                              VENDOR NAME <span className="text-rose-500">*</span>
                            </label>
                            <input
                              type="text"
                              list="vendor-suggestions"
                              value={vendorName}
                              onChange={(e) => setVendorName(e.target.value)}
                              placeholder="e.g. Sharada Engineering, Lakshmi CNC..."
                              className="w-full rounded-xl border border-purple-300 dark:border-purple-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
                              required={productionType === "VENDOR"}
                            />
                            <datalist id="vendor-suggestions">
                              <option value="Sharada Engineering" />
                              <option value="Lakshmi CNC Machining" />
                              <option value="Super Tech Precision Works" />
                              <option value="Standard Machining Works" />
                              <option value="A-One Engineering Works" />
                            </datalist>
                          </div>

                          <div>
                            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5 flex items-center gap-1.5">
                              <Truck className="h-3.5 w-3.5 text-purple-600" />
                              DELIVERY CHALLAN NUMBER (DC #) <span className="text-rose-500">*</span>
                            </label>
                            <input
                              type="text"
                              value={dcNumber}
                              onChange={(e) => setDcNumber(e.target.value)}
                              placeholder="e.g. DC-2026-0042..."
                              className="w-full rounded-xl border border-purple-300 dark:border-purple-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-purple-500"
                              required={productionType === "VENDOR"}
                            />
                          </div>

                          <div className="col-span-full pt-1">
                            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5 flex items-center gap-1.5">
                              <ArrowRight className="h-3.5 w-3.5 text-purple-600" />
                              EXPECTED RETURN DESTINATION (WHERE DOES MATERIAL GO WHEN RECEIVED?) *
                            </label>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                              <button
                                type="button"
                                onClick={() => setTargetReturnStage("FI")}
                                className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                                  targetReturnStage === "FI"
                                    ? "border-emerald-600 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-900 dark:text-emerald-100 ring-2 ring-emerald-500/20"
                                    : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                                }`}
                              >
                                <div className="flex items-center gap-1.5 mb-0.5">
                                  <span className="w-2 h-2 rounded-full bg-emerald-500" />
                                  <span className="font-extrabold text-xs">Return Directly to FI (Final Inspection)</span>
                                </div>
                                <p className="text-[10px] text-zinc-500 leading-tight">
                                  Vendor completes external machining/coating. Parts arrive directly to FI for CMM/QA and packing.
                                </p>
                              </button>

                              <button
                                type="button"
                                onClick={() => setTargetReturnStage("F2")}
                                className={`p-3 rounded-xl border text-left transition-all cursor-pointer ${
                                  targetReturnStage === "F2"
                                    ? "border-indigo-600 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-900 dark:text-indigo-100 ring-2 ring-indigo-500/20"
                                    : "border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50"
                                }`}
                              >
                                <div className="flex items-center gap-1.5 mb-0.5">
                                  <span className="w-2 h-2 rounded-full bg-indigo-500" />
                                  <span className="font-extrabold text-xs">Return to F2 (Fettling & Finishing)</span>
                                </div>
                                <p className="text-[10px] text-zinc-500 leading-tight">
                                  Intermediate outside process. Parts return to F2 for in-house grinding, fettling, or finishing.
                                </p>
                              </button>
                            </div>
                          </div>
                        </div>
                      )}
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
                        {machineOptions.map((m) => (
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
                        {operatorOptions.map((op) => (
                          <option key={op.id} value={op.name}>
                            {op.name} {op.id ? `(${op.id})` : ""}
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
                        {shiftOptions.map((s) => (
                          <option key={s.code} value={s.value}>
                            {s.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  </div>

                  {/* Heat Number & Remarks */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5 flex items-center gap-1.5">
                        <Flame className="h-3.5 w-3.5 text-amber-500" />
                        HEAT NUMBER / MELT BATCH
                      </label>
                      <input
                        type="text"
                        value={heatNumber}
                        onChange={(e) => setHeatNumber(e.target.value)}
                        placeholder="e.g. HT-2026-904..."
                        className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950 px-3.5 py-2.5 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-amber-500"
                      />
                      <span className="text-[10px] text-zinc-400 mt-1 block">Heat batch from which parts are being produced</span>
                    </div>

                    <div>
                      <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1.5 flex items-center justify-between">
                        <span>REMARKS / LOG DETAILS {isF1ExcessActive ? <span className="text-rose-500 font-extrabold">* (Mandatory for F1 Excess)</span> : <span className="text-zinc-400 font-normal">(Optional)</span>}</span>
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
                  </div>

                  {/* F1 Excess Production Alert Banner */}
                  {isF1ExcessActive && (
                    <div className="rounded-xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-3.5 flex items-start gap-3 text-xs">
                      <AlertTriangle className="h-4 w-4 text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
                      <div className="space-y-0.5">
                        <div className="font-bold text-amber-900 dark:text-amber-200">
                          ⚠️ F1 Excess Production: Planned {remainingTargetForStage} | Total {curProcTotal} (+{f1ExcessAmount} Excess pcs)
                        </div>
                        <p className="text-[11px] text-amber-800 dark:text-amber-300">
                          Work Order planned quantity and downstream route targets will automatically expand to {woData?.physical_wo_qty ? woData.physical_wo_qty + f1ExcessAmount : curProcTotal} pcs. Remarks / reason is mandatory.
                        </p>
                      </div>
                    </div>
                  )}

                  {/* F1 Shortfall (Less Production Closure) Card */}
                  {isStageF1 && curProcTotal > 0 && curProcTotal < remainingTargetForStage && (
                    <div className="rounded-xl border border-sky-300 dark:border-sky-800 bg-sky-50/70 dark:bg-sky-950/40 p-3.5 space-y-2 text-xs">
                      <div className="flex items-center gap-2.5">
                        <input
                          type="checkbox"
                          id="f1ShortfallCheck"
                          checked={isF1ShortfallChecked}
                          onChange={(e) => setIsF1ShortfallChecked(e.target.checked)}
                          className="h-4 w-4 rounded border-sky-300 text-sky-600 focus:ring-sky-500 cursor-pointer"
                        />
                        <label htmlFor="f1ShortfallCheck" className="font-bold text-sky-900 dark:text-sky-200 cursor-pointer select-none">
                          Close F1 Heat / Batch with Less Production (Shortfall of {remainingTargetForStage - curProcTotal} pcs)
                        </label>
                      </div>
                      {isF1ShortfallChecked && (
                        <div className="pl-6 space-y-2 pt-1 border-t border-sky-200 dark:border-sky-800/60">
                          <p className="text-[11px] text-sky-800 dark:text-sky-300">
                            Finalizes F1 stage at {curProcTotal} pcs and adjusts downstream routes. The parent OAR will record a shortfall of {remainingTargetForStage - curProcTotal} pcs for Patch WO planning.
                          </p>
                          <div>
                            <label className="block text-[11px] font-bold text-rose-600 dark:text-rose-400 mb-1">
                              Reason for Less Production / Shortfall * (Mandatory)
                            </label>
                            <input
                              type="text"
                              value={shortfallReason}
                              onChange={(e) => setShortfallReason(e.target.value)}
                              placeholder="e.g. Metal short in ladle, furnace heat ended, mould shortage, core breakdown..."
                              className="w-full rounded-lg border border-sky-300 dark:border-sky-700 bg-white dark:bg-zinc-900 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  )}

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
                )}
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
              {successResult.stage === "F2" && (
                <div className="pt-1">
                  {successResult.production_type === "VENDOR" ? (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-purple-100 text-purple-900 dark:bg-purple-950/60 dark:text-purple-200 font-bold text-[11px] border border-purple-200 dark:border-purple-800">
                      <Building2 className="h-3.5 w-3.5 text-purple-600" />
                      <span>Production at Vendor: <strong>{successResult.vendor_name}</strong> (DC #{successResult.dc_number})</span>
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 text-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200 font-bold text-[11px] border border-indigo-200 dark:border-indigo-800">
                      <Factory className="h-3.5 w-3.5 text-indigo-600" />
                      <span>In-House Production ({selectedMachine})</span>
                    </span>
                  )}
                </div>
              )}
              <div className="flex flex-wrap gap-4 pt-1 font-mono font-bold text-zinc-800 dark:text-zinc-200">
                <span>Stage OK Total: <strong className="text-emerald-600">{successResult.stage_ok_total}</strong></span>
                <span>Stage Rejection Total: <strong className="text-rose-600">{successResult.stage_rejection_total}</strong></span>
                <span>On-Hand Available: <strong className="text-blue-600">{successResult.stage_onhand_available}</strong></span>
                <span>In-Process Remaining: <strong className="text-amber-600">{successResult.stage_inproc_remaining}</strong></span>
              </div>
              {successResult.patch_wo_number && (
                <div className="pt-2">
                  <div className="p-3 rounded-xl bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800 flex items-center justify-between">
                    <div>
                      <span className="text-[10px] uppercase font-bold text-purple-600 block">Patch Work Order Spawned</span>
                      <strong className="text-sm font-mono text-purple-900 dark:text-purple-100">{successResult.patch_wo_number}</strong>
                    </div>
                    <Link
                      href={`/production/entry?wo=${encodeURIComponent(successResult.patch_wo_number)}&stage=F1`}
                      className="px-3 py-1.5 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-bold text-xs shadow-sm transition"
                    >
                      Open Patch WO in F1
                    </Link>
                  </div>
                </div>
              )}
              {successResult.stage_onhand_available > 0 && (
                <div className="pt-2">
                  <Link
                    href={`/production/entry?tab=move&wo=${encodeURIComponent(successResult.wo_number)}&stage=${encodeURIComponent(successResult.stage)}`}
                    className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-bold text-xs shadow-sm transition-all"
                  >
                    <span>Move Parts Now</span>
                    <ArrowRight className="h-3.5 w-3.5" />
                  </Link>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Shortfall Declaration Modal */}
        {isShortfallModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 animate-in fade-in duration-150">
            <div className="w-full max-w-lg rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xl overflow-hidden">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 px-6 py-4 bg-amber-50/50 dark:bg-amber-950/20">
                <div className="flex items-center gap-2.5">
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-950 dark:text-amber-300">
                    <AlertTriangle className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="text-base font-extrabold text-zinc-900 dark:text-zinc-50">
                      Declare F1 Shortfall &amp; Create Patch WO
                    </h3>
                    <p className="text-[11px] text-zinc-500">
                      Work Order: <strong className="font-mono text-zinc-800 dark:text-zinc-200">{woData?.wo_number}</strong>
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setIsShortfallModalOpen(false)}
                  className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              <div className="p-6 space-y-4 text-xs">
                <div className="grid grid-cols-3 gap-2 p-3 rounded-xl bg-zinc-50 dark:bg-zinc-950 border border-zinc-200/80 dark:border-zinc-800 text-center font-mono">
                  <div>
                    <span className="text-[10px] text-zinc-400 uppercase font-sans font-bold block">Planned Target</span>
                    <span className="font-bold text-zinc-800 dark:text-zinc-200 text-sm">{woData?.physical_wo_qty ?? 0} pcs</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-emerald-600 uppercase font-sans font-bold block">Produced OK</span>
                    <span className="font-bold text-emerald-600 text-sm">{activeStage?.ok_completed_qty ?? 0} pcs</span>
                  </div>
                  <div>
                    <span className="text-[10px] text-amber-600 uppercase font-sans font-bold block">Remaining</span>
                    <span className="font-bold text-amber-600 text-sm">{remainingTargetForStage} pcs</span>
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                    Shortfall Quantity to Close Out (pcs) *
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={remainingTargetForStage}
                    value={shortfallDeclareQty}
                    onChange={(e) => setShortfallDeclareQty(e.target.value === "" ? "" : Number(e.target.value))}
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3.5 py-2.5 text-sm font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:border-amber-500 focus:outline-none"
                  />
                  <p className="mt-1 text-[11px] text-zinc-500">
                    Current WO planned qty will be reduced to {Math.max((woData?.physical_wo_qty || 0) - (Number(shortfallDeclareQty) || 0), 0)} good pcs.
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-bold text-rose-600 dark:text-rose-400 mb-1">
                    Reason for Shortfall / Less Production * (Mandatory)
                  </label>
                  <input
                    type="text"
                    required
                    value={shortfallDeclareReason}
                    onChange={(e) => setShortfallDeclareReason(e.target.value)}
                    placeholder="e.g. Ladle metal short, mould leak, sand collapse, furnace heat balance ended..."
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 focus:border-rose-500 focus:outline-none"
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                    Heat Number (Optional)
                  </label>
                  <input
                    type="text"
                    value={heatNumber}
                    onChange={(e) => setHeatNumber(e.target.value)}
                    placeholder={woData?.heat_number || "e.g. H-2026-9021"}
                    className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3.5 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                  />
                </div>

                <div className="p-3.5 rounded-xl border border-purple-200 dark:border-purple-800/80 bg-purple-50/50 dark:bg-purple-950/20">
                  <label className="flex items-start gap-2.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={createPatchWO}
                      onChange={(e) => setCreatePatchWO(e.target.checked)}
                      className="mt-0.5 h-4 w-4 rounded border-purple-300 text-purple-600 focus:ring-purple-500 cursor-pointer"
                    />
                    <div className="space-y-0.5">
                      <span className="font-extrabold text-purple-900 dark:text-purple-200">
                        Automatically create New Patch Work Order for shortfall quantity
                      </span>
                      <p className="text-[11px] text-purple-700 dark:text-purple-300">
                        Generates a new sequential Work Order ID linked to the same OAR and auto-releases it so the shop floor can immediately cast the remaining pieces.
                      </p>
                    </div>
                  </label>
                </div>
              </div>

              <div className="flex items-center justify-end gap-2.5 border-t border-zinc-100 dark:border-zinc-800 px-6 py-4 bg-zinc-50 dark:bg-zinc-950">
                <button
                  type="button"
                  onClick={() => setIsShortfallModalOpen(false)}
                  className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={declaringShortfall || !shortfallDeclareReason.trim()}
                  onClick={handleConfirmShortfall}
                  className="rounded-xl bg-amber-600 hover:bg-amber-500 disabled:opacity-50 px-5 py-2 text-xs font-extrabold text-white shadow-md shadow-amber-500/20 transition cursor-pointer flex items-center gap-1.5"
                >
                  {declaringShortfall ? (
                    <>
                      <RotateCcw className="h-3.5 w-3.5 animate-spin" />
                      <span>Closing &amp; Spawning Patch WO...</span>
                    </>
                  ) : (
                    <>
                      <AlertTriangle className="h-3.5 w-3.5" />
                      <span>Confirm Shortfall &amp; Create Patch WO</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
  );
}

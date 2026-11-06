"use client";
import React, { useState } from "react";
import { AlertTriangle, Check, RefreshCw, X } from "lucide-react";
import {
  WorkOrderListItem,
  WorkOrderUpdatePayload,
  updateWorkOrder
} from "@/lib/api";

const DEFAULT_STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];

export interface EditWorkOrderModalProps {
  wo: WorkOrderListItem;
  onClose: () => void;
  onSuccess: (updated: WorkOrderListItem) => void;
}

export function EditWorkOrderModal({ wo, onClose, onSuccess }: EditWorkOrderModalProps) {
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm overflow-y-auto animate-in fade-in">
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
            className="rounded-lg p-1 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
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
                    className={`px-3 py-1 rounded-lg text-xs font-mono font-bold transition cursor-pointer ${
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
              className="px-4 py-2 rounded-xl border border-zinc-300 dark:border-zinc-700 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={saving}
              className="px-5 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold transition shadow-sm flex items-center gap-1.5 disabled:opacity-60 cursor-pointer"
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

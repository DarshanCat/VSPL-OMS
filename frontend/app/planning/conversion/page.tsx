"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  ArrowRightLeft,
  CheckCircle2,
  AlertTriangle,
  Layers,
  ArrowRight,
  ShieldCheck
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getWorkOrders, createConversion } from "@/lib/api";

const STAGES = ["F1", "F2", "F3", "SP", "FI", "PACKING"];

export default function ConversionPage() {
  const [wos, setWos] = useState<any[]>([]);
  const [conversionWOName, setConversionWOName] = useState("C-0021");
  const [sourceWO, setSourceWO] = useState("WO-1001");
  const [destOAR, setDestOAR] = useState("OAR-0002");
  const [quantity, setQuantity] = useState<number | "">(100);
  const [entryStage, setEntryStage] = useState("F2");
  const [reason, setReason] = useState("Expedited customer order reallocation (same bronze alloy)");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successResult, setSuccessResult] = useState<any>(null);

  useEffect(() => {
    getWorkOrders()
      .then((data) => {
        setWos(data);
        if (data.length > 0) {
          setSourceWO(data[0].wo_number);
          setDestOAR(data[1]?.oar_number || "OAR-0002");
        }
      })
      .catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessResult(null);

    const qty = Number(quantity);
    if (qty <= 0) {
      setError("Conversion quantity must be greater than 0.");
      return;
    }

    if (!conversionWOName.trim()) {
      setError("Planner must supply a unique Conversion WO name (e.g. C-0021).");
      return;
    }

    setLoading(true);

    try {
      const res = await createConversion({
        conversion_wo_number: conversionWOName.trim(),
        source_wo_number: sourceWO,
        destination_oar_number: destOAR,
        quantity: qty,
        entry_stage: entryStage,
        reason: reason,
      });

      setSuccessResult(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Conversion transaction failed.");
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
            <span className="rounded-md bg-indigo-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Material Reallocation
            </span>
            <span className="text-xs text-zinc-400">Planner Conversions</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Work Order Conversions
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Reallocate pieces between Work Orders & OARs with strict debit-stage WIP validation and lineage tracking.
          </p>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {successResult && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-5 space-y-3">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-500" />
              <div>
                <h4 className="text-sm font-bold text-emerald-800 dark:text-emerald-300">
                  {successResult.message}
                </h4>
                <p className="text-xs text-emerald-600 dark:text-emerald-400">
                  Source: <strong>{successResult.source_wo_number}</strong> → Conversion WO: <strong>{successResult.conversion_wo_number}</strong> at stage {successResult.entry_stage}
                </p>
              </div>
            </div>
            <Link
              href={`/production/tracking?wo=${successResult.conversion_wo_number}`}
              className="inline-flex items-center gap-1 text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline"
            >
              <span>Track New Conversion WO {successResult.conversion_wo_number}</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        )}

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                Conversion WO Name (Planner Assigned) *
              </label>
              <input
                type="text"
                required
                value={conversionWOName}
                onChange={(e) => setConversionWOName(e.target.value)}
                placeholder="e.g. C-0021"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-extrabold text-indigo-600 dark:text-indigo-400 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Quantity to Convert (pcs) *</label>
              <input
                type="number"
                required
                min={1}
                value={quantity}
                onChange={(e) => setQuantity(e.target.value === "" ? "" : Number(e.target.value))}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Source Work Order</label>
              <select
                value={sourceWO}
                onChange={(e) => setSourceWO(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                {wos.map((w) => (
                  <option key={w.wo_number} value={w.wo_number}>
                    {w.wo_number} — {w.current_stage} ({w.available_wip_at_current_stage} avail)
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Destination OAR Number</label>
              <input
                type="text"
                required
                value={destOAR}
                onChange={(e) => setDestOAR(e.target.value)}
                placeholder="e.g. OAR-0002"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Entry Stage on Destination</label>
              <select
                value={entryStage}
                onChange={(e) => setEntryStage(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                {STAGES.map((s) => (
                  <option key={s} value={s}>
                    Stage {s}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div>
            <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Conversion Rationale / Reason *</label>
            <input
              type="text"
              required
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
            />
          </div>

          <div className="pt-2">
            <button
              type="submit"
              disabled={loading || !quantity || !conversionWOName}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-indigo-600 py-3.5 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              <ArrowRightLeft className="h-4 w-4" />
              <span>{loading ? "Reallocating WIP..." : "Execute Material Conversion"}</span>
            </button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}

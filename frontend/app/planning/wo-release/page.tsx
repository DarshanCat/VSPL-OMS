"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  Factory,
  Search,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  Route,
  Check,
  ClipboardCheck,
  Wrench
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getWorkOrders, releaseWorkOrder, engineeringReleaseWorkOrder, manufacturingReleaseWorkOrder } from "@/lib/api";

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
  const [wos, setWos] = useState<any[]>([]);
  const [selectedWO, setSelectedWO] = useState<string>("WO-1002");
  const [physicalQty, setPhysicalQty] = useState<number | "">(500);
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

  // Release chain: Engineering Release -> Manufacturing Release -> WO Release (below).
  const [chainBusy, setChainBusy] = useState<"engineering" | "manufacturing" | null>(null);
  const [chainError, setChainError] = useState("");
  const [chainResult, setChainResult] = useState<{ engineering?: any; manufacturing?: any }>({});

  const handleEngineeringRelease = async () => {
    setChainError("");
    setChainBusy("engineering");
    try {
      const res = await engineeringReleaseWorkOrder(selectedWO);
      setChainResult((prev) => ({ ...prev, engineering: res }));
    } catch (err: any) {
      setChainError(err?.response?.data?.detail || "Failed to record Engineering Release.");
    } finally {
      setChainBusy(null);
    }
  };

  const handleManufacturingRelease = async () => {
    setChainError("");
    setChainBusy("manufacturing");
    try {
      const res = await manufacturingReleaseWorkOrder(selectedWO);
      setChainResult((prev) => ({ ...prev, manufacturing: res }));
    } catch (err: any) {
      setChainError(err?.response?.data?.detail || "Failed to record Manufacturing Release.");
    } finally {
      setChainBusy(null);
    }
  };

  useEffect(() => {
    getWorkOrders()
      .then((data) => {
        setWos(data);
        if (data.length > 0) {
          const candidate = data.find((w: any) => w.status === "planned" || w.status === "in_production") || data[0];
          setSelectedWO(candidate.wo_number);
          setPhysicalQty(candidate.physical_wo_qty);
        }
      })
      .catch(() => {});
  }, []);

  const handleWOSelect = (woNum: string) => {
    setSelectedWO(woNum);
    setChainResult({});
    setChainError("");
    const found = wos.find((w) => w.wo_number === woNum);
    if (found) {
      setPhysicalQty(found.physical_wo_qty);
    }
  };

  const toggleStage = (stgCode: string) => {
    if (stgCode === "DISPATCH") return; // Dispatch is always terminal
    if (selectedStages.includes(stgCode)) {
      setSelectedStages(selectedStages.filter((s) => s !== stgCode));
    } else {
      // Keep in canonical order
      const order = ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];
      const newStages = [...selectedStages, stgCode].sort((a, b) => order.indexOf(a) - order.indexOf(b));
      setSelectedStages(newStages);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessResult(null);

    const qty = Number(physicalQty);
    if (qty <= 0) {
      setError("Physical WO Quantity must be greater than 0.");
      return;
    }

    if (selectedStages.length === 0) {
      setError("Please select at least one production stage.");
      return;
    }

    setLoading(true);

    try {
      const res = await releaseWorkOrder({
        wo_number: selectedWO,
        physical_wo_qty: qty,
        route_stages: selectedStages,
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
              Planning & WO Release
            </span>
            <span className="text-xs text-zinc-400">Dynamic Stage Routing</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Work Order Release & Custom Routing
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Planner declares physical released quantity and sets custom stage routing (skipping non-applicable gates).
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
                  Route: <strong>{successResult.route}</strong>
                </p>
              </div>
            </div>
            <div className="flex gap-2">
              <Link
                href={`/production/tracking?wo=${successResult.wo_number}`}
                className="inline-flex items-center gap-1 text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline"
              >
                <span>Track {successResult.wo_number} on Floor</span>
                <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </div>
        )}

        {/* Release chain: Engineering Release -> Manufacturing Release -> WO Release */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm space-y-3">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
            Release Chain for <span className="font-mono">{selectedWO}</span>
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
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={handleEngineeringRelease}
              disabled={chainBusy !== null || !!chainResult.engineering}
              className="flex items-center gap-1.5 rounded-lg bg-indigo-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-indigo-500 disabled:opacity-50 transition-colors"
            >
              <ClipboardCheck className="h-3.5 w-3.5" />
              {chainResult.engineering ? "Engineering Released" : chainBusy === "engineering" ? "Releasing..." : "Engineering Release"}
            </button>
            <button
              type="button"
              onClick={handleManufacturingRelease}
              disabled={chainBusy !== null || !!chainResult.manufacturing}
              className="flex items-center gap-1.5 rounded-lg bg-purple-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-purple-500 disabled:opacity-50 transition-colors"
            >
              <Wrench className="h-3.5 w-3.5" />
              {chainResult.manufacturing ? "Manufacturing Released" : chainBusy === "manufacturing" ? "Releasing..." : "Manufacturing Release"}
            </button>
          </div>
        </div>

        {/* Form */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Select Work Order</label>
              <select
                value={selectedWO}
                onChange={(e) => handleWOSelect(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                {wos.map((w) => (
                  <option key={w.wo_number} value={w.wo_number}>
                    {w.wo_number} — {w.part_number} ({w.customer_code})
                  </option>
                ))}
              </select>
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

          {/* Route Stages Checklist */}
          <div>
            <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300 block mb-2">
              Declared Stage Routing (Select stages this WO will physically move through):
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {ALL_POSSIBLE_STAGES.map((stg) => {
                const isChecked = selectedStages.includes(stg.code);
                return (
                  <button
                    type="button"
                    key={stg.code}
                    onClick={() => toggleStage(stg.code)}
                    className={`flex items-center justify-between p-3 rounded-xl border text-left transition-all ${
                      isChecked
                        ? "border-blue-500 bg-blue-50/60 dark:bg-blue-950/40 text-blue-900 dark:text-blue-100"
                        : "border-zinc-200 dark:border-zinc-800 text-zinc-400 bg-zinc-50/40 dark:bg-zinc-950/40"
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <div
                        className={`flex h-5 w-5 items-center justify-center rounded-md border ${
                          isChecked ? "border-blue-600 bg-blue-600 text-white" : "border-zinc-300 dark:border-zinc-700"
                        }`}
                      >
                        {isChecked && <Check className="h-3.5 w-3.5" />}
                      </div>
                      <span className="text-xs font-bold">{stg.name}</span>
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
              disabled={loading || !physicalQty || selectedStages.length === 0}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              <Factory className="h-4 w-4" />
              <span>{loading ? "Releasing to Floor..." : `Release Work Order ${selectedWO}`}</span>
            </button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}

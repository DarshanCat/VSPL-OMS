"use client";
import React, { useState } from "react";
import Link from "next/link";
import {
  FilePlus,
  CheckCircle2,
  AlertTriangle,
  Building,
  Layers,
  ArrowRight,
  Package
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { createOrderIntake } from "@/lib/api";

const PRESET_CUSTOMERS = [
  { code: "CUST-VALVE", name: "Flowserve Controls Ltd" },
  { code: "CUST-PUMP", name: "Kirloskar Brothers Pumps" },
  { code: "CUST-AERO", name: "HAL Aerospace Components" },
  { code: "CUST-TURB", name: "Bharat Heavy Electricals (BHEL)" },
  { code: "CUST-AUTO", name: "L&T Heavy Engineering" },
];

const PRESET_PARTS = [
  { num: "BRZ-BUSH-100", grade: "PB2 / CuSn11P", desc: "Centrifugal Cast Bushing OD 120mm x ID 80mm" },
  { num: "BRZ-RING-250", grade: "SAE 660 / RG7", desc: "Wear Ring Seal 250mm x 20mm" },
  { num: "BRZ-SLV-400", grade: "AB2 / CuAl10Fe5Ni5", desc: "Heavy Duty Aluminium Bronze Sleeve 400mm" },
  { num: "BRZ-GEAR-150", grade: "CuSn12", desc: "Worm Gear Blank Bronze Casting 150mm" },
  { num: "BRZ-FLG-300", grade: "LG2 / Gunmetal", desc: "High Pressure Flanged Liner 300mm" },
];

export default function OrderIntakePage() {
  const [customerCode, setCustomerCode] = useState("CUST-VALVE");
  const [customerName, setCustomerName] = useState("Flowserve Controls Ltd");
  const [customerPO, setCustomerPO] = useState("PO-2026-950");
  const [partNumber, setPartNumber] = useState("BRZ-BUSH-100");
  const [grade, setGrade] = useState("PB2 / CuSn11P");
  const [partDesc, setPartDesc] = useState("Centrifugal Cast Bushing OD 120mm x ID 80mm");
  const [poQty, setPoQty] = useState<number | "">(1000);
  const [batchSize, setBatchSize] = useState<number | "">(500);
  const [deliveryDate, setDeliveryDate] = useState("2026-09-20");
  const [orderType, setOrderType] = useState("Standard");

  const [splitMode, setSplitMode] = useState<"auto" | "manual">("auto");
  const [manualQtys, setManualQtys] = useState<string[]>(["", ""]);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successResult, setSuccessResult] = useState<any>(null);

  const manualAllocated = manualQtys.reduce((sum, v) => sum + (Number(v) || 0), 0);
  const manualRemaining = Number(poQty || 0) - manualAllocated;
  const manualComplete = Number(poQty) > 0 && manualRemaining === 0 && manualQtys.every((v) => Number(v) > 0);

  const updateManualQty = (idx: number, value: string) => {
    setManualQtys((prev) => prev.map((v, i) => (i === idx ? value : v)));
  };

  const addManualRow = () => setManualQtys((prev) => [...prev, ""]);
  const removeManualRow = (idx: number) =>
    setManualQtys((prev) => (prev.length > 1 ? prev.filter((_, i) => i !== idx) : prev));

  const handleCustomerChange = (code: string) => {
    setCustomerCode(code);
    const found = PRESET_CUSTOMERS.find((c) => c.code === code);
    if (found) setCustomerName(found.name);
  };

  const handlePartChange = (num: string) => {
    setPartNumber(num);
    const found = PRESET_PARTS.find((p) => p.num === num);
    if (found) {
      setGrade(found.grade);
      setPartDesc(found.desc);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setSuccessResult(null);

    const qty = Number(poQty);
    const batch = Number(batchSize);

    if (qty <= 0 || batch <= 0) {
      setError("PO Quantity and Max Batch Size must be greater than 0.");
      return;
    }

    let wo_quantities: number[] | undefined = undefined;
    if (splitMode === "manual") {
      const parsed = manualQtys.map((v) => Number(v));
      if (parsed.some((v) => !v || v <= 0)) {
        setError("Every WO quantity must be a whole number greater than 0.");
        return;
      }
      const allocated = parsed.reduce((sum, v) => sum + v, 0);
      if (allocated !== qty) {
        setError(
          `Allocated WO quantities (${allocated}) must exactly equal the OAR quantity (${qty}). ` +
            `${allocated > qty ? "Reduce" : "Increase"} the allocation by ${Math.abs(allocated - qty)}.`
        );
        return;
      }
      wo_quantities = parsed;
    }

    setLoading(true);

    try {
      const res = await createOrderIntake({
        customer_code: customerCode,
        customer_name: customerName,
        customer_po: customerPO.trim(),
        part_number: partNumber,
        grade: grade,
        part_description: partDesc,
        po_quantity: qty,
        max_batch_size: batch,
        delivery_date: deliveryDate,
        order_type: orderType,
        wo_quantities,
      });

      setSuccessResult(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to process Order Intake.");
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
              Sales & Order Entry
            </span>
            <span className="text-xs text-zinc-400">Order Acknowledgement Record</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Order Intake & WO Split
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Accept customer Purchase Orders, auto-generate OAR records, and split large orders into standard batch Work Orders.
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
                  OAR Reference: <strong>{successResult.oar_number}</strong> | Total Quantity: {successResult.total_qty} pcs | {successResult.wos_created.length} Work Order(s) created
                </p>
              </div>
            </div>

            <div className="rounded-xl bg-white dark:bg-zinc-900 p-3.5 border border-zinc-200 dark:border-zinc-800 text-xs">
              <span className="font-bold text-zinc-900 dark:text-zinc-100 block mb-1">
                Generated Work Orders (Initialized at Stage F1):
              </span>
              <div className="flex flex-wrap gap-2">
                {successResult.wos_created.map((wo: string, idx: number) => (
                  <Link
                    key={wo}
                    href={`/production/tracking?wo=${wo}`}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-blue-50 dark:bg-blue-950/60 px-3 py-1 font-mono font-bold text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800 hover:underline"
                  >
                    <span>{wo}</span>
                    {Array.isArray(successResult.wo_quantities) && successResult.wo_quantities[idx] != null && (
                      <span className="text-zinc-500 dark:text-zinc-400 font-semibold">
                        ({successResult.wo_quantities[idx]} pcs)
                      </span>
                    )}
                    <ArrowRight className="h-3 w-3" />
                  </Link>
                ))}
              </div>
            </div>

            <div className="pt-1">
              <Link
                href="/orders/list"
                className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-700 dark:text-emerald-400 hover:underline"
              >
                <span>View in OAR &amp; WO List</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </div>
        )}

        {/* Intake Form */}
        <form
          onSubmit={handleSubmit}
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5"
        >
          <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
            <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50">
              Customer PO Details
            </h3>
            <span className="text-xs text-zinc-400">OAR Entry Form</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Customer</label>
              <select
                value={customerCode}
                onChange={(e) => handleCustomerChange(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                {PRESET_CUSTOMERS.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.name} ({c.code})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Customer PO Number *</label>
              <input
                type="text"
                required
                value={customerPO}
                onChange={(e) => setCustomerPO(e.target.value)}
                placeholder="e.g. PO-2026-950"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Part Number</label>
              <select
                value={partNumber}
                onChange={(e) => handlePartChange(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                {PRESET_PARTS.map((p) => (
                  <option key={p.num} value={p.num}>
                    {p.num} — {p.grade}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Material Grade</label>
              <input
                type="text"
                value={grade}
                onChange={(e) => setGrade(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Total PO Quantity (pcs) *</label>
              <input
                type="number"
                required
                min={1}
                value={poQty}
                onChange={(e) => setPoQty(e.target.value === "" ? "" : Number(e.target.value))}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Max Batch Size (pcs) *</label>
              <input
                type="number"
                required
                min={1}
                value={batchSize}
                onChange={(e) => setBatchSize(e.target.value === "" ? "" : Number(e.target.value))}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Customer Delivery Date</label>
              <input
                type="date"
                value={deliveryDate}
                onChange={(e) => setDeliveryDate(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>
          </div>

          {/* WO Quantity Allocation */}
          <div className="pt-3 border-t border-zinc-100 dark:border-zinc-800 space-y-3">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-bold text-zinc-900 dark:text-zinc-50">Work Order Quantity Split</h4>
              <div className="flex rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden">
                <button
                  type="button"
                  onClick={() => setSplitMode("auto")}
                  className={`px-3 py-1.5 text-[11px] font-bold transition-colors ${
                    splitMode === "auto"
                      ? "bg-blue-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-500 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  }`}
                >
                  Auto Split
                </button>
                <button
                  type="button"
                  onClick={() => setSplitMode("manual")}
                  className={`px-3 py-1.5 text-[11px] font-bold transition-colors ${
                    splitMode === "manual"
                      ? "bg-blue-600 text-white"
                      : "bg-white dark:bg-zinc-900 text-zinc-500 hover:bg-zinc-50 dark:hover:bg-zinc-800"
                  }`}
                >
                  Manual Split
                </button>
              </div>
            </div>

            {splitMode === "auto" ? (
              Number(poQty) > 0 && Number(batchSize) > 0 && (
                <div className="rounded-xl bg-blue-50/50 dark:bg-blue-950/30 p-3.5 border border-blue-200 dark:border-blue-900/40 text-xs flex items-center justify-between">
                  <span className="text-zinc-600 dark:text-zinc-400">
                    Order will be split into: <strong className="text-blue-600">{Math.ceil(Number(poQty) / Number(batchSize))} Work Orders</strong>
                  </span>
                  <span className="font-mono text-zinc-500">
                    {poQty} pcs ÷ {batchSize} batch max
                  </span>
                </div>
              )
            ) : (
              <div className="space-y-2">
                {manualQtys.map((v, idx) => (
                  <div key={idx} className="flex items-center gap-2">
                    <span className="w-14 text-[11px] font-mono font-bold text-zinc-400">WO #{idx + 1}</span>
                    <input
                      type="number"
                      min={1}
                      value={v}
                      onChange={(e) => updateManualQty(idx, e.target.value)}
                      placeholder="Quantity"
                      className="flex-1 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-1.5 text-xs font-bold font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => removeManualRow(idx)}
                      disabled={manualQtys.length <= 1}
                      className="text-[11px] font-bold text-rose-500 disabled:opacity-30 disabled:cursor-not-allowed px-2"
                    >
                      Remove
                    </button>
                  </div>
                ))}
                <button
                  type="button"
                  onClick={addManualRow}
                  className="text-[11px] font-bold text-blue-600 hover:underline"
                >
                  + Add another Work Order
                </button>

                <div
                  className={`rounded-xl p-3.5 border text-xs flex items-center justify-between ${
                    manualComplete
                      ? "bg-emerald-50/50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-900/40"
                      : "bg-amber-50/50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40"
                  }`}
                >
                  <span className="text-zinc-600 dark:text-zinc-400">
                    Allocated: <strong className="font-mono">{manualAllocated}</strong> / {Number(poQty) || 0} pcs
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

          <div className="pt-2">
            <button
              type="submit"
              disabled={loading || !poQty || !batchSize || (splitMode === "manual" && !manualComplete)}
              className="flex w-full items-center justify-center gap-2 rounded-xl bg-blue-600 py-3.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              <FilePlus className="h-4 w-4" />
              <span>{loading ? "Creating OAR & Work Orders..." : "Accept Order & Create Work Orders"}</span>
            </button>
          </div>
        </form>
      </div>
    </AppShell>
  );
}

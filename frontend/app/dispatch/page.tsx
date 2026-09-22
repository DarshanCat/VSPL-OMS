"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  Truck,
  Search,
  CheckCircle2,
  AlertTriangle,
  Download,
  FileText,
  RefreshCw,
  ArrowRight,
  ShieldCheck,
  Building,
  Calendar
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import { getDispatchQueue, executeDispatch, getDispatchHistory, API_BASE } from "@/lib/api";

export default function DispatchPage() {
  const [activeTab, setActiveTab] = useState<"queue" | "history">("queue");
  const [queue, setQueue] = useState<any[]>([]);
  const [history, setHistory] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  // Dispatch Action Modal
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [invoiceNo, setInvoiceNo] = useState("");
  const [dispatchQty, setDispatchQty] = useState<number | "">("");
  const [vehicleNo, setVehicleNo] = useState("");
  const [transporter, setTransporter] = useState("");
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");
  const [dispatchSuccess, setDispatchSuccess] = useState<any>(null);

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [qData, hData] = await Promise.all([
        getDispatchQueue(),
        getDispatchHistory(),
      ]);
      setQueue(qData);
      setHistory(hData);
    } catch (err: any) {
      setError("Failed to fetch dispatch records from server.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openShipModal = (item: any) => {
    setSelectedItem(item);
    // Dispatch quantity is always a fresh transaction amount, never prefilled with the
    // full ready-for-dispatch quantity -- the operator must enter what is actually
    // being shipped in this consignment.
    setDispatchQty("");
    const invCount = history.length + 1;
    setInvoiceNo(`INV-2026-${String(invCount).padStart(4, "0")}`);
    setVehicleNo("KA-04-E-8821");
    setTransporter("VRL Logistics Express");
    setRemarks("");
    setModalError("");
  };

  const handleShipSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedItem) return;

    const qty = Number(dispatchQty);
    if (qty <= 0) {
      setModalError("Please enter a valid dispatch quantity (> 0).");
      return;
    }

    // STRICT VALIDATION AGAINST PACKING READY QTY
    if (qty > selectedItem.ready_for_dispatch_qty) {
      setModalError(
        `Cannot dispatch ${qty} pieces. Only ${selectedItem.ready_for_dispatch_qty} pieces are ready for dispatch after Packing / BSR for WO ${selectedItem.wo_number}.`
      );
      return;
    }

    if (!invoiceNo.trim()) {
      setModalError("Invoice Number is mandatory for dispatch.");
      return;
    }

    setSubmitting(true);
    setModalError("");

    try {
      const res = await executeDispatch({
        wo_number: selectedItem.wo_number,
        invoice_number: invoiceNo.trim(),
        dispatched_quantity: qty,
        customer_po: selectedItem.customer_po,
        vehicle_number: vehicleNo,
        transporter: transporter,
        remarks: remarks,
      });

      setDispatchSuccess(res);
      setSelectedItem(null);
      loadData();
    } catch (err: any) {
      setModalError(err?.response?.data?.detail || "Dispatch validation failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Final Gate / Dispatch
              </span>
              <span className="text-xs text-zinc-400">Strict Packing Validation</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Dispatch & Outward Shipping Bay
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Execute customer dispatches against verified Packing/BSR inventory with invoice traceability.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <a
              href={`${API_BASE}/api/v1/reports/export/dispatch-csv`}
              download
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <Download className="h-3.5 w-3.5 text-blue-600" />
              <span>Export Invoices CSV</span>
            </a>
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl bg-blue-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-blue-500 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Tab Toggle */}
        <div className="flex items-center gap-2 border-b border-zinc-200 dark:border-zinc-800 pb-2">
          <button
            type="button"
            onClick={() => setActiveTab("queue")}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-lg transition-colors ${
              activeTab === "queue"
                ? "bg-blue-600 text-white shadow-xs"
                : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <Truck className="h-4 w-4" />
            <span>Ready for Dispatch Queue ({queue.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("history")}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-lg transition-colors ${
              activeTab === "history"
                ? "bg-blue-600 text-white shadow-xs"
                : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <FileText className="h-4 w-4" />
            <span>Dispatch Invoices History ({history.length})</span>
          </button>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Success Alert */}
        {dispatchSuccess && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-center justify-between text-xs text-emerald-700 dark:text-emerald-300">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              <span className="font-bold">{dispatchSuccess.message}</span>
            </div>
            <button
              onClick={() => setDispatchSuccess(null)}
              className="text-zinc-400 hover:text-zinc-600 text-xs font-semibold"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Tab 1: Ready Queue */}
        {activeTab === "queue" && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                  <tr>
                    <th className="py-3 px-3">Work Order</th>
                    <th className="py-3 px-3">Customer Code</th>
                    <th className="py-3 px-3">Customer Name</th>
                    <th className="py-3 px-3">Customer PO</th>
                    <th className="py-3 px-3">Part Number</th>
                    <th className="py-3 px-3 text-right">Order Qty</th>
                    <th className="py-3 px-3 text-right font-extrabold text-emerald-600">Ready for Dispatch</th>
                    <th className="py-3 px-3 text-right text-zinc-400">Already Shipped</th>
                    <th className="py-3 px-3 text-center">Action</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                  {queue.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-zinc-400 text-xs">
                        No goods currently in the Ready for Dispatch queue. Complete Packing / BSR first.
                      </td>
                    </tr>
                  ) : (
                    queue.map((item) => (
                      <tr key={item.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                        <td className="py-3 px-3 font-mono font-bold">
                          <Link
                            href={`/production/tracking?wo=${item.wo_number}`}
                            className="text-blue-600 dark:text-blue-400 hover:underline"
                          >
                            {item.wo_number}
                          </Link>
                        </td>
                        <td className="py-3 px-3 font-mono text-zinc-500">{item.customer_code}</td>
                        <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300 truncate max-w-[150px]">
                          {item.customer_name}
                        </td>
                        <td className="py-3 px-3 font-mono text-zinc-700 dark:text-zinc-300">{item.customer_po}</td>
                        <td className="py-3 px-3 font-semibold text-zinc-900 dark:text-zinc-100">{item.part_number}</td>
                        <td className="py-3 px-3 text-right text-zinc-500 font-mono">{item.order_qty} pcs</td>
                        <td className="py-3 px-3 text-right font-mono font-extrabold text-emerald-600 dark:text-emerald-400 text-sm">
                          {item.ready_for_dispatch_qty} pcs
                        </td>
                        <td className="py-3 px-3 text-right text-zinc-400 font-mono">{item.already_dispatched_qty} pcs</td>
                        <td className="py-3 px-3 text-center">
                          <button
                            type="button"
                            onClick={() => openShipModal(item)}
                            disabled={item.ready_for_dispatch_qty <= 0}
                            className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-emerald-500 disabled:opacity-30 transition-colors"
                          >
                            Ship Goods
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 2: Dispatch History */}
        {activeTab === "history" && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                  <tr>
                    <th className="py-3 px-3">Invoice Number</th>
                    <th className="py-3 px-3">Dispatch Date</th>
                    <th className="py-3 px-3">Work Order</th>
                    <th className="py-3 px-3">Customer</th>
                    <th className="py-3 px-3">Customer PO</th>
                    <th className="py-3 px-3">Part Number</th>
                    <th className="py-3 px-3 text-right font-bold text-emerald-600">Dispatched Qty</th>
                    <th className="py-3 px-3">Dispatcher</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                  {history.map((h) => (
                    <tr key={h.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                      <td className="py-3 px-3 font-mono font-bold text-emerald-600 dark:text-emerald-400">
                        {h.invoice_number}
                      </td>
                      <td className="py-3 px-3 text-zinc-500">{h.dispatch_date?.substring(0, 10)}</td>
                      <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        <Link href={`/production/tracking?wo=${h.wo_number}`} className="hover:underline">
                          {h.wo_number}
                        </Link>
                      </td>
                      <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300">{h.customer_name}</td>
                      <td className="py-3 px-3 font-mono text-zinc-500">{h.customer_po}</td>
                      <td className="py-3 px-3 font-semibold text-zinc-900 dark:text-zinc-100">{h.part_number}</td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-emerald-600">
                        {h.dispatched_qty} pcs
                      </td>
                      <td className="py-3 px-3 text-zinc-500">{h.dispatcher_name || "Dispatch Officer"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Ship Goods Modal */}
        <Modal
          isOpen={!!selectedItem}
          onClose={() => setSelectedItem(null)}
          title={`Generate Invoice & Dispatch Goods — ${selectedItem?.wo_number}`}
          subtitle={`Customer: ${selectedItem?.customer_name} | Ready for Dispatch: ${selectedItem?.ready_for_dispatch_qty} pcs`}
        >
          <form onSubmit={handleShipSubmit} className="space-y-4">
            {modalError && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                {modalError}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Invoice Number *
                </label>
                <input
                  type="text"
                  required
                  value={invoiceNo}
                  onChange={(e) => setInvoiceNo(e.target.value)}
                  placeholder="e.g. INV-2026-0082"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:border-emerald-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                  <span>Dispatch Qty (pcs) *</span>
                  <span className="text-[10px] text-zinc-400">Max: {selectedItem?.ready_for_dispatch_qty}</span>
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  max={selectedItem?.ready_for_dispatch_qty}
                  value={dispatchQty}
                  onChange={(e) => setDispatchQty(e.target.value === "" ? "" : Number(e.target.value))}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-extrabold text-emerald-600 focus:border-emerald-500 focus:outline-none"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Vehicle Number
                </label>
                <input
                  type="text"
                  value={vehicleNo}
                  onChange={(e) => setVehicleNo(e.target.value)}
                  placeholder="e.g. KA-01-AB-1234"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Transporter / Logistics
                </label>
                <input
                  type="text"
                  value={transporter}
                  onChange={(e) => setTransporter(e.target.value)}
                  placeholder="e.g. VRL Logistics / Direct Truck"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                Dispatch Remarks / E-Way Bill No
              </label>
              <input
                type="text"
                value={remarks}
                onChange={(e) => setRemarks(e.target.value)}
                placeholder="e.g. E-Way Bill generated, dispatched to customer central warehouse"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setSelectedItem(null)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !dispatchQty || !invoiceNo}
                className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-500 disabled:opacity-50 transition-colors"
              >
                <Truck className="h-4 w-4" />
                <span>{submitting ? "Processing..." : "Confirm & Finalize Dispatch"}</span>
              </button>
            </div>
          </form>
        </Modal>
      </div>
    </AppShell>
  );
}

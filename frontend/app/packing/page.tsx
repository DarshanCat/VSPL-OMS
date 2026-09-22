"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  PackageCheck,
  Search,
  CheckCircle2,
  Boxes,
  Truck,
  ArrowRight,
  Clock,
  RefreshCw
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import { getPackingQueue, updatePacking } from "@/lib/api";

export default function PackingPage() {
  const [queue, setQueue] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  // Pack Action Modal
  const [selectedWO, setSelectedWO] = useState<any>(null);
  const [packQty, setPackQty] = useState<number | "">("");
  const [boxCount, setBoxCount] = useState(1);
  const [packageType, setPackageType] = useState("Standard Wooden Box");
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");

  const loadQueue = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getPackingQueue();
      setQueue(data);
    } catch (err: any) {
      setError("Failed to fetch packing queue from server.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadQueue();
  }, []);

  const openPackModal = (item: any) => {
    setSelectedWO(item);
    // Packing quantity is always a fresh transaction amount, never prefilled with the
    // full pending quantity -- the operator must enter what was actually just packed.
    setPackQty("");
    setBoxCount(1);
    setRemarks("");
    setModalError("");
  };

  const handlePackSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWO) return;

    const qty = Number(packQty);
    if (qty <= 0) {
      setModalError("Please enter a valid packing quantity (> 0).");
      return;
    }

    if (qty > selectedWO.pending_qty) {
      setModalError(
        `Cannot pack ${qty} pieces. Only ${selectedWO.pending_qty} pieces are pending packing for ${selectedWO.wo_number}.`
      );
      return;
    }

    setSubmitting(true);
    setModalError("");

    try {
      await updatePacking({
        wo_number: selectedWO.wo_number,
        packed_quantity: qty,
        box_count: boxCount,
        package_type: packageType,
        remarks: remarks,
      });

      setSelectedWO(null);
      loadQueue();
    } catch (err: any) {
      setModalError(err?.response?.data?.detail || "Packing update failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const filteredQueue = queue.filter(
    (item) =>
      !search ||
      item.wo_number.toLowerCase().includes(search.toLowerCase()) ||
      item.part_number.toLowerCase().includes(search.toLowerCase()) ||
      item.customer_name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-purple-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Stage 6 / Gate BSR
              </span>
              <span className="text-xs text-zinc-400">Post-Final Inspection</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Packing & BSR Execution
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Verify FI-approved quantities, execute protective packing, and prepare goods for validated dispatch.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <Link
              href="/dispatch"
              className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-emerald-500 transition-colors"
            >
              <Truck className="h-3.5 w-3.5" />
              <span>Go to Dispatch Bay</span>
            </Link>
            <button
              onClick={loadQueue}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <div className="relative">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search Packing Queue by WO Number, Part Number, or Customer..."
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-10 pr-4 py-2 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Packing Queue Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-3 px-3">Work Order</th>
                  <th className="py-3 px-3">Customer</th>
                  <th className="py-3 px-3">Part Details</th>
                  <th className="py-3 px-3 text-right">FI Approved</th>
                  <th className="py-3 px-3 text-right">Packed / Done</th>
                  <th className="py-3 px-3 text-right font-bold text-purple-600">Pending Packing</th>
                  <th className="py-3 px-3 text-right font-bold text-emerald-600">Ready for Dispatch</th>
                  <th className="py-3 px-3">Status</th>
                  <th className="py-3 px-3 text-center">Action</th>
                </tr>
              </thead>

              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {filteredQueue.map((item) => (
                  <tr key={item.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                    <td className="py-3 px-3 font-mono font-bold">
                      <Link
                        href={`/production/tracking?wo=${item.wo_number}`}
                        className="text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        {item.wo_number}
                      </Link>
                    </td>
                    <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300 truncate max-w-[150px]">
                      {item.customer_name}
                    </td>
                    <td className="py-3 px-3">
                      <span className="font-semibold text-zinc-900 dark:text-zinc-100">{item.part_number}</span>
                      <span className="text-[10px] text-zinc-400 block">{item.grade || "Standard Bronze"}</span>
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-zinc-800 dark:text-zinc-200 font-mono">
                      {item.fi_approved_qty} pcs
                    </td>
                    <td className="py-3 px-3 text-right font-bold text-zinc-600 dark:text-zinc-400 font-mono">
                      {item.packed_qty} pcs
                    </td>
                    <td className="py-3 px-3 text-right font-mono font-extrabold text-purple-600 dark:text-purple-400">
                      {item.pending_qty} pcs
                    </td>
                    <td className="py-3 px-3 text-right font-mono font-extrabold text-emerald-600 dark:text-emerald-400">
                      {item.ready_for_dispatch_qty} pcs
                    </td>
                    <td className="py-3 px-3">
                      <Badge variant={getRAGVariant(item.status)} size="sm">
                        {item.status}
                      </Badge>
                    </td>
                    <td className="py-3 px-3 text-center">
                      <button
                        type="button"
                        onClick={() => openPackModal(item)}
                        disabled={item.pending_qty <= 0}
                        className="rounded-lg bg-purple-600 px-3 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-purple-500 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      >
                        Pack Parts
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pack Parts Modal */}
        <Modal
          isOpen={!!selectedWO}
          onClose={() => setSelectedWO(null)}
          title={`Pack Parts & Complete BSR — ${selectedWO?.wo_number}`}
          subtitle={`FI Approved: ${selectedWO?.fi_approved_qty} pcs | Pending Packing: ${selectedWO?.pending_qty} pcs`}
        >
          <form onSubmit={handlePackSubmit} className="space-y-4">
            {modalError && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                {modalError}
              </div>
            )}

            <div>
              <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                <span>Quantity to Pack (pcs) *</span>
                <span className="text-[11px] text-zinc-400">Pending: {selectedWO?.pending_qty}</span>
              </label>
              <input
                type="number"
                required
                min={1}
                max={selectedWO?.pending_qty}
                value={packQty}
                onChange={(e) => setPackQty(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="Enter packed quantity"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-4 py-2.5 text-base font-extrabold text-zinc-900 dark:text-zinc-50 focus:border-purple-500 focus:outline-none font-mono"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Box / Pallet Count
                </label>
                <input
                  type="number"
                  min={1}
                  value={boxCount}
                  onChange={(e) => setBoxCount(Number(e.target.value))}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Packaging Type
                </label>
                <select
                  value={packageType}
                  onChange={(e) => setPackageType(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  <option value="Standard Wooden Box">Standard Wooden Box</option>
                  <option value="Corrugated Heavy Box">Corrugated Heavy Box</option>
                  <option value="Pallet with Shrinkwrap">Pallet with Shrinkwrap</option>
                  <option value="VCI Anti-Corrosion Bag">VCI Anti-Corrosion Bag</option>
                </select>
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                Packaging Notes / BSR Number
              </label>
              <input
                type="text"
                value={remarks}
                onChange={(e) => setRemarks(e.target.value)}
                placeholder="e.g. BSR-2026-042 banded and preserved with rust preventive oil"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setSelectedWO(null)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !packQty}
                className="flex items-center gap-1.5 rounded-xl bg-purple-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-purple-500 disabled:opacity-50 transition-colors"
              >
                <PackageCheck className="h-4 w-4" />
                <span>{submitting ? "Saving..." : "Confirm Packing & Ready for Dispatch"}</span>
              </button>
            </div>
          </form>
        </Modal>
      </div>
    </AppShell>
  );
}

"use client";
import React, { useState } from "react";
import { AlertTriangle, Check, RefreshCw, X, ShoppingCart, CalendarClock, Trash2 } from "lucide-react";
import { OARListItem, updateOAR, deleteOAR } from "@/lib/api";

function formatDate(dateStr?: string | null): string {
  if (!dateStr) return "—";
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    return d.toLocaleDateString("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
  } catch {
    return dateStr;
  }
}

export interface EditOARModalProps {
  oar: OARListItem;
  onClose: () => void;
  onSuccess: (updatedOar: OARListItem) => void;
  onDelete?: (deletedOarNumber: string) => void;
}

export function EditOARModal({ oar, onClose, onSuccess, onDelete }: EditOARModalProps) {
  const isAlreadyCommitted = Boolean(oar.commitment_date || oar.revised_commitment_date);
  const currentEffDate = oar.effective_commitment_date || oar.revised_commitment_date || oar.commitment_date;
  const initialCommitmentDate = currentEffDate
    ? currentEffDate.slice(0, 10)
    : "";
  const initialDeliveryDate = oar.delivery_date ? oar.delivery_date.slice(0, 10) : "";

  const [qty, setQty] = useState<number | "">(oar.oar_qty);
  const [deliveryDate, setDeliveryDate] = useState<string>(initialDeliveryDate);
  const [commitmentDate, setCommitmentDate] = useState<string>(initialCommitmentDate);
  const [revisionReason, setRevisionReason] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");

  const minAllowedQty = oar.allocated_qty || 1;

  const handleDeleteOar = async () => {
    if (!window.confirm(`Are you sure you want to permanently delete OAR ${oar.oar_number}? This will unlink it from the Customer PO line.`)) {
      return;
    }
    try {
      setDeleting(true);
      setError("");
      await deleteOAR(oar.oar_number);
      if (onDelete) {
        onDelete(oar.oar_number);
      } else {
        onClose();
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to delete OAR.";
      setError(msg);
    } finally {
      setDeleting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const numQty = Number(qty);
    if (!numQty || numQty <= 0) {
      setError("OAR Quantity must be greater than 0.");
      return;
    }

    if (numQty < (oar.allocated_qty || 0)) {
      setError(
        `Cannot reduce OAR quantity to ${numQty} pcs because ${oar.allocated_qty} pcs are already allocated to Work Orders. Please delete or reduce existing Work Orders first.`
      );
      return;
    }

    try {
      setSaving(true);
      setError("");

      const payload: {
        oar_qty?: number;
        commitment_date?: string;
        revised_commitment_date?: string;
        revision_reason?: string;
        delivery_date?: string;
      } = {};

      if (numQty !== oar.oar_qty) {
        payload.oar_qty = numQty;
      }

      if (deliveryDate && deliveryDate !== initialDeliveryDate) {
        payload.delivery_date = deliveryDate;
      }

      if (commitmentDate) {
        if (isAlreadyCommitted) {
          if (commitmentDate !== (currentEffDate ? currentEffDate.slice(0, 10) : "")) {
            payload.revised_commitment_date = commitmentDate;
            payload.revision_reason = revisionReason.trim() || undefined;
          }
        } else {
          payload.commitment_date = commitmentDate;
          if (revisionReason.trim()) {
            payload.revision_reason = revisionReason.trim();
          }
        }
      }

      const updated = await updateOAR(oar.oar_number, payload);
      onSuccess(updated);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to update OAR.";
      setError(typeof msg === "string" ? msg : JSON.stringify(msg));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in overflow-y-auto">
      <div className="w-full max-w-lg rounded-2xl bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 shadow-2xl overflow-hidden my-8">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/50">
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-emerald-100 dark:bg-emerald-950/70 text-emerald-600 dark:text-emerald-400">
              <ShoppingCart className="h-5 w-5" />
            </div>
            <div>
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
                Edit OAR &amp; Sync Customer PO
              </h3>
              <p className="text-[11px] text-zinc-500 font-mono">OAR: {oar.oar_number}</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 transition cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-5 space-y-4 text-xs">
          {error && (
            <div className="p-3 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-300 text-xs flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* OAR Context Card */}
          <div className="rounded-xl bg-zinc-50 dark:bg-zinc-800/40 p-3.5 border border-zinc-200 dark:border-zinc-800 space-y-2">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <span className="text-[10px] text-zinc-400 block uppercase font-bold">Customer</span>
                <span className="font-semibold text-zinc-800 dark:text-zinc-200 truncate block">
                  {oar.customer_name}
                </span>
                <span className="text-[10px] text-zinc-400 font-mono">PO: {oar.customer_po || "—"}</span>
              </div>
              <div>
                <span className="text-[10px] text-zinc-400 block uppercase font-bold">Part</span>
                <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200 block truncate">
                  {oar.customer_part_number || oar.part_number}
                </span>
                {oar.customer_part_number && oar.customer_part_number !== oar.part_number && (
                  <span className="text-[10px] text-zinc-400 font-mono block">Internal: {oar.part_number}</span>
                )}
              </div>
            </div>

            <div className="pt-2 border-t border-zinc-200/70 dark:border-zinc-700/70 grid grid-cols-3 gap-2 text-[11px]">
              <div>
                <span className="text-zinc-400 block">Current OAR Qty:</span>
                <span className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{oar.oar_qty} pcs</span>
              </div>
              <div>
                <span className="text-zinc-400 block">Allocated to WOs:</span>
                <span className="font-mono font-bold text-blue-600">{oar.allocated_qty || 0} pcs</span>
              </div>
              <div>
                <span className="text-zinc-400 block">Unallocated:</span>
                <span className="font-mono font-bold text-amber-600">{oar.remaining_qty} pcs</span>
              </div>
            </div>
          </div>

          {/* Quantity Edit Field */}
          <div>
            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
              OAR &amp; Customer PO Quantity (pcs) *
            </label>
            <input
              type="number"
              required
              min={minAllowedQty}
              value={qty}
              onChange={(e) => setQty(e.target.value === "" ? "" : Number(e.target.value))}
              className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
            />
            <p className="text-[10px] text-zinc-500 dark:text-zinc-400 mt-1">
              Syncs directly with linked Customer PO line <strong className="text-zinc-700 dark:text-zinc-300 font-mono">PO: {oar.customer_po || "N/A"}</strong> and re-computes PO total value.
              {oar.allocated_qty > 0 && (
                <span className="block text-amber-600 dark:text-amber-400 mt-0.5">
                  Minimum quantity is {oar.allocated_qty} pcs (already planned in Work Orders).
                </span>
              )}
            </p>
          </div>

          {/* Delivery Date & Commitment Date in 2 columns */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                PO Delivery Date
              </label>
              <input
                type="date"
                value={deliveryDate}
                onChange={(e) => setDeliveryDate(e.target.value)}
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1 flex items-center justify-between">
                <span className="flex items-center gap-1">
                  <CalendarClock className="h-3.5 w-3.5 text-blue-500" />
                  <span>Commitment Date</span>
                </span>
                {!isAlreadyCommitted && (
                  <span className="text-[10px] text-zinc-400 font-normal italic">(Currently: Not Set)</span>
                )}
              </label>
              <input
                type="date"
                value={commitmentDate}
                onChange={(e) => setCommitmentDate(e.target.value)}
                className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
              />
            </div>
          </div>

          {/* Revision Reason / Remarks */}
          <div>
            <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
              Revision Reason / Remarks (Optional)
            </label>
            <input
              type="text"
              placeholder="e.g., Customer amendment, PO quantity revision..."
              value={revisionReason}
              onChange={(e) => setRevisionReason(e.target.value)}
              className="w-full rounded-xl border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3.5 py-2 text-xs text-zinc-900 dark:text-zinc-50 focus:border-blue-500 focus:outline-none"
            />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between pt-3 border-t border-zinc-200 dark:border-zinc-800">
            {(!oar.allocated_qty || oar.allocated_qty === 0) ? (
              <button
                type="button"
                onClick={handleDeleteOar}
                disabled={deleting || saving}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold text-rose-600 hover:text-rose-700 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition cursor-pointer"
                title="Permanently delete this unstarted OAR"
              >
                <Trash2 className="h-4 w-4" />
                <span>{deleting ? "Deleting OAR..." : "Delete OAR"}</span>
              </button>
            ) : <div />}

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={onClose}
                disabled={saving || deleting}
                className="px-3.5 py-2 rounded-xl border border-zinc-300 dark:border-zinc-700 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={saving || deleting}
                className="px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold transition shadow-sm flex items-center gap-1.5 disabled:opacity-60 cursor-pointer"
              >
                {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                <span>{saving ? "Saving Changes..." : "Update OAR & PO"}</span>
              </button>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

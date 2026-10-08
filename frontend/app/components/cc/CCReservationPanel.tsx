"use client";
import React, { useCallback, useEffect, useState } from "react";
import { X } from "lucide-react";
import { CCActionForm } from "./CCActionForm";
import { CCConfirmModal } from "./CCConfirmModal";
import { CCErrorBanner } from "./CCErrorBanner";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { CCUnitBalances } from "./CCUnitBalances";
import {
  ccErrorMessage, ccGetStockUnit, ccReleaseReservation, ccReserve, CCAllocationOut, CCStockMovementResult,
  CCStockUnitDetail,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls, parsePositiveInt } from "@/lib/continuousCastingForm";

// Reserve, or Release a reservation of, ONE allocation. These are two separate operations (the caller picks `mode`):
//  - Reserve: reserves planned stock. It does not consume physical material (no issue, no cut).
//  - Release reservation: releases only reserved length; issued and consumed material is untouched.
// The panel asks only for a length and an optional reason. Every figure shown is the backend's; the backend decides
// what is allowed. `allocation` is the latest backend row (refreshed by the caller after every change).
export function CCReservationPanel({ mode, allocation, onClose, onChanged }: {
  mode: "reserve" | "release";
  allocation: CCAllocationOut;
  onClose: () => void;
  onChanged: () => void; // reload routings, allocations and gate status
}) {
  const [unit, setUnit] = useState<CCStockUnitDetail | null>(null);
  const [unitError, setUnitError] = useState<string | null>(null);
  const [length, setLength] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<CCStockMovementResult | null>(null);

  const loadUnit = useCallback(async () => {
    try {
      setUnit(await ccGetStockUnit(allocation.stock_unit_id));
      setUnitError(null);
    } catch (err) {
      setUnitError(ccErrorMessage(err));
    }
  }, [allocation.stock_unit_id]);

  useEffect(() => { void loadUnit(); }, [loadUnit]);

  const isReserve = mode === "reserve";
  const title = isReserve ? "Reserve allocation" : "Release reservation";
  // Display of the backend's own routing status: reservation actions apply to an ACTIVE routing only.
  const routingActive = allocation.routing_status === "ACTIVE";

  const run = async () => {
    if (busy) return;
    const lengthMm = parsePositiveInt(length);
    setBusy(true);
    setError(null);
    try {
      const body = {
        routing_id: allocation.routing_id, allocation_id: allocation.allocation_id,
        length_mm: lengthMm, reason: reason.trim() === "" ? null : reason.trim(),
      };
      const res = isReserve ? await ccReserve(body) : await ccReleaseReservation(body);
      setConfirmOpen(false);
      setResult(res);
      setLength(""); setReason("");
      await loadUnit();
      onChanged();
    } catch (err) {
      setError(ccErrorMessage(err)); // backend text verbatim; never retried
      setConfirmOpen(false);
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 400 || status === 404 || status === 409) {
        await loadUnit();
        onChanged();
      }
    } finally {
      setBusy(false);
    }
  };

  const submit = () => {
    if (Number.isNaN(parsePositiveInt(length))) return setError("Length must be a whole number of mm greater than 0.");
    setError(null);
    if (isReserve) void run();
    else setConfirmOpen(true); // releasing a reservation changes stock commitments: confirm first
  };

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd>{v}</dd></div>
  );

  return (
    <section className={`space-y-3 rounded-xl border bg-white p-4 text-xs dark:bg-zinc-900 ${isReserve ? "border-purple-500/40" : "border-amber-500/40"}`}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
          {title} <span className="font-mono">{allocation.allocation_number}</span>
        </h3>
        <button type="button" onClick={onClose} aria-label="Close" className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"><X className="h-4 w-4" /></button>
      </div>
      <p className={`rounded-lg border px-3 py-2 font-semibold ${isReserve ? "border-purple-500/30 bg-purple-500/10 text-purple-800 dark:text-purple-200" : "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-200"}`}>
        {isReserve
          ? "Reservation reserves planned stock. It does not consume physical material."
          : "Releases only reserved length. Issued and consumed material is not released by this action."}
      </p>
      {!isReserve && (
        <p className="text-[11px] text-zinc-500">Returning issued material is the Stores Return transaction, not this action.</p>
      )}

      <div>
        <p className="mb-1 font-semibold">Allocation (backend values)</p>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {kv("Allocation", <CCTxnNumber value={allocation.allocation_number} />)}
          {kv("Routing", <span className="font-mono">v{allocation.routing_version} <CCStatusBadge status={allocation.routing_status} /></span>)}
          {kv("WO", <span className="font-mono">{allocation.wo_number}</span>)}
          {kv("Stock unit", <span className="font-mono">{allocation.stock_unit_number}</span>)}
          {kv("Allocation status", <CCStatusBadge status={allocation.status} />)}
          {kv("Planned", <CCLengthCell mm={allocation.planned_length_mm} />)}
          {kv("Reserved", <CCLengthCell mm={allocation.reserved_length_mm} />)}
          {kv("Issued", <CCLengthCell mm={allocation.issued_length_mm} />)}
          {kv("Consumed", <CCLengthCell mm={allocation.consumed_length_mm} />)}
          {kv("Plan remaining", <CCLengthCell mm={allocation.plan_remaining_length_mm} />)}
        </dl>
      </div>
      <div>
        <p className="mb-1 font-semibold">Stock unit (backend values)</p>
        <CCErrorBanner message={unitError} />
        {unit && <CCUnitBalances unit={unit} />}
      </div>

      {result && (
        <div role="status" className="space-y-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-emerald-900 dark:text-emerald-200">
          <p className="font-semibold">{result.message}</p>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {kv("Ledger transaction", <b><CCTxnNumber value={result.ledger_transaction_number} /></b>)}
            {kv("Movement", <span className="font-mono">{result.movement_type}</span>)}
            {kv("Length", <CCLengthCell mm={result.length_mm} />)}
            {kv("Allocation status", <CCStatusBadge status={result.allocation_status} />)}
            {kv("Planned", <CCLengthCell mm={result.allocation_planned_length_mm} />)}
            {kv("Reserved", <CCLengthCell mm={result.allocation_reserved_length_mm} />)}
            {kv("Issued", <CCLengthCell mm={result.allocation_issued_length_mm} />)}
            {kv("Consumed", <CCLengthCell mm={result.allocation_consumed_length_mm} />)}
            {kv("Unit remaining", <CCLengthCell mm={result.unit_remaining_length_mm} />)}
            {kv("Unit reserved", <CCLengthCell mm={result.unit_reserved_length_mm} />)}
            {kv("Unit issued", <CCLengthCell mm={result.unit_issued_length_mm} />)}
            {kv("Unit free", <CCLengthCell mm={result.unit_free_length_mm} />)}
            {kv("Ledger reserved length", <CCLengthCell mm={result.ledger_reserved_length_mm} />)}
            {kv("Reconciled", result.reconciled ? "Yes" : "No")}
          </dl>
        </div>
      )}

      {routingActive ? (
        <CCActionForm onSubmit={submit} busy={busy} error={confirmOpen ? null : error} submitLabel={isReserve ? "Reserve" : "Review release"}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={ccLabelCls}>{isReserve ? "Length to reserve (mm) *" : "Length to release (mm) *"}</label>
              <input className={ccInputCls} inputMode="numeric" value={length} onChange={(e) => setLength(e.target.value)} autoFocus />
            </div>
            <div className="sm:col-span-2">
              <label className={ccLabelCls}>Reason (optional)</label>
              <input className={ccInputCls} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
            </div>
          </div>
        </CCActionForm>
      ) : (
        <p className="rounded-lg border border-zinc-300 px-3 py-2 text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
          The backend reports this allocation&apos;s routing as {allocation.routing_status}. Reserve and Release reservation
          are only offered on an ACTIVE routing. Use &quot;Release superseded reservations&quot; on the routing version instead.
        </p>
      )}
      {!routingActive && <CCErrorBanner message={error} />}

      <CCConfirmModal
        isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} onConfirm={() => void run()}
        title="Confirm release reservation" confirmLabel="Release reservation" busy={busy}
      >
        <dl className="grid grid-cols-2 gap-2 text-xs">
          {kv("Allocation", <span className="font-mono">{allocation.allocation_number}</span>)}
          {kv("Routing", <span className="font-mono">v{allocation.routing_version}</span>)}
          {kv("Length to release", <CCLengthCell mm={parsePositiveInt(length)} />)}
          {kv("Currently reserved (backend)", <CCLengthCell mm={allocation.reserved_length_mm} />)}
          {kv("Issued (backend)", <CCLengthCell mm={allocation.issued_length_mm} />)}
          {kv("Consumed (backend)", <CCLengthCell mm={allocation.consumed_length_mm} />)}
        </dl>
        <p className="text-zinc-500">Only reserved length is released. Issued and consumed material is not affected. The backend validates the amount.</p>
      </CCConfirmModal>
    </section>
  );
}

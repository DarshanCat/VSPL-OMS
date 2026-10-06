"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import { CCActionForm } from "./CCActionForm";
import { CCConfirmModal } from "./CCConfirmModal";
import { CCErrorBanner } from "./CCErrorBanner";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { CCUnitBalances } from "./CCUnitBalances";
import {
  ccCutConsume, ccErrorMessage, ccGetStockUnit, CCAllocationOut, CCStockMovementResult, CCStockUnitDetail,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccPrimaryBtnCls, ccSecondaryBtnCls, parsePositiveInt } from "@/lib/continuousCastingForm";

// CUT_CONSUME for ONE allocation: the irreversible, physical consumption of raw length.
// POST /cut-consume has NO idempotency key, so this panel: locks the moment a request starts (a ref, so a double
// click or a second Enter cannot slip through), asks for confirmation, never retries, and after a lost response
// refreshes the backend state and keeps the form locked until the user has reviewed it.
// It asks only for a length and an optional reason. Every figure shown is the backend's; the backend decides what
// is allowed. It does not create a cut result and creates no usable OMS blanks.
export function CCCutConsumePanel({ allocation, onClose, onChanged }: {
  allocation: CCAllocationOut; // the newest backend row for this allocation
  onClose: () => void;
  onChanged: () => void; // reload routings, gate status, allocations, awaiting-result list and cut results
}) {
  const [unit, setUnit] = useState<CCStockUnitDetail | null>(null);
  const [unitError, setUnitError] = useState<string | null>(null);
  const [length, setLength] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<CCStockMovementResult | null>(null);
  // Set after a lost response: the cut may or may not have been recorded, so another attempt stays blocked until
  // the state has been refreshed and the user explicitly acknowledges it.
  const [reviewLock, setReviewLock] = useState<"refreshing" | "review" | null>(null);
  const inFlight = useRef(false);

  const loadUnit = useCallback(async () => {
    try {
      setUnit(await ccGetStockUnit(allocation.stock_unit_id));
      setUnitError(null);
    } catch (err) {
      setUnitError(ccErrorMessage(err));
    }
  }, [allocation.stock_unit_id]);

  useEffect(() => { void loadUnit(); }, [loadUnit]);

  // Display of the backend's own routing status: a new cut is only offered on an ACTIVE routing.
  const routingActive = allocation.routing_status === "ACTIVE";

  const run = async () => {
    if (inFlight.current) return; // never a second request while one is in flight
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const res = await ccCutConsume({
        routing_id: allocation.routing_id, allocation_id: allocation.allocation_id,
        stock_unit_id: allocation.stock_unit_id, length_mm: parsePositiveInt(length),
        reason: reason.trim() === "" ? null : reason.trim(),
      });
      setConfirmOpen(false);
      setResult(res);
      setLength(""); setReason("");
      await loadUnit();
      onChanged();
    } catch (err) {
      setConfirmOpen(false);
      const response = (err as { response?: { status?: number } })?.response;
      if (!response) {
        // Transport failure: the server may have recorded the cut even though no answer arrived.
        setError(`${ccErrorMessage(err)} The cut may or may not have been recorded.`);
        setReviewLock("refreshing");
        await loadUnit();
        onChanged();
        setReviewLock("review");
      } else {
        setError(ccErrorMessage(err)); // backend text verbatim; never retried
        if (response.status === 400 || response.status === 404 || response.status === 409) {
          await loadUnit();
          onChanged();
        }
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const submit = () => {
    if (busy || reviewLock) return;
    if (Number.isNaN(parsePositiveInt(length))) return setError("Length must be a whole number of mm greater than 0.");
    setError(null);
    setConfirmOpen(true); // CUT_CONSUME is irreversible: always confirm
  };

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd>{v}</dd></div>
  );

  return (
    <section className="space-y-3 rounded-xl border border-rose-500/40 bg-white p-4 text-xs dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
          Cut consumption <span className="font-mono">{allocation.allocation_number}</span>
        </h3>
        <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="text-zinc-400 hover:text-zinc-700 disabled:opacity-40 dark:hover:text-zinc-200"><X className="h-4 w-4" /></button>
      </div>
      <div className="space-y-1 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-rose-900 dark:text-rose-200">
        <p className="font-semibold">Cut consumption permanently consumes physical stock and cannot be undone.</p>
        <p>
          It takes length from ISSUED stock: the unit&apos;s remaining physical length goes down and its consumed length goes up. It
          does not create a cut result, and it does not create good or rejected blanks or any usable OMS capacity. Cut result
          recording is a separate operation.
        </p>
      </div>

      <div>
        <p className="mb-1 font-semibold">Allocation (backend values)</p>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
          {kv("WO", <span className="font-mono">{allocation.wo_number}</span>)}
          {kv("Routing", <span className="font-mono">v{allocation.routing_version} <CCStatusBadge status={allocation.routing_status} /></span>)}
          {kv("Allocation", <CCTxnNumber value={allocation.allocation_number} />)}
          {kv("Stock unit", <span className="font-mono">{allocation.stock_unit_number}</span>)}
          {kv("Inward", <span className="font-mono">{allocation.inward_number}</span>)}
          {kv("Allocation status", <CCStatusBadge status={allocation.status} />)}
          {kv("Planned", <CCLengthCell mm={allocation.planned_length_mm} />)}
          {kv("Reserved", <CCLengthCell mm={allocation.reserved_length_mm} />)}
          {kv("Issued", <CCLengthCell mm={allocation.issued_length_mm} />)}
          {kv("Consumed", <CCLengthCell mm={allocation.consumed_length_mm} />)}
          {kv("Plan remaining", <CCLengthCell mm={allocation.plan_remaining_length_mm} />)}
        </dl>
      </div>
      <div>
        <p className="mb-1 font-semibold">Stock unit (fetched fresh from the backend)</p>
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
            {kv("Allocation planned", <CCLengthCell mm={result.allocation_planned_length_mm} />)}
            {kv("Allocation reserved", <CCLengthCell mm={result.allocation_reserved_length_mm} />)}
            {kv("Allocation issued", <CCLengthCell mm={result.allocation_issued_length_mm} />)}
            {kv("Allocation consumed", <CCLengthCell mm={result.allocation_consumed_length_mm} />)}
            {kv("Unit remaining", <CCLengthCell mm={result.unit_remaining_length_mm} />)}
            {kv("Unit reserved", <CCLengthCell mm={result.unit_reserved_length_mm} />)}
            {kv("Unit issued", <CCLengthCell mm={result.unit_issued_length_mm} />)}
            {kv("Unit consumed", <CCLengthCell mm={result.unit_consumed_length_mm} />)}
            {kv("Unit free", <CCLengthCell mm={result.unit_free_length_mm} />)}
            {kv("Ledger reserved length", <CCLengthCell mm={result.ledger_reserved_length_mm} />)}
            {kv("Reconciled", result.reconciled ? "Yes" : "No")}
          </dl>
          <p className="text-emerald-800/80 dark:text-emerald-300/80">
            This consumption now waits for a cut result. It adds no usable OMS blanks by itself.
          </p>
        </div>
      )}

      {reviewLock && (
        <div role="alert" className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-900 dark:text-amber-200">
          <p className="font-semibold">The response was lost, so the outcome of the last cut is unknown.</p>
          <p>
            {reviewLock === "refreshing"
              ? "Refreshing the allocation, stock unit, awaiting-result list and gate status..."
              : "State has been refreshed. Check the allocation, stock unit and the awaiting-result list before deciding whether to cut again."}
          </p>
          {reviewLock === "review" && (
            <button type="button" onClick={() => { setReviewLock(null); setError(null); }} className={ccSecondaryBtnCls}>
              I have reviewed the refreshed state; allow another attempt
            </button>
          )}
        </div>
      )}

      {routingActive ? (
        <CCActionForm onSubmit={submit} busy={busy || reviewLock !== null} error={confirmOpen ? null : error} submitLabel="Review cut consumption">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <label className={ccLabelCls}>Length to consume (mm) *</label>
              <input className={ccInputCls} inputMode="numeric" value={length} disabled={busy}
                onChange={(e) => setLength(e.target.value)} autoFocus />
            </div>
            <div className="sm:col-span-2">
              <label className={ccLabelCls}>Reason (optional)</label>
              <input className={ccInputCls} maxLength={500} value={reason} disabled={busy} onChange={(e) => setReason(e.target.value)} />
            </div>
          </div>
        </CCActionForm>
      ) : (
        <>
          <p className="rounded-lg border border-zinc-300 px-3 py-2 text-zinc-600 dark:border-zinc-700 dark:text-zinc-300">
            The backend reports this allocation&apos;s routing as {allocation.routing_status}. A new cut consumption is only offered on an ACTIVE routing.
          </p>
          <CCErrorBanner message={error} />
        </>
      )}

      <CCConfirmModal
        isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} onConfirm={() => void run()}
        title="Confirm cut consumption" confirmLabel="Consume stock permanently" busy={busy}
      >
        <p className="font-semibold text-rose-700 dark:text-rose-300">This will permanently consume physical stock.</p>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          {kv("WO / routing", <span className="font-mono">{allocation.wo_number} / v{allocation.routing_version}</span>)}
          {kv("Allocation", <span className="font-mono">{allocation.allocation_number}</span>)}
          {kv("Stock unit", <span className="font-mono">{allocation.stock_unit_number}</span>)}
          {kv("Length to consume", <b><CCLengthCell mm={parsePositiveInt(length)} /></b>)}
          {kv("Allocation issued (backend)", <CCLengthCell mm={allocation.issued_length_mm} />)}
          {kv("Unit remaining (backend)", unit ? <CCLengthCell mm={unit.remaining_length_mm} /> : "-")}
          {reason.trim() && <div className="col-span-2"><dt className="text-zinc-500">Reason</dt><dd>{reason.trim()}</dd></div>}
        </dl>
        <p className="text-zinc-500">
          The consumed length will reduce the stock unit&apos;s remaining physical length and increase consumed length. It does not create
          a cut result. The backend validates the amount and reports the resulting figures.
        </p>
      </CCConfirmModal>

      {result && <div className="flex justify-end"><button type="button" onClick={onClose} className={ccPrimaryBtnCls}>Done</button></div>}
    </section>
  );
}

"use client";
import React, { useRef, useState } from "react";
import { X } from "lucide-react";
import { CCActionForm } from "./CCActionForm";
import { CCConfirmModal } from "./CCConfirmModal";
import { CCErrorBanner } from "./CCErrorBanner";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import {
  ccErrorMessage, ccNewRequestId, ccRecordCutResult, CCCutAvailableOut, CCCutResultResult,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccPrimaryBtnCls, ccSecondaryBtnCls, parseNonNegativeInt } from "@/lib/continuousCastingForm";

interface Fields { good: string; rejected: string; cuts: string; trim: string; remarks: string }
const EMPTY: Fields = { good: "", rejected: "", cuts: "", trim: "", remarks: "" };

// Record the cut result of ONE awaiting CUT_CONSUME (chosen from GET /cut-results/available, never typed).
// Reconciliation is automatic inside the backend call: it returns RECONCILED or VARIANCE and usable_for_oms. This
// panel never calculates required length, variance, usable blanks or capacity, and never says whether an entry will
// produce VARIANCE. It checks only input shape (whole numbers, 0 or more) as the backend schema does.
// The request carries a client_request_id (the schema supports one): one key per intended submission, kept for a
// retry of the very same entries and dropped as soon as anything changes. Nothing is ever retried automatically.
export function CCCutResultPanel({ operation, onClose, onChanged }: {
  operation: CCCutAvailableOut; // the awaiting CUT_CONSUME this result is recorded against
  onClose: () => void;
  onChanged: () => void; // reload routings, gate status, allocations, awaiting list and cut results
}) {
  const [f, setF] = useState<Fields>(EMPTY);
  const [requestId, setRequestId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [result, setResult] = useState<CCCutResultResult | null>(null);
  // Set after a lost response: the result may or may not have been recorded; another attempt stays blocked until
  // the state has been refreshed and the user has acknowledged it.
  const [reviewLock, setReviewLock] = useState<"refreshing" | "review" | null>(null);
  const inFlight = useRef(false);

  const update = (patch: Partial<Fields>) => { setF({ ...f, ...patch }); setRequestId(null); };
  const inputsLocked = busy || reviewLock !== null;

  const parsed = () => ({
    good: parseNonNegativeInt(f.good), rejected: parseNonNegativeInt(f.rejected),
    cuts: parseNonNegativeInt(f.cuts), trim: parseNonNegativeInt(f.trim),
  });

  const run = async () => {
    if (inFlight.current) return; // never a second request while one is in flight
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const v = parsed();
      const res = await ccRecordCutResult({
        routing_id: operation.routing_id, allocation_id: operation.allocation_id, stock_unit_id: operation.stock_unit_id,
        ledger_transaction_number: operation.ledger_transaction_number, consumed_length_mm: operation.consumed_length_mm,
        actual_good_blanks: v.good, rejected_blanks: v.rejected, actual_cuts: v.cuts, end_trim_mm: v.trim,
        remarks: f.remarks.trim() === "" ? null : f.remarks.trim(),
        client_request_id: requestId ?? ccNewRequestId(),
      });
      setConfirmOpen(false);
      setResult(res);
      setF(EMPTY);
      setRequestId(null);
      onChanged();
    } catch (err) {
      setConfirmOpen(false);
      const response = (err as { response?: { status?: number } })?.response;
      if (!response) {
        // Transport failure: the server may have recorded the result even though no answer arrived.
        setError(`${ccErrorMessage(err)} The cut result may or may not have been recorded.`);
        setReviewLock("refreshing");
        onChanged();
        setReviewLock("review");
      } else {
        setError(ccErrorMessage(err)); // backend text verbatim
        if (response.status === 400 || response.status === 404 || response.status === 409) onChanged();
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  const submit = () => {
    if (inputsLocked) return;
    const v = parsed();
    if ([v.good, v.rejected, v.cuts, v.trim].some((n) => Number.isNaN(n))) {
      return setError("Good blanks, rejected blanks, actual cuts and end trim must each be a whole number (0 or more).");
    }
    setError(null);
    setRequestId((k) => k ?? ccNewRequestId()); // one key for this intended submission
    setConfirmOpen(true);
  };

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd>{v}</dd></div>
  );
  const supersededNote = (
    <p className="font-semibold text-rose-600">SUPERSEDED ROUTING — NOT USABLE FOR OMS CAPACITY</p>
  );

  return (
    <section className="space-y-3 rounded-xl border border-blue-500/40 bg-white p-4 text-xs dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
          Record cut result for <span className="font-mono">{operation.ledger_transaction_number}</span>
        </h3>
        <button type="button" onClick={onClose} disabled={busy} aria-label="Close" className="text-zinc-400 hover:text-zinc-700 disabled:opacity-40 dark:hover:text-zinc-200"><X className="h-4 w-4" /></button>
      </div>

      <div className="space-y-1 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-rose-900 dark:text-rose-200">
        <p className="font-semibold">The cut result is permanently recorded.</p>
        <p>
          If the consumed length exceeds the backend-required length, the backend will record VARIANCE. A VARIANCE result is
          permanently unusable for OMS capacity and has no correction or replacement workflow.
        </p>
      </div>
      <p className="text-zinc-500">
        Good blanks may contribute to OMS capacity only if the backend reconciles the result and marks it usable. Rejected blanks
        never contribute to usable OMS capacity. The backend works out reconciliation; nothing is calculated here.
      </p>

      <div>
        <p className="mb-1 font-semibold">CUT_CONSUME and routing (backend values)</p>
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {kv("CUT_CONSUME transaction", <b><CCTxnNumber value={operation.ledger_transaction_number} /></b>)}
          {kv("WO", <span className="font-mono">{operation.wo_number}</span>)}
          {kv("Routing", <span className="font-mono">v{operation.routing_version} <CCStatusBadge status={operation.routing_status} /></span>)}
          {kv("Allocation", <span className="font-mono">{operation.allocation_number}</span>)}
          {kv("Stock unit", <span className="font-mono">{operation.stock_unit_number}</span>)}
          {kv("Consumed length", <b><CCLengthCell mm={operation.consumed_length_mm} /></b>)}
          {kv("Planned blanks", <span className="font-mono">{operation.planned_blanks}</span>)}
          {kv("Blank length", <CCLengthCell mm={operation.blank_length_mm} />)}
          {kv("Kerf", <CCLengthCell mm={operation.kerf_mm} />)}
          {kv("Planned cuts", <span className="font-mono">{operation.planned_cuts ?? "-"}</span>)}
          {kv("Blanks already recorded", <span className="font-mono">{operation.routing_blanks_recorded}</span>)}
          {kv("Blanks remaining in plan", <span className="font-mono">{operation.routing_blanks_remaining_in_plan}</span>)}
        </dl>
        {operation.routing_status === "SUPERSEDED" && <div className="mt-2">{supersededNote}</div>}
      </div>

      {result && (
        <div role="status" className="space-y-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-emerald-900 dark:text-emerald-200">
          <p className="font-semibold">{result.message}</p>
          {result.replayed && <p className="font-semibold">Replay: this result had already been recorded; nothing was repeated.</p>}
          {result.reconciliation_status === "VARIANCE" && (
            <p className="rounded-md border border-rose-500/40 bg-rose-500/10 px-2 py-1 font-bold text-rose-700 dark:text-rose-300">
              VARIANCE — permanently unusable for OMS capacity.
            </p>
          )}
          {result.routing_status === "SUPERSEDED" && supersededNote}
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {kv("Cut result number", <b><CCTxnNumber value={result.cut_number} /></b>)}
            {kv("CUT_CONSUME transaction", <CCTxnNumber value={result.ledger_transaction_number} />)}
            {kv("WO", <span className="font-mono">{result.wo_number}</span>)}
            {kv("Routing", <span className="font-mono">v{result.routing_version} <CCStatusBadge status={result.routing_status} /></span>)}
            {kv("Allocation", <span className="font-mono">{result.allocation_number}</span>)}
            {kv("Stock unit", <span className="font-mono">{result.stock_unit_number}</span>)}
            {kv("Consumed length", <CCLengthCell mm={result.consumed_length_mm} />)}
            {kv("Planned blanks", <span className="font-mono">{result.planned_blanks}</span>)}
            {kv("Good blanks", <b className="font-mono text-emerald-600">{result.actual_good_blanks}</b>)}
            {kv("Rejected blanks", <b className="font-mono text-rose-600">{result.rejected_blanks}</b>)}
            {kv("Actual cuts", <span className="font-mono">{result.actual_cuts}</span>)}
            {kv("End trim", <CCLengthCell mm={result.end_trim_mm} />)}
            {kv("Blank length / kerf", <span className="font-mono">{result.blank_length_mm} / {result.kerf_mm} mm</span>)}
            {kv("Required length (backend)", <CCLengthCell mm={result.required_length_mm} />)}
            {kv("Reconciliation", <CCStatusBadge status={result.reconciliation_status} size="md" />)}
            {kv("Variance", <CCLengthCell mm={result.variance_mm} />)}
            {kv("Usable for OMS", <b className={result.usable_for_oms ? "text-emerald-600" : "text-rose-600"}>{result.usable_for_oms ? "YES" : "NO"}</b>)}
            {kv("Routing blanks recorded / planned", <span className="font-mono">{result.routing_blanks_recorded} / {result.routing_planned_blanks}</span>)}
          </dl>
        </div>
      )}

      {reviewLock && (
        <div role="alert" className="space-y-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-900 dark:text-amber-200">
          <p className="font-semibold">The response was lost, so the outcome of the last attempt is unknown.</p>
          <p>
            {reviewLock === "refreshing"
              ? "Refreshing the awaiting list, cut results, allocations, routing and gate status..."
              : "State has been refreshed. Check the awaiting list and the cut results before deciding whether to try again. An unchanged retry reuses the same request key, so a result that was already saved is not duplicated."}
          </p>
          {reviewLock === "review" && (
            <button type="button" onClick={() => { setReviewLock(null); setError(null); }} className={ccSecondaryBtnCls}>
              I have reviewed the refreshed state; allow another attempt
            </button>
          )}
        </div>
      )}

      {!result && (
        <CCActionForm onSubmit={submit} busy={inputsLocked} error={confirmOpen ? null : error} submitLabel="Review cut result">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <div>
              <label className={`${ccLabelCls} text-emerald-700`}>GOOD blanks *</label>
              <input className={ccInputCls} inputMode="numeric" value={f.good} disabled={inputsLocked} onChange={(e) => update({ good: e.target.value })} autoFocus />
            </div>
            <div>
              <label className={`${ccLabelCls} text-rose-700`}>REJECTED blanks *</label>
              <input className={ccInputCls} inputMode="numeric" value={f.rejected} disabled={inputsLocked} onChange={(e) => update({ rejected: e.target.value })} />
            </div>
            <div>
              <label className={ccLabelCls}>Actual cuts (saw cuts) *</label>
              <input className={ccInputCls} inputMode="numeric" value={f.cuts} disabled={inputsLocked} onChange={(e) => update({ cuts: e.target.value })} />
            </div>
            <div>
              <label className={ccLabelCls}>End trim, total (mm) *</label>
              <input className={ccInputCls} inputMode="numeric" value={f.trim} disabled={inputsLocked} onChange={(e) => update({ trim: e.target.value })} />
            </div>
            <div className="col-span-2 sm:col-span-4">
              <label className={ccLabelCls}>Remarks (optional)</label>
              <input className={ccInputCls} maxLength={2000} value={f.remarks} disabled={inputsLocked} onChange={(e) => update({ remarks: e.target.value })} />
            </div>
          </div>
          <p className="text-[11px] text-zinc-500">
            Consumed length ({operation.consumed_length_mm.toLocaleString("en-US")} mm) comes from the CUT_CONSUME and is sent as the confirmation the backend requires.
          </p>
        </CCActionForm>
      )}
      {result && <div className="flex justify-end"><button type="button" onClick={onClose} className={ccPrimaryBtnCls}>Done</button></div>}

      <CCConfirmModal
        isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} onConfirm={() => void run()}
        title="Confirm cut result" confirmLabel="Record cut result permanently" busy={busy}
      >
        <div className="space-y-1 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-rose-900 dark:text-rose-200">
          <p className="font-semibold">The cut result is permanently recorded.</p>
          <p>
            If the consumed length exceeds the backend-required length, the backend will record VARIANCE. A VARIANCE result is
            permanently unusable for OMS capacity and has no correction or replacement workflow.
          </p>
        </div>
        <dl className="grid grid-cols-2 gap-2 text-xs">
          {kv("WO", <span className="font-mono">{operation.wo_number}</span>)}
          {kv("Routing", <span className="font-mono">v{operation.routing_version} ({operation.routing_status})</span>)}
          {kv("Allocation", <span className="font-mono">{operation.allocation_number}</span>)}
          {kv("Stock unit", <span className="font-mono">{operation.stock_unit_number}</span>)}
          {kv("CUT_CONSUME", <span className="font-mono">{operation.ledger_transaction_number}</span>)}
          {kv("Consumed length", <CCLengthCell mm={operation.consumed_length_mm} />)}
          {kv("Planned blanks", <span className="font-mono">{operation.planned_blanks}</span>)}
          {kv("Blank length", <CCLengthCell mm={operation.blank_length_mm} />)}
          {kv("Kerf", <CCLengthCell mm={operation.kerf_mm} />)}
          {kv("Planned cuts", <span className="font-mono">{operation.planned_cuts ?? "-"}</span>)}
          {kv("GOOD blanks (entered)", <b className="font-mono text-emerald-600">{f.good.trim()}</b>)}
          {kv("REJECTED blanks (entered)", <b className="font-mono text-rose-600">{f.rejected.trim()}</b>)}
          {kv("Actual cuts (entered)", <span className="font-mono">{f.cuts.trim()}</span>)}
          {kv("End trim (entered)", <span className="font-mono">{f.trim.trim()} mm</span>)}
        </dl>
        {operation.routing_status === "SUPERSEDED" && supersededNote}
      </CCConfirmModal>
    </section>
  );
}

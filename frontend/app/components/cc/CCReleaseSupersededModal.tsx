"use client";
import React, { useEffect, useState } from "react";
import { Modal } from "@/app/components/ui/Modal";
import { CCErrorBanner } from "./CCErrorBanner";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { ccErrorMessage, ccReleaseSupersededRouting, CCRoutingOut, CCRoutingReleaseResult } from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccPrimaryBtnCls, ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

// "Release superseded reservations": one explicit action for ONE superseded routing version. It is not the same
// as releasing a single reservation. Only reservations are released; issued and consumed material is untouched and
// no allocation or routing is deleted. A backend 200 that says nothing was reserved is a success, not an error.
export function CCReleaseSupersededModal({ routing, onClose, onChanged }: {
  routing: CCRoutingOut | null; // null = closed
  onClose: () => void;
  onChanged: () => void; // reload routings, allocations and gate status
}) {
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CCRoutingReleaseResult | null>(null);

  useEffect(() => { setReason(""); setError(null); setResult(null); }, [routing?.routing_id]);

  const confirm = async () => {
    if (!routing || busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await ccReleaseSupersededRouting(routing.routing_id, reason.trim() === "" ? {} : { reason: reason.trim() });
      setResult(res);
      onChanged();
    } catch (err) {
      setError(ccErrorMessage(err)); // backend text verbatim; never retried
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 400 || status === 404 || status === 409) onChanged();
    } finally {
      setBusy(false);
    }
  };

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd>{v}</dd></div>
  );

  return (
    <Modal isOpen={!!routing} onClose={busy ? () => {} : onClose} title="Release superseded reservations"
      subtitle={routing ? `Work Order ${routing.wo_number} - routing v${routing.version} (${routing.status})` : undefined} maxWidth="2xl">
      <div className="max-h-[75vh] space-y-3 overflow-y-auto px-6 py-4 text-xs">
        {result ? (
          <>
            <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-emerald-700 dark:text-emerald-300">
              {result.message}
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {kv("Routing id", <CCTxnNumber value={result.routing_id} />)}
              {kv("Routing version", <span className="font-mono">v{result.routing_version}</span>)}
              {kv("Allocations released", <b className="font-mono">{result.allocations_released}</b>)}
              {kv("Total released", <b><CCLengthCell mm={result.total_released_length_mm} /></b>)}
            </dl>
            {result.releases.length > 0 && (
              <div className="max-h-56 overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
                <table className="w-full">
                  <thead className="bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-800/50">
                    <tr>{["Ledger transaction", "Allocation", "Unit", "Released", "Allocation status", "Unit reserved", "Unit free", "Reconciled"].map((h) => (
                      <th key={h} className="whitespace-nowrap px-2 py-1">{h}</th>))}</tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                    {result.releases.map((r) => (
                      <tr key={r.ledger_transaction_number}>
                        <td className="px-2 py-1"><CCTxnNumber value={r.ledger_transaction_number} /></td>
                        <td className="px-2 py-1 font-mono">{r.allocation_number}</td>
                        <td className="px-2 py-1 font-mono">{r.stock_unit_number}</td>
                        <td className="px-2 py-1 text-right"><CCLengthCell mm={r.length_mm} /></td>
                        <td className="px-2 py-1"><CCStatusBadge status={r.allocation_status} /></td>
                        <td className="px-2 py-1 text-right"><CCLengthCell mm={r.unit_reserved_length_mm} /></td>
                        <td className="px-2 py-1 text-right"><CCLengthCell mm={r.unit_free_length_mm} /></td>
                        <td className="px-2 py-1">{r.reconciled ? "Yes" : "No"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="text-zinc-500">The routing stays SUPERSEDED and its allocations remain; only reservations were released.</p>
            <div className="flex justify-end"><button type="button" onClick={onClose} className={ccPrimaryBtnCls}>Close</button></div>
          </>
        ) : (
          <>
            <div className="space-y-1 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-900 dark:text-amber-200">
              <p className="font-semibold">This releases all remaining reservations on this superseded routing.</p>
              <p>It does not release or return issued material.</p>
              <p>One release ledger transaction is created for each allocation that still has a reservation.</p>
              <p>Allocations and the routing itself are kept.</p>
            </div>
            <div>
              <label className={ccLabelCls}>Reason (optional)</label>
              <input className={ccInputCls} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
            </div>
            <CCErrorBanner message={error} />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={onClose} disabled={busy} className={ccSecondaryBtnCls}>Cancel</button>
              <button type="button" onClick={() => void confirm()} disabled={busy} className={ccPrimaryBtnCls}>
                {busy ? "Working..." : "Release superseded reservations"}
              </button>
            </div>
          </>
        )}
      </div>
    </Modal>
  );
}

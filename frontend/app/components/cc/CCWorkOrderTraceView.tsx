"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { ccAllocationColumns } from "./CCAllocationList";
import { ccCutResultColumns } from "./CCCutResultList";
import { CCErrorBanner } from "./CCErrorBanner";
import { CCGateStatusPanel } from "./CCGateStatusPanel";
import { TraceUnitsTable } from "./CCInwardTraceView";
import { CCLedgerTable } from "./CCLedgerTable";
import { CCLengthCell } from "./CCLengthCell";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCRoutingVersionHistory } from "./CCRoutingVersionHistory";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import {
  ccErrorMessage, ccGetGateStatus, ccTraceWorkOrder, CCGateStatus, CCTraceInwardRollup, CCTraceWorkOrder,
} from "@/lib/continuousCastingApi";
import { ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

// Read-only trace of ONE Work Order (GET /traceability/work-orders/{wo_number}) plus the backend's gate status and a
// WO-filtered ledger. The model is relational and many-to-many: a WO has routing versions and allocations, draws on
// many inwards and units, and a unit can have several allocations. Every value is the backend's. The only arithmetic
// is the "Showing X of Y" caption: a returned list length against the backend's own total.
export function CCWorkOrderTraceView({ woNumber, onOpenInward }: {
  woNumber: string; onOpenInward?: (inwardId: string) => void;
}) {
  const [trace, setTrace] = useState<CCTraceWorkOrder | null>(null);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [gate, setGate] = useState<CCGateStatus | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ledgerKey, setLedgerKey] = useState(0);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    const [t, g] = await Promise.allSettled([ccTraceWorkOrder(woNumber), ccGetGateStatus(woNumber)]);
    if (mine !== seq.current) return; // a newer selection superseded this load
    if (t.status === "fulfilled") { setTrace(t.value); setTraceError(null); }
    else { setTrace(null); setTraceError(ccErrorMessage(t.reason)); }
    if (g.status === "fulfilled") { setGate(g.value); setGateError(null); }
    else { setGate(null); setGateError(ccErrorMessage(g.reason)); }
    setLoading(false);
  }, [woNumber]);

  useEffect(() => { setTrace(null); setGate(null); setTraceError(null); setGateError(null); void load(); }, [load]);

  const showing = (shown: number, total: number) => (
    <p className="text-[11px] text-zinc-500">Showing {shown} of {total}</p>
  );

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  const inwardColumns: CCColumn<CCTraceInwardRollup>[] = [
    {
      header: "Inward",
      render: (i) => (onOpenInward ? (
        <button type="button" onClick={() => onOpenInward(i.inward_id)} title="Open the inward trace"
          className="font-mono font-semibold text-blue-600 hover:underline dark:text-blue-400">{i.inward_number}</button>
      ) : <span className="font-mono">{i.inward_number}</span>),
    },
    { header: "Units", className: "text-right font-mono", render: (i) => i.unit_count },
    { header: "Allocations", className: "text-right font-mono", render: (i) => i.allocation_count },
    { header: "Planned", className: "text-right", render: (i) => <CCLengthCell mm={i.planned_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (i) => <CCLengthCell mm={i.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (i) => <CCLengthCell mm={i.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (i) => <CCLengthCell mm={i.consumed_length_mm} /> },
  ];

  // Backend values only: the status is read from the routing row whose version the backend names as active.
  const activeRow = trace?.routings.find((r) => r.version === trace.active_routing_version) ?? null;

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
            Work Order <span className="font-mono">{woNumber}</span>
          </h2>
          <button type="button" disabled={loading} onClick={() => { void load(); setLedgerKey((k) => k + 1); }} className={`${ccSecondaryBtnCls} inline-flex items-center gap-1`}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
        <CCErrorBanner message={traceError} />
        {trace && (
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {kv("WO number", <CCTxnNumber value={trace.wo_number} />)}
            {kv("Active routing", trace.active_routing_version === null
              ? "No active routing"
              : <span className="font-mono">v{trace.active_routing_version} {activeRow && <CCStatusBadge status={activeRow.status} />}</span>)}
            {kv("Usable good blanks", trace.usable_good_blanks === null
              ? <span className="text-zinc-500">null — not available (no ACTIVE routing)</span>
              : <b className="font-mono">{trace.usable_good_blanks}</b>)}
            {kv("Allocations", <b className="font-mono">{trace.allocations_total}</b>)}
            {kv("Cut results", <b className="font-mono">{trace.cut_results_total}</b>)}
          </dl>
        )}
        {!trace && !traceError && <p className="text-zinc-400">{loading ? "Loading trace..." : ""}</p>}
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">OMS material gate</h3>
        <p className="text-[11px] text-zinc-500">The gate verdict and capacity are the backend&apos;s own gate-status answer, not derived from the trace below.</p>
        <CCErrorBanner message={gateError} />
        <CCGateStatusPanel gate={gate} />
      </section>

      {trace && (
        <>
          <section className="space-y-2">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Routing versions</h3>
            {trace.routings.length === 0
              ? <p className="rounded-lg border border-zinc-200 px-3 py-4 text-xs text-zinc-500 dark:border-zinc-800">No continuous-casting routing found.</p>
              : <CCRoutingVersionHistory routings={trace.routings} />}
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Allocations</h3>
            <p className="text-[11px] text-zinc-500">One row per stock unit and routing. A unit can carry allocations on several routings, and a routing on several units.</p>
            <CCPagedTable
              columns={ccAllocationColumns} items={trace.allocations}
              total={trace.allocations_total} limit={Math.max(trace.allocations.length, 1)} offset={0} onPageChange={() => {}}
              rowKey={(a) => a.allocation_id} hidePager emptyText="No continuous-casting allocations recorded."
            />
            {showing(trace.allocations.length, trace.allocations_total)}
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Inwards drawn on</h3>
            <p className="text-[11px] text-zinc-500">A relational rollup: this Work Order can draw on many inwards, and each inward can feed many Work Orders. Totals are the backend&apos;s sums over this Work Order&apos;s allocations.</p>
            <CCPagedTable
              columns={inwardColumns} items={trace.inwards} total={trace.inwards.length} limit={Math.max(trace.inwards.length, 1)}
              offset={0} onPageChange={() => {}} rowKey={(i) => i.inward_id} hidePager emptyText="No inward material allocated to this work order."
            />
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Stock units</h3>
            <p className="text-[11px] text-zinc-500">Only units that carry an allocation of this Work Order. Open a row to see those allocations.</p>
            <TraceUnitsTable units={trace.units} emptyText="No stock units associated with this work order." />
            <p className="text-[11px] text-zinc-500">{trace.units.length} unit(s) in this trace.</p>
          </section>

          <section className="space-y-2">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Cut results</h3>
            <p className="text-[11px] text-zinc-500">
              Good and rejected blanks are separate; rejected blanks are never usable capacity. A VARIANCE result is permanent. Usable for
              OMS is the backend&apos;s flag.
            </p>
            <CCPagedTable
              columns={ccCutResultColumns(true)} items={trace.cut_results} total={trace.cut_results_total}
              limit={Math.max(trace.cut_results.length, 1)} offset={0} onPageChange={() => {}}
              rowKey={(r) => r.cut_result_id} hidePager emptyText="No cut results recorded."
            />
            {showing(trace.cut_results.length, trace.cut_results_total)}
          </section>
        </>
      )}

      <section className="space-y-2">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Ledger for this Work Order</h3>
        <p className="text-[11px] text-zinc-500">
          The Work Order trace carries no ledger rows, so this is the ledger filtered to the Work Order. A CUT_CONSUME that has no cut result
          yet does not appear in the cut results above; it is visible here.
        </p>
        <CCLedgerTable woNumber={woNumber} refreshKey={ledgerKey} emptyText="No ledger activity recorded for this work order." />
      </section>

      {trace && (
        <section className="rounded-lg border border-zinc-200 p-3 text-xs dark:border-zinc-800">
          <p className="mb-1 font-semibold">Notes from the backend</p>
          {trace.truncated && (
            <p className="mb-1 text-amber-700 dark:text-amber-300">
              The backend reports that at least one section above is an excerpt (see the &quot;Showing X of Y&quot; lines).
            </p>
          )}
          <ul className="list-disc space-y-0.5 pl-4 text-zinc-600 dark:text-zinc-300">
            {trace.limitations.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </section>
      )}
    </div>
  );
}

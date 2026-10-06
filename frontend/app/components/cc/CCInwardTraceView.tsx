"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { CCErrorBanner } from "./CCErrorBanner";
import { ccCutResultColumns } from "./CCCutResultList";
import { CCLedgerTable, ccLedgerColumns } from "./CCLedgerTable";
import { CCLengthCell } from "./CCLengthCell";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { ccErrorMessage, ccTraceInward, CCTraceInward, CCTraceUnit, CCTraceWorkOrderRollup } from "@/lib/continuousCastingApi";
import { ccSecondaryBtnCls, fmtDateTime } from "@/lib/continuousCastingForm";

// Read-only trace of ONE inward (GET /traceability/inwards/{inward UUID}). The model is relational and many-to-many:
// an inward has many units, a unit can have many allocations, and an inward can feed many Work Orders. Every value is
// the backend's. The only arithmetic anywhere is the "Showing X of Y" caption: a returned list length against the
// backend's own total.
export function CCInwardTraceView({ inwardId }: { inwardId: string }) {
  const [trace, setTrace] = useState<CCTraceInward | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showFullLedger, setShowFullLedger] = useState(false);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const data = await ccTraceInward(inwardId); // the trace endpoint takes the inward UUID, never the number
      if (mine !== seq.current) return; // a newer selection superseded this load
      setTrace(data); setError(null);
    } catch (err) {
      if (mine === seq.current) { setTrace(null); setError(ccErrorMessage(err)); }
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [inwardId]);

  useEffect(() => { setTrace(null); setError(null); setShowFullLedger(false); void load(); }, [load]);

  const showing = (shown: number, total: number) => (
    <p className="text-[11px] text-zinc-500">Showing {shown} of {total}</p>
  );

  if (!trace) {
    return (
      <div className="space-y-2">
        <CCErrorBanner message={error} />
        {!error && <p className="text-xs text-zinc-400">{loading ? "Loading trace..." : ""}</p>}
      </div>
    );
  }

  const inward = trace.inward;
  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  const rollupColumns: CCColumn<CCTraceWorkOrderRollup>[] = [
    { header: "Work Order", render: (w) => <b className="font-mono">{w.wo_number}</b> },
    { header: "Routing versions", render: (w) => <span className="font-mono">{w.routing_versions.map((v) => `v${v}`).join(", ")}</span> },
    { header: "Active routing", render: (w) => (w.active_routing_version === null ? "-" : <span className="font-mono">v{w.active_routing_version}</span>) },
    { header: "Allocations", className: "text-right font-mono", render: (w) => w.allocation_count },
    { header: "Planned", className: "text-right", render: (w) => <CCLengthCell mm={w.planned_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (w) => <CCLengthCell mm={w.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (w) => <CCLengthCell mm={w.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (w) => <CCLengthCell mm={w.consumed_length_mm} /> },
  ];

  const totalsEntries = Object.entries(trace.ledger_totals_by_movement);

  return (
    <div className="space-y-5">
      <CCErrorBanner message={error} />

      {/* ---------------------------------------------------------------- summary */}
      <section className="rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
            Inward <span className="font-mono">{inward.inward_number}</span>
          </h2>
          <button type="button" disabled={loading} onClick={() => void load()} className={`${ccSecondaryBtnCls} inline-flex items-center gap-1`}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {kv("Inward number", <CCTxnNumber value={inward.inward_number} />)}
          {kv("Material code", <span className="font-mono">{inward.material_code}</span>)}
          {kv("Grade", inward.grade)}
          {kv("Section", inward.section)}
          {kv("Dimensions", <span className="font-mono">{inward.stock_dimension_a_mm}{inward.stock_dimension_b_mm ? ` × ${inward.stock_dimension_b_mm}` : ""} mm</span>)}
          {kv("QA status", <CCStatusBadge status={inward.qa_status} size="md" />)}
          {kv("Received", fmtDateTime(inward.received_at))}
          {kv("GRN reference", inward.grn_reference ?? "-")}
          {kv("Physical units", <b className="font-mono">{trace.units_total}</b>)}
          {kv("Allocations", <b className="font-mono">{trace.allocations_total}</b>)}
          {kv("Cut results", <b className="font-mono">{trace.cut_results_total}</b>)}
          {kv("Ledger rows", <b className="font-mono">{trace.ledger_rows_total}</b>)}
        </dl>
        <div className="mt-3 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
          <p className="mb-1 font-semibold">QA decision</p>
          {inward.qa_decision ? (
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {kv("Decision", <CCStatusBadge status={inward.qa_decision.decision} />)}
              {kv("Previous status", inward.qa_decision.previous_qa_status ?? "-")}
              {kv("Decided by", inward.qa_decision.decided_by ?? "-")}
              {kv("Decided at", fmtDateTime(inward.qa_decision.decided_at))}
              {kv("Reason", inward.qa_decision.reason ?? "-")}
            </dl>
          ) : (
            <p className="text-zinc-600 dark:text-zinc-300">
              {inward.qa_status === "PENDING_QA" ? "PENDING QA — no QA decision recorded" : "No QA decision details recorded"}
            </p>
          )}
        </div>
      </section>

      {/* ---------------------------------------------------------------- units + their allocations */}
      <section className="space-y-2">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Stock units and their allocations</h3>
        <p className="text-[11px] text-zinc-500">
          A unit can carry allocations on several routings and Work Orders. Open a row to see them. Parent shows split lineage
          (the parent unit number); the full child list is on the unit&apos;s own record.
        </p>
        <TraceUnitsTable units={trace.units} />
        {showing(trace.units.length, trace.units_total)}
      </section>

      {/* ---------------------------------------------------------------- WO rollup */}
      <section className="space-y-2">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Work Orders drawing on this inward</h3>
        <p className="text-[11px] text-zinc-500">
          A relational rollup: one inward can feed many Work Orders, and a Work Order can draw on many inwards.
          Totals are the backend&apos;s sums over this inward&apos;s allocations.
        </p>
        <CCPagedTable
          columns={rollupColumns} items={trace.work_orders} total={trace.work_orders.length} limit={Math.max(trace.work_orders.length, 1)}
          offset={0} onPageChange={() => {}} rowKey={(w) => w.wo_number} hidePager emptyText="No work-order allocations recorded."
        />
      </section>

      {/* ---------------------------------------------------------------- cut results */}
      <section className="space-y-2">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Cut results</h3>
        <p className="text-[11px] text-zinc-500">
          Good and rejected blanks are separate; rejected blanks are never usable capacity. A VARIANCE result is permanent. Usable
          for OMS is the backend&apos;s flag.
        </p>
        <CCPagedTable
          columns={ccCutResultColumns(true)} items={trace.cut_results} total={trace.cut_results_total} limit={Math.max(trace.cut_results.length, 1)}
          offset={0} onPageChange={() => {}} rowKey={(r) => r.cut_result_id} hidePager emptyText="No cut results recorded."
        />
        {showing(trace.cut_results.length, trace.cut_results_total)}
      </section>

      {/* ---------------------------------------------------------------- ledger */}
      <section className="space-y-2">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Recent ledger</h3>
        <div className="rounded-lg border border-zinc-200 p-3 text-xs dark:border-zinc-800">
          <p className="mb-1 font-semibold">Sum of length by movement type</p>
          <p className="mb-2 text-[11px] text-zinc-500">
            A raw sum per movement type from the ledger. It is not a stock balance: for example INWARD is the length received,
            not what is currently in stock.
          </p>
          {totalsEntries.length === 0 ? (
            <p className="text-zinc-500">No ledger activity.</p>
          ) : (
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {totalsEntries.map(([movement, mm]) => (
                <div key={movement}><dt className="font-mono text-zinc-500">{movement}</dt><dd><CCLengthCell mm={typeof mm === "number" ? mm : null} /></dd></div>
              ))}
            </dl>
          )}
        </div>
        <CCPagedTable
          columns={ccLedgerColumns} items={trace.recent_ledger} total={trace.ledger_rows_total} limit={Math.max(trace.recent_ledger.length, 1)}
          offset={0} onPageChange={() => {}} rowKey={(r) => r.transaction_number} hidePager emptyText="No ledger activity."
        />
        <div className="flex items-center justify-between">
          {showing(trace.recent_ledger.length, trace.ledger_rows_total)}
          {trace.ledger_rows_total > trace.recent_ledger.length && (
            <button type="button" onClick={() => setShowFullLedger((v) => !v)} className="text-xs font-semibold text-blue-600 hover:underline dark:text-blue-400">
              {showFullLedger ? "Hide full ledger" : "View full ledger"}
            </button>
          )}
        </div>
        {showFullLedger && <CCLedgerTable inwardId={inwardId} />}
      </section>

      {/* ---------------------------------------------------------------- backend notes */}
      <section className="rounded-lg border border-zinc-200 p-3 text-xs dark:border-zinc-800">
        <p className="mb-1 font-semibold">Notes from the backend</p>
        {trace.truncated && (
          <p className="mb-1 text-amber-700 dark:text-amber-300">
            The backend reports that at least one section above is an excerpt (see each &quot;Showing X of Y&quot; line).
          </p>
        )}
        <ul className="list-disc space-y-0.5 pl-4 text-zinc-600 dark:text-zinc-300">
          {trace.limitations.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      </section>
    </div>
  );
}

// Units with an expandable nested allocation table. Nothing is derived: balances, parent and allocations are the
// backend's trace values.
export function TraceUnitsTable({ units, emptyText = "No stock units." }: { units: CCTraceUnit[]; emptyText?: string }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const th = "whitespace-nowrap px-3 py-2 font-semibold";
  return (
    <div className="max-h-[28rem] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
      <table className="w-full text-xs">
        <thead className="sticky top-0 bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-800">
          <tr>
            <th className={th} />
            {["Stock unit", "Parent", "Original", "Remaining", "Reserved", "Issued", "Consumed", "Scrapped", "Free", "Status", "Allocations"].map((h) => (
              <th key={h} className={th}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {units.length === 0 && (
            <tr><td colSpan={12} className="px-3 py-6 text-center text-zinc-400">{emptyText}</td></tr>
          )}
          {units.map((u) => {
            const isOpen = !!open[u.unit_id];
            return (
              <React.Fragment key={u.unit_id}>
                <tr className="hover:bg-zinc-50 dark:hover:bg-zinc-800/30">
                  <td className="px-2 py-1.5">
                    {u.allocations.length > 0 && (
                      <button type="button" aria-label={isOpen ? "Hide allocations" : "Show allocations"} onClick={() => setOpen({ ...open, [u.unit_id]: !isOpen })}>
                        {isOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                      </button>
                    )}
                  </td>
                  <td className="px-3 py-1.5"><CCTxnNumber value={u.unit_number} /></td>
                  <td className="px-3 py-1.5 font-mono">{u.parent_unit_number ?? "-"}</td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={u.original_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={u.remaining_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={u.reserved_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={u.issued_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={u.consumed_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={u.scrapped_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right font-semibold"><CCLengthCell mm={u.free_length_mm} /></td>
                  <td className="px-3 py-1.5"><CCStatusBadge status={u.status} /></td>
                  <td className="px-3 py-1.5 text-right font-mono">{u.allocations.length}</td>
                </tr>
                {isOpen && (
                  <tr>
                    <td />
                    <td colSpan={11} className="bg-zinc-50 px-3 py-2 dark:bg-zinc-800/30">
                      <table className="w-full">
                        <thead className="text-left text-zinc-500">
                          <tr>{["Allocation", "WO", "Routing", "Status", "Planned", "Reserved", "Issued", "Consumed", "Plan remaining"].map((h) => (
                            <th key={h} className="whitespace-nowrap px-2 py-1 font-semibold">{h}</th>))}</tr>
                        </thead>
                        <tbody>
                          {u.allocations.map((a) => (
                            <tr key={a.allocation_id}>
                              <td className="px-2 py-1"><CCTxnNumber value={a.allocation_number} /></td>
                              <td className="px-2 py-1 font-mono">{a.wo_number}</td>
                              <td className="px-2 py-1"><span className="font-mono">v{a.routing_version}</span> <CCStatusBadge status={a.routing_status} /></td>
                              <td className="px-2 py-1"><CCStatusBadge status={a.status} /></td>
                              <td className="px-2 py-1 text-right"><CCLengthCell mm={a.planned_length_mm} /></td>
                              <td className="px-2 py-1 text-right"><CCLengthCell mm={a.reserved_length_mm} /></td>
                              <td className="px-2 py-1 text-right"><CCLengthCell mm={a.issued_length_mm} /></td>
                              <td className="px-2 py-1 text-right"><CCLengthCell mm={a.consumed_length_mm} /></td>
                              <td className="px-2 py-1 text-right"><CCLengthCell mm={a.plan_remaining_length_mm} /></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

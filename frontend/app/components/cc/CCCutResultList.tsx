"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { ccErrorMessage, ccListCutResults, CCCutResultOut } from "@/lib/continuousCastingApi";
import { fmtDateTime } from "@/lib/continuousCastingForm";

const PAGE_SIZE = 25;

// Columns for a list of cut results. `extended` adds WO, inward, blank length, kerf and end trim (used by the
// inward trace). Every value is the backend's; nothing is calculated.
export function ccCutResultColumns(extended = false): CCColumn<CCCutResultOut>[] {
  return [
    { header: "Cut number", render: (r) => <b><CCTxnNumber value={r.cut_number} /></b> },
    { header: "CUT_CONSUME transaction", render: (r) => <CCTxnNumber value={r.ledger_transaction_number} /> },
    { header: "Recorded", render: (r) => <span>{fmtDateTime(r.created_at)}<br /><span className="text-zinc-400">{r.performed_by ?? ""}</span></span> },
    { header: "Routing", render: (r) => <span><span className="font-mono">v{r.routing_version}</span> <CCStatusBadge status={r.routing_status} /></span> },
    { header: "Allocation", render: (r) => <span className="font-mono">{r.allocation_number}</span> },
    { header: "Stock unit", render: (r) => <span className="font-mono">{r.stock_unit_number}</span> },
    { header: "Consumed", className: "text-right", render: (r) => <CCLengthCell mm={r.consumed_length_mm} /> },
    { header: "Planned blanks", className: "text-right font-mono", render: (r) => r.planned_blanks },
    { header: "Good blanks", className: "text-right font-mono font-semibold text-emerald-600", render: (r) => r.actual_good_blanks },
    { header: "Rejected blanks", className: "text-right font-mono text-rose-600", render: (r) => r.rejected_blanks },
    { header: "Cuts", className: "text-right font-mono", render: (r) => r.actual_cuts },
    { header: "Reconciliation", render: (r) => <CCStatusBadge status={r.reconciliation_status} /> },
    { header: "Variance", className: "text-right", render: (r) => <CCLengthCell mm={r.variance_mm} /> },
    {
      header: "Usable for OMS",
      render: (r) => (
        <span>
          <span className={`font-semibold ${r.usable_for_oms ? "text-emerald-600" : "text-rose-600"}`}>{r.usable_for_oms ? "YES" : "NO"}</span>
          {r.routing_status === "SUPERSEDED" && (
            <span className="block text-[10px] font-semibold text-rose-600">SUPERSEDED ROUTING - NOT USABLE FOR OMS CAPACITY</span>
          )}
          {r.reconciliation_status === "VARIANCE" && (
            <span className="block text-[10px] text-zinc-500">Variance is permanent; there is no correction.</span>
          )}
        </span>
      ),
    },
    ...(extended
      ? [
          { header: "WO", render: (r: CCCutResultOut) => <span className="font-mono">{r.wo_number}</span> },
          { header: "Inward", render: (r: CCCutResultOut) => <span className="font-mono">{r.inward_number}</span> },
          { header: "Blank length", className: "text-right", render: (r: CCCutResultOut) => <CCLengthCell mm={r.blank_length_mm} /> },
          { header: "Kerf", className: "text-right", render: (r: CCCutResultOut) => <CCLengthCell mm={r.kerf_mm} /> },
          { header: "End trim", className: "text-right", render: (r: CCCutResultOut) => <CCLengthCell mm={r.end_trim_mm} /> },
        ]
      : []),
  ];
}

// Recorded cut results of one Work Order (GET /cut-results?wo_number=). Read-only.
// Reconciliation status, variance and usable_for_oms are the backend's own answers; nothing is derived here.
// Rejected blanks are shown separately from good blanks and are never presented as capacity.
export function CCCutResultList({ woNumber, refreshKey = 0 }: { woNumber: string; refreshKey?: number }) {
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCCutResultOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => { setOffset(0); }, [woNumber]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const page = await ccListCutResults({ wo_number: woNumber, limit: PAGE_SIZE, offset });
      if (mine !== seq.current) return; // a newer selection superseded this load
      setRows(page.items); setTotal(page.total); setError(null);
    } catch (err) {
      if (mine === seq.current) { setRows([]); setTotal(0); setError(ccErrorMessage(err)); }
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [woNumber, offset]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const columns = ccCutResultColumns(false);

  return (
    <CCPagedTable
      columns={columns} items={rows} total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset}
      rowKey={(r) => r.cut_result_id} loading={loading} error={error} emptyText="No cut results recorded for this Work Order."
    />
  );
}

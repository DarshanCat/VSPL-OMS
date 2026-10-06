"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { ccErrorMessage, ccListAvailableCutConsumes, CCCutAvailableOut } from "@/lib/continuousCastingApi";
import { fmtDateTime } from "@/lib/continuousCastingForm";

const PAGE_SIZE = 25;

// CUT_CONSUME transactions of one Work Order that have no cut result yet (GET /cut-results/available).
// Read-only. Every value, including the routing's recorded and remaining blank counts, is the backend's; no blank
// count is suggested or calculated here.
// `renderActions` (optional) adds a per-row actions column; every row here is a backend-listed awaiting operation.
export function CCAvailableCutList({ woNumber, refreshKey = 0, renderActions }: {
  woNumber: string; refreshKey?: number; renderActions?: (operation: CCCutAvailableOut) => React.ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCCutAvailableOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => { setOffset(0); }, [woNumber]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const page = await ccListAvailableCutConsumes({ wo_number: woNumber, limit: PAGE_SIZE, offset });
      if (mine !== seq.current) return; // a newer selection superseded this load
      setRows(page.items); setTotal(page.total); setError(null);
    } catch (err) {
      if (mine === seq.current) { setRows([]); setTotal(0); setError(ccErrorMessage(err)); }
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [woNumber, offset]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const columns: CCColumn<CCCutAvailableOut>[] = [
    { header: "CUT_CONSUME transaction", render: (c) => <b><CCTxnNumber value={c.ledger_transaction_number} /></b> },
    { header: "Time", render: (c) => fmtDateTime(c.created_at) },
    { header: "Allocation", render: (c) => <span className="font-mono">{c.allocation_number}</span> },
    { header: "Stock unit", render: (c) => <span className="font-mono">{c.stock_unit_number}</span> },
    { header: "WO", render: (c) => <span className="font-mono">{c.wo_number}</span> },
    { header: "Routing", render: (c) => <span><span className="font-mono">v{c.routing_version}</span> <CCStatusBadge status={c.routing_status} /><br /><CCTxnNumber value={c.routing_id} /></span> },
    {
      header: "OMS capacity",
      render: (c) => (c.routing_status === "SUPERSEDED"
        ? <span className="font-semibold text-rose-600">SUPERSEDED ROUTING - NOT USABLE FOR OMS CAPACITY</span>
        : <span className="text-zinc-400">-</span>),
    },
    { header: "Consumed", className: "text-right", render: (c) => <CCLengthCell mm={c.consumed_length_mm} /> },
    { header: "Planned blanks", className: "text-right font-mono", render: (c) => c.planned_blanks },
    { header: "Blank length", className: "text-right", render: (c) => <CCLengthCell mm={c.blank_length_mm} /> },
    { header: "Kerf", className: "text-right", render: (c) => <CCLengthCell mm={c.kerf_mm} /> },
    { header: "Planned cuts", className: "text-right font-mono", render: (c) => c.planned_cuts ?? "-" },
    { header: "Blanks recorded", className: "text-right font-mono", render: (c) => c.routing_blanks_recorded },
    { header: "Blanks remaining in plan", className: "text-right font-mono", render: (c) => c.routing_blanks_remaining_in_plan },
    ...(renderActions ? [{ header: "Actions", render: (c: CCCutAvailableOut) => renderActions(c) }] : []),
  ];

  return (
    <CCPagedTable
      columns={columns} items={rows} total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset}
      rowKey={(c) => c.ledger_transaction_number} loading={loading} error={error}
      emptyText="No cut consumptions are waiting for a cut result."
    />
  );
}

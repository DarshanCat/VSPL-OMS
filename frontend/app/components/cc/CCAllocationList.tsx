"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { ccErrorMessage, ccListAllocations, CCAllocationOut } from "@/lib/continuousCastingApi";

const PAGE_SIZE = 25;

// Base allocation columns, shared with views that already hold allocation rows (for example the WO trace).
export const ccAllocationColumns: CCColumn<CCAllocationOut>[] = [
  { header: "Allocation", render: (a) => <b><CCTxnNumber value={a.allocation_number} /></b> },
  { header: "Routing", render: (a) => <span className="font-mono">v{a.routing_version} <CCStatusBadge status={a.routing_status} /></span> },
  { header: "Status", render: (a) => <CCStatusBadge status={a.status} /> },
  { header: "Inward", render: (a) => <span className="font-mono">{a.inward_number}</span> },
  { header: "Stock unit", render: (a) => <span className="font-mono">{a.stock_unit_number}</span> },
  { header: "Planned", className: "text-right", render: (a) => <CCLengthCell mm={a.planned_length_mm} /> },
  { header: "Reserved", className: "text-right", render: (a) => <CCLengthCell mm={a.reserved_length_mm} /> },
  { header: "Issued", className: "text-right", render: (a) => <CCLengthCell mm={a.issued_length_mm} /> },
  { header: "Consumed", className: "text-right", render: (a) => <CCLengthCell mm={a.consumed_length_mm} /> },
  { header: "Plan remaining", className: "text-right", render: (a) => <CCLengthCell mm={a.plan_remaining_length_mm} /> },
];

// Allocations of one Work Order across every routing version, inward and stock unit (GET /allocations?wo_number=).
// All quantities, including plan remaining, are the backend's; nothing is calculated here.
// `renderActions` (optional) adds a per-row actions column; `onLoaded` reports the latest page of backend rows.
export function CCAllocationList({ woNumber, refreshKey = 0, renderActions, onLoaded }: {
  woNumber: string; refreshKey?: number;
  renderActions?: (allocation: CCAllocationOut) => React.ReactNode;
  onLoaded?: (rows: CCAllocationOut[]) => void;
}) {
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCAllocationOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const loadedRef = useRef(onLoaded);
  loadedRef.current = onLoaded;

  useEffect(() => { setOffset(0); }, [woNumber]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const page = await ccListAllocations({ wo_number: woNumber, limit: PAGE_SIZE, offset });
      if (mine !== seq.current) return;
      setRows(page.items); setTotal(page.total); setError(null);
      loadedRef.current?.(page.items);
    } catch (err) {
      if (mine === seq.current) setError(ccErrorMessage(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [woNumber, offset]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const columns: CCColumn<CCAllocationOut>[] = [
    ...ccAllocationColumns,
    ...(renderActions ? [{ header: "Actions", render: (a: CCAllocationOut) => renderActions(a) }] : []),
  ];

  return (
    <CCPagedTable
      columns={columns} items={rows} total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset}
      rowKey={(a) => a.allocation_id} loading={loading} error={error} emptyText="No allocations for this Work Order."
    />
  );
}

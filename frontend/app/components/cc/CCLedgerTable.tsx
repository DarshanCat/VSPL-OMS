"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { CCFilterBar } from "./CCFilterBar";
import { CCLengthCell } from "./CCLengthCell";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCTxnNumber } from "./CCTxnNumber";
import { ccErrorMessage, ccListInwards, ccListLedger, CCInwardStockOut, CCLedgerOut, CCMovementType } from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls, fmtDateTime } from "@/lib/continuousCastingForm";

const MOVEMENTS: CCMovementType[] = [
  "INWARD", "RESERVE", "RELEASE", "ISSUE", "CUT_CONSUME", "RETURN", "HOLD", "HOLD_RELEASE", "SCRAP",
  "ADJUSTMENT_IN", "ADJUSTMENT_OUT", "SPLIT_OUT", "SPLIT_IN",
];

interface Filters {
  inward_id: string; allocation_id: string; routing_id: string; wo_number: string;
  movement_type: "" | CCMovementType; from: string; to: string; onlyUnit: boolean;
}
const NO_FILTERS: Filters = { inward_id: "", allocation_id: "", routing_id: "", wo_number: "", movement_type: "", from: "", to: "", onlyUnit: true };

// Ledger table columns, shared with views that already hold ledger rows (for example the inward trace).
export const ccLedgerColumns: CCColumn<CCLedgerOut>[] = [
  { header: "Transaction", render: (r) => <b><CCTxnNumber value={r.transaction_number} /></b> },
  { header: "Movement", render: (r) => <span className="font-mono">{r.movement_type}</span> },
  { header: "Unit", render: (r) => <span className="font-mono">{r.stock_unit_number}</span> },
  { header: "Inward", render: (r) => <span className="font-mono">{r.inward_number}</span> },
  { header: "Allocation", render: (r) => <span className="font-mono">{r.allocation_number ?? "-"}</span> },
  { header: "WO", render: (r) => r.wo_number ?? "-" },
  { header: "Length", className: "text-right", render: (r) => <CCLengthCell mm={r.length_mm} /> },
  { header: "Pcs", className: "text-right font-mono", render: (r) => r.piece_qty ?? "-" },
  { header: "Reason", render: (r) => r.reason ?? "-" },
  { header: "Reference", render: (r) => r.reference ?? "-" },
  { header: "User", render: (r) => r.performed_by ?? "-" },
  { header: "Time", render: (r) => fmtDateTime(r.created_at) },
];

// Read-only ledger (GET /ledger). `unitId`, when given, can be used as the stock-unit filter.
// Optional presets: `inwardId` / `woNumber` fix that filter (and hide its input); used by Traceability.
export function CCLedgerTable({ unitId, inwardId, woNumber, refreshKey = 0, pageSize = 25, emptyText = "No ledger rows." }: {
  unitId?: string | null; inwardId?: string | null; woNumber?: string | null; refreshKey?: number; pageSize?: number;
  emptyText?: string;
}) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCLedgerOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inwards, setInwards] = useState<CCInwardStockOut[]>([]);
  const seq = useRef(0);

  useEffect(() => { ccListInwards({ limit: 500 }).then((p) => setInwards(p.items)).catch(() => {}); }, []);
  useEffect(() => { setOffset(0); }, [unitId, inwardId, woNumber]);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const page = await ccListLedger({
        stock_unit_id: unitId && applied.onlyUnit ? unitId : undefined,
        inward_id: inwardId ?? applied.inward_id, allocation_id: applied.allocation_id.trim(), routing_id: applied.routing_id.trim(),
        wo_number: woNumber ?? applied.wo_number.trim(),
        movement_type: applied.movement_type === "" ? undefined : applied.movement_type,
        created_from: applied.from ? `${applied.from}T00:00:00` : undefined,
        created_to: applied.to ? `${applied.to}T23:59:59` : undefined,
        limit: pageSize, offset,
      });
      if (mine !== seq.current) return;
      setRows(page.items); setTotal(page.total); setError(null);
    } catch (err) {
      if (mine === seq.current) setError(ccErrorMessage(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [applied, offset, pageSize, unitId, inwardId, woNumber]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const columns = ccLedgerColumns;

  return (
    <div className="space-y-2">
      <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setApplied(filters); }}>
        <CCFilterBar onClear={() => { setFilters(NO_FILTERS); setApplied(NO_FILTERS); setOffset(0); }}>
          {unitId && (
            <label className="flex items-center gap-1 pb-1 text-xs">
              <input type="checkbox" checked={filters.onlyUnit} onChange={(e) => setFilters({ ...filters, onlyUnit: e.target.checked })} />
              Selected unit only
            </label>
          )}
          {!inwardId && (
            <div>
              <label className={ccLabelCls}>Inward</label>
              <select className={ccInputCls} value={filters.inward_id} onChange={(e) => setFilters({ ...filters, inward_id: e.target.value })}>
                <option value="">All</option>
                {inwards.map((i) => <option key={i.inward_id} value={i.inward_id}>{i.inward_number}</option>)}
              </select>
            </div>
          )}
          <div>
            <label className={ccLabelCls}>Movement</label>
            <select className={ccInputCls} value={filters.movement_type} onChange={(e) => setFilters({ ...filters, movement_type: e.target.value as Filters["movement_type"] })}>
              <option value="">All</option>
              {MOVEMENTS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          {!woNumber && (
            <div><label className={ccLabelCls}>WO number</label><input className={ccInputCls} value={filters.wo_number} onChange={(e) => setFilters({ ...filters, wo_number: e.target.value })} /></div>
          )}
          <div><label className={ccLabelCls}>Allocation id</label><input className={`${ccInputCls} font-mono`} value={filters.allocation_id} onChange={(e) => setFilters({ ...filters, allocation_id: e.target.value })} /></div>
          <div><label className={ccLabelCls}>Routing id</label><input className={`${ccInputCls} font-mono`} value={filters.routing_id} onChange={(e) => setFilters({ ...filters, routing_id: e.target.value })} /></div>
          <div><label className={ccLabelCls}>From</label><input type="date" className={ccInputCls} value={filters.from} onChange={(e) => setFilters({ ...filters, from: e.target.value })} /></div>
          <div><label className={ccLabelCls}>To</label><input type="date" className={ccInputCls} value={filters.to} onChange={(e) => setFilters({ ...filters, to: e.target.value })} /></div>
          <button type="submit" className={ccSecondaryBtnCls}>Apply</button>
        </CCFilterBar>
      </form>
      <CCPagedTable
        columns={columns} items={rows} total={total} limit={pageSize} offset={offset}
        onPageChange={setOffset} rowKey={(r) => r.transaction_number} loading={loading} error={error} emptyText={emptyText}
      />
    </div>
  );
}

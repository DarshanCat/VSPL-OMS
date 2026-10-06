"use client";
import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, X } from "lucide-react";
import { CCErrorBanner } from "@/app/components/cc/CCErrorBanner";
import { CCLengthCell } from "@/app/components/cc/CCLengthCell";
import { CCPagedTable, CCColumn } from "@/app/components/cc/CCPagedTable";
import { CCRoleGate } from "@/app/components/cc/CCRoleGate";
import { CCStatusBadge } from "@/app/components/cc/CCStatusBadge";
import { CCTxnNumber } from "@/app/components/cc/CCTxnNumber";
import { CCUnitBalances } from "@/app/components/cc/CCUnitBalances";
import { CCUnitList } from "@/app/components/cc/CCUnitList";
import { ccErrorMessage, ccGetStockUnit, CCAllocationOut, CCStockUnitDetail, CCUnitChild } from "@/lib/continuousCastingApi";
import {
  CC_ADJUSTMENT_ROLES, CC_HOLD_ROLES, CC_HOLD_RELEASE_ROLES, CC_ISSUE_ROLES, CC_SCRAP_ROLES,
} from "@/lib/continuousCastingRoles";
import { fmtDateTime } from "@/lib/continuousCastingForm";

// Every role that can use at least one Stores action sees the shortcut; the backend still decides each action.
const ANY_STORES_ROLE = Array.from(new Set([
  ...CC_ISSUE_ROLES, ...CC_HOLD_ROLES, ...CC_HOLD_RELEASE_ROLES, ...CC_SCRAP_ROLES, ...CC_ADJUSTMENT_ROLES,
]));

export default function StockContent() {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
          <Boxes className="h-3.5 w-3.5" /> Continuous Casting
        </p>
        <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Stock</h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Physical bars (stock units). All quantities are the backend&apos;s own figures; this screen never calculates them.
        </p>
      </div>

      {selectedId && <StockUnitDetailPanel unitId={selectedId} onSelect={setSelectedId} onClose={() => setSelectedId(null)} />}

      <CCUnitList onSelect={(u) => setSelectedId(u.unit_id)} selectedId={selectedId} />
    </div>
  );
}

function StockUnitDetailPanel({ unitId, onSelect, onClose }: {
  unitId: string; onSelect: (id: string) => void; onClose: () => void;
}) {
  const [unit, setUnit] = useState<CCStockUnitDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setUnit(await ccGetStockUnit(unitId));
      setError(null);
    } catch (err) {
      setError(ccErrorMessage(err));
    }
  }, [unitId]);

  useEffect(() => { setUnit(null); void load(); }, [load]);

  const childCols: CCColumn<CCUnitChild>[] = [
    {
      header: "Child unit",
      render: (c) => (
        <button type="button" onClick={() => onSelect(c.unit_id)} className="font-mono font-semibold text-blue-600 hover:underline dark:text-blue-400">
          {c.unit_number}
        </button>
      ),
    },
    { header: "Original", className: "text-right", render: (c) => <CCLengthCell mm={c.original_length_mm} /> },
    { header: "Remaining", className: "text-right", render: (c) => <CCLengthCell mm={c.remaining_length_mm} /> },
    { header: "Status", render: (c) => <CCStatusBadge status={c.status} /> },
  ];

  const allocCols: CCColumn<CCAllocationOut>[] = [
    { header: "Allocation", render: (a) => <CCTxnNumber value={a.allocation_number} /> },
    { header: "WO", render: (a) => a.wo_number },
    { header: "Routing", render: (a) => <span>v{a.routing_version} <CCStatusBadge status={a.routing_status} /></span> },
    { header: "Planned", className: "text-right", render: (a) => <CCLengthCell mm={a.planned_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (a) => <CCLengthCell mm={a.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (a) => <CCLengthCell mm={a.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (a) => <CCLengthCell mm={a.consumed_length_mm} /> },
    { header: "Plan remaining", className: "text-right", render: (a) => <CCLengthCell mm={a.plan_remaining_length_mm} /> },
    { header: "Status", render: (a) => <CCStatusBadge status={a.status} /> },
  ];

  return (
    <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
          Stock unit {unit && <span className="ml-1 font-mono">{unit.unit_number}</span>}
        </h2>
        <div className="flex items-center gap-3">
          <CCRoleGate allowed={ANY_STORES_ROLE}>
            <Link href={`/continuous-casting/stores?unit=${unitId}`} className="font-semibold text-blue-600 hover:underline dark:text-blue-400">
              Open in Stores Transactions
            </Link>
          </CCRoleGate>
          <button type="button" onClick={onClose} aria-label="Close detail" className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"><X className="h-4 w-4" /></button>
        </div>
      </div>
      <CCErrorBanner message={error} />

      {unit && (
        <>
          <CCUnitBalances unit={unit} />
          <p className="text-[11px] text-zinc-500">
            Physical status and allocation eligibility are separate: a bar can be IN_STOCK and still not be eligible for allocation.
          </p>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-1 font-semibold">Lineage</p>
              <p>
                Parent:{" "}
                {unit.parent_unit_id && unit.parent_unit_number ? (
                  <button type="button" onClick={() => onSelect(unit.parent_unit_id as string)} className="font-mono font-semibold text-blue-600 hover:underline dark:text-blue-400">
                    {unit.parent_unit_number}
                  </button>
                ) : "none (original bar of the inward)"}
              </p>
              <p className="mt-1">Children: {unit.children.length === 0 ? "none" : unit.children.length}</p>
              <p className="mt-1">Net adjustment: <CCLengthCell mm={unit.net_adjustment_mm} /></p>
            </div>
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-1 font-semibold">Last hold event</p>
              {unit.last_hold_event ? (
                <dl className="grid grid-cols-2 gap-2">
                  <div><dt className="text-zinc-500">Movement</dt><dd className="font-mono">{unit.last_hold_event.movement_type}</dd></div>
                  <div><dt className="text-zinc-500">Transaction</dt><dd><CCTxnNumber value={unit.last_hold_event.transaction_number} /></dd></div>
                  <div><dt className="text-zinc-500">By</dt><dd>{unit.last_hold_event.performed_by ?? "-"}</dd></div>
                  <div><dt className="text-zinc-500">At</dt><dd>{fmtDateTime(unit.last_hold_event.created_at)}</dd></div>
                  <div className="col-span-2"><dt className="text-zinc-500">Reason</dt><dd>{unit.last_hold_event.reason ?? "-"}</dd></div>
                </dl>
              ) : <p className="text-zinc-500">No hold events.</p>}
            </div>
          </div>

          <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
            <p className="mb-1 flex items-center gap-2 font-semibold">
              Ledger integrity (informational)
              <CCStatusBadge status={unit.integrity.consistent ? "RECONCILED" : "VARIANCE"} />
            </p>
            <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              <div><dt className="text-zinc-500">Ledger remaining</dt><dd><CCLengthCell mm={unit.integrity.ledger_remaining_length_mm} /></dd></div>
              <div><dt className="text-zinc-500">Ledger reserved</dt><dd><CCLengthCell mm={unit.integrity.ledger_reserved_length_mm} /></dd></div>
              <div><dt className="text-zinc-500">Ledger issued</dt><dd><CCLengthCell mm={unit.integrity.ledger_issued_length_mm} /></dd></div>
              <div><dt className="text-zinc-500">Ledger consumed</dt><dd><CCLengthCell mm={unit.integrity.ledger_consumed_length_mm} /></dd></div>
              <div><dt className="text-zinc-500">Ledger scrapped</dt><dd><CCLengthCell mm={unit.integrity.ledger_scrapped_length_mm} /></dd></div>
            </dl>
          </div>

          <div>
            <p className="mb-1 font-semibold">Child units ({unit.children.length})</p>
            <CCPagedTable columns={childCols} items={unit.children} total={unit.children.length} limit={Math.max(unit.children.length, 1)} offset={0}
              onPageChange={() => {}} rowKey={(c) => c.unit_id} emptyText="No child units." />
          </div>
          <div>
            <p className="mb-1 font-semibold">Allocations ({unit.allocations.length})</p>
            <CCPagedTable columns={allocCols} items={unit.allocations} total={unit.allocations.length} limit={Math.max(unit.allocations.length, 1)} offset={0}
              onPageChange={() => {}} rowKey={(a) => a.allocation_id} emptyText="No allocations." />
          </div>
        </>
      )}
    </section>
  );
}

"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { CCErrorBanner } from "./CCErrorBanner";
import { ccCutResultColumns } from "./CCCutResultList";
import { CCLengthCell } from "./CCLengthCell";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import {
  ccErrorMessage,
  ccTraceHeat,
  CCAllocationOut,
  CCInwardStockOut,
  CCStockUnitOut,
  CCTraceHeat,
  CCTraceWorkOrderRollup,
} from "@/lib/continuousCastingApi";
import { ccSecondaryBtnCls, fmtDateTime } from "@/lib/continuousCastingForm";

export function CCHeatTraceView({ heatNumber }: { heatNumber: string }) {
  const [trace, setTrace] = useState<CCTraceHeat | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!heatNumber.trim()) return;
    const mine = ++seq.current;
    setLoading(true);
    try {
      const data = await ccTraceHeat(heatNumber.trim());
      if (mine !== seq.current) return;
      setTrace(data);
      setError(null);
    } catch (err) {
      if (mine === seq.current) {
        setTrace(null);
        setError(ccErrorMessage(err));
      }
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [heatNumber]);

  useEffect(() => {
    setTrace(null);
    setError(null);
    void load();
  }, [load]);

  if (!trace) {
    return (
      <div className="space-y-2">
        <CCErrorBanner message={error} />
        {!error && <p className="text-xs text-zinc-400">{loading ? "Loading heat traceability..." : ""}</p>}
      </div>
    );
  }

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}>
      <dt className="text-zinc-500">{k}</dt>
      <dd className="text-zinc-900 dark:text-zinc-100">{v}</dd>
    </div>
  );

  const woColumns: CCColumn<CCTraceWorkOrderRollup>[] = [
    { header: "Work Order", render: (w) => <b className="font-mono">{w.wo_number}</b> },
    {
      header: "Routing versions",
      render: (w) => <span className="font-mono">{w.routing_versions.map((v) => `v${v}`).join(", ")}</span>,
    },
    {
      header: "Active routing",
      render: (w) => (w.active_routing_version === null ? "-" : <span className="font-mono">v{w.active_routing_version}</span>),
    },
    { header: "Allocations", className: "text-right font-mono", render: (w) => w.allocation_count },
    { header: "Planned", className: "text-right", render: (w) => <CCLengthCell mm={w.planned_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (w) => <CCLengthCell mm={w.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (w) => <CCLengthCell mm={w.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (w) => <CCLengthCell mm={w.consumed_length_mm} /> },
  ];

  const inwardColumns: CCColumn<CCInwardStockOut>[] = [
    { header: "Inward no.", render: (i) => <CCTxnNumber value={i.inward_number} /> },
    { header: "Material", render: (i) => <span className="font-mono">{i.material_code}</span> },
    { header: "Grade / Section", render: (i) => <span>{i.grade} / {i.section}</span> },
    {
      header: "Dimensions",
      render: (i) => (
        <span className="font-mono">
          {i.stock_dimension_a_mm}{i.stock_dimension_b_mm ? ` × ${i.stock_dimension_b_mm}` : ""} mm
        </span>
      ),
    },
    { header: "QA status", render: (i) => <CCStatusBadge status={i.qa_status} /> },
    { header: "Received at", render: (i) => fmtDateTime(i.received_at) },
    { header: "Units", className: "text-right font-mono", render: (i) => i.unit_count },
    { header: "Received length", className: "text-right", render: (i) => <CCLengthCell mm={i.received_total_length_mm} /> },
    { header: "Free length", className: "text-right font-semibold", render: (i) => <CCLengthCell mm={i.free_length_mm} /> },
  ];

  const unitColumns: CCColumn<CCStockUnitOut>[] = [
    { header: "Unit", render: (u) => <CCTxnNumber value={u.unit_number} /> },
    { header: "Inward", render: (u) => <span className="font-mono">{u.inward_number}</span> },
    { header: "Material", render: (u) => <span className="font-mono">{u.material_code}</span> },
    { header: "Parent", render: (u) => (u.parent_unit_number ? <span className="font-mono">{u.parent_unit_number}</span> : "-") },
    { header: "Original", className: "text-right", render: (u) => <CCLengthCell mm={u.original_length_mm} /> },
    { header: "Remaining", className: "text-right", render: (u) => <CCLengthCell mm={u.remaining_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (u) => <CCLengthCell mm={u.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (u) => <CCLengthCell mm={u.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (u) => <CCLengthCell mm={u.consumed_length_mm} /> },
    { header: "Free", className: "text-right font-semibold", render: (u) => <CCLengthCell mm={u.free_length_mm} /> },
    { header: "Status", render: (u) => <CCStatusBadge status={u.status} /> },
    { header: "Location", render: (u) => u.location ?? "-" },
  ];

  const allocColumns: CCColumn<CCAllocationOut>[] = [
    { header: "Allocation", render: (a) => <CCTxnNumber value={a.allocation_number} /> },
    { header: "Work Order", render: (a) => <b className="font-mono">{a.wo_number}</b> },
    { header: "Routing", render: (a) => <span>v{a.routing_version} <CCStatusBadge status={a.routing_status} /></span> },
    { header: "Inward", render: (a) => <span className="font-mono">{a.inward_number}</span> },
    { header: "Stock Unit", render: (a) => <span className="font-mono">{a.stock_unit_number}</span> },
    { header: "Planned", className: "text-right", render: (a) => <CCLengthCell mm={a.planned_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (a) => <CCLengthCell mm={a.consumed_length_mm} /> },
    { header: "Status", render: (a) => <CCStatusBadge status={a.status} /> },
  ];

  const cutColumns = ccCutResultColumns(true);

  return (
    <div className="space-y-5">
      <CCErrorBanner message={error} />

      {/* Heat Summary Card */}
      <section className="rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
            Heat Number Traceability — <span className="font-mono text-blue-600 dark:text-blue-400">{trace.heat_number}</span>
          </h2>
          <button
            type="button"
            disabled={loading}
            onClick={() => void load()}
            className={`${ccSecondaryBtnCls} inline-flex items-center gap-1`}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </button>
        </div>

        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {kv("Heat Number", <span className="font-mono font-bold text-sm text-zinc-900 dark:text-zinc-100">{trace.heat_number}</span>)}
          {kv("Inwards Count", <b className="font-mono">{trace.total_inwards}</b>)}
          {kv("Physical Stock Units", <b className="font-mono">{trace.total_units}</b>)}
          {kv("Work Orders Fed", <b className="font-mono">{trace.total_work_orders}</b>)}
          {kv("Cut Results Recorded", <b className="font-mono">{trace.total_cuts}</b>)}
        </dl>
      </section>

      {/* Work Orders Rollup */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
          Work Orders Consuming this Heat ({trace.work_orders.length})
        </h3>
        <CCPagedTable
          columns={woColumns}
          items={trace.work_orders}
          total={trace.work_orders.length}
          limit={Math.max(trace.work_orders.length, 1)}
          offset={0}
          onPageChange={() => {}}
          rowKey={(w) => w.wo_number}
          emptyText="No Work Orders have consumed or reserved stock from this heat number."
        />
      </section>

      {/* Inwards */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
          Inwards Received under this Heat ({trace.inwards.length})
        </h3>
        <CCPagedTable
          columns={inwardColumns}
          items={trace.inwards}
          total={trace.inwards.length}
          limit={Math.max(trace.inwards.length, 1)}
          offset={0}
          onPageChange={() => {}}
          rowKey={(i) => i.inward_id}
          emptyText="No inwards under this heat number."
        />
      </section>

      {/* Physical Stock Units */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
          Physical Stock Units ({trace.units.length})
        </h3>
        <CCPagedTable
          columns={unitColumns}
          items={trace.units}
          total={trace.units.length}
          limit={Math.max(trace.units.length, 1)}
          offset={0}
          onPageChange={() => {}}
          rowKey={(u) => u.unit_id}
          emptyText="No stock units found for this heat number."
        />
      </section>

      {/* Allocations */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
          Allocations ({trace.allocations.length})
        </h3>
        <CCPagedTable
          columns={allocColumns}
          items={trace.allocations}
          total={trace.allocations.length}
          limit={Math.max(trace.allocations.length, 1)}
          offset={0}
          onPageChange={() => {}}
          rowKey={(a) => a.allocation_id}
          emptyText="No allocations created from stock of this heat number."
        />
      </section>

      {/* Cut Results */}
      <section className="space-y-2">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
          Cut Results ({trace.cut_results.length})
        </h3>
        <CCPagedTable
          columns={cutColumns}
          items={trace.cut_results}
          total={trace.cut_results.length}
          limit={Math.max(trace.cut_results.length, 1)}
          offset={0}
          onPageChange={() => {}}
          rowKey={(c) => c.cut_result_id}
          emptyText="No cut results recorded for this heat number."
        />
      </section>
    </div>
  );
}

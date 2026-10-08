"use client";
import React, { useState } from "react";
import { X } from "lucide-react";
import { CCActionForm } from "./CCActionForm";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { CCUnitBalances } from "./CCUnitBalances";
import { CCUnitList } from "./CCUnitList";
import {
  ccCreateAllocation, ccErrorMessage, CCAllocationResult, CCRoutingOut, CCStockUnitOut,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls, parsePositiveInt } from "@/lib/continuousCastingForm";

// Add one allocation (planning only) to an ACTIVE routing: pick a backend-eligible stock unit, enter a planned
// length, submit. The panel never reserves stock and never computes free, available-for-planning or plan remaining.
export function CCAllocationPanel({ routing, onClose, onChanged }: {
  routing: CCRoutingOut;
  onClose: () => void;
  onChanged: () => void; // reload routings, allocations and gate status (after a success, or a 400/404/409)
}) {
  const [unit, setUnit] = useState<CCStockUnitOut | null>(null);
  const [length, setLength] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CCAllocationResult | null>(null);
  const [listKey, setListKey] = useState(0);

  const submit = async () => {
    if (busy) return;
    if (!unit) return setError("Select a stock unit.");
    const planned = parsePositiveInt(length);
    if (Number.isNaN(planned)) return setError("Planned length must be a whole number of mm greater than 0.");
    setBusy(true);
    setError(null);
    try {
      const res = await ccCreateAllocation({ routing_id: routing.routing_id, stock_unit_id: unit.unit_id, planned_length_mm: planned });
      setResult(res);
      setUnit(null);
      setLength("");
      setListKey((k) => k + 1);
      onChanged();
    } catch (err) {
      setError(ccErrorMessage(err)); // backend text verbatim; never retried
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 400 || status === 404 || status === 409) {
        setListKey((k) => k + 1);
        onChanged();
      }
    } finally {
      setBusy(false);
    }
  };

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd>{v}</dd></div>
  );

  return (
    <section className="space-y-3 rounded-xl border border-blue-500/30 bg-white p-4 text-xs dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
          Add allocation to routing v{routing.version}
        </h3>
        <button type="button" onClick={onClose} aria-label="Close" className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"><X className="h-4 w-4" /></button>
      </div>
      <p className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 py-2 font-semibold text-blue-800 dark:text-blue-200">
        Allocation is planning only. It reserves no stock.
      </p>

      {result && (
        <div role="status" className="space-y-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-emerald-900 dark:text-emerald-200">
          <p className="font-semibold">{result.message}</p>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {kv("Allocation", <CCTxnNumber value={result.allocation_number} />)}
            {kv("Status", <CCStatusBadge status={result.status} />)}
            {kv("Reserved", <b><CCLengthCell mm={result.reserved_length_mm} /></b>)}
            {kv("Planned", <CCLengthCell mm={result.planned_length_mm} />)}
            {kv("WO / routing", <span className="font-mono">{result.wo_number} / v{result.routing_version}</span>)}
            {kv("Stock unit", <span className="font-mono">{result.stock_unit_number}</span>)}
            {kv("Inward", <span className="font-mono">{result.inward_number}</span>)}
            {kv("Unit free", <CCLengthCell mm={result.unit_free_length_mm} />)}
            {kv("Unit available for planning", <b><CCLengthCell mm={result.unit_available_for_planning_mm} /></b>)}
            {kv("Routing gross required", <CCLengthCell mm={result.routing_gross_required_length_mm} />)}
            {kv("Routing planned total", <CCLengthCell mm={result.routing_planned_total_mm} />)}
          </dl>
          <button type="button" onClick={() => setResult(null)} className={ccSecondaryBtnCls}>Add another</button>
        </div>
      )}

      <div>
        <p className="mb-1 font-semibold">1. Select stock unit</p>
        <p className="mb-1 text-[11px] text-zinc-500">
          Filters default to the routing&apos;s material and available stock as a convenience only. A unit can be chosen
          only when the backend marks it allocation eligible; the backend decides everything else.
        </p>
        <CCUnitList
          key={routing.routing_id}
          onSelect={(u) => { setUnit(u); setError(null); }}
          selectedId={unit?.unit_id}
          refreshKey={listKey}
          pageSize={10}
          initialFilters={{ material_id: routing.validated_material_id ?? undefined, available: true }}
          isSelectable={(u) => u.allocation_eligible === true}
          showEligibility
        />
      </div>

      <div>
        <p className="mb-1 font-semibold">2. Planned length</p>
        {unit ? (
          <div className="mb-2 space-y-1">
            <CCUnitBalances unit={unit} />
            <p className="text-[11px] text-zinc-500">
              Free length above is the backend&apos;s. The length actually available for planning is reported by the backend after the allocation is made.
            </p>
          </div>
        ) : (
          <p className="mb-2 text-zinc-500">No stock unit selected.</p>
        )}
        <CCActionForm onSubmit={submit} busy={busy} error={error} submitLabel="Add allocation">
          <div className="w-56">
            <label className={ccLabelCls}>Planned length (mm) *</label>
            <input className={ccInputCls} inputMode="numeric" value={length} onChange={(e) => setLength(e.target.value)} />
          </div>
        </CCActionForm>
      </div>
    </section>
  );
}

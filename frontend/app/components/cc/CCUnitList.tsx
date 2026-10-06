"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { CCFilterBar } from "./CCFilterBar";
import { CCLengthCell } from "./CCLengthCell";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCStatusBadge } from "./CCStatusBadge";
import {
  ccErrorMessage, ccListInwards, ccListMaterials, ccListStockUnits,
  CCInwardStockOut, CCMaterialOut, CCStockUnitOut, CCStockUnitStatus,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

interface Filters {
  inward_id: string; material_id: string; status: "" | CCStockUnitStatus; location: string;
  on_hold: "" | "true" | "false"; available: "" | "true" | "false"; parent_unit_id: string;
}
const NO_FILTERS: Filters = {
  inward_id: "", material_id: "", status: "", location: "", on_hold: "", available: "", parent_unit_id: "",
};
const triBool = (v: "" | "true" | "false") => (v === "" ? undefined : v === "true");

// Filterable, paged stock-unit table (GET /stock-units). Selecting a row is the caller's concern.
// Optional props for the allocation picker: `initialFilters` pre-sets convenience filters, `isSelectable` (a backend
// flag such as allocation_eligible, never a rule of our own) disables rows, and `showEligibility` adds the backend's
// eligibility answer and reason.
export function CCUnitList({ onSelect, selectedId, refreshKey = 0, pageSize = 25, initialFilters, isSelectable, showEligibility = false }: {
  onSelect: (unit: CCStockUnitOut) => void; selectedId?: string | null; refreshKey?: number; pageSize?: number;
  initialFilters?: { material_id?: string; available?: boolean };
  isSelectable?: (unit: CCStockUnitOut) => boolean;
  showEligibility?: boolean;
}) {
  const [start] = useState<Filters>(() => ({
    ...NO_FILTERS,
    material_id: initialFilters?.material_id ?? "",
    available: initialFilters?.available === undefined ? "" : initialFilters.available ? "true" : "false",
  }));
  const [filters, setFilters] = useState<Filters>(start);
  const [applied, setApplied] = useState<Filters>(start);
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCStockUnitOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inwards, setInwards] = useState<CCInwardStockOut[]>([]);
  const [materials, setMaterials] = useState<CCMaterialOut[]>([]);
  const seq = useRef(0);

  useEffect(() => {
    ccListInwards({ limit: 500 }).then((p) => setInwards(p.items)).catch(() => {});
    ccListMaterials({ limit: 500 }).then((p) => setMaterials(p.items)).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const page = await ccListStockUnits({
        inward_id: applied.inward_id, material_id: applied.material_id, location: applied.location,
        parent_unit_id: applied.parent_unit_id.trim(),
        status: applied.status === "" ? undefined : applied.status,
        on_hold: triBool(applied.on_hold), available: triBool(applied.available),
        limit: pageSize, offset,
      });
      if (mine !== seq.current) return;
      setRows(page.items); setTotal(page.total); setError(null);
    } catch (err) {
      if (mine === seq.current) setError(ccErrorMessage(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [applied, offset, pageSize]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const columns: CCColumn<CCStockUnitOut>[] = [
    {
      header: "Unit",
      render: (u) => (
        <button type="button" onClick={() => onSelect(u)} disabled={isSelectable ? !isSelectable(u) : false}
          className={`font-mono font-semibold enabled:hover:underline disabled:cursor-not-allowed disabled:text-zinc-400 ${u.unit_id === selectedId ? "text-emerald-600" : "text-blue-600 dark:text-blue-400"}`}>
          {u.unit_number}
        </button>
      ),
    },
    { header: "Inward", render: (u) => <span className="font-mono">{u.inward_number}</span> },
    { header: "Material", render: (u) => <span className="font-mono">{u.material_code}</span> },
    { header: "Original", className: "text-right", render: (u) => <CCLengthCell mm={u.original_length_mm} /> },
    { header: "Remaining", className: "text-right", render: (u) => <CCLengthCell mm={u.remaining_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (u) => <CCLengthCell mm={u.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (u) => <CCLengthCell mm={u.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (u) => <CCLengthCell mm={u.consumed_length_mm} /> },
    { header: "Scrapped", className: "text-right", render: (u) => <CCLengthCell mm={u.scrapped_length_mm} /> },
    { header: "Free", className: "text-right font-semibold", render: (u) => <CCLengthCell mm={u.free_length_mm} /> },
    { header: "Status", render: (u) => <CCStatusBadge status={u.status} /> },
    { header: "Location", render: (u) => u.location ?? "-" },
    { header: "Parent", render: (u) => (u.parent_unit_number ? <span className="font-mono">{u.parent_unit_number}</span> : "-") },
    ...(showEligibility
      ? [{
          header: "Allocation eligible",
          render: (u: CCStockUnitOut) => (u.allocation_eligible ? "Yes" : `No${u.allocation_ineligible_reason ? ` - ${u.allocation_ineligible_reason}` : ""}`),
        }]
      : []),
  ];

  const triSelect = (key: "on_hold" | "available", label: string) => (
    <div>
      <label className={ccLabelCls}>{label}</label>
      <select className={ccInputCls} value={filters[key]} onChange={(e) => setFilters({ ...filters, [key]: e.target.value as "" | "true" | "false" })}>
        <option value="">All</option><option value="true">Yes</option><option value="false">No</option>
      </select>
    </div>
  );

  return (
    <div className="space-y-2">
      <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setApplied(filters); }}>
        <CCFilterBar onClear={() => { setFilters(NO_FILTERS); setApplied(NO_FILTERS); setOffset(0); }}>
          <div>
            <label className={ccLabelCls}>Inward</label>
            <select className={ccInputCls} value={filters.inward_id} onChange={(e) => setFilters({ ...filters, inward_id: e.target.value })}>
              <option value="">All</option>
              {inwards.map((i) => <option key={i.inward_id} value={i.inward_id}>{i.inward_number}</option>)}
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>Material</label>
            <select className={ccInputCls} value={filters.material_id} onChange={(e) => setFilters({ ...filters, material_id: e.target.value })}>
              <option value="">All</option>
              {materials.map((m) => <option key={m.material_id} value={m.material_id}>{m.material_code}</option>)}
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>Status</label>
            <select className={ccInputCls} value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value as Filters["status"] })}>
              <option value="">All</option>
              <option value="IN_STOCK">IN_STOCK</option><option value="ON_HOLD">ON_HOLD</option>
              <option value="CONSUMED">CONSUMED</option><option value="SCRAPPED">SCRAPPED</option>
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>Location</label>
            <input className={ccInputCls} value={filters.location} onChange={(e) => setFilters({ ...filters, location: e.target.value })} />
          </div>
          {triSelect("on_hold", "On hold")}
          {triSelect("available", "Available")}
          <div>
            <label className={ccLabelCls}>Parent unit id</label>
            <input className={`${ccInputCls} font-mono`} value={filters.parent_unit_id} placeholder="uuid" onChange={(e) => setFilters({ ...filters, parent_unit_id: e.target.value })} />
          </div>
          <button type="submit" className={ccSecondaryBtnCls}>Apply</button>
        </CCFilterBar>
      </form>
      <CCPagedTable
        columns={columns} items={rows} total={total} limit={pageSize} offset={offset}
        onPageChange={setOffset} rowKey={(u) => u.unit_id} loading={loading} error={error} emptyText="No stock units found."
      />
    </div>
  );
}

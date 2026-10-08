"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Layers, Package } from "lucide-react";
import { CCErrorBanner } from "./CCErrorBanner";
import { CCFilterBar } from "./CCFilterBar";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import {
  ccErrorMessage,
  ccListMaterialStockSummary,
  ccListStockUnits,
  CCMaterialStockSummaryOut,
  CCMaterialStockSummaryResponse,
  CCStockUnitOut,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

interface Filters {
  search: string;
  grade: string;
  section: string;
  status: string;
  location: string;
}

const NO_FILTERS: Filters = {
  search: "",
  grade: "",
  section: "",
  status: "",
  location: "",
};

export function CCMaterialStockSummary({
  onSelectUnit,
  selectedUnitId,
  refreshKey = 0,
}: {
  onSelectUnit: (unit: CCStockUnitOut) => void;
  selectedUnitId?: string | null;
  refreshKey?: number;
}) {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [data, setData] = useState<CCMaterialStockSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const res = await ccListMaterialStockSummary({
        search: applied.search.trim() || undefined,
        grade: applied.grade.trim() || undefined,
        section: applied.section.trim() || undefined,
        status: applied.status.trim() || undefined,
        location: applied.location.trim() || undefined,
        limit: 100,
        offset: 0,
      });
      if (mine !== seq.current) return;
      setData(res);
      setError(null);
    } catch (err) {
      if (mine === seq.current) setError(ccErrorMessage(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [applied]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const toggleExpand = (materialId: string) => {
    setExpandedId((prev) => (prev === materialId ? null : materialId));
  };

  return (
    <div className="space-y-3">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(filters);
        }}
      >
        <CCFilterBar
          onClear={() => {
            setFilters(NO_FILTERS);
            setApplied(NO_FILTERS);
          }}
        >
          <div>
            <label className={ccLabelCls}>Material search</label>
            <input
              className={ccInputCls}
              placeholder="e.g. CC-01"
              value={filters.search}
              onChange={(e) => setFilters({ ...filters, search: e.target.value })}
            />
          </div>
          <div>
            <label className={ccLabelCls}>Grade</label>
            <input
              className={ccInputCls}
              placeholder="e.g. SG 500/7"
              value={filters.grade}
              onChange={(e) => setFilters({ ...filters, grade: e.target.value })}
            />
          </div>
          <div>
            <label className={ccLabelCls}>Section</label>
            <input
              className={ccInputCls}
              placeholder="e.g. RECTANGLE"
              value={filters.section}
              onChange={(e) => setFilters({ ...filters, section: e.target.value })}
            />
          </div>
          <div>
            <label className={ccLabelCls}>Status</label>
            <select
              className={ccInputCls}
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
            >
              <option value="">All</option>
              <option value="IN_STOCK">IN_STOCK</option>
              <option value="ON_HOLD">ON_HOLD</option>
              <option value="OUT_OF_STOCK">OUT_OF_STOCK</option>
              <option value="CONSUMED">CONSUMED</option>
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>Location</label>
            <input
              className={ccInputCls}
              placeholder="e.g. vspl f1"
              value={filters.location}
              onChange={(e) => setFilters({ ...filters, location: e.target.value })}
            />
          </div>
          <button type="submit" className={ccSecondaryBtnCls}>
            Apply
          </button>
        </CCFilterBar>
      </form>

      <CCErrorBanner message={error} />

      <div className="overflow-x-auto rounded-lg border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-zinc-200 bg-zinc-50 font-semibold text-zinc-600 dark:border-zinc-800 dark:bg-zinc-800/60 dark:text-zinc-300">
            <tr>
              <th className="w-8 px-3 py-2.5"></th>
              <th className="px-3 py-2.5">Material</th>
              <th className="px-3 py-2.5">Grade</th>
              <th className="px-3 py-2.5">Section</th>
              <th className="px-3 py-2.5">Size</th>
              <th className="px-3 py-2.5 text-right">Bars</th>
              <th className="px-3 py-2.5 text-right">Total Length</th>
              <th className="px-3 py-2.5 text-right">Documented Weight</th>
              <th className="px-3 py-2.5 text-center">Status</th>
              <th className="px-3 py-2.5 text-center">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {loading && !data && (
              <tr>
                <td colSpan={10} className="px-3 py-8 text-center text-zinc-400">
                  Loading material inventory summary...
                </td>
              </tr>
            )}
            {!loading && data && data.items.length === 0 && (
              <tr>
                <td colSpan={10} className="px-3 py-8 text-center text-zinc-400">
                  No materials match the filter criteria.
                </td>
              </tr>
            )}
            {data &&
              data.items.map((m) => {
                const isExpanded = expandedId === m.material_id;
                return (
                  <React.Fragment key={m.material_id}>
                    <tr
                      onClick={() => toggleExpand(m.material_id)}
                      className={`cursor-pointer transition-colors hover:bg-zinc-50/80 dark:hover:bg-zinc-800/40 ${
                        isExpanded ? "bg-blue-50/40 dark:bg-blue-950/20" : ""
                      }`}
                    >
                      <td className="px-3 py-2 text-zinc-400">
                        {isExpanded ? (
                          <ChevronDown className="h-4 w-4 text-blue-600 dark:text-blue-400" />
                        ) : (
                          <ChevronRight className="h-4 w-4" />
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono font-bold text-blue-600 dark:text-blue-400">
                        {m.material_code}
                      </td>
                      <td className="px-3 py-2 font-medium text-zinc-900 dark:text-zinc-100">{m.grade}</td>
                      <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400">{m.section}</td>
                      <td className="px-3 py-2 font-mono text-zinc-700 dark:text-zinc-300">{m.size_display}</td>
                      <td className="px-3 py-2 text-right font-semibold text-zinc-900 dark:text-zinc-100">
                        {m.unit_count.toLocaleString()} bars
                      </td>
                      <td className="px-3 py-2 text-right">
                        <CCLengthCell mm={m.total_length_mm} />
                      </td>
                      <td className="px-3 py-2 text-right font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                        {m.documented_weight_kg !== null
                          ? `${m.documented_weight_kg.toLocaleString("en-US", {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })} kg`
                          : "-"}
                      </td>
                      <td className="px-3 py-2 text-center">
                        <CCStatusBadge status={m.status} />
                      </td>
                      <td className="px-3 py-2 text-center" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          onClick={() => toggleExpand(m.material_id)}
                          className="rounded border border-zinc-300 bg-white px-2 py-0.5 text-[11px] font-medium text-zinc-700 shadow-sm hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-200 dark:hover:bg-zinc-700"
                        >
                          {isExpanded ? "Hide Bars" : "View Bars"}
                        </button>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="bg-zinc-50/70 dark:bg-zinc-900/90">
                        <td colSpan={10} className="p-3">
                          <MaterialUnitsSubTable
                            materialId={m.material_id}
                            materialCode={m.material_code}
                            onSelectUnit={onSelectUnit}
                            selectedUnitId={selectedUnitId}
                          />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
          </tbody>
          {data && data.items.length > 0 && (
            <tfoot className="border-t-2 border-zinc-300 bg-zinc-100/80 font-bold text-zinc-900 dark:border-zinc-700 dark:bg-zinc-800/80 dark:text-zinc-50">
              <tr>
                <td className="px-3 py-2.5"></td>
                <td className="px-3 py-2.5 font-bold uppercase tracking-wider text-zinc-800 dark:text-zinc-200">
                  Total ({data.total} materials)
                </td>
                <td className="px-3 py-2.5 text-zinc-500">-</td>
                <td className="px-3 py-2.5 text-zinc-500">-</td>
                <td className="px-3 py-2.5 text-zinc-500">-</td>
                <td className="px-3 py-2.5 text-right font-extrabold text-blue-700 dark:text-blue-400">
                  {data.totals.total_bars.toLocaleString()} bars
                </td>
                <td className="px-3 py-2.5 text-right">
                  <CCLengthCell mm={data.totals.total_length_mm} />
                </td>
                <td className="px-3 py-2.5 text-right font-mono font-extrabold text-emerald-700 dark:text-emerald-400">
                  {data.totals.total_weight_kg.toLocaleString("en-US", {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2,
                  })}{" "}
                  kg
                </td>
                <td className="px-3 py-2.5 text-center">
                  <CCStatusBadge status="IN_STOCK" />
                </td>
                <td className="px-3 py-2.5"></td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}

function MaterialUnitsSubTable({
  materialId,
  materialCode,
  onSelectUnit,
  selectedUnitId,
}: {
  materialId: string;
  materialCode: string;
  onSelectUnit: (unit: CCStockUnitOut) => void;
  selectedUnitId?: string | null;
}) {
  const [units, setUnits] = useState<CCStockUnitOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    ccListStockUnits({ material_id: materialId, limit: 500 })
      .then((res) => {
        if (active) {
          setUnits(res.items);
          setError(null);
        }
      })
      .catch((err) => {
        if (active) setError(ccErrorMessage(err));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [materialId]);

  return (
    <div className="space-y-2 rounded-md border border-zinc-200 bg-white p-3 shadow-inner dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex items-center justify-between">
        <p className="flex items-center gap-1.5 font-semibold text-zinc-900 dark:text-zinc-100">
          <Package className="h-4 w-4 text-amber-600" /> Physical Stock Units for {materialCode} (
          {units.length} bars)
        </p>
        <span className="text-[11px] text-zinc-500">Click any unit to open detailed inspector</span>
      </div>

      <CCErrorBanner message={error} />

      {loading && <p className="py-4 text-center text-xs text-zinc-400">Loading bars for {materialCode}...</p>}

      {!loading && units.length > 0 && (
        <div className="max-h-72 overflow-y-auto rounded border border-zinc-100 dark:border-zinc-800">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-zinc-100 font-semibold text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
              <tr>
                <th className="px-2.5 py-1.5">Unit Number</th>
                <th className="px-2.5 py-1.5">Inward</th>
                <th className="px-2.5 py-1.5 text-right">Original Length</th>
                <th className="px-2.5 py-1.5 text-right">Remaining Length</th>
                <th className="px-2.5 py-1.5 text-right">Free Length</th>
                <th className="px-2.5 py-1.5 text-center">Status</th>
                <th className="px-2.5 py-1.5">Location</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {units.map((u) => {
                const isSelected = u.unit_id === selectedUnitId;
                return (
                  <tr
                    key={u.unit_id}
                    onClick={() => onSelectUnit(u)}
                    className={`cursor-pointer transition-colors hover:bg-blue-50/50 dark:hover:bg-blue-950/30 ${
                      isSelected ? "bg-emerald-50/60 font-semibold dark:bg-emerald-950/30" : ""
                    }`}
                  >
                    <td className="px-2.5 py-1 font-mono text-blue-600 dark:text-blue-400">{u.unit_number}</td>
                    <td className="px-2.5 py-1 font-mono text-zinc-600 dark:text-zinc-400">{u.inward_number}</td>
                    <td className="px-2.5 py-1 text-right">
                      <CCLengthCell mm={u.original_length_mm} />
                    </td>
                    <td className="px-2.5 py-1 text-right">
                      <CCLengthCell mm={u.remaining_length_mm} />
                    </td>
                    <td className="px-2.5 py-1 text-right font-medium">
                      <CCLengthCell mm={u.free_length_mm} />
                    </td>
                    <td className="px-2.5 py-1 text-center">
                      <CCStatusBadge status={u.status} />
                    </td>
                    <td className="px-2.5 py-1 text-zinc-600 dark:text-zinc-400">{u.location ?? "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

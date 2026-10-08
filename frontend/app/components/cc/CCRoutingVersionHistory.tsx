"use client";
import React, { useState } from "react";
import type { CCRoutingOut } from "@/lib/continuousCastingTypes";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import { fmtDateTime } from "@/lib/continuousCastingForm";

// Read-only view of a Work Order's China routings, newest version first (as the backend returns them).
// Every figure, including blank length and gross required length, is the backend's; none is calculated here.
// `renderActions` (optional) adds an actions column to the version table.
export function CCRoutingVersionHistory({ routings, renderActions }: {
  routings: CCRoutingOut[]; renderActions?: (routing: CCRoutingOut) => React.ReactNode;
}) {
  const [showAll, setShowAll] = useState(false);
  const active = routings.find((r) => r.status === "ACTIVE");
  const older = routings.filter((r) => r !== active);
  const rows = showAll || !active ? routings : [active];

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
        <h3 className="mb-2 text-sm font-bold text-zinc-900 dark:text-zinc-50">Active routing</h3>
        {active ? (
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {kv("Routing id", <CCTxnNumber value={active.routing_id} />)}
            {kv("Version", <b className="font-mono">v{active.version}</b>)}
            {kv("Status", <CCStatusBadge status={active.status} />)}
            {kv("Material source", active.material_source)}
            {kv("Material", <span className="font-mono">{active.validated_material_code ?? "-"}</span>)}
            {kv("Required grade / section", `${active.required_grade ?? "-"} / ${active.required_section ?? "-"}`)}
            {kv("Finished dimension A", <CCLengthCell mm={active.finished_dimension_a_mm} />)}
            {kv("Finished dimension B", <CCLengthCell mm={active.finished_dimension_b_mm} />)}
            {kv("Finished axial length", <CCLengthCell mm={active.finished_axial_length_mm} />)}
            {kv("Machining stock A", <CCLengthCell mm={active.machining_stock_a_mm} />)}
            {kv("Machining stock B", <CCLengthCell mm={active.machining_stock_b_mm} />)}
            {kv("Blank length", <b><CCLengthCell mm={active.blank_length_mm} /></b>)}
            {kv("Planned blanks", <span className="font-mono">{active.planned_blanks ?? "-"}</span>)}
            {kv("Planned cuts", <span className="font-mono">{active.planned_cuts ?? "-"}</span>)}
            {kv("Kerf", <CCLengthCell mm={active.kerf_mm} />)}
            {kv("End trim (total)", <CCLengthCell mm={active.end_trim_mm} />)}
            {kv("Gross required length", <b><CCLengthCell mm={active.gross_required_length_mm} /></b>)}
            {kv("Allocations", <span className="font-mono">{active.allocation_count}</span>)}
            {kv("Validated by / at", `${active.validated_by ?? "-"} / ${fmtDateTime(active.validated_at)}`)}
            {kv("Created by / at", `${active.created_by ?? "-"} / ${fmtDateTime(active.created_at)}`)}
          </dl>
        ) : (
          <p className="text-zinc-500">No active Continuous Casting routing</p>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Routing versions ({routings.length})</h3>
          {active && older.length > 0 && (
            <button type="button" onClick={() => setShowAll(!showAll)} className="text-xs font-semibold text-blue-600 hover:underline dark:text-blue-400">
              {showAll ? "Hide older versions" : `Show ${older.length} older version${older.length === 1 ? "" : "s"}`}
            </button>
          )}
        </div>
        <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
          <table className="w-full text-xs">
            <thead className="bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-800/50">
              <tr>
                {["Routing id", "Version", "Status", "Source", "Material", "Blank length", "Gross required", "Planned blanks", "Planned cuts", "Kerf", "End trim", "Superseded", ...(renderActions ? ["Actions"] : [])].map((h) => (
                  <th key={h} className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {rows.map((r) => (
                <tr key={r.routing_id} className={r.status === "ACTIVE" ? "bg-emerald-500/5" : ""}>
                  <td className="px-3 py-1.5"><CCTxnNumber value={r.routing_id} /></td>
                  <td className="px-3 py-1.5 font-mono font-semibold">v{r.version}</td>
                  <td className="px-3 py-1.5"><CCStatusBadge status={r.status} /></td>
                  <td className="px-3 py-1.5">{r.material_source}</td>
                  <td className="px-3 py-1.5 font-mono">{r.validated_material_code ?? "-"}</td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={r.blank_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={r.gross_required_length_mm} /></td>
                  <td className="px-3 py-1.5 text-right font-mono">{r.planned_blanks ?? "-"}</td>
                  <td className="px-3 py-1.5 text-right font-mono">{r.planned_cuts ?? "-"}</td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={r.kerf_mm} /></td>
                  <td className="px-3 py-1.5 text-right"><CCLengthCell mm={r.end_trim_mm} /></td>
                  <td className="px-3 py-1.5">
                    {r.superseded_at ? (
                      <span>{fmtDateTime(r.superseded_at)} by {r.superseded_by ?? "-"}<br /><span className="text-zinc-500">{r.supersede_reason ?? ""}</span></span>
                    ) : "-"}
                  </td>
                  {renderActions && <td className="px-3 py-1.5">{renderActions(r)}</td>}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={13} className="px-3 py-6 text-center text-zinc-400">No routings for this Work Order.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

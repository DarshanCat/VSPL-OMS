import React from "react";
import type { CCGateStatus } from "@/lib/continuousCastingTypes";
import { CCStatusBadge } from "./CCStatusBadge";

// Displays the backend gate-status answer as returned. The verdict, counts and reasons are never computed here.
export function CCGateStatusPanel({ gate }: { gate: CCGateStatus | null | undefined }) {
  if (!gate) return null;
  const rows: [string, React.ReactNode][] = [
    ["Material source", gate.material_source ?? "-"],
    ["Routing version", gate.routing_version ?? "-"],
    ["First route stage", gate.first_route_stage ?? "-"],
    ["Planned blanks", gate.planned_blanks ?? "-"],
    ["Recorded blanks", gate.recorded_blanks ?? "-"],
    ["Usable good blanks", gate.usable_good_blanks ?? "-"],
    ["First-stage good / rejected", `${gate.first_stage_good_qty ?? "-"} / ${gate.first_stage_rejected_qty ?? "-"}`],
    ["Remaining capacity", gate.remaining_capacity ?? "-"],
  ];
  return (
    <div className="rounded-lg border border-zinc-200 p-3 text-xs dark:border-zinc-800">
      <div className="mb-2 flex items-center gap-2">
        <span className="font-semibold">Material gate - {gate.wo_number}</span>
        <CCStatusBadge status={gate.verdict} />
        {!gate.gate_applies && <span className="text-zinc-400">(gate does not apply)</span>}
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt className="text-zinc-500">{k}</dt>
            <dd className="font-mono">{v}</dd>
          </div>
        ))}
      </dl>
      {gate.reasons.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-zinc-600 dark:text-zinc-300">
          {gate.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

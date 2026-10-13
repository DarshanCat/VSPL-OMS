"use client";
import React from "react";
import { CheckCircle2, AlertCircle, Layers, Scale, Ruler, Scissors, Box } from "lucide-react";
import type { CCRoutingOut, CCWorkOrderListItem, CCGateStatus } from "@/lib/continuousCastingTypes";
import { CCLengthCell } from "./CCLengthCell";

interface CCRequirementCardProps {
  wo: CCWorkOrderListItem;
  routing: CCRoutingOut | null;
  gate?: CCGateStatus | null;
}

export function CCRequirementCard({ wo, routing, gate }: CCRequirementCardProps) {
  if (!routing) {
    return (
      <div className="rounded-xl border border-amber-200 bg-amber-50/50 p-4 text-xs dark:border-amber-900/30 dark:bg-amber-950/20">
        <div className="flex items-center gap-2 text-amber-800 dark:text-amber-200">
          <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-400" />
          <span className="font-semibold">Continuous Casting Routing Required</span>
        </div>
        <p className="mt-1 text-amber-700 dark:text-amber-300">
          Work Order <span className="font-mono font-bold">{wo.wo_number}</span> has no active Continuous Casting routing. Create and activate a routing below to compute exact material and blank requirements.
        </p>
      </div>
    );
  }

  const isRound = routing.required_section?.toUpperCase() === "ROUND" || !!routing.stock_diameter_mm;
  const isSufficient = routing.stock_sufficiency_status === "SUFFICIENT";
  const dimB = routing.finished_dimension_b_mm ?? routing.finished_dimension_a_mm;
  const totalMachiningStock = (routing.machining_stock_a_mm ?? 0) + (routing.machining_stock_b_mm ?? 0);

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      {/* Header */}
      <div className="border-b border-zinc-200 bg-zinc-50/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-800/40">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded bg-amber-600 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-white">
                Requirement Card
              </span>
              <h2 className="text-base font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">
                CONTINUOUS CASTING REQUIREMENT
              </h2>
            </div>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              Work Order <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100">{wo.wo_number}</span> &bull; Customer: <span className="font-medium text-zinc-800 dark:text-zinc-200">{wo.customer_code} {wo.customer_name}</span> &bull; Part: <span className="font-mono font-semibold text-zinc-900 dark:text-zinc-100">{wo.part_number}</span> {wo.part_name ? `(${wo.part_name})` : ""}
            </p>
          </div>

          {/* Sufficiency Badge */}
          <div>
            {isSufficient ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-300 bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300">
                <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />
                🟢 SUFFICIENT
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-rose-300 bg-rose-50 px-3 py-1 text-xs font-bold text-rose-800 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-300">
                <AlertCircle className="h-4 w-4 text-rose-600 dark:text-rose-400" />
                🔴 SHORT
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="p-4 text-xs space-y-4">
        {/* Top Grid: Material & Geometry */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
          {/* Card 1: Material & Grade */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50/50 p-3 dark:border-zinc-800 dark:bg-zinc-800/20">
            <div className="flex items-center gap-1.5 font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              <Box className="h-3.5 w-3.5 text-blue-600" />
              <span>Material Specification</span>
            </div>
            <dl className="space-y-1.5">
              <div className="flex justify-between">
                <dt className="text-zinc-500">Material Code:</dt>
                <dd className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{routing.validated_material_code ?? "-"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Grade:</dt>
                <dd className="font-medium text-zinc-900 dark:text-zinc-100">{routing.required_grade ?? "-"}</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Section Shape:</dt>
                <dd className="font-medium text-zinc-900 dark:text-zinc-100 uppercase">{routing.required_section ?? "-"}</dd>
              </div>
              {isRound && (
                <div className="flex justify-between">
                  <dt className="text-zinc-500">Diameter:</dt>
                  <dd className="font-mono font-bold text-blue-600 dark:text-blue-400">
                    Ø {routing.stock_diameter_mm ?? routing.stock_dimension_a_mm ?? routing.finished_dimension_a_mm} mm
                  </dd>
                </div>
              )}
              {!isRound && routing.stock_dimension_a_mm && (
                <div className="flex justify-between">
                  <dt className="text-zinc-500">Stock Section:</dt>
                  <dd className="font-mono text-zinc-900 dark:text-zinc-100">
                    {routing.stock_dimension_a_mm} × {routing.stock_dimension_b_mm ?? routing.stock_dimension_a_mm} mm
                  </dd>
                </div>
              )}
            </dl>
          </div>

          {/* Card 2: Dimensions & Allowance */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50/50 p-3 dark:border-zinc-800 dark:bg-zinc-800/20">
            <div className="flex items-center gap-1.5 font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              <Ruler className="h-3.5 w-3.5 text-indigo-600" />
              <span>Part Dimensions & Blank</span>
            </div>
            <dl className="space-y-1.5">
              <div className="flex justify-between">
                <dt className="text-zinc-500">Finished Size:</dt>
                <dd className="font-mono text-zinc-900 dark:text-zinc-100">
                  {routing.finished_dimension_a_mm} × {dimB} × {routing.finished_axial_length_mm} mm
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Machining Allowance:</dt>
                <dd className="font-mono text-zinc-900 dark:text-zinc-100">
                  {routing.machining_stock_a_mm} + {routing.machining_stock_b_mm} mm ({totalMachiningStock} mm)
                </dd>
              </div>
              <div className="flex justify-between pt-1 border-t border-zinc-200 dark:border-zinc-700">
                <dt className="font-bold text-zinc-700 dark:text-zinc-300">Blank Length:</dt>
                <dd className="font-mono font-bold text-indigo-600 dark:text-indigo-400">
                  <CCLengthCell mm={routing.blank_length_mm} />
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">WO Quantity:</dt>
                <dd className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{wo.physical_wo_qty} pcs</dd>
              </div>
            </dl>
          </div>

          {/* Card 3: Cutting Plan */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50/50 p-3 dark:border-zinc-800 dark:bg-zinc-800/20">
            <div className="flex items-center gap-1.5 font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              <Scissors className="h-3.5 w-3.5 text-amber-600" />
              <span>Cutting & Length Plan</span>
            </div>
            <dl className="space-y-1.5">
              <div className="flex justify-between">
                <dt className="text-zinc-500">Required Blanks:</dt>
                <dd className="font-mono font-bold text-zinc-900 dark:text-zinc-100">{routing.planned_blanks} pcs</dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Planned Cuts & Kerf:</dt>
                <dd className="font-mono text-zinc-900 dark:text-zinc-100">
                  {routing.planned_cuts} cuts @ {routing.kerf_mm} mm
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">End Trim Allowance:</dt>
                <dd className="font-mono text-zinc-900 dark:text-zinc-100">{routing.end_trim_mm} mm</dd>
              </div>
              <div className="flex justify-between pt-1 border-t border-zinc-200 dark:border-zinc-700">
                <dt className="font-bold text-zinc-700 dark:text-zinc-300">Gross Required:</dt>
                <dd className="font-mono font-bold text-amber-600 dark:text-amber-400">
                  <CCLengthCell mm={routing.gross_required_length_mm} />
                </dd>
              </div>
            </dl>
          </div>

          {/* Card 4: Weight Breakdown */}
          <div className="rounded-lg border border-zinc-200 bg-zinc-50/50 p-3 dark:border-zinc-800 dark:bg-zinc-800/20">
            <div className="flex items-center gap-1.5 font-semibold text-zinc-700 dark:text-zinc-300 mb-2">
              <Scale className="h-3.5 w-3.5 text-purple-600" />
              <span>Weight Breakdown</span>
            </div>
            <dl className="space-y-1.5">
              <div className="flex justify-between">
                <dt className="text-zinc-500">Net Blank Weight:</dt>
                <dd className="font-mono font-bold text-zinc-900 dark:text-zinc-100">
                  {routing.net_blank_weight_kg !== null && routing.net_blank_weight_kg !== undefined
                    ? `${routing.net_blank_weight_kg.toFixed(2)} kg / blank`
                    : "-"}
                </dd>
              </div>
              <div className="flex justify-between">
                <dt className="text-zinc-500">Net Blank Total:</dt>
                <dd className="font-mono font-bold text-purple-600 dark:text-purple-400">
                  {routing.net_blank_weight_total_kg !== null && routing.net_blank_weight_total_kg !== undefined
                    ? `${routing.net_blank_weight_total_kg.toFixed(2)} kg`
                    : "-"}
                </dd>
              </div>
              <div className="flex justify-between pt-1 border-t border-zinc-200 dark:border-zinc-700">
                <dt className="font-bold text-zinc-700 dark:text-zinc-300">Gross Material Wt:</dt>
                <dd className="font-mono font-bold text-purple-700 dark:text-purple-300">
                  {routing.gross_material_weight_kg !== null && routing.gross_material_weight_kg !== undefined
                    ? `${routing.gross_material_weight_kg.toFixed(2)} kg`
                    : "-"}
                </dd>
              </div>
              <p className="text-[10px] text-zinc-400 dark:text-zinc-500">
                Density: 7.20 g/cm³ &bull; Gross includes cuts + trim
              </p>
            </dl>
          </div>
        </div>

        {/* Stock & Sufficiency Overview Panel */}
        <div className="rounded-lg border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-800/40">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-6">
              <div>
                <span className="text-[11px] text-zinc-500 uppercase font-semibold">Available Stock</span>
                <p className="font-mono font-bold text-zinc-900 dark:text-zinc-100 text-sm">
                  {routing.available_stock_length_mm?.toLocaleString() ?? 0} mm
                  <span className="text-xs font-normal text-zinc-500 ml-1">
                    ({routing.available_stock_bars ?? 0} bars)
                  </span>
                </p>
              </div>
              <div className="border-l border-zinc-200 dark:border-zinc-700 pl-6">
                <span className="text-[11px] text-zinc-500 uppercase font-semibold">Allocated Stock</span>
                <p className="font-mono font-bold text-blue-600 dark:text-blue-400 text-sm">
                  {routing.allocated_length_mm?.toLocaleString() ?? 0} mm
                  <span className="text-xs font-normal text-zinc-500 ml-1">
                    ({routing.allocation_count} allocation{routing.allocation_count === 1 ? "" : "s"})
                  </span>
                </p>
              </div>
              <div className="border-l border-zinc-200 dark:border-zinc-700 pl-6">
                <span className="text-[11px] text-zinc-500 uppercase font-semibold">Remaining Requirement</span>
                <p className="font-mono font-bold text-amber-600 dark:text-amber-400 text-sm">
                  {routing.remaining_required_length_mm?.toLocaleString() ?? 0} mm
                </p>
              </div>
            </div>

            {/* Shortage Breakdown if SHORT */}
            {!isSufficient && (
              <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-1.5 text-xs text-rose-800 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-300">
                <span className="font-bold">Shortage Details: </span>
                Required: <span className="font-mono font-semibold">{routing.gross_required_length_mm?.toLocaleString()} mm</span> &bull; Available: <span className="font-mono font-semibold">{((routing.allocated_length_mm ?? 0) + (routing.available_stock_length_mm ?? 0)).toLocaleString()} mm</span> &bull; Short: <span className="font-mono font-bold text-rose-600 dark:text-rose-400">{routing.stock_shortage_length_mm?.toLocaleString()} mm</span>
              </div>
            )}
          </div>
        </div>

        {/* Material Gate Status Indicator */}
        {gate && (
          <div className="flex items-center justify-between rounded-lg border border-zinc-200 bg-zinc-50/50 px-3 py-2 text-xs dark:border-zinc-800 dark:bg-zinc-800/20">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-zinc-500" />
              <span className="font-semibold text-zinc-700 dark:text-zinc-300">Phase 10 Material Gate:</span>
              <span className="font-mono text-zinc-600 dark:text-zinc-400">
                Verdict: <b className="text-zinc-900 dark:text-zinc-100">{gate.verdict}</b> &bull; Usable Good Blanks: <b className="text-zinc-900 dark:text-zinc-100">{gate.usable_good_blanks ?? 0}</b> / {gate.planned_blanks ?? routing.planned_blanks ?? 0} pcs
              </span>
            </div>
            <div className="text-[11px] text-zinc-500">
              {gate.gate_applies ? "Shop-floor production gated by reconciled cut blanks" : "Standard production"}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

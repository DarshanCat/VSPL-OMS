import React from "react";
import type { CCStockUnitOut } from "@/lib/continuousCastingTypes";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";

// Summary of one stock unit exactly as the backend reports it. No value here is calculated in the browser.
// Physical status and allocation eligibility are two separate answers and are shown separately.
export function CCUnitBalances({ unit }: { unit: CCStockUnitOut }) {
  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );
  return (
    <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
      {kv("Unit", <CCTxnNumber value={unit.unit_number} />)}
      {kv("Inward", <span className="font-mono">{unit.inward_number}</span>)}
      {kv("Material", <span className="font-mono">{unit.material_code}</span>)}
      {kv("Physical status", <CCStatusBadge status={unit.status} />)}
      {kv("Inward QA", <CCStatusBadge status={unit.inward_qa_status} />)}
      {kv("Allocation eligible", unit.allocation_eligible ? "Yes" : `No${unit.allocation_ineligible_reason ? ` - ${unit.allocation_ineligible_reason}` : ""}`)}
      {kv("Location", unit.location ?? "-")}
      {kv("Parent unit", unit.parent_unit_number ? <span className="font-mono">{unit.parent_unit_number}</span> : "-")}
      {kv("Original", <CCLengthCell mm={unit.original_length_mm} />)}
      {kv("Remaining", <CCLengthCell mm={unit.remaining_length_mm} />)}
      {kv("Reserved", <CCLengthCell mm={unit.reserved_length_mm} />)}
      {kv("Issued", <CCLengthCell mm={unit.issued_length_mm} />)}
      {kv("Consumed", <CCLengthCell mm={unit.consumed_length_mm} />)}
      {kv("Scrapped", <CCLengthCell mm={unit.scrapped_length_mm} />)}
      {kv("Free", <b><CCLengthCell mm={unit.free_length_mm} /></b>)}
      {kv("Piece quantity", unit.piece_quantity)}
    </dl>
  );
}

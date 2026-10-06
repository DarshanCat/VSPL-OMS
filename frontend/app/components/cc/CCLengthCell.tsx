import React from "react";

// A whole-millimetre value from the backend, shown as received (thousands separators only).
export function CCLengthCell({ mm, unit = true }: { mm: number | null | undefined; unit?: boolean }) {
  if (mm === null || mm === undefined) return <span className="text-zinc-400">-</span>;
  return (
    <span className="font-mono tabular-nums">
      {mm.toLocaleString("en-US")}
      {unit && <span className="ml-0.5 text-zinc-400">mm</span>}
    </span>
  );
}

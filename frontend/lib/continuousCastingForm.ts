// Form-entry helpers for the Continuous Casting screens: UX-level input checks and display formatting only.
// The backend validates everything again and stays authoritative.

// "" -> null (field left empty); a whole positive integer -> number; anything else -> NaN.
export function parseOptionalPositiveInt(text: string): number | null {
  const t = text.trim();
  if (t === "") return null;
  if (!/^\d+$/.test(t)) return NaN;
  const n = Number(t);
  return Number.isSafeInteger(n) && n > 0 ? n : NaN;
}

export function parsePositiveInt(text: string): number {
  const n = parseOptionalPositiveInt(text);
  return n === null ? NaN : n;
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export const ccInputCls =
  "w-full rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 placeholder-zinc-400 " +
  "focus:border-blue-500 focus:outline-none dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100";
export const ccLabelCls = "mb-0.5 block text-[11px] font-medium text-zinc-500";
export const ccPrimaryBtnCls =
  "rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50";
export const ccSecondaryBtnCls =
  "rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 " +
  "dark:border-zinc-700 dark:hover:bg-zinc-800";

// Whole number >= 0 (for fields the backend accepts as zero, e.g. kerf or machining stock). "" -> NaN.
export function parseNonNegativeInt(text: string): number {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return NaN;
  const n = Number(t);
  return Number.isSafeInteger(n) ? n : NaN;
}

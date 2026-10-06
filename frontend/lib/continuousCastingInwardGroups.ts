// Entry-form helpers for a homogeneous inward: ONE material, one or more LENGTH GROUPS (length + number of bars).
// UI assistance only. The backend still validates everything and creates one stock unit per physical bar from the
// flat `unit_lengths_mm` list this module builds at submit time. Lengths are whole millimetres (integers) throughout;
// no floating-point length is ever held or computed.

export interface LengthGroupInput { length: string; count: string }

export interface ValidGroup { length_mm: number; bar_count: number }

// A technical guard against freezing the browser while expanding the list; it is not a business limit.
export const MAX_BARS_PER_SUBMIT = 100_000;

const WHOLE = /^\d+$/;

function whole(text: string): number {
  const t = text.trim();
  if (!WHOLE.test(t)) return NaN;
  const n = Number(t);
  return Number.isSafeInteger(n) && n > 0 ? n : NaN;
}

export function isBlankGroup(g: LengthGroupInput): boolean {
  return g.length.trim() === "" && g.count.trim() === "";
}

export type GroupCheck = { ok: true; groups: ValidGroup[] } | { ok: false; error: string };

// Whole-form check used at submit: every non-blank row must be a positive integer length and a positive integer bar
// count; at least one group; no length value twice.
export function validateLengthGroups(rows: LengthGroupInput[]): GroupCheck {
  const filled = rows.filter((g) => !isBlankGroup(g));
  if (filled.length === 0) return { ok: false, error: "Enter at least one length group (length and number of bars)." };
  const groups: ValidGroup[] = [];
  const seen = new Set<number>();
  for (const g of filled) {
    const length = whole(g.length);
    const count = whole(g.count);
    if (Number.isNaN(length)) return { ok: false, error: `Length "${g.length.trim()}" must be a whole number of mm greater than 0.` };
    if (Number.isNaN(count)) return { ok: false, error: `Number of bars "${g.count.trim()}" must be a whole number greater than 0.` };
    if (seen.has(length)) {
      return {
        ok: false,
        error: `Length ${length} mm appears more than once. Use one group for ${length} mm with the total number of bars (for example ${length} × 105 instead of ${length} × 50 and ${length} × 55).`,
      };
    }
    seen.add(length);
    groups.push({ length_mm: length, bar_count: count });
  }
  const bars = groups.reduce((s, g) => s + g.bar_count, 0);
  if (bars > MAX_BARS_PER_SUBMIT) {
    return { ok: false, error: `Too many bars for one inward in this form (${MAX_BARS_PER_SUBMIT.toLocaleString("en-US")} at most). Split the receipt.` };
  }
  return { ok: true, groups };
}

// Submit-time expansion: [{1000, 105}, {750, 20}] -> [1000 x105, 750 x20]. The backend creates the stock units.
export function expandUnitLengths(groups: ValidGroup[]): number[] {
  const out: number[] = [];
  for (const g of groups) for (let i = 0; i < g.bar_count; i++) out.push(g.length_mm);
  return out;
}

export interface EntrySummary { bars: number; totalMm: number }

// Live entry summary over the rows that are individually valid so far (invalid or half-typed rows are skipped).
export function summarizeGroups(rows: LengthGroupInput[]): EntrySummary {
  let bars = 0;
  let totalMm = 0;
  for (const g of rows) {
    const length = whole(g.length);
    const count = whole(g.count);
    if (Number.isNaN(length) || Number.isNaN(count)) continue;
    bars += count;
    totalMm += length * count;
  }
  return { bars, totalMm };
}

// Whole millimetres -> "130.000" (metres, always 3 decimals) using integer arithmetic only.
export function formatMetres(totalMm: number): string {
  const whole_m = Math.floor(totalMm / 1000);
  const rest = totalMm % 1000;
  return `${whole_m.toLocaleString("en-US")}.${String(rest).padStart(3, "0")}`;
}

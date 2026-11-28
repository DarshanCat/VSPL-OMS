"use client";
// Shared building blocks for the Sales dashboards (order status, schedule status).
import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, ArrowDown, ArrowLeft, ArrowUp, Download, Loader2, Pencil, Printer, RefreshCw, Search, X } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AppShell } from "@/app/components/layout/AppShell";
import { getCurrentUserRole, getCurrentUserRoles, PriceTarget, setOrderPrice, updatePOLinePrice, updateSchedule } from "@/lib/api";

// ---------------------------------------------------------------- formatting
export const inrFull = (n: number) => "₹" + Math.round(n || 0).toLocaleString("en-IN");
export const inrPlain = (n: number) => Math.round(n || 0).toLocaleString("en-IN");
/** ₹1.65 Cr / ₹16.45 L / ₹12.5 K for tight spots. */
export function inrCompact(n: number): string {
  const v = Math.abs(n || 0);
  const sign = (n || 0) < 0 ? "-" : "";
  const f = (x: number, d = 2) => String(parseFloat(x.toFixed(d)));
  if (v >= 1e7) return `${sign}₹${f(v / 1e7)} Cr`;
  if (v >= 1e5) return `${sign}₹${f(v / 1e5)} L`;
  if (v >= 1e3) return `${sign}₹${f(v / 1e3, 1)} K`;
  return `${sign}₹${Math.round(v)}`;
}
export const dmy = (iso?: string | null) => {
  if (!iso) return "-";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
};
export const dMonthY = (iso: string) => {
  const dt = new Date(iso + "T00:00:00");
  return dt.toLocaleDateString("en-IN", { day: "numeric", month: "long", year: "numeric" });
};

// ---------------------------------------------------------------- access
export function useSalesAccess(): boolean | null {
  const [allowed, setAllowed] = useState<boolean | null>(null);
  useEffect(() => {
    const all = [getCurrentUserRole(), ...getCurrentUserRoles()].map((r) => String(r || "").toLowerCase());
    setAllowed(all.includes("sales") || all.includes("admin"));
  }, []);
  return allowed;
}

export function NoAccess({ title, backHref, backLabel }: { title: string; backHref: string; backLabel: string }) {
  return (
    <AppShell>
      <div className="max-w-xl mx-auto mt-16 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-8 text-center">
        <h1 className="text-lg font-extrabold text-zinc-900 dark:text-zinc-50">This report is for the Sales team</h1>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">Your account does not have access to the {title}.</p>
        <Link href={backHref} className="mt-4 inline-block text-sm font-bold text-blue-600">Back to {backLabel}</Link>
      </div>
    </AppShell>
  );
}

// ---------------------------------------------------------------- layout
export const PRINT_CSS = `@media print {
  .no-print { display: none !important; }
  .print-card { break-inside: avoid; box-shadow: none !important; }
  body { background: #fff !important; }
  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
}`;

export function ReportHeader(props: {
  eyebrow: string;
  title: string;
  subtitle: string;
  asOf?: string;
  backHref: string;
  backLabel: string;
  loading: boolean;
  downloading: boolean;
  canDownload: boolean;
  onRefresh: () => void;
  onDownload: () => void;
}) {
  const btn = "inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-60";
  return (
    <div className="space-y-3">
      <Link href={props.backHref} className="no-print inline-flex items-center gap-1 text-xs font-bold text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200">
        <ArrowLeft className="h-3.5 w-3.5" /> {props.backLabel}
      </Link>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">{props.eyebrow}</span>
          <h1 className="mt-1 text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">{props.title}</h1>
          <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {props.subtitle}
            {props.asOf && <span className="font-semibold text-zinc-700 dark:text-zinc-300"> · As of {dMonthY(props.asOf)}</span>}
          </p>
        </div>
        <div className="no-print flex items-center gap-2">
          <button onClick={props.onRefresh} disabled={props.loading} className={btn}>
            <RefreshCw className={`h-3.5 w-3.5 ${props.loading ? "animate-spin" : ""}`} /> Refresh
          </button>
          <button onClick={props.onDownload} disabled={props.downloading || !props.canDownload} className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-3 py-2 text-xs font-bold text-white hover:bg-blue-700 disabled:opacity-60">
            {props.downloading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />} Download Excel
          </button>
          <button onClick={() => window.print()} className={btn}>
            <Printer className="h-3.5 w-3.5" /> Print
          </button>
        </div>
      </div>
    </div>
  );
}

export function ErrorBanner({ message, onClose }: { message: string; onClose?: () => void }) {
  if (!message) return null;
  return (
    <div className="no-print flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-3 text-xs font-semibold text-rose-700 dark:text-rose-300">
      <AlertTriangle className="h-4 w-4 shrink-0" />
      <span className="flex-1 break-words">{message}</span>
      {onClose && (
        <button onClick={onClose} aria-label="Dismiss"><X className="h-3.5 w-3.5" /></button>
      )}
    </div>
  );
}

export function Card({ title, hint, right, children, className = "" }: { title?: string; hint?: string; right?: React.ReactNode; children: React.ReactNode; className?: string }) {
  return (
    <section className={`print-card rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm ${className}`}>
      {(title || right) && (
        <div className="flex items-center justify-between gap-3 px-5 pt-4 pb-2">
          <div>
            {title && <h3 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">{title}</h3>}
            {hint && <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{hint}</p>}
          </div>
          {right}
        </div>
      )}
      <div className="px-5 pb-4">{children}</div>
    </section>
  );
}

type Tone = "hero" | "red" | "amber" | "blue" | "neutral";
const TONES: Record<Tone, { bar: string; value: string; card: string }> = {
  hero: { bar: "bg-blue-600", value: "text-zinc-900 dark:text-zinc-50", card: "bg-gradient-to-br from-blue-50 to-white dark:from-blue-950/40 dark:to-zinc-900 border-blue-200 dark:border-blue-900" },
  red: { bar: "bg-rose-500", value: "text-rose-600 dark:text-rose-400", card: "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800" },
  amber: { bar: "bg-amber-500", value: "text-amber-600 dark:text-amber-400", card: "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800" },
  blue: { bar: "bg-sky-500", value: "text-zinc-900 dark:text-zinc-50", card: "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800" },
  neutral: { bar: "bg-zinc-400", value: "text-zinc-900 dark:text-zinc-50", card: "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800" },
};

/** One KPI. `money` shows compact form big and the full amount under it, so nothing ever wraps. */
export function Kpi(props: { label: string; tone?: Tone; money?: number; count?: number; sub?: string; foot?: string; onClick?: () => void; active?: boolean }) {
  const t = TONES[props.tone || "neutral"];
  const big = props.money !== undefined ? inrCompact(props.money) : inrPlain(props.count || 0);
  const clickable = !!props.onClick;
  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={props.onClick}
      onKeyDown={clickable ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); props.onClick!(); } } : undefined}
      title={clickable ? "Click to see these in the list below" : undefined}
      className={`print-card relative overflow-hidden rounded-2xl border p-4 shadow-sm ${t.card} ${
        clickable ? "cursor-pointer transition hover:-translate-y-0.5 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-blue-500/50" : ""
      } ${props.active ? "ring-2 ring-blue-500" : ""}`}
    >
      <span className={`absolute inset-y-0 left-0 w-1 ${t.bar}`} />
      <p className="text-[10px] font-bold uppercase tracking-wider text-zinc-500 dark:text-zinc-400">{props.label}</p>
      <p className={`mt-1 whitespace-nowrap font-extrabold tabular-nums leading-tight ${t.value} ${props.tone === "hero" ? "text-3xl" : "text-2xl"}`}>{big}</p>
      {props.money !== undefined && (
        <p className="whitespace-nowrap text-[11px] tabular-nums text-zinc-500 dark:text-zinc-400" title={inrFull(props.money)}>{inrFull(props.money)}</p>
      )}
      {props.sub && <p className="mt-1 text-[11px] font-semibold text-zinc-600 dark:text-zinc-300">{props.sub}</p>}
      {props.foot && <p className="text-[11px] text-zinc-500 dark:text-zinc-400">{props.foot}</p>}
      {clickable && <p className="no-print mt-1 text-[10px] font-bold uppercase tracking-wide text-blue-600 dark:text-blue-400">{props.active ? "Showing below ↓" : "View orders ↓"}</p>}
    </div>
  );
}

// ---------------------------------------------------------------- small visuals
export function ShareBar({ pct, color = "#2563eb" }: { pct: number; color?: string }) {
  const w = Math.max(0, Math.min(100, pct));
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 sm:w-32 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div className="h-full rounded-full" style={{ width: `${w}%`, background: color }} />
      </div>
      <span className="w-10 text-right text-[11px] tabular-nums text-zinc-500">{w.toFixed(0)}%</span>
    </div>
  );
}

export function BarList({ rows, empty = "Nothing to show." }: { rows: { label: string; value: number; sub?: string }[]; empty?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (!rows.length) return <p className="py-6 text-center text-xs text-zinc-400">{empty}</p>;
  return (
    <ul className="space-y-3">
      {rows.map((r, i) => (
        <li key={r.label + i}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-xs font-semibold text-zinc-800 dark:text-zinc-100" title={r.label}>{r.label || "—"}</span>
            <span className="shrink-0 whitespace-nowrap text-xs font-extrabold tabular-nums text-zinc-900 dark:text-zinc-50" title={inrFull(r.value)}>{inrCompact(r.value)}</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
            <div className="h-full rounded-full bg-blue-600" style={{ width: `${(r.value / max) * 100}%` }} />
          </div>
          {r.sub && <p className="mt-0.5 text-[10px] text-zinc-500">{r.sub}</p>}
        </li>
      ))}
    </ul>
  );
}

export type ChartSeries = { key: string; label: string; color: string };

/** Value-by-month column chart. Each row: {key, label, ...series values}. Click a column to select it. */
export function MonthChart({ rows, series, activeKey, onSelect }: {
  rows: Record<string, any>[];
  series: ChartSeries[];
  activeKey: string | null;
  onSelect: (key: string | null) => void;
}) {
  const stacked = series.length > 1;
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }} barCategoryGap="22%">
          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#a1a1aa33" />
          <XAxis dataKey="label" tick={{ fill: "#71717a", fontSize: 11 }} tickLine={false} axisLine={false} interval={0} />
          <YAxis tick={{ fill: "#71717a", fontSize: 11 }} tickLine={false} axisLine={false} width={64} tickFormatter={(v) => inrCompact(Number(v))} />
          <Tooltip
            cursor={{ fill: "#a1a1aa22" }}
            formatter={(v: any, name: any) => [inrFull(Number(v)), name]}
            labelFormatter={(l: any) => String(l)}
            contentStyle={{ borderRadius: 12, border: "1px solid #e4e4e7", fontSize: 12 }}
          />
          {series.map((s, si) => (
            <Bar
              key={s.key}
              dataKey={s.key}
              name={s.label}
              stackId={stacked ? "a" : undefined}
              fill={s.color}
              radius={stacked ? (si === series.length - 1 ? [6, 6, 0, 0] : 0) : [6, 6, 0, 0]}
              cursor="pointer"
              onClick={(d: any) => onSelect(d?.key && d.key !== activeKey ? d.key : null)}
            >
              {rows.map((r) => (
                <Cell key={r.key} fillOpacity={activeKey && activeKey !== r.key ? 0.35 : 1} />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
      {stacked && (
        <div className="mt-1 flex flex-wrap items-center justify-center gap-4">
          {series.map((s) => (
            <span key={s.key} className="inline-flex items-center gap-1.5 text-[11px] font-semibold text-zinc-600 dark:text-zinc-300">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} /> {s.label}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- detail table
export type Column<T> = {
  key: string;
  label: string;
  align?: "left" | "right";
  value: (r: T) => string | number | null;       // used for sort and search
  render?: (r: T) => React.ReactNode;
  searchable?: boolean;
};

export function DataTable<T>({ rows, columns, title, filterLabel, onClearFilter, rowKey }: {
  rows: T[];
  columns: Column<T>[];
  title: string;
  filterLabel?: string | null;
  onClearFilter?: () => void;
  rowKey: (r: T, i: number) => string;
}) {
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    let out = needle
      ? rows.filter((r) => columns.some((c) => c.searchable !== false && String(c.value(r) ?? "").toLowerCase().includes(needle)))
      : rows.slice();
    if (sort) {
      const col = columns.find((c) => c.key === sort.key);
      if (col) {
        out = out.sort((a, b) => {
          const x = col.value(a), y = col.value(b);
          if (x === y) return 0;
          if (x === null || x === undefined) return 1;
          if (y === null || y === undefined) return -1;
          return (typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y))) * sort.dir;
        });
      }
    }
    return out;
  }, [rows, columns, q, sort]);
  const toggle = (key: string) => setSort((s) => (s?.key === key ? (s.dir === 1 ? { key, dir: -1 } : null) : { key, dir: 1 }));

  return (
    <Card
      title={title}
      hint={`${shown.length} of ${rows.length} shown`}
      right={
        <div className="no-print flex items-center gap-2">
          {filterLabel && (
            <button onClick={onClearFilter} className="inline-flex items-center gap-1 rounded-full bg-blue-50 dark:bg-blue-950/50 px-2.5 py-1 text-[11px] font-bold text-blue-700 dark:text-blue-300">
              {filterLabel} <X className="h-3 w-3" />
            </button>
          )}
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-zinc-400" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search customer, part, PO…"
              className="w-44 sm:w-60 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-950 py-1.5 pl-8 pr-2 text-xs text-zinc-800 dark:text-zinc-100 outline-none focus:border-blue-500"
            />
          </div>
        </div>
      }
    >
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="border-b border-zinc-200 dark:border-zinc-800 text-[10px] uppercase tracking-wider text-zinc-500">
              {columns.map((c) => (
                <th key={c.key} className={`px-3 py-2 font-bold ${c.align === "right" ? "text-right" : "text-left"}`}>
                  <button onClick={() => toggle(c.key)} className="inline-flex items-center gap-1 uppercase hover:text-zinc-800 dark:hover:text-zinc-200">
                    {c.label}
                    {sort?.key === c.key && (sort.dir === 1 ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {shown.map((r, i) => (
              <tr key={rowKey(r, i)} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                {columns.map((c) => (
                  <td key={c.key} className={`px-3 py-2 ${c.align === "right" ? "text-right tabular-nums whitespace-nowrap" : ""}`}>
                    {c.render ? c.render(r) : (c.value(r) ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
            {!shown.length && (
              <tr><td colSpan={columns.length} className="px-3 py-8 text-center text-zinc-400">No rows match.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

export function PeriodTable({ rows, activeKey, onSelect, total, valueLabel = "Value", countLabel = "Orders" }: {
  rows: { key: string; label: string; count: number; value: number; qty: number }[];
  activeKey: string | null;
  onSelect: (key: string | null) => void;
  total: { count: number; value: number; qty: number };
  valueLabel?: string;
  countLabel?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="min-w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-200 dark:border-zinc-800 text-[10px] uppercase tracking-wider text-zinc-500">
            <th className="px-3 py-2 text-left font-bold">Period</th>
            <th className="px-3 py-2 text-right font-bold">{countLabel}</th>
            <th className="px-3 py-2 text-right font-bold">{valueLabel}</th>
            <th className="px-3 py-2 text-right font-bold">Qty</th>
            <th className="px-3 py-2 text-left font-bold">Share</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {rows.map((b) => (
            <tr
              key={b.key}
              onClick={() => onSelect(activeKey === b.key ? null : b.key)}
              className={`cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/40 ${activeKey === b.key ? "bg-blue-50 dark:bg-blue-950/30" : ""}`}
            >
              <td className="px-3 py-2 font-semibold text-zinc-800 dark:text-zinc-100 whitespace-nowrap">{b.label}</td>
              <td className="px-3 py-2 text-right tabular-nums">{inrPlain(b.count)}</td>
              <td className="px-3 py-2 text-right font-bold tabular-nums whitespace-nowrap">{inrFull(b.value)}</td>
              <td className="px-3 py-2 text-right tabular-nums">{inrPlain(b.qty)}</td>
              <td className="px-3 py-2"><ShareBar pct={total.value ? (b.value / total.value) * 100 : 0} /></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-zinc-300 dark:border-zinc-700 font-extrabold text-zinc-900 dark:text-zinc-50">
            <td className="px-3 py-2">Total</td>
            <td className="px-3 py-2 text-right tabular-nums">{inrPlain(total.count)}</td>
            <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{inrFull(total.value)}</td>
            <td className="px-3 py-2 text-right tabular-nums">{inrPlain(total.qty)}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export function Loading() {
  return <div className="flex items-center justify-center py-24 text-zinc-400"><Loader2 className="h-6 w-6 animate-spin" /></div>;
}


// ---------------------------------------------------------------- edit price
export type PriceEditRow = {
  ref: string;            // order / PO / schedule reference shown in the list
  customer: string;
  part: string;
  po?: string;            // customer PO number (named in the message for an order that has no PO line yet)
  qty: number;            // pending quantity (used only to preview the new value)
  unitPrice: number | null;
  target: PriceTarget;
};

/** Small "Edit price" button for a table row; renders nothing when the row has no price to edit. */
export function EditPriceButton({ target, onClick }: { target?: PriceTarget | null; onClick: () => void }) {
  if (!target) return null;
  return (
    <button
      type="button"
      onClick={onClick}
      title="Edit the unit price"
      className="no-print inline-flex items-center gap-1 rounded-lg border border-zinc-200 dark:border-zinc-700 px-2 py-1 text-[10px] font-bold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-100 dark:hover:bg-zinc-800"
    >
      <Pencil className="h-3 w-3" /> Edit price
    </button>
  );
}

/** Dialog that changes one unit price through the same Masters endpoints PO Master / Schedule Master use. */
export function PriceEditDialog({ row, onClose, onSaved }: { row: PriceEditRow; onClose: () => void; onSaved: (message: string) => void | Promise<void> }) {
  const [value, setValue] = useState(row.unitPrice ? String(row.unitPrice) : "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const price = Number(value);
  const valid = value.trim() !== "" && isFinite(price) && price >= 0;
  const changed = valid && Math.round(price * 100) !== Math.round((row.unitPrice || 0) * 100);
  const kind = row.target.type;

  const save = async () => {
    if (!valid) { setErr("Enter a price of zero or more."); return; }
    if (!changed) { setErr("The price is the same as before."); return; }
    setSaving(true);
    setErr("");
    try {
      if (row.target.type === "PO_LINE") await updatePOLinePrice(row.target.po_id, row.target.line_id, price);
      else if (row.target.type === "ORDER") await setOrderPrice(row.target.order_id, price);
      else await updateSchedule(row.target.id, { unit_price: price });
      await onSaved(`Price of ${row.ref} (${row.part}) changed to ₹${price.toLocaleString("en-IN")}.`);
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      setErr(typeof d === "string" ? d : e?.message || "Could not save the price.");
      setSaving(false);
    }
  };

  const labelCls = "block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1";
  return (
    <div className="no-print fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label="Edit price">
      <div className="w-full max-w-md rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 space-y-3 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">Edit price · {row.ref}</h2>
            <p className="text-[11px] text-zinc-500">{row.customer} · {row.part} · {row.qty.toLocaleString("en-IN")} pcs</p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose}><X className="h-4 w-4 text-zinc-500" /></button>
        </div>
        <p className="rounded-xl bg-zinc-100 dark:bg-zinc-800 p-2.5 text-[11px] text-zinc-600 dark:text-zinc-300">
          {kind === "PO_LINE"
            ? "This changes the unit price on the PO line (PO Master). Quantity, dates and other lines are not touched."
            : kind === "ORDER"
            ? `This order has no PO line, so there is no price record yet. Saving records PO ${row.po || "(its PO number)"} in PO Master with one line for ${row.part} at this price, and links this order to it. The order itself is not changed.`
            : "This changes the unit price on the schedule (Schedule Master). Quantity, dates and status are not touched."}
        </p>
        {err && (
          <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-2.5 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{err}</span>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 items-end">
          <div>
            <span className={labelCls}>Current price</span>
            <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-sm font-semibold text-zinc-700 dark:text-zinc-300">
              {row.unitPrice ? `₹${row.unitPrice.toLocaleString("en-IN")}` : "no price"}
            </div>
          </div>
          <div>
            <label htmlFor="new-unit-price" className={labelCls}>New unit price (₹) *</label>
            <input
              id="new-unit-price" type="number" min={0} step="0.01" autoFocus value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") save(); }}
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-sm font-mono font-bold text-zinc-900 dark:text-zinc-100"
            />
          </div>
        </div>
        {valid && (
          <p className="text-[11px] text-zinc-500">
            New value for {row.qty.toLocaleString("en-IN")} pcs: <span className="font-bold text-zinc-800 dark:text-zinc-100">{inrFull(row.qty * price)}</span>
          </p>
        )}
        <div className="flex items-center gap-2 pt-1">
          <button type="button" onClick={save} disabled={saving || !changed}
            className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save price
          </button>
          <button type="button" onClick={onClose} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Cancel</button>
        </div>
      </div>
    </div>
  );
}

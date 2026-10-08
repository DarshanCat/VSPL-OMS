"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { CCErrorBanner } from "./CCErrorBanner";
import { ccErrorMessage, ccSearchWorkOrders, CCWorkOrderListItem } from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

const PAGE_SIZE = 10;

// Search-based picker over the existing OMS Work Orders (GET /api/v1/work-orders; search matches WO number,
// customer, part and PO). It only selects: it never creates or changes a Work Order.
export function CCWorkOrderSelector({ selectedWoNumber, onSelect }: {
  selectedWoNumber?: string | null; onSelect: (wo: CCWorkOrderListItem) => void;
}) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCWorkOrderListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const items = await ccSearchWorkOrders({ search: query.trim(), limit: PAGE_SIZE, offset });
      if (mine !== seq.current) return;
      setRows(items);
      setError(null);
    } catch (err) {
      if (mine === seq.current) setError(ccErrorMessage(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [query, offset]);

  useEffect(() => { void load(); }, [load]);

  const from = rows.length === 0 ? 0 : offset + 1;
  const to = offset + rows.length;

  return (
    <div className="space-y-2">
      <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setQuery(text); }} className="flex items-end gap-2">
        <div className="w-full max-w-md">
          <label className={ccLabelCls}>Search Work Order</label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1.5 h-3.5 w-3.5 text-zinc-400" />
            <input className={`${ccInputCls} pl-7`} value={text} placeholder="WO number, customer, part or PO"
              onChange={(e) => setText(e.target.value)} autoFocus />
          </div>
        </div>
        <button type="submit" className={ccSecondaryBtnCls}>Search</button>
      </form>
      <CCErrorBanner message={error} />
      <div className="overflow-x-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
        <table className="w-full text-xs">
          <thead className="bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-800/50">
            <tr>
              {["WO", "OAR", "Customer", "Part", "Grade", "WO qty", "Stage", "Status", "Delivery"].map((h) => (
                <th key={h} className="whitespace-nowrap px-3 py-2 font-semibold">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {rows.map((w) => (
              <tr key={w.id} className={`hover:bg-zinc-50 dark:hover:bg-zinc-800/30 ${w.wo_number === selectedWoNumber ? "bg-emerald-500/5" : ""}`}>
                <td className="px-3 py-1.5">
                  <button type="button" onClick={() => onSelect(w)}
                    className={`font-mono font-semibold hover:underline ${w.wo_number === selectedWoNumber ? "text-emerald-600" : "text-blue-600 dark:text-blue-400"}`}>
                    {w.wo_number}
                  </button>
                </td>
                <td className="px-3 py-1.5 font-mono">{w.oar_number ?? "-"}</td>
                <td className="px-3 py-1.5">{w.customer_code} <span className="text-zinc-400">{w.customer_name}</span></td>
                <td className="px-3 py-1.5"><span className="font-mono">{w.part_number}</span>{w.part_name ? <span className="text-zinc-400"> {w.part_name}</span> : null}</td>
                <td className="px-3 py-1.5">{w.grade ?? "-"}</td>
                <td className="px-3 py-1.5 text-right font-mono">{w.physical_wo_qty}</td>
                <td className="px-3 py-1.5 font-mono">{w.current_stage}</td>
                <td className="px-3 py-1.5">{w.status}</td>
                <td className="px-3 py-1.5 whitespace-nowrap">{w.delivery_date ?? "-"}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={9} className="px-3 py-6 text-center text-zinc-400">{loading ? "Loading..." : "No Work Orders found."}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <span>Showing {from}-{to}</span>
        <span className="flex gap-1">
          <button type="button" disabled={loading || offset <= 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="rounded-md border border-zinc-300 px-2 py-1 disabled:opacity-40 dark:border-zinc-700">Prev</button>
          {/* The endpoint returns no total, so "Next" is offered while a full page came back. */}
          <button type="button" disabled={loading || rows.length < PAGE_SIZE} onClick={() => setOffset(offset + PAGE_SIZE)}
            className="rounded-md border border-zinc-300 px-2 py-1 disabled:opacity-40 dark:border-zinc-700">Next</button>
        </span>
      </div>
    </div>
  );
}

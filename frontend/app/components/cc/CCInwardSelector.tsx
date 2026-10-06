"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { CCPagedTable, CCColumn } from "./CCPagedTable";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { ccErrorMessage, ccListInwards, CCInwardStockOut } from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls, fmtDateTime } from "@/lib/continuousCastingForm";

const PAGE_SIZE = 10;

// Search-and-select over existing inwards: GET /inwards with its inward_number contains-search. Selecting a row hands
// back the row (its inward_id is the UUID the trace endpoint needs; the number is only for people).
export function CCInwardSelector({ selectedInwardId, onSelect }: {
  selectedInwardId?: string | null; onSelect: (inward: CCInwardStockOut) => void;
}) {
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCInwardStockOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    setLoading(true);
    try {
      const page = await ccListInwards({ inward_number: query.trim(), limit: PAGE_SIZE, offset });
      if (mine !== seq.current) return;
      setRows(page.items); setTotal(page.total); setError(null);
    } catch (err) {
      if (mine === seq.current) setError(ccErrorMessage(err));
    } finally {
      if (mine === seq.current) setLoading(false);
    }
  }, [query, offset]);

  useEffect(() => { void load(); }, [load]);

  const columns: CCColumn<CCInwardStockOut>[] = [
    {
      header: "Inward no.",
      render: (r) => (
        <button type="button" onClick={() => onSelect(r)}
          className={`font-mono font-semibold hover:underline ${r.inward_id === selectedInwardId ? "text-emerald-600" : "text-blue-600 dark:text-blue-400"}`}>
          {r.inward_number}
        </button>
      ),
    },
    { header: "Material", render: (r) => <span><span className="font-mono">{r.material_code}</span><br /><span className="text-zinc-400">{r.grade} / {r.section}</span></span> },
    { header: "Dimensions", render: (r) => <span className="font-mono">{r.stock_dimension_a_mm}{r.stock_dimension_b_mm ? ` × ${r.stock_dimension_b_mm}` : ""} mm</span> },
    { header: "QA", render: (r) => <CCStatusBadge status={r.qa_status} /> },
    { header: "Received", render: (r) => fmtDateTime(r.received_at) },
    { header: "GRN", render: (r) => r.grn_reference ?? "-" },
    { header: "Units", className: "text-right font-mono", render: (r) => r.unit_count },
    { header: "Received length", className: "text-right", render: (r) => <CCLengthCell mm={r.received_total_length_mm} /> },
  ];

  return (
    <div className="space-y-2">
      <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setQuery(text); }} className="flex items-end gap-2">
        <div className="w-full max-w-md">
          <label className={ccLabelCls}>Search inward number</label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-2 top-1.5 h-3.5 w-3.5 text-zinc-400" />
            <input className={`${ccInputCls} pl-7`} value={text} placeholder="e.g. INW-000002" onChange={(e) => setText(e.target.value)} />
          </div>
        </div>
        <button type="submit" className={ccSecondaryBtnCls}>Search</button>
      </form>
      <CCPagedTable
        columns={columns} items={rows} total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset}
        rowKey={(r) => r.inward_id} loading={loading} error={error} emptyText="No inwards found."
      />
    </div>
  );
}

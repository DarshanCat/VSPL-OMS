"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  BarList, Card, Column, DataTable, EditPriceButton, ErrorBanner, inrCompact, inrFull, dmy, Kpi, Loading, MonthChart, NoAccess, PeriodTable,
  PRINT_CSS, PriceEditDialog, PriceEditRow, ReportHeader, useSalesAccess,
} from "@/app/components/sales/SalesUi";
import { downloadSalesOrderStatusExcel, getSalesOrderStatus, SalesOrderStatus, SalesSource, SalesStatusItem } from "@/lib/api";

const SOURCES: { key: SalesSource; label: string; color: string }[] = [
  { key: "OAR", label: "Accepted orders", color: "#2563eb" },
  { key: "PO_LINE", label: "PO lines without an OAR", color: "#f59e0b" },
  { key: "SCHEDULE", label: "Schedules without an OAR or PO", color: "#8b5cf6" },
];
const SOURCE_TAG: Record<string, string> = {
  OAR: "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300",
  PO_LINE: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
  SCHEDULE: "bg-violet-100 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300",
};
const SOURCE_SHORT: Record<string, string> = { OAR: "Order", PO_LINE: "PO line", SCHEDULE: "Schedule" };
const ALL: SalesSource[] = ["OAR", "PO_LINE", "SCHEDULE"];

export default function SalesOrderStatusPage() {
  const allowed = useSalesAccess();
  const [data, setData] = useState<SalesOrderStatus | null>(null);
  const [sources, setSources] = useState<SalesSource[]>(ALL);
  const [bucket, setBucket] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [editRow, setEditRow] = useState<PriceEditRow | null>(null);
  const [notice, setNotice] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getSalesOrderStatus(sources.length === 3 ? undefined : sources));
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      setError(typeof d === "string" ? d : e?.message || "Could not load the report.");
    } finally {
      setLoading(false);
    }
  }, [sources]);

  useEffect(() => {
    if (allowed) load();
  }, [allowed, load]);

  const toggleSource = (k: SalesSource) =>
    setSources((cur) => {
      const next = cur.includes(k) ? cur.filter((x) => x !== k) : [...cur, k];
      return next.length ? next : cur; // always keep one source
    });

  const download = async () => {
    setDownloading(true);
    setError("");
    try {
      await downloadSalesOrderStatusExcel(sources.length === 3 ? undefined : sources);
    } catch (e: any) {
      setError(e?.message || "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  // bucket is a month key from the chart/table, or one of the special views opened from the cards
  const items = useMemo(() => {
    if (!data) return [];
    if (!bucket) return data.items;
    if (bucket === "__overdue") return data.items.filter((i) => !!i.date && i.date < data.as_of);
    if (bucket === "__noprice") return data.items.filter((i) => !i.has_price);
    return data.items.filter((i) => i.bucket === bucket);
  }, [data, bucket]);
  const bucketLabel =
    bucket === "__overdue" ? "Overdue orders" : bucket === "__noprice" ? "Orders without price" : data?.buckets.find((b) => b.key === bucket)?.label;
  const openView = (key: string | null) => {
    setBucket(key);
    setTimeout(() => document.getElementById("open-list")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };
  const activeSeries = SOURCES.filter((s) => sources.includes(s.key));
  const chartRows = useMemo(
    () =>
      (data?.buckets || []).map((b) => ({
        key: b.key,
        label: b.label.replace(" Delivery", ""),
        ...Object.fromEntries(SOURCES.map((s) => [s.key, b.by_source?.[s.key]?.value ?? 0])),
      })),
    [data],
  );
  const columns: Column<SalesStatusItem>[] = useMemo(
    () => [
      { key: "source", label: "Source", value: (r) => SOURCE_SHORT[r.source], render: (r) => <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${SOURCE_TAG[r.source]}`}>{SOURCE_SHORT[r.source]}</span> },
      { key: "ref", label: "Reference", value: (r) => r.ref, render: (r) => <span className="font-mono font-semibold">{r.ref || "—"}</span> },
      { key: "customer", label: "Customer", value: (r) => r.customer },
      { key: "po", label: "PO / Schedule ref", value: (r) => r.po },
      { key: "part", label: "Part", value: (r) => r.part },
      { key: "qty", label: "Pending qty", align: "right", value: (r) => r.pending_qty, render: (r) => r.pending_qty.toLocaleString("en-IN") },
      { key: "price", label: "Unit price", align: "right", value: (r) => r.unit_price, render: (r) => (r.unit_price ? r.unit_price.toLocaleString("en-IN") : <span className="text-amber-600 font-semibold">no price</span>) },
      { key: "value", label: "Value", align: "right", value: (r) => r.value, render: (r) => <span className="font-bold">{inrFull(r.value)}</span> },
      { key: "date", label: "Delivery", align: "right", value: (r) => r.date, render: (r) => dmy(r.date) },
      {
        key: "edit", label: "", value: () => "", searchable: false,
        render: (r) => (
          <EditPriceButton
            target={r.price_target}
            onClick={() => r.price_target && setEditRow({ ref: r.ref, customer: r.customer, part: r.part, po: r.po, qty: r.pending_qty, unitPrice: r.unit_price, target: r.price_target })}
          />
        ),
      },
    ],
    [],
  );

  if (allowed === false) return <NoAccess title="Sales Order Status dashboard" backHref="/masters/pos" backLabel="PO Master" />;

  return (
    <AppShell>
      <style>{PRINT_CSS}</style>
      <div className="max-w-6xl mx-auto space-y-5">
        <ReportHeader
          eyebrow="Sales"
          title="Sales Order Status"
          subtitle="Open pending orders by delivery month"
          asOf={data?.as_of}
          backHref="/masters/pos"
          backLabel="PO Master"
          loading={loading}
          downloading={downloading}
          canDownload={!!data}
          onRefresh={load}
          onDownload={download}
        />
        <ErrorBanner message={error} onClose={() => setError("")} />
        {notice && (
          <div className="no-print flex items-start justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40 p-3 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
            <span>{notice}</span>
            <button type="button" aria-label="Dismiss" onClick={() => setNotice("")}>×</button>
          </div>
        )}

        {!data ? (
          <Loading />
        ) : (
          <>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <Kpi tone="hero" label="Total pending value" onClick={() => openView(null)} active={!bucket} money={data.total.value} sub={`${data.total.count.toLocaleString("en-IN")} open orders`} foot={`${data.total.qty.toLocaleString("en-IN")} pcs to deliver`} />
              <Kpi tone="red" label="Overdue" onClick={() => openView("__overdue")} active={bucket === "__overdue"} money={data.overdue.value} sub={`${data.overdue.count.toLocaleString("en-IN")} orders past delivery date`} />
              <Kpi tone="blue" label={data.buckets[0]?.label || "Due this month"} onClick={() => openView(data.buckets[0]?.key || null)} active={!!bucket && bucket === data.buckets[0]?.key} money={data.buckets[0]?.value || 0} sub={`${(data.buckets[0]?.count || 0).toLocaleString("en-IN")} orders (overdue included)`} />
              <Kpi tone="amber" label="Orders without price" onClick={() => openView("__noprice")} active={bucket === "__noprice"} count={data.no_price_count} sub={data.no_price_count ? "counted as ₹0 value" : "every order is priced"} />
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2" title="Pending value by delivery month" hint="Click a column to filter the orders below">
                <MonthChart rows={chartRows} series={activeSeries.length ? activeSeries : [SOURCES[0]]} activeKey={bucket} onSelect={setBucket} />
              </Card>
              <Card title="What is counted" hint="Choose which orders feed the report">
                <ul className="space-y-2">
                  {SOURCES.map((s) => (
                    <li key={s.key}>
                      <label className="flex cursor-pointer items-center gap-3 rounded-xl border border-zinc-200 dark:border-zinc-800 px-3 py-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/40">
                        <input type="checkbox" checked={sources.includes(s.key)} onChange={() => toggleSource(s.key)} className="h-4 w-4 accent-blue-600 no-print" />
                        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
                        <span className="flex-1 text-xs font-semibold text-zinc-800 dark:text-zinc-100">{s.label}</span>
                        <span className="text-right text-[11px] tabular-nums text-zinc-500">
                          <span className="block font-extrabold text-zinc-900 dark:text-zinc-50" title={inrFull(data.by_source[s.key].value)}>{inrCompact(data.by_source[s.key].value)}</span>
                          {data.by_source[s.key].count} orders
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2" title="Summary by period" hint="Click a row to filter the orders below">
                <PeriodTable rows={data.buckets} activeKey={bucket} onSelect={setBucket} total={data.total} />
              </Card>
              <Card title="Top customers" hint="By pending value">
                <BarList rows={data.top_customers.map((c) => ({ label: c.customer, value: c.value, sub: `${c.count} orders` }))} />
              </Card>
            </div>

            <div id="open-list" className="scroll-mt-4" />
            <DataTable
              title="Open orders"
              rows={items}
              columns={columns}
              filterLabel={bucketLabel || null}
              onClearFilter={() => setBucket(null)}
              rowKey={(r, i) => `${r.source}-${r.ref}-${i}`}
            />
          </>
        )}
      </div>
      {editRow && (
        <PriceEditDialog
          row={editRow}
          onClose={() => setEditRow(null)}
          onSaved={async (msg) => { setEditRow(null); setNotice(msg); await load(); }}
        />
      )}
    </AppShell>
  );
}

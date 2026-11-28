"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  BarList, Card, Column, DataTable, dmy, EditPriceButton, ErrorBanner, inrCompact, inrFull, Kpi, Loading, MonthChart, NoAccess, PeriodTable,
  PRINT_CSS, PriceEditDialog, PriceEditRow, ReportHeader, ShareBar, useSalesAccess,
} from "@/app/components/sales/SalesUi";
import { downloadScheduleStatusExcel, getScheduleStatus, ScheduleStatus, ScheduleStatusItem } from "@/lib/api";

const STATUS_STYLE: Record<string, { badge: string; dot: string }> = {
  scheduled: { badge: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300", dot: "#71717a" },
  awaiting_po: { badge: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300", dot: "#f59e0b" },
  po_received: { badge: "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300", dot: "#2563eb" },
  matched: { badge: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300", dot: "#10b981" },
  cancelled: { badge: "bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300", dot: "#f43f5e" },
};
const STATUS_LABEL: Record<string, string> = {
  scheduled: "Scheduled", awaiting_po: "Awaiting PO", po_received: "PO received", matched: "Matched", cancelled: "Cancelled",
};

export default function ScheduleStatusPage() {
  const allowed = useSalesAccess();
  const [data, setData] = useState<ScheduleStatus | null>(null);
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
      setData(await getScheduleStatus());
    } catch (e: any) {
      const d = e?.response?.data?.detail;
      setError(typeof d === "string" ? d : e?.message || "Could not load the report.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (allowed) load();
  }, [allowed, load]);

  const download = async () => {
    setDownloading(true);
    setError("");
    try {
      await downloadScheduleStatusExcel();
    } catch (e: any) {
      setError(e?.message || "Download failed.");
    } finally {
      setDownloading(false);
    }
  };

  const items = useMemo(() => {
    if (!data) return [];
    if (!bucket) return data.items;
    if (bucket === "__overdue") return data.items.filter((i) => !!i.date && i.date < data.as_of);
    if (bucket === "__awaiting") return data.items.filter((i) => i.status === "awaiting_po");
    if (bucket === "__noprice") return data.items.filter((i) => !i.has_price);
    return data.items.filter((i) => i.bucket === bucket);
  }, [data, bucket]);
  const bucketLabel =
    bucket === "__overdue" ? "Overdue schedules" : bucket === "__awaiting" ? "Awaiting PO" : bucket === "__noprice" ? "Schedules without price"
      : data?.buckets.find((b) => b.key === bucket)?.label;
  const openView = (key: string | null) => {
    setBucket(key);
    setTimeout(() => document.getElementById("open-list")?.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  };
  const chartRows = useMemo(() => (data?.buckets || []).map((b) => ({ key: b.key, label: b.label.replace(" Delivery", ""), value: b.value })), [data]);
  const statusTotal = useMemo(() => (data?.status_split || []).reduce((a, s) => a + s.count, 0), [data]);

  const columns: Column<ScheduleStatusItem>[] = useMemo(
    () => [
      { key: "schedule", label: "Schedule", value: (r) => r.schedule, render: (r) => <span className="font-mono font-semibold">{r.schedule}</span> },
      { key: "customer", label: "Customer", value: (r) => r.customer },
      { key: "ref", label: "Customer ref", value: (r) => r.customer_ref },
      { key: "part", label: "Part", value: (r) => r.part },
      { key: "qty", label: "Qty", align: "right", value: (r) => r.qty, render: (r) => r.qty.toLocaleString("en-IN") },
      { key: "price", label: "Unit price", align: "right", value: (r) => r.unit_price, render: (r) => (r.unit_price ? r.unit_price.toLocaleString("en-IN") : <span className="text-amber-600 font-semibold">no price</span>) },
      { key: "value", label: "Value", align: "right", value: (r) => r.value, render: (r) => <span className="font-bold">{inrFull(r.value)}</span> },
      { key: "status", label: "Status", value: (r) => STATUS_LABEL[r.status] || r.status, render: (r) => <span className={`rounded-md px-1.5 py-0.5 text-[10px] font-bold ${STATUS_STYLE[r.status]?.badge || ""}`}>{STATUS_LABEL[r.status] || r.status}</span> },
      { key: "date", label: "Required", align: "right", value: (r) => r.date, render: (r) => dmy(r.date) },
      {
        key: "edit", label: "", value: () => "", searchable: false,
        render: (r) => (
          <EditPriceButton
            target={r.price_target}
            onClick={() => r.price_target && setEditRow({ ref: r.schedule, customer: r.customer, part: r.part, qty: r.qty, unitPrice: r.unit_price, target: r.price_target })}
          />
        ),
      },
    ],
    [],
  );

  if (allowed === false) return <NoAccess title="Customer Schedule Status dashboard" backHref="/masters/schedules" backLabel="Schedule Master" />;

  return (
    <AppShell>
      <style>{PRINT_CSS}</style>
      <div className="max-w-6xl mx-auto space-y-5">
        <ReportHeader
          eyebrow="Sales"
          title="Customer Schedule Status"
          subtitle="Schedules not yet converted to an order, by required month"
          asOf={data?.as_of}
          backHref="/masters/schedules"
          backLabel="Schedule Master"
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
              <Kpi tone="hero" label="Open schedule value" onClick={() => openView(null)} active={!bucket} money={data.total.value} sub={`${data.total.count.toLocaleString("en-IN")} open schedules`} foot={`${data.total.qty.toLocaleString("en-IN")} pcs scheduled`} />
              <Kpi tone="amber" label="Awaiting PO" onClick={() => openView("__awaiting")} active={bucket === "__awaiting"} money={data.awaiting_po.value} sub={`${data.awaiting_po.count.toLocaleString("en-IN")} schedules without a PO`} />
              <Kpi tone="red" label="Overdue" onClick={() => openView("__overdue")} active={bucket === "__overdue"} money={data.overdue.value} sub={`${data.overdue.count.toLocaleString("en-IN")} schedules past required date`} />
              <Kpi tone="neutral" label="Schedules without price" onClick={() => openView("__noprice")} active={bucket === "__noprice"} count={data.no_price_count} sub={data.no_price_count ? "counted as ₹0 value" : "every schedule is priced"} />
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2" title="Schedule value by required month" hint="Click a column to filter the schedules below">
                <MonthChart rows={chartRows} series={[{ key: "value", label: "Schedule value", color: "#2563eb" }]} activeKey={bucket} onSelect={setBucket} />
              </Card>
              <Card title="By status" hint="All schedules, including converted and cancelled">
                <ul className="space-y-3">
                  {data.status_split.map((s) => (
                    <li key={s.status}>
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="inline-flex items-center gap-2 font-semibold text-zinc-800 dark:text-zinc-100">
                          <span className="h-2.5 w-2.5 rounded-sm" style={{ background: STATUS_STYLE[s.status]?.dot }} /> {s.label}
                        </span>
                        <span className="whitespace-nowrap tabular-nums text-zinc-500">
                          <b className="text-zinc-900 dark:text-zinc-50" title={inrFull(s.value)}>{inrCompact(s.value)}</b> · {s.count}
                        </span>
                      </div>
                      <div className="mt-1"><ShareBar pct={statusTotal ? (s.count / statusTotal) * 100 : 0} color={STATUS_STYLE[s.status]?.dot} /></div>
                    </li>
                  ))}
                </ul>
              </Card>
            </div>

            <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
              <Card className="lg:col-span-2" title="Summary by period" hint="Click a row to filter the schedules below">
                <PeriodTable rows={data.buckets} activeKey={bucket} onSelect={setBucket} total={data.total} countLabel="Schedules" />
              </Card>
              <Card title="Top customers" hint="By open schedule value">
                <BarList rows={data.top_customers.map((c) => ({ label: c.customer, value: c.value, sub: `${c.count} schedules` }))} />
              </Card>
            </div>

            <div id="open-list" className="scroll-mt-4" />
            <DataTable
              title="Open schedules"
              rows={items}
              columns={columns}
              filterLabel={bucketLabel || null}
              onClearFilter={() => setBucket(null)}
              rowKey={(r, i) => `${r.schedule}-${i}`}
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

"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getMasterCustomers, getSchedules, createSchedule, MasterCustomer, ScheduleOut } from "@/lib/api";
import { CalendarClock, AlertTriangle, FileSpreadsheet } from "lucide-react";

const STATUS_STYLES: Record<string, string> = {
  scheduled: "bg-zinc-200 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  awaiting_po: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400",
  po_received: "bg-blue-100 text-blue-700 dark:bg-blue-950/50 dark:text-blue-400",
  matched: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400",
  cancelled: "bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-400",
};

function statusLabel(s: string) {
  return s.split("_").map((w) => w[0]?.toUpperCase() + w.slice(1)).join(" ");
}

export default function ScheduleMasterPage() {
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [schedules, setSchedules] = useState<ScheduleOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [customerCode, setCustomerCode] = useState("");
  const [partNumber, setPartNumber] = useState("");
  const [scheduledQty, setScheduledQty] = useState("");
  const [requiredDate, setRequiredDate] = useState("");
  const [customerScheduleRef, setCustomerScheduleRef] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  async function loadAll() {
    setLoading(true);
    setListError("");
    try {
      const [c, s] = await Promise.all([getMasterCustomers(), getSchedules()]);
      setCustomers(c);
      setSchedules(s);
      if (!customerCode && c.length) setCustomerCode(c[0].customer_code);
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load schedule data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      await createSchedule({
        customer_code: customerCode,
        part_number: partNumber,
        scheduled_qty: Number(scheduledQty),
        required_date: requiredDate || undefined,
        customer_schedule_ref: customerScheduleRef || undefined,
      });
      setPartNumber("");
      setScheduledQty("");
      setRequiredDate("");
      setCustomerScheduleRef("");
      await loadAll();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Could not create schedule.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-6">
        <div>
          <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
            Masters
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Schedule Master
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Forecast/planned demand a customer has not yet released a PO for. A schedule is never
            treated as a confirmed PO — see PO Matching to link a PO once received.
          </p>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <CalendarClock className="h-4 w-4 text-blue-500" /> Add Schedule
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <select required value={customerCode} onChange={(e) => setCustomerCode(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs">
              <option value="" disabled>Select customer</option>
              {customers.map((c) => (
                <option key={c.id} value={c.customer_code}>{c.customer_code} — {c.name}</option>
              ))}
            </select>
            <input required placeholder="Part number" value={partNumber} onChange={(e) => setPartNumber(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <input required type="number" min={1} placeholder="Scheduled qty" value={scheduledQty}
              onChange={(e) => setScheduledQty(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <input type="date" value={requiredDate} onChange={(e) => setRequiredDate(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <input placeholder="Customer schedule reference" value={customerScheduleRef}
              onChange={(e) => setCustomerScheduleRef(e.target.value)}
              className="md:col-span-2 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <button type="submit" disabled={creating}
              className="md:col-span-3 justify-self-end rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors">
              {creating ? "Creating..." : "Add Schedule"}
            </button>
          </form>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-zinc-500" />
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing Schedules</h3>
          </div>
          {listError && (
            <div className="m-4 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{listError}</span>
            </div>
          )}
          {loading ? (
            <div className="p-4 text-xs text-zinc-500">Loading...</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold">Schedule #</th>
                  <th className="text-left px-4 py-2 font-semibold">Customer</th>
                  <th className="text-left px-4 py-2 font-semibold">Part</th>
                  <th className="text-right px-4 py-2 font-semibold">Qty</th>
                  <th className="text-left px-4 py-2 font-semibold">Required Date</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-left px-4 py-2 font-semibold">Linked OAR</th>
                </tr>
              </thead>
              <tbody>
                {schedules.map((s) => (
                  <tr key={s.id} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-4 py-2 font-mono">{s.schedule_number}</td>
                    <td className="px-4 py-2">{s.customer_code} — {s.customer_name}</td>
                    <td className="px-4 py-2 font-mono">{s.part_number}</td>
                    <td className="px-4 py-2 text-right">{s.scheduled_qty}</td>
                    <td className="px-4 py-2">{s.required_date || "-"}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${STATUS_STYLES[s.po_status] || ""}`}>
                        {statusLabel(s.po_status)}
                      </span>
                    </td>
                    <td className="px-4 py-2 font-mono">{s.linked_oar_number || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </AppShell>
  );
}

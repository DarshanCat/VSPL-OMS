"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, GanttChartSquare, Loader2, RefreshCw, X } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getSetupDetail, listSetups, planningErrorText, PlanGate, PlanWorkOrder, SetupDetail, SetupSummary, updateWorkOrderPlan,
} from "@/lib/api";
import { fmtDay, fmtDayYear, gateTone, GateTone, PlanStatusChip, TONE_LABEL } from "@/app/components/planning/PlanUi";

// Planning table (SAP PP style): work orders as rows grouped under their setup, a fixed left block of
// order data, and one bar per gate on a day scale to the right. Reads the same setup data as the Setups
// page and saves through the same plan endpoint (with a reason), so nothing new is stored.

const DAY_W = 30;            // px per day
const LEFT_W = 400;          // px of the fixed order columns
const ROW_H = 44;

const BAR: Record<GateTone, string> = {
  done: "bg-emerald-500 border-emerald-700 text-white",
  prog: "bg-blue-500 border-blue-700 text-white",
  late: "bg-rose-500 border-rose-700 text-white",
  risk: "bg-amber-400 border-amber-600 text-amber-950",
  plan: "bg-slate-300 border-slate-500 text-slate-900 dark:bg-slate-600 dark:border-slate-400 dark:text-white",
  none: "",
};

const toDay = (iso: string) => Math.round(Date.parse(`${iso}T00:00:00Z`) / 86400000);
const fromDay = (n: number) => new Date(n * 86400000);
const iso = (n: number) => fromDay(n).toISOString().slice(0, 10);

interface Block { setup: SetupDetail["setup"]; wos: PlanWorkOrder[] }

export default function PlanningTablePage() {
  const [setups, setSetups] = useState<SetupSummary[]>([]);
  const [pick, setPick] = useState<string>("ALL");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [edit, setEdit] = useState<{ wo: PlanWorkOrder; gate: PlanGate; closed: boolean } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const open = await listSetups("OPEN");
      setSetups(open);
      const chosen = pick === "ALL" ? open.slice(0, 25) : open.filter((s) => s.setup_number === pick);
      const details = await Promise.all(chosen.map((s) => getSetupDetail(s.setup_number)));
      setBlocks(details.map((d) => ({ setup: d.setup, wos: d.work_orders })));
    } catch (err: any) {
      setError(planningErrorText(err, "Could not load the planning table."));
    } finally {
      setLoading(false);
    }
  }, [pick]);

  useEffect(() => { load(); }, [load]);

  const today = toDay(new Date().toISOString().slice(0, 10));

  // Visible day range: earliest gate start to latest gate end / commitment, with a margin.
  const [minD, maxD] = useMemo(() => {
    const days: number[] = [today];
    blocks.forEach((b) => b.wos.forEach((w) => {
      if (w.commitment_date) days.push(toDay(w.commitment_date));
      w.gates.forEach((g) => {
        if (g.planned_start) days.push(toDay(g.planned_start));
        if (g.planned_end) days.push(toDay(g.planned_end));
      });
    }));
    return [Math.min(...days) - 3, Math.max(...days) + 4];
  }, [blocks, today]);

  const nDays = maxD - minD + 1;
  const gridW = nDays * DAY_W;
  const x = (d: number) => (d - minD) * DAY_W;

  const dayCells = useMemo(() => Array.from({ length: nDays }, (_, i) => minD + i), [nDays, minD]);
  const monthSpans = useMemo(() => {
    const out: { label: string; start: number; len: number }[] = [];
    dayCells.forEach((d, i) => {
      const dt = fromDay(d);
      const label = dt.toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
      const last = out[out.length - 1];
      if (last && last.label === label) last.len += 1; else out.push({ label, start: i, len: 1 });
    });
    return out;
  }, [dayCells]);

  const totalWos = blocks.reduce((n, b) => n + b.wos.length, 0);

  return (
    <AppShell>
      <div className="max-w-[1500px] mx-auto space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-orange-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">PPC</span>
              <span className="text-xs text-zinc-400">Planning &amp; Scheduling</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1 flex items-center gap-2">
              <GanttChartSquare className="h-6 w-6 text-orange-500" /> Planning Table
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5 max-w-2xl">
              Work orders by setup with one bar per gate. Click a bar to change its dates (a reason is needed and goes in the change log).
            </p>
          </div>
          <div className="flex items-center gap-2">
            <label htmlFor="pt-setup" className="sr-only">Setup</label>
            <select id="pt-setup" value={pick} onChange={(e) => setPick(e.target.value)}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-200">
              <option value="ALL">All open setups</option>
              {setups.map((s) => <option key={s.setup_number} value={s.setup_number}>{s.setup_number}</option>)}
            </select>
            <button type="button" onClick={load}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800">
              <RefreshCw className="h-3.5 w-3.5" /> Refresh
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-[11px] text-zinc-500 dark:text-zinc-400">
          {(["done", "prog", "plan", "risk", "late"] as GateTone[]).map((t) => (
            <span key={t} className="inline-flex items-center gap-1.5">
              <span className={`inline-block h-3 w-5 rounded-sm border ${BAR[t]}`} /> {TONE_LABEL[t]}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5"><span className="inline-block h-3 w-0.5 bg-red-500" /> today</span>
          <span className="inline-flex items-center gap-1.5"><span className="inline-block h-2.5 w-2.5 rotate-45 bg-violet-600" /> commitment date</span>
        </div>

        {notice && (
          <div className="flex items-start justify-between gap-2 rounded-xl border border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40 p-2.5 text-xs font-semibold text-emerald-800 dark:text-emerald-300">
            <span>{notice}</span>
            <button type="button" aria-label="Dismiss" onClick={() => setNotice("")}><X className="h-3.5 w-3.5" /></button>
          </div>
        )}

        {error ? (
          <div className="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-4 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center gap-2 p-10 text-xs text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Loading planning table...</div>
        ) : totalWos === 0 ? (
          <div className="rounded-2xl border border-dashed border-zinc-300 dark:border-zinc-700 p-10 text-center text-xs text-zinc-500">
            No work orders in the open setups yet. <Link href="/planning/setups" className="font-bold text-orange-700 hover:underline">Open Setups</Link> to create one.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900">
            <div style={{ width: LEFT_W + gridW }}>
              {/* header */}
              <div className="flex sticky top-0 z-20 border-b border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800 text-[10px] font-extrabold uppercase tracking-wider text-zinc-600 dark:text-zinc-300">
                <div className="sticky left-0 z-30 flex items-end bg-zinc-100 dark:bg-zinc-800 border-r border-zinc-300 dark:border-zinc-700" style={{ width: LEFT_W, minWidth: LEFT_W }}>
                  <div className="w-[120px] px-3 py-2">Work order</div>
                  <div className="flex-1 px-2 py-2">Part</div>
                  <div className="w-[44px] px-1 py-2 text-right">Qty</div>
                  <div className="w-[86px] px-2 py-2">Status</div>
                </div>
                <div style={{ width: gridW }}>
                  <div className="flex border-b border-zinc-300 dark:border-zinc-700">
                    {monthSpans.map((m) => (
                      <div key={m.label + m.start} style={{ width: m.len * DAY_W }} className="px-2 py-1 border-r border-zinc-300 dark:border-zinc-700 truncate">{m.label}</div>
                    ))}
                  </div>
                  <div className="flex">
                    {dayCells.map((d) => (
                      <div key={d} style={{ width: DAY_W }}
                        className={`py-1 text-center border-r border-zinc-200 dark:border-zinc-700 ${d === today ? "bg-red-500 text-white" : ""}`}>
                        {fromDay(d).getUTCDate()}
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {blocks.map((b) => (
                <div key={b.setup.setup_number}>
                  {/* setup group row */}
                  <div className="flex border-b border-zinc-200 dark:border-zinc-800 bg-sky-50 dark:bg-sky-950/30">
                    <div className="sticky left-0 z-10 flex items-center gap-2 px-3 py-1.5 bg-sky-50 dark:bg-sky-950/30 text-xs" style={{ width: LEFT_W, minWidth: LEFT_W }}>
                      <Link href={`/planning/setups/${encodeURIComponent(b.setup.setup_number)}`} className="font-mono font-extrabold text-sky-800 dark:text-sky-300 hover:underline">{b.setup.setup_number}</Link>
                      <span className="text-zinc-500">{fmtDayYear(b.setup.setup_date)}</span>
                      <span className="text-zinc-500">· {b.wos.length} WO</span>
                    </div>
                    <div style={{ width: gridW }} />
                  </div>

                  {b.wos.map((w) => (
                    <div key={w.wo_number} className="flex border-b border-zinc-100 dark:border-zinc-800/60 hover:bg-zinc-50/60 dark:hover:bg-zinc-800/20" style={{ height: ROW_H }}>
                      <div className="sticky left-0 z-10 flex items-center bg-white dark:bg-zinc-900 border-r border-zinc-200 dark:border-zinc-800 text-xs" style={{ width: LEFT_W, minWidth: LEFT_W }}>
                        <div className="w-[120px] px-3 font-mono font-extrabold text-zinc-900 dark:text-zinc-100 truncate" title={w.wo_number}>{w.wo_number}</div>
                        <div className="flex-1 px-2 truncate text-zinc-600 dark:text-zinc-300" title={`${w.part_number || ""} ${w.part_name || ""}`}>{w.part_number || "—"}</div>
                        <div className="w-[44px] px-1 text-right font-semibold">{w.qty}</div>
                        <div className="w-[86px] px-2"><PlanStatusChip status={w.plan_status} text={w.plan_text} compact /></div>
                      </div>
                      <div className="relative" style={{ width: gridW }}>
                        {/* today line */}
                        <div className="absolute top-0 bottom-0 w-0.5 bg-red-500/70 z-[1]" style={{ left: x(today) + DAY_W / 2 }} />
                        {/* commitment flag */}
                        {w.commitment_date && (
                          <div className="absolute z-[3]" style={{ left: x(toDay(w.commitment_date)) + DAY_W / 2 - 6, top: ROW_H / 2 - 6 }}
                            title={`Commitment ${fmtDay(w.commitment_date)}`}>
                            <div className="h-3 w-3 rotate-45 bg-violet-600 border border-white dark:border-zinc-900" />
                          </div>
                        )}
                        {w.gates.map((g) => {
                          const end = g.planned_end ? toDay(g.planned_end) : null;
                          if (end === null) return null;
                          const start = g.planned_start ? toDay(g.planned_start) : end;
                          const left = x(Math.min(start, end));
                          const width = (Math.abs(end - start) + 1) * DAY_W;
                          const tone = gateTone(g);
                          return (
                            <button key={g.stage} type="button"
                              onClick={() => setEdit({ wo: w, gate: g, closed: b.setup.status === "CLOSED" })}
                              title={`${g.stage}: ${fmtDay(g.planned_start)} to ${fmtDay(g.planned_end)} · ${TONE_LABEL[tone]}${g.flag === "LATE" ? ` +${g.days_late}d` : ""}`}
                              className={`absolute z-[2] h-6 rounded border text-[10px] font-extrabold leading-none flex items-center justify-center overflow-hidden whitespace-nowrap shadow-sm hover:brightness-95 ${BAR[tone]}`}
                              style={{ left: left + 1, width: width - 2, top: (ROW_H - 24) / 2 }}>
                              {g.stage}
                            </button>
                          );
                        })}
                        {w.gates.every((g) => !g.planned_end) && (
                          <div className="absolute inset-y-0 flex items-center px-3 text-[11px] italic text-zinc-400" style={{ left: x(today) + 8 }}>no gate dates yet</div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {edit && (
        <EditGate
          wo={edit.wo} gate={edit.gate} closed={edit.closed}
          onClose={() => setEdit(null)}
          onSaved={async (msg) => { setEdit(null); setNotice(msg); await load(); }}
        />
      )}
    </AppShell>
  );
}

function EditGate({ wo, gate, closed, onClose, onSaved }: {
  wo: PlanWorkOrder; gate: PlanGate; closed: boolean; onClose: () => void; onSaved: (msg: string) => void | Promise<void>;
}) {
  const [start, setStart] = useState(gate.planned_start || "");
  const [end, setEnd] = useState(gate.planned_end || "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");

  const inputCls = "w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-sm text-zinc-900 dark:text-zinc-100 disabled:opacity-60";
  const labelCls = "block text-[11px] font-bold uppercase tracking-wider text-zinc-600 dark:text-zinc-400 mb-1";

  const save = async () => {
    setErr("");
    if (!end) { setErr("Enter the end date."); return; }
    if (start && start > end) { setErr("The start date cannot be after the end date."); return; }
    if (start === (gate.planned_start || "") && end === (gate.planned_end || "")) { setErr("Nothing changed."); return; }
    if (reason.trim().length < 3) { setErr("Give a short reason (it goes in the change log)."); return; }
    setSaving(true);
    try {
      const res = await updateWorkOrderPlan(wo.wo_number, {
        gates: [{ stage: gate.stage, planned_start: start || null, planned_end: end }],
        reason: reason.trim(),
        expected_plan_version: wo.plan_version,
      });
      await onSaved(`${wo.wo_number} ${gate.stage} saved.${res.warnings.length ? " " + res.warnings.map((w) => w.message).join(" ") : ""}`);
    } catch (e: any) {
      setErr(planningErrorText(e, "Could not save the plan."));
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-label={`Change ${gate.stage} dates`}>
      <div className="w-full max-w-md rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 space-y-3 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h2 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">{wo.wo_number} · {gate.stage}</h2>
            <p className="text-[11px] text-zinc-500">{wo.part_number || ""} · {wo.qty} pcs{wo.commitment_date ? ` · commitment ${fmtDay(wo.commitment_date)}` : ""}</p>
          </div>
          <button type="button" aria-label="Close" onClick={onClose}><X className="h-4 w-4 text-zinc-500" /></button>
        </div>
        {closed && <div className="rounded-xl bg-zinc-100 dark:bg-zinc-800 p-2 text-xs text-zinc-600 dark:text-zinc-300">This setup is closed, so dates cannot be changed.</div>}
        {err && (
          <div className="flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-2.5 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{err}</span>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label htmlFor="pt-start" className={labelCls}>Start</label>
            <input id="pt-start" type="date" value={start} onChange={(e) => setStart(e.target.value)} disabled={closed} className={inputCls} />
          </div>
          <div>
            <label htmlFor="pt-end" className={labelCls}>End *</label>
            <input id="pt-end" type="date" value={end} onChange={(e) => setEnd(e.target.value)} disabled={closed} className={inputCls} />
          </div>
        </div>
        <div>
          <label htmlFor="pt-reason" className={labelCls}>Reason *</label>
          <input id="pt-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} disabled={closed} className={inputCls} placeholder="e.g. Furnace breakdown, moved by 2 days" />
        </div>
        <div className="flex items-center gap-2 pt-1">
          <button type="button" onClick={save} disabled={saving || closed}
            className="inline-flex items-center gap-1.5 rounded-xl bg-orange-600 hover:bg-orange-500 disabled:opacity-60 px-4 py-2 text-xs font-bold text-white">
            {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Save dates
          </button>
          <button type="button" onClick={onClose} className="rounded-xl px-3 py-2 text-xs font-bold text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800">Cancel</button>
        </div>
      </div>
    </div>
  );
}

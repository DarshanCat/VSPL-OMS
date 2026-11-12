"use client";

import React, { useMemo, useState } from "react";
import {
  BarChart3,
  Clock,
  Flame,
  Layers,
  ChevronDown,
  ChevronUp,
  X,
  TrendingUp,
  Package,
} from "lucide-react";

export interface RejectionRecordItem {
  nc_number: string;
  wo_number: string;
  oar_number?: string | null;
  customer_code?: string | null;
  customer_name?: string | null;
  part_number?: string | null;
  stage?: string | null;
  source_type: string;
  qty: number;
  consumed_qty: number;
  remaining_qty: number;
  reason?: string | null;
  status: string;
  disposition?: string | null;
  date_raised: string;
}

interface Props {
  records: RejectionRecordItem[];
  selectedStage: string;
  onSelectStage: (stage: string) => void;
  selectedReason: string;
  onSelectReason: (reason: string) => void;
  lastUpdatedAt: Date | null;
}

type MetricMode = "qty" | "count";

function formatISTTimestamp(iso: string | Date | null | undefined): string {
  if (!iso) return "—";
  const d = typeof iso === "string" ? new Date(iso) : iso;
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
    timeZone: "Asia/Kolkata",
  });
}

function toISTDateKey(iso: string): { key: string; label: string } {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return { key: "unknown", label: "Unknown" };
  const parts = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    timeZone: "Asia/Kolkata",
  }).formatToParts(d);
  const y = parts.find((p) => p.type === "year")?.value ?? "0000";
  const m = parts.find((p) => p.type === "month")?.value ?? "00";
  const day = parts.find((p) => p.type === "day")?.value ?? "00";
  const key = `${y}-${m}-${day}`;
  const label = d.toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    timeZone: "Asia/Kolkata",
  });
  return { key, label };
}

export function RejectionAnalyticsDashboard({
  records,
  selectedStage,
  onSelectStage,
  selectedReason,
  onSelectReason,
  lastUpdatedAt,
}: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const [metric, setMetric] = useState<MetricMode>("qty");

  const analytics = useMemo(() => {
    const totalQty = records.reduce((s, r) => s + (Number(r.qty) || 0), 0);
    const totalCount = records.length;

    // 1. By Area / Stage
    const stageMap = new Map<
      string,
      {
        stage: string;
        qty: number;
        count: number;
        remaining: number;
        reasons: Map<string, number>;
      }
    >();

    // 2. By Defect / Reason
    const reasonMap = new Map<
      string,
      {
        reason: string;
        qty: number;
        count: number;
        stages: Set<string>;
      }
    >();

    // 3. By Date (IST)
    const dateMap = new Map<
      string,
      { key: string; label: string; qty: number; count: number }
    >();

    // 4. By Part
    const partMap = new Map<
      string,
      { part: string; qty: number; count: number; topStage: string; topReason: string }
    >();

    let latestRecord: RejectionRecordItem | null = null;

    for (const r of records) {
      const qty = Number(r.qty) || 0;
      const rem = Number(r.remaining_qty) || 0;
      const stage = (r.stage || "UNASSIGNED").trim() || "UNASSIGNED";
      const reason = (r.reason || "Unspecified").trim() || "Unspecified";
      const part = (r.part_number || "Unknown").trim() || "Unknown";

      if (
        !latestRecord ||
        new Date(r.date_raised).getTime() > new Date(latestRecord.date_raised).getTime()
      ) {
        latestRecord = r;
      }

      // Stage aggregation
      const st = stageMap.get(stage) || {
        stage,
        qty: 0,
        count: 0,
        remaining: 0,
        reasons: new Map<string, number>(),
      };
      st.qty += qty;
      st.count += 1;
      st.remaining += rem;
      st.reasons.set(reason, (st.reasons.get(reason) || 0) + (metric === "qty" ? qty : 1));
      stageMap.set(stage, st);

      // Reason aggregation
      const rs = reasonMap.get(reason) || {
        reason,
        qty: 0,
        count: 0,
        stages: new Set<string>(),
      };
      rs.qty += qty;
      rs.count += 1;
      rs.stages.add(stage);
      reasonMap.set(reason, rs);

      // Date aggregation
      const { key, label } = toISTDateKey(r.date_raised);
      const dt = dateMap.get(key) || { key, label, qty: 0, count: 0 };
      dt.qty += qty;
      dt.count += 1;
      dateMap.set(key, dt);

      // Part aggregation
      const pt = partMap.get(part) || {
        part,
        qty: 0,
        count: 0,
        topStage: stage,
        topReason: reason,
      };
      pt.qty += qty;
      pt.count += 1;
      partMap.set(part, pt);
    }

    const totalMetric = metric === "qty" ? totalQty : totalCount;

    const stages = Array.from(stageMap.values())
      .map((s) => {
        const val = metric === "qty" ? s.qty : s.count;
        const pct = totalMetric > 0 ? (val / totalMetric) * 100 : 0;
        let topReason = "—";
        let topReasonVal = -1;
        s.reasons.forEach((v, k) => {
          if (v > topReasonVal) {
            topReasonVal = v;
            topReason = k;
          }
        });
        return { ...s, val, pct, topReason };
      })
      .sort((a, b) => b.val - a.val || b.qty - a.qty);

    let runningPct = 0;
    const reasons = Array.from(reasonMap.values())
      .map((r) => {
        const val = metric === "qty" ? r.qty : r.count;
        const pct = totalMetric > 0 ? (val / totalMetric) * 100 : 0;
        return { ...r, val, pct, stageList: Array.from(r.stages) };
      })
      .sort((a, b) => b.val - a.val || b.qty - a.qty)
      .map((r) => {
        runningPct = Math.min(100, runningPct + r.pct);
        return { ...r, cumPct: runningPct };
      });

    const timeline = Array.from(dateMap.values()).sort((a, b) =>
      a.key.localeCompare(b.key)
    );
    const maxTimelineVal = timeline.reduce(
      (m, d) => Math.max(m, metric === "qty" ? d.qty : d.count),
      0
    );
    const peakDay =
      timeline.length > 0
        ? [...timeline].sort(
            (a, b) => (metric === "qty" ? b.qty - a.qty : b.count - a.count)
          )[0]
        : null;

    const parts = Array.from(partMap.values())
      .map((p) => ({
        ...p,
        val: metric === "qty" ? p.qty : p.count,
        pct: totalMetric > 0 ? ((metric === "qty" ? p.qty : p.count) / totalMetric) * 100 : 0,
      }))
      .sort((a, b) => b.val - a.val || b.qty - a.qty)
      .slice(0, 6);

    return {
      totalQty,
      totalCount,
      totalMetric,
      stages,
      reasons,
      timeline,
      maxTimelineVal,
      peakDay,
      parts,
      latestRecord,
    };
  }, [records, metric]);

  const topStage = analytics.stages[0];
  const topReason = analytics.reasons[0];

  return (
    <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
      {/* Dashboard Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/70 dark:bg-zinc-950/60">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-xl bg-rose-500/10 text-rose-600 flex items-center justify-center">
            <BarChart3 className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-extrabold text-zinc-900 dark:text-zinc-100">
                Rejection Hotspot &amp; Defect Analytics
              </h2>
              <span className="inline-flex items-center gap-1 rounded-full bg-zinc-200/70 dark:bg-zinc-800 px-2 py-0.5 text-[10px] font-bold text-zinc-600 dark:text-zinc-300">
                {analytics.totalCount} NCs · {analytics.totalQty} pcs
              </span>
            </div>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400 flex items-center gap-1.5 mt-0.5">
              <Clock className="h-3 w-3 text-zinc-400" />
              <span>
                Updated: {formatISTTimestamp(lastUpdatedAt)} IST
                {analytics.latestRecord
                  ? ` · Latest NC (${analytics.latestRecord.nc_number}): ${formatISTTimestamp(
                      analytics.latestRecord.date_raised
                    )}`
                  : ""}
              </span>
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Active filter pills */}
          {selectedStage && (
            <button
              onClick={() => onSelectStage("")}
              className="inline-flex items-center gap-1 rounded-lg bg-rose-500/10 border border-rose-500/30 px-2 py-1 text-[11px] font-bold text-rose-600 hover:bg-rose-500/20 cursor-pointer"
            >
              <span>Stage: {selectedStage}</span>
              <X className="h-3 w-3" />
            </button>
          )}
          {selectedReason && (
            <button
              onClick={() => onSelectReason("")}
              className="inline-flex items-center gap-1 rounded-lg bg-amber-500/10 border border-amber-500/30 px-2 py-1 text-[11px] font-bold text-amber-600 hover:bg-amber-500/20 cursor-pointer"
            >
              <span>Defect: {selectedReason}</span>
              <X className="h-3 w-3" />
            </button>
          )}

          {/* Metric toggle */}
          <div className="inline-flex rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-0.5">
            <button
              type="button"
              onClick={() => setMetric("qty")}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-colors cursor-pointer ${
                metric === "qty"
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              }`}
            >
              Qty (pcs)
            </button>
            <button
              type="button"
              onClick={() => setMetric("count")}
              className={`px-2.5 py-1 rounded-lg text-[11px] font-bold transition-colors cursor-pointer ${
                metric === "count"
                  ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                  : "text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200"
              }`}
            >
              NC Count
            </button>
          </div>

          <button
            type="button"
            onClick={() => setCollapsed((c) => !c)}
            className="inline-flex items-center gap-1 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-2.5 py-1.5 text-[11px] font-bold text-zinc-600 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 cursor-pointer"
          >
            {collapsed ? (
              <>
                <span>Expand</span>
                <ChevronDown className="h-3.5 w-3.5" />
              </>
            ) : (
              <>
                <span>Collapse</span>
                <ChevronUp className="h-3.5 w-3.5" />
              </>
            )}
          </button>
        </div>
      </div>

      {!collapsed && (
        <div className="p-4 space-y-4">
          {records.length === 0 ? (
            <div className="py-8 text-center text-xs text-zinc-400">
              No rejection records in the selected timeframe/filter to analyze.
            </div>
          ) : (
            <>
              {/* Top Hotspot Callouts */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
                <div className="rounded-xl border border-rose-500/20 bg-rose-500/5 p-3.5 flex items-start justify-between gap-2">
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600 flex items-center gap-1">
                      <Layers className="h-3 w-3" /> Highest Rejection Area
                    </span>
                    <p className="text-lg font-black font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                      {topStage ? topStage.stage : "—"}
                    </p>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {topStage
                        ? `${topStage.qty} pcs (${topStage.pct.toFixed(1)}%) · ${topStage.count} NC(s)`
                        : "No stage data"}
                    </p>
                  </div>
                  {topStage && (
                    <span className="rounded-lg bg-rose-600 text-white px-2 py-0.5 text-[10px] font-extrabold font-mono">
                      #{1} AREA
                    </span>
                  )}
                </div>

                <div className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3.5 flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-amber-600 flex items-center gap-1">
                      <Flame className="h-3 w-3" /> Top Rejection Type
                    </span>
                    <p
                      className="text-base font-black text-zinc-900 dark:text-zinc-100 mt-1 truncate"
                      title={topReason?.reason}
                    >
                      {topReason ? topReason.reason : "—"}
                    </p>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {topReason
                        ? `${topReason.qty} pcs (${topReason.pct.toFixed(1)}%) · ${topReason.count} NC(s)`
                        : "No defect data"}
                    </p>
                  </div>
                  {topReason && (
                    <span className="shrink-0 rounded-lg bg-amber-600 text-white px-2 py-0.5 text-[10px] font-extrabold font-mono">
                      #{1} DEFECT
                    </span>
                  )}
                </div>

                <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-3.5 flex items-start justify-between gap-2">
                  <div>
                    <span className="text-[10px] font-bold uppercase tracking-wider text-blue-600 flex items-center gap-1">
                      <TrendingUp className="h-3 w-3" /> Peak Rejection Day
                    </span>
                    <p className="text-lg font-black font-mono text-zinc-900 dark:text-zinc-100 mt-1">
                      {analytics.peakDay ? analytics.peakDay.label : "—"}
                    </p>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">
                      {analytics.peakDay
                        ? `${analytics.peakDay.qty} pcs across ${analytics.peakDay.count} NC(s)`
                        : "—"}
                    </p>
                  </div>
                  <span className="rounded-lg bg-blue-600 text-white px-2 py-0.5 text-[10px] font-extrabold">
                    IST
                  </span>
                </div>
              </div>

              {/* 2 Main Ranked Charts: Area (Stage) vs Type (Defect) */}
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {/* Area / Stage Breakdown */}
                <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3.5">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h3 className="text-xs font-extrabold text-zinc-900 dark:text-zinc-100">
                        Rejections by Area / Stage
                      </h3>
                      <p className="text-[10px] text-zinc-400">
                        Click a stage bar to filter the table below
                      </p>
                    </div>
                    <span className="text-[10px] font-bold text-zinc-400 uppercase">
                      {analytics.stages.length} stage(s)
                    </span>
                  </div>
                  <div className="space-y-2.5">
                    {analytics.stages.map((s, idx) => {
                      const isActive = selectedStage === s.stage;
                      const maxVal = analytics.stages[0]?.val || 1;
                      const barWidth = Math.max(4, (s.val / maxVal) * 100);
                      return (
                        <button
                          key={s.stage}
                          type="button"
                          onClick={() => onSelectStage(isActive ? "" : s.stage)}
                          className={`w-full text-left rounded-lg p-2 transition-all cursor-pointer border ${
                            isActive
                              ? "border-rose-500 bg-rose-500/5 ring-1 ring-rose-500/30"
                              : "border-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                          }`}
                        >
                          <div className="flex items-center justify-between text-xs mb-1">
                            <div className="flex items-center gap-2">
                              <span
                                className={`inline-flex items-center justify-center rounded-md px-1.5 py-0.5 font-mono text-[11px] font-extrabold ${
                                  idx === 0
                                    ? "bg-rose-600 text-white"
                                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
                                }`}
                              >
                                {s.stage}
                              </span>
                              <span className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate max-w-[180px]">
                                Top: {s.topReason}
                              </span>
                            </div>
                            <div className="font-mono text-[11px] font-bold text-zinc-800 dark:text-zinc-200 whitespace-nowrap">
                              {s.qty} pcs{" "}
                              <span className="text-zinc-400 font-normal">
                                ({s.pct.toFixed(1)}% · {s.count} NC)
                              </span>
                            </div>
                          </div>
                          <div className="h-2 w-full rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                idx === 0
                                  ? "bg-rose-600"
                                  : idx === 1
                                  ? "bg-rose-400"
                                  : "bg-zinc-400 dark:bg-zinc-500"
                              }`}
                              style={{ width: `${barWidth}%` }}
                            />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Defect / Type Pareto Breakdown */}
                <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3.5">
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <h3 className="text-xs font-extrabold text-zinc-900 dark:text-zinc-100">
                        Rejections by Defect Type (Pareto)
                      </h3>
                      <p className="text-[10px] text-zinc-400">
                        Click a defect bar to filter the table below
                      </p>
                    </div>
                    <span className="text-[10px] font-bold text-zinc-400 uppercase">
                      {analytics.reasons.length} type(s)
                    </span>
                  </div>
                  <div className="space-y-2.5 max-h-[280px] overflow-y-auto pr-1">
                    {analytics.reasons.map((r, idx) => {
                      const isActive = selectedReason === r.reason;
                      const maxVal = analytics.reasons[0]?.val || 1;
                      const barWidth = Math.max(4, (r.val / maxVal) * 100);
                      return (
                        <button
                          key={r.reason}
                          type="button"
                          onClick={() => onSelectReason(isActive ? "" : r.reason)}
                          className={`w-full text-left rounded-lg p-2 transition-all cursor-pointer border ${
                            isActive
                              ? "border-amber-500 bg-amber-500/5 ring-1 ring-amber-500/30"
                              : "border-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800/50"
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 text-xs mb-1">
                            <div className="flex items-center gap-2 min-w-0">
                              <span
                                className={`shrink-0 text-[10px] font-mono font-extrabold px-1.5 py-0.5 rounded ${
                                  idx === 0
                                    ? "bg-amber-600 text-white"
                                    : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300"
                                }`}
                              >
                                #{idx + 1}
                              </span>
                              <span
                                className="font-bold text-zinc-800 dark:text-zinc-200 truncate"
                                title={r.reason}
                              >
                                {r.reason}
                              </span>
                              <span className="shrink-0 text-[10px] font-mono text-zinc-400">
                                [{r.stageList.join(", ")}]
                              </span>
                            </div>
                            <div className="shrink-0 font-mono text-[11px] font-bold text-zinc-800 dark:text-zinc-200 whitespace-nowrap">
                              {r.qty} pcs{" "}
                              <span className="text-zinc-400 font-normal">
                                ({r.pct.toFixed(1)}% · Σ{r.cumPct.toFixed(0)}%)
                              </span>
                            </div>
                          </div>
                          <div className="h-2 w-full rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                idx === 0
                                  ? "bg-amber-500"
                                  : idx === 1
                                  ? "bg-amber-400"
                                  : "bg-zinc-400 dark:bg-zinc-500"
                              }`}
                              style={{ width: `${barWidth}%` }}
                            />
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Bottom Row: Daily Timeline + Top Rejected Parts */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div className="lg:col-span-2 rounded-xl border border-zinc-200 dark:border-zinc-800 p-3.5">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-extrabold text-zinc-900 dark:text-zinc-100">
                      Rejection Trend by Date (IST)
                    </h3>
                    <span className="text-[10px] text-zinc-400">
                      {analytics.timeline.length} active day(s)
                    </span>
                  </div>
                  <div className="flex items-end gap-2 h-28 pt-4 overflow-x-auto">
                    {analytics.timeline.map((d) => {
                      const val = metric === "qty" ? d.qty : d.count;
                      const heightPct =
                        analytics.maxTimelineVal > 0
                          ? Math.max(10, (val / analytics.maxTimelineVal) * 100)
                          : 10;
                      return (
                        <div
                          key={d.key}
                          className="flex-1 min-w-[44px] flex flex-col items-center gap-1 h-full justify-end group"
                          title={`${d.label}: ${d.qty} pcs (${d.count} NC)`}
                        >
                          <span className="text-[10px] font-mono font-bold text-zinc-600 dark:text-zinc-300">
                            {val}
                          </span>
                          <div className="w-full max-w-[36px] flex-1 flex items-end">
                            <div
                              className="w-full rounded-t-md bg-rose-500/80 group-hover:bg-rose-600 transition-colors"
                              style={{ height: `${heightPct}%` }}
                            />
                          </div>
                          <span className="text-[10px] text-zinc-400 whitespace-nowrap">
                            {d.label}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 p-3.5">
                  <div className="flex items-center justify-between mb-2.5">
                    <h3 className="text-xs font-extrabold text-zinc-900 dark:text-zinc-100 flex items-center gap-1.5">
                      <Package className="h-3.5 w-3.5 text-zinc-400" />
                      Top Rejected Parts
                    </h3>
                    <span className="text-[10px] text-zinc-400">By qty</span>
                  </div>
                  <div className="space-y-1.5">
                    {analytics.parts.map((p) => (
                      <div
                        key={p.part}
                        className="flex items-center justify-between text-xs py-1 border-b border-zinc-100 dark:border-zinc-800/60 last:border-0"
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span className="font-mono font-bold text-zinc-800 dark:text-zinc-200">
                            {p.part}
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">
                            ({p.count} NC)
                          </span>
                        </div>
                        <span className="font-mono font-bold text-rose-600">
                          {p.qty} pcs ({p.pct.toFixed(0)}%)
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

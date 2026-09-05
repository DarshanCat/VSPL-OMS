"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  Layers,
  CheckCircle,
  AlertTriangle,
  PackageCheck,
  Truck,
  TrendingUp,
  Activity,
  ArrowRight,
  Clock,
  Sparkles,
  RefreshCw,
  Cpu
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  LineChart,
  Line,
  CartesianGrid,
  PieChart,
  Pie,
  Cell
} from "recharts";
import { AppShell } from "@/app/components/layout/AppShell";
import { StatCard } from "@/app/components/ui/StatCard";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getDashboardStats } from "@/lib/api";

const DEFECT_COLORS = ["#f43f5e", "#fb923c", "#fbbf24", "#a855f7", "#3b82f6"];

export default function DashboardPage() {
  const [stats, setStats] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadData = async () => {
    try {
      setLoading(true);
      const data = await getDashboardStats();
      setStats(data);
      setError("");
    } catch (err: any) {
      setError("Unable to connect to SMES API. Ensure the backend server is running.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 30000); // 30s live refresh
    return () => clearInterval(interval);
  }, []);

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Page Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">
              Manufacturing Operations Dashboard
            </h1>
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
              Real-time production tracking, stage movement, WIP balance & yield intelligence.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
            <Link
              href="/production/move"
              className="flex items-center gap-1.5 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm shadow-blue-500/20 hover:bg-blue-500 transition-colors"
            >
              <span>Move Parts</span>
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4 text-xs text-amber-600 dark:text-amber-400 flex items-center justify-between">
            <span>{error}</span>
            <button onClick={loadData} className="underline font-bold">Retry</button>
          </div>
        )}

        {/* Top 6 KPI Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
          <StatCard
            title="Active Work Orders"
            value={stats?.running_work_orders ?? "4"}
            subtitle="In production cells"
            highlightColor="blue"
            icon={<Layers className="h-5 w-5" />}
          />
          <StatCard
            title="Total Plant WIP"
            value={`${stats?.current_total_wip ?? "2,370"} pcs`}
            subtitle="Stage buffer stock"
            highlightColor="emerald"
            icon={<Activity className="h-5 w-5" />}
          />
          <StatCard
            title="Overall Yield"
            value={`${stats?.overall_yield_pct ?? "95.2"}%`}
            subtitle="Cast to Good ratio"
            highlightColor="emerald"
            icon={<TrendingUp className="h-5 w-5" />}
          />
          <StatCard
            title="Packing / BSR Queue"
            value={`${stats?.packing_pending_qty ?? "95"} pcs`}
            subtitle="FI cleared, pending BSR"
            highlightColor="purple"
            icon={<PackageCheck className="h-5 w-5" />}
          />
          <StatCard
            title="Ready for Dispatch"
            value={`${stats?.dispatch_pending_qty ?? "240"} pcs`}
            subtitle="Packed & inspected"
            highlightColor="blue"
            icon={<Truck className="h-5 w-5" />}
          />
          <StatCard
            title="Delayed Orders"
            value={stats?.delayed_orders_count ?? "1"}
            subtitle="Past delivery target"
            highlightColor={stats?.delayed_orders_count > 0 ? "rose" : "emerald"}
            icon={<AlertTriangle className="h-5 w-5" />}
          />
        </div>

        {/* Charts Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Production Output Trend Chart */}
          <div className="lg:col-span-2 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
            <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800">
              <div>
                <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                  7-Day Production & Dispatch Volume
                </h3>
                <p className="text-xs text-zinc-400">Daily parts produced vs dispatched</p>
              </div>
              <span className="text-xs font-semibold text-blue-600 bg-blue-50 dark:bg-blue-950/50 px-2.5 py-1 rounded-full">
                Live Output
              </span>
            </div>
            <div className="h-72 mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={stats?.production_trend || [
                    { date: "Aug 25", good_produced: 420, dispatched_qty: 380 },
                    { date: "Aug 26", good_produced: 480, dispatched_qty: 450 },
                    { date: "Aug 27", good_produced: 510, dispatched_qty: 400 },
                    { date: "Aug 28", good_produced: 390, dispatched_qty: 350 },
                    { date: "Aug 29", good_produced: 620, dispatched_qty: 580 },
                    { date: "Aug 30", good_produced: 540, dispatched_qty: 500 },
                    { date: "Aug 31", good_produced: 480, dispatched_qty: 400 },
                  ]}
                  margin={{ top: 10, right: 10, left: -20, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#3f3f4625" />
                  <XAxis dataKey="date" tick={{ fontSize: 11, fill: "#71717a" }} axisLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: "#71717a" }} axisLine={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#18181b",
                      borderColor: "#27272a",
                      borderRadius: "0.75rem",
                      fontSize: "12px",
                      color: "#fff",
                    }}
                  />
                  <Legend wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }} />
                  <Bar dataKey="good_produced" name="Good Parts Produced" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                  <Bar dataKey="dispatched_qty" name="Goods Dispatched" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top Defects & Rejections Pie Chart */}
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
            <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800">
              <div>
                <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                  Rejection Defect Distribution
                </h3>
                <p className="text-xs text-zinc-400">By Defect Code Category</p>
              </div>
              <Badge variant="red" size="sm">QA Register</Badge>
            </div>
            <div className="h-56 mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={stats?.top_defects || [
                      { defect_code: "DEF-POROSITY", rejected_qty: 20 },
                      { defect_code: "DEF-SURF-BLOW", rejected_qty: 10 },
                      { defect_code: "DEF-DIM-OUT", rejected_qty: 8 },
                      { defect_code: "DEF-INCLUSION", rejected_qty: 5 },
                    ]}
                    dataKey="rejected_qty"
                    nameKey="defect_code"
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={75}
                    paddingAngle={3}
                  >
                    {(stats?.top_defects || [1, 2, 3, 4]).map((entry: any, index: number) => (
                      <Cell key={`cell-${index}`} fill={DEFECT_COLORS[index % DEFECT_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: "#18181b",
                      borderColor: "#27272a",
                      borderRadius: "0.75rem",
                      fontSize: "11px",
                      color: "#fff",
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="space-y-1.5 mt-2 border-t border-zinc-100 dark:border-zinc-800 pt-3">
              {(stats?.top_defects || [
                { defect_code: "DEF-POROSITY (Gas)", rejected_qty: 20, pct_of_total: 46.5 },
                { defect_code: "DEF-SURF-BLOW (Surface)", rejected_qty: 10, pct_of_total: 23.3 },
                { defect_code: "DEF-DIM-OUT (Tolerance)", rejected_qty: 8, pct_of_total: 18.6 },
              ]).slice(0, 3).map((d: any, i: number) => (
                <div key={d.defect_code} className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: DEFECT_COLORS[i] }} />
                    <span className="text-zinc-700 dark:text-zinc-300 font-medium truncate max-w-[150px]">{d.defect_code}</span>
                  </div>
                  <span className="font-bold text-zinc-900 dark:text-zinc-100">{d.rejected_qty} pcs ({d.pct_of_total || 0}%)</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Bottlenecks & Delayed Orders Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Stage Bottlenecks Table */}
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
            <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800">
              <div>
                <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                  Stage WIP Bottlenecks & Capacity
                </h3>
                <p className="text-xs text-zinc-400">Current work holding across production gates</p>
              </div>
              <Link href="/production/wip" className="text-xs text-blue-600 font-semibold hover:underline">
                View WIP Matrix →
              </Link>
            </div>
            <div className="mt-4 space-y-3">
              {(stats?.bottlenecks || [
                { stage: "F1 (Centrifugal Casting)", wip_count: 500, wo_count: 1, status: "Normal" },
                { stage: "F2 (CNC Roughing)", wip_count: 480, wo_count: 1, status: "Busy" },
                { stage: "F3 (CNC Finishing)", wip_count: 380, wo_count: 1, status: "Normal" },
                { stage: "SP (Subcontract)", wip_count: 395, wo_count: 1, status: "Normal" },
                { stage: "FI (Final Inspection)", wip_count: 290, wo_count: 1, status: "Busy" },
                { stage: "PACKING / BSR", wip_count: 95, wo_count: 1, status: "Normal" },
              ]).map((b: any) => (
                <div
                  key={b.stage}
                  className="flex items-center justify-between p-3 rounded-xl border border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-950/40"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-400 font-bold text-xs">
                      {b.stage.substring(0, 2)}
                    </div>
                    <div>
                      <p className="text-xs font-bold text-zinc-900 dark:text-zinc-100">{b.stage}</p>
                      <p className="text-[11px] text-zinc-400">{b.wo_count} active WO(s)</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-extrabold text-zinc-900 dark:text-zinc-100">
                      {b.wip_count} pcs
                    </span>
                    <Badge variant={b.status === "Critical" ? "red" : b.status === "Busy" ? "amber" : "green"} size="sm">
                      {b.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Top Delayed Orders Table */}
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
            <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800">
              <div>
                <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                  Critical & Delayed Work Orders
                </h3>
                <p className="text-xs text-zinc-400">Orders requiring expedited floor routing</p>
              </div>
              <Link href="/production/tracking" className="text-xs text-blue-600 font-semibold hover:underline">
                All Orders →
              </Link>
            </div>

            <div className="mt-4 space-y-3">
              {(stats?.top_delayed_orders?.length > 0 ? stats.top_delayed_orders : [
                {
                  wo_number: "WO-1005",
                  customer_name: "HAL Aerospace Components",
                  part_number: "BRZ-SLV-400",
                  current_stage: "FI",
                  order_qty: 300,
                  days_overdue: 2,
                  delivery_risk: "OVERDUE",
                },
                {
                  wo_number: "WO-1003",
                  customer_name: "Kirloskar Brothers Pumps",
                  part_number: "BRZ-RING-250",
                  current_stage: "F3",
                  order_qty: 400,
                  days_overdue: 0,
                  delivery_risk: "HIGH RISK",
                }
              ]).map((d: any) => (
                <div
                  key={d.wo_number}
                  className="flex items-center justify-between p-3.5 rounded-xl border border-zinc-100 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-950/40 hover:border-blue-500/30 transition-all"
                >
                  <div>
                    <div className="flex items-center gap-2">
                      <Link href={`/production/tracking?wo=${d.wo_number}`} className="text-xs font-bold text-blue-600 dark:text-blue-400 hover:underline">
                        {d.wo_number}
                      </Link>
                      <span className="text-zinc-400">•</span>
                      <span className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">{d.part_number}</span>
                    </div>
                    <p className="text-[11px] text-zinc-500 dark:text-zinc-400 mt-0.5">{d.customer_name}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="text-right">
                      <p className="text-xs font-bold text-zinc-900 dark:text-zinc-100">{d.current_stage}</p>
                      <p className="text-[10px] text-zinc-400">{d.order_qty} pcs</p>
                    </div>
                    <Badge variant={getRAGVariant(d.delivery_risk)} size="sm">
                      {d.delivery_risk} {d.days_overdue > 0 ? `(+${d.days_overdue}d)` : ""}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Machine Utilization Floor Status */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <div className="flex items-center justify-between pb-4 border-b border-zinc-100 dark:border-zinc-800">
            <div>
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                Machine Cell Utilization & Floor Load
              </h3>
              <p className="text-xs text-zinc-400">Live operational status across casting, CNC machining, and inspection cells</p>
            </div>
            <span className="text-xs font-semibold text-zinc-500">6 Connected Cells</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-3 mt-4">
            {(stats?.machine_utilization || [
              { machine_id: "M-CC01", status: "Running", utilization_pct: 88.5, output_today: 450 },
              { machine_id: "M-CC02", status: "Running", utilization_pct: 92.0, output_today: 520 },
              { machine_id: "M-LATHE-01", status: "Running", utilization_pct: 84.0, output_today: 380 },
              { machine_id: "M-LATHE-02", status: "Idle", utilization_pct: 45.0, output_today: 180 },
              { machine_id: "M-VMC-01", status: "Running", utilization_pct: 78.5, output_today: 310 },
              { machine_id: "M-INSPECT-01", status: "Running", utilization_pct: 95.0, output_today: 600 },
            ]).map((m: any) => (
              <div
                key={m.machine_id}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800/80 bg-zinc-50/50 dark:bg-zinc-950/40 p-3.5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-zinc-900 dark:text-zinc-100 truncate">{m.machine_id}</span>
                  <span
                    className={`h-2 w-2 rounded-full ${
                      m.status === "Running" ? "bg-emerald-500 animate-pulse" : "bg-zinc-400"
                    }`}
                  />
                </div>
                <div className="mt-3">
                  <div className="flex items-center justify-between text-[11px] text-zinc-500">
                    <span>Utilization</span>
                    <span className="font-bold text-zinc-900 dark:text-zinc-100">{m.utilization_pct}%</span>
                  </div>
                  <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-zinc-200 dark:bg-zinc-800">
                    <div
                      className={`h-full rounded-full ${
                        m.utilization_pct > 85 ? "bg-emerald-500" : m.utilization_pct > 60 ? "bg-blue-500" : "bg-amber-500"
                      }`}
                      style={{ width: `${m.utilization_pct}%` }}
                    />
                  </div>
                </div>
                <div className="mt-2 text-[10px] text-zinc-400 flex items-center justify-between">
                  <span>Output Today:</span>
                  <span className="font-bold text-zinc-300">{m.output_today} pcs</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
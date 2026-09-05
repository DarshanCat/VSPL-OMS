"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  Layers,
  Search,
  Download,
  Filter,
  RefreshCw,
  ArrowRight,
  CheckCircle2,
  FileSpreadsheet
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getWIPMatrix, API_BASE } from "@/lib/api";

export default function WIPMatrixPage() {
  const [wipData, setWipData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState("ALL");
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getWIPMatrix();
      setWipData(data);
    } catch (err: any) {
      setError("Failed to load WIP Matrix from server.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const stages = wipData?.stages || ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"];

  const filteredWOs = (wipData?.work_orders || []).filter((wo: any) => {
    const matchesSearch =
      !search ||
      wo.wo_number.toLowerCase().includes(search.toLowerCase()) ||
      wo.part_number.toLowerCase().includes(search.toLowerCase()) ||
      (wo.customer_name && wo.customer_name.toLowerCase().includes(search.toLowerCase()));

    const matchesStage = stageFilter === "ALL" || wo.current_stage.toUpperCase() === stageFilter;

    return matchesSearch && matchesStage;
  });

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">
              Live Stage-Wise WIP Matrix
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Auditable inventory buffers held across all manufacturing stages calculated bottom-up per Work Order.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <a
              href={`${API_BASE}/api/v1/reports/export/wip-csv`}
              download
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <Download className="h-3.5 w-3.5 text-blue-600" />
              <span>Export WIP CSV</span>
            </a>
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl bg-blue-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-blue-500 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-col sm:flex-row gap-3 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter by WO Number, Part Number, or Customer..."
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-10 pr-4 py-2 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-zinc-400" />
            <select
              value={stageFilter}
              onChange={(e) => setStageFilter(e.target.value)}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
            >
              <option value="ALL">All Current Stages</option>
              {stages.map((s: string) => (
                <option key={s} value={s}>
                  Stage {s}
                </option>
              ))}
            </select>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* WIP Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-3 px-3">Work Order</th>
                  <th className="py-3 px-3">Customer</th>
                  <th className="py-3 px-3">Part No</th>
                  <th className="py-3 px-3 text-center">Stage</th>
                  <th className="py-3 px-3 text-right">Order Qty</th>
                  {stages.map((s: string) => (
                    <th key={s} className="py-3 px-2.5 text-right font-mono">
                      {s}
                    </th>
                  ))}
                  <th className="py-3 px-3 text-right font-extrabold text-blue-600">Total WIP</th>
                </tr>
              </thead>

              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {filteredWOs.map((wo: any) => (
                  <tr key={wo.wo_id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                    <td className="py-3 px-3 font-mono font-bold">
                      <Link
                        href={`/production/tracking?wo=${wo.wo_number}`}
                        className="text-blue-600 dark:text-blue-400 hover:underline"
                      >
                        {wo.wo_number}
                      </Link>
                    </td>
                    <td className="py-3 px-3 text-zinc-600 dark:text-zinc-400 truncate max-w-[150px]">
                      {wo.customer_name}
                    </td>
                    <td className="py-3 px-3 text-zinc-800 dark:text-zinc-200 font-semibold">{wo.part_number}</td>
                    <td className="py-3 px-3 text-center">
                      <Badge variant="blue" size="sm">
                        {wo.current_stage}
                      </Badge>
                    </td>
                    <td className="py-3 px-3 text-right text-zinc-500">{wo.order_qty}</td>

                    {/* Stage cell numbers */}
                    {stages.map((s: string) => {
                      const qty = wo.stage_wips?.[s] || 0;
                      return (
                        <td
                          key={s}
                          className={`py-3 px-2.5 text-right font-mono ${
                            qty > 0 ? "font-bold text-zinc-900 dark:text-zinc-50 bg-blue-50/30 dark:bg-blue-950/20" : "text-zinc-300 dark:text-zinc-700"
                          }`}
                        >
                          {qty > 0 ? qty : "—"}
                        </td>
                      );
                    })}

                    <td className="py-3 px-3 text-right font-mono font-extrabold text-blue-600 dark:text-blue-400">
                      {wo.total_wip} pcs
                    </td>
                  </tr>
                ))}
              </tbody>

              {/* Summary Footer */}
              <tfoot className="border-t-2 border-zinc-300 dark:border-zinc-700 font-extrabold text-xs bg-zinc-50/50 dark:bg-zinc-950/50">
                <tr>
                  <td colSpan={5} className="py-3.5 px-3 text-zinc-900 dark:text-zinc-50 uppercase text-[11px]">
                    Plant Stage WIP Totals
                  </td>
                  {stages.map((s: string) => (
                    <td key={s} className="py-3.5 px-2.5 text-right font-mono text-blue-600 dark:text-blue-400">
                      {wipData?.stage_totals?.[s] ?? 0}
                    </td>
                  ))}
                  <td className="py-3.5 px-3 text-right font-mono text-emerald-600 dark:text-emerald-400 text-sm">
                    {wipData?.grand_total_wip ?? 0} pcs
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

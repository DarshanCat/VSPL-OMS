"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  History,
  Search,
  Download,
  Filter,
  RefreshCw,
  ArrowRight,
  Cpu,
  UserCheck
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getMovements, API_BASE } from "@/lib/api";

export default function MovementHistoryPage() {
  const [movements, setMovements] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [stageFilter, setStageFilter] = useState("ALL");
  const [error, setError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const data = await getMovements({ limit: 200 });
      setMovements(data);
    } catch (err: any) {
      setError("Failed to fetch movement history from server.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const filteredMovements = movements.filter((m) => {
    const matchesSearch =
      !search ||
      m.movement_id.toLowerCase().includes(search.toLowerCase()) ||
      m.wo_number.toLowerCase().includes(search.toLowerCase()) ||
      (m.part_number && m.part_number.toLowerCase().includes(search.toLowerCase())) ||
      (m.operator_name && m.operator_name.toLowerCase().includes(search.toLowerCase()));

    const matchesStage =
      stageFilter === "ALL" ||
      m.from_stage.toUpperCase() === stageFilter ||
      m.to_stage.toUpperCase() === stageFilter;

    return matchesSearch && matchesStage;
  });

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">
              Production Movement Ledger
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Permanent immutable transaction history of all physical manufacturing stage movements.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <a
              href={`${API_BASE}/api/v1/reports/export/movements-csv`}
              download
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <Download className="h-3.5 w-3.5 text-blue-600" />
              <span>Export Ledger CSV</span>
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
              placeholder="Search by Movement ID, Work Order, Part, or Operator..."
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
              <option value="ALL">All Stages</option>
              <option value="F1">F1 (Casting)</option>
              <option value="F2">F2 (Roughing)</option>
              <option value="F3">F3 (Finishing)</option>
              <option value="SP">SP (Subcontract)</option>
              <option value="FI">FI (Final Inspection)</option>
              <option value="PACKING">PACKING / BSR</option>
              <option value="DISPATCH">DISPATCH</option>
            </select>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Ledger Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-3 px-3">Movement ID</th>
                  <th className="py-3 px-3">Date / Time</th>
                  <th className="py-3 px-3">Work Order</th>
                  <th className="py-3 px-3">Part Number</th>
                  <th className="py-3 px-3">Transition</th>
                  <th className="py-3 px-3 text-right">Qty Moved</th>
                  <th className="py-3 px-3 text-right">Rejected</th>
                  <th className="py-3 px-3">Machine</th>
                  <th className="py-3 px-3">Operator / Shift</th>
                  <th className="py-3 px-3">Remarks</th>
                </tr>
              </thead>

              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {filteredMovements.map((m: any) => (
                  <tr key={m.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                    <td className="py-3 px-3 font-mono font-bold text-blue-600 dark:text-blue-400">
                      {m.movement_id}
                    </td>
                    <td className="py-3 px-3 text-zinc-500 whitespace-nowrap">
                      {m.movement_date || m.created_at?.substring(0, 10)} {m.movement_time || ""}
                    </td>
                    <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                      <Link href={`/production/tracking?wo=${m.wo_number}`} className="hover:underline">
                        {m.wo_number}
                      </Link>
                    </td>
                    <td className="py-3 px-3 font-semibold text-zinc-700 dark:text-zinc-300">
                      {m.part_number || "N/A"}
                    </td>
                    <td className="py-3 px-3">
                      <span className="inline-flex items-center gap-1 font-mono font-bold text-zinc-800 dark:text-zinc-200 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded-md text-[11px]">
                        {m.from_stage} → {m.to_stage}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right font-mono font-bold text-emerald-600">
                      {m.quantity_moved}
                    </td>
                    <td className="py-3 px-3 text-right font-mono font-bold text-rose-600">
                      {m.rejected_quantity > 0 ? m.rejected_quantity : "0"}
                    </td>
                    <td className="py-3 px-3 text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
                      {m.machine_id || "—"}
                    </td>
                    <td className="py-3 px-3 text-zinc-600 dark:text-zinc-400 whitespace-nowrap">
                      {m.operator_name || "Operator"} ({m.shift || "A"})
                    </td>
                    <td className="py-3 px-3 text-zinc-500 max-w-[180px] truncate">
                      {m.remarks || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

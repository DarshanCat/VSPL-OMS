"use client";
import React, { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import {
  Search,
  ChevronDown,
  ChevronRight,
  FileSpreadsheet,
  ArrowRight
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { getOarList } from "@/lib/api";

export default function OarWoListPage() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [oars, setOars] = useState<any[]>([]);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const fetchOars = useCallback(async (searchTerm: string, status: string) => {
    setLoading(true);
    setError("");
    try {
      const data = await getOarList({
        search: searchTerm.trim() || undefined,
        status_filter: status || undefined,
        limit: 200
      });
      setOars(Array.isArray(data) ? data : []);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load OAR & WO list.");
      setOars([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOars("", "");
  }, [fetchOars]);

  const toggleExpand = (oarNumber: string) => {
    setExpanded((prev) => ({ ...prev, [oarNumber]: !prev[oarNumber] }));
  };

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Order Tracking
            </span>
            <span className="text-xs text-zinc-400">Read-Only OAR / WO Roll-Up</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            OAR &amp; WO List
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Search and drill into every Order Acknowledgement Record and its allocated Work Orders. Figures are read
            directly from existing order, release, production, and dispatch records — nothing here is recalculated
            business logic.
          </p>
        </div>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            fetchOars(search, statusFilter);
          }}
          className="flex flex-col sm:flex-row gap-3"
        >
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search OAR, WO, customer, part, or PO..."
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-10 pr-4 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none font-medium"
            />
          </div>
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value);
              fetchOars(search, e.target.value);
            }}
            className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2.5 text-xs text-zinc-900 dark:text-zinc-100 font-semibold focus:outline-none"
          >
            <option value="">All Statuses</option>
            <option value="accept">Accept</option>
            <option value="hold">Hold</option>
            <option value="reject">Reject</option>
          </select>
          <button
            type="submit"
            disabled={loading}
            className="rounded-xl bg-blue-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 transition-colors cursor-pointer"
          >
            {loading ? "Searching..." : "Search"}
          </button>
        </form>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-2.5 px-3 w-8"></th>
                  <th className="py-2.5 px-3">OAR ID</th>
                  <th className="py-2.5 px-3">Customer</th>
                  <th className="py-2.5 px-3">PO</th>
                  <th className="py-2.5 px-3">Part</th>
                  <th className="py-2.5 px-3 text-right">OAR Qty</th>
                  <th className="py-2.5 px-3 text-right">Allocated</th>
                  <th className="py-2.5 px-3 text-right">Remaining</th>
                  <th className="py-2.5 px-3 text-center"># WOs</th>
                  <th className="py-2.5 px-3">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {oars.map((oar) => (
                  <React.Fragment key={oar.oar_number}>
                    <tr
                      onClick={() => toggleExpand(oar.oar_number)}
                      className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40 cursor-pointer"
                    >
                      <td className="py-3 px-3 text-zinc-400">
                        {expanded[oar.oar_number] ? (
                          <ChevronDown className="h-3.5 w-3.5" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5" />
                        )}
                      </td>
                      <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {oar.oar_number}
                      </td>
                      <td className="py-3 px-3">
                        <div className="text-zinc-800 dark:text-zinc-200">{oar.customer_name}</div>
                        <div className="text-[10px] text-zinc-400 font-mono">{oar.customer_code}</div>
                      </td>
                      <td className="py-3 px-3 font-mono text-zinc-600 dark:text-zinc-400">{oar.customer_po}</td>
                      <td className="py-3 px-3 font-mono text-zinc-600 dark:text-zinc-400">{oar.part_number}</td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {oar.oar_qty}
                      </td>
                      <td className="py-3 px-3 text-right font-mono font-bold text-blue-600">{oar.allocated_qty}</td>
                      <td className="py-3 px-3 text-right font-mono font-bold">
                        <span className={oar.remaining_qty === 0 ? "text-emerald-600" : "text-amber-600"}>
                          {oar.remaining_qty}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center font-mono font-bold text-zinc-700 dark:text-zinc-300">
                        {oar.num_wos}
                      </td>
                      <td className="py-3 px-3">
                        <Badge variant={getRAGVariant(oar.status)} size="sm">
                          {oar.status.toUpperCase()}
                        </Badge>
                      </td>
                    </tr>

                    {expanded[oar.oar_number] && (
                      <tr>
                        <td colSpan={10} className="bg-zinc-50/60 dark:bg-zinc-950/40 p-0">
                          <div className="p-4">
                            {oar.work_orders.length === 0 ? (
                              <div className="text-[11px] text-zinc-400 px-2 py-1">
                                No Work Orders were created for this OAR.
                              </div>
                            ) : (
                              <table className="w-full text-left text-[11px]">
                                <thead className="text-zinc-400 uppercase text-[9px] font-bold">
                                  <tr>
                                    <th className="py-1.5 px-2">WO ID</th>
                                    <th className="py-1.5 px-2 text-right">Qty</th>
                                    <th className="py-1.5 px-2">Release Status</th>
                                    <th className="py-1.5 px-2">Current Stage</th>
                                    <th className="py-1.5 px-2">WO Status</th>
                                    <th className="py-1.5 px-2 text-right">Production OK</th>
                                    <th className="py-1.5 px-2 text-right">Rejected</th>
                                    <th className="py-1.5 px-2 text-right">Movable WIP</th>
                                    <th className="py-1.5 px-2 text-right">Dispatched</th>
                                    <th className="py-1.5 px-2"></th>
                                  </tr>
                                </thead>
                                <tbody className="divide-y divide-zinc-200/60 dark:divide-zinc-800/60">
                                  {oar.work_orders.map((wo: any) => (
                                    <tr key={wo.wo_number}>
                                      <td className="py-2 px-2 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                                        {wo.wo_number}
                                      </td>
                                      <td className="py-2 px-2 text-right font-mono font-bold">{wo.allocated_qty}</td>
                                      <td className="py-2 px-2">
                                        <Badge
                                          variant={wo.release_status === "Released" ? "green" : "gray"}
                                          size="sm"
                                        >
                                          {wo.release_status}
                                        </Badge>
                                      </td>
                                      <td className="py-2 px-2 font-mono font-bold text-blue-600">
                                        {wo.current_stage}
                                      </td>
                                      <td className="py-2 px-2">
                                        <Badge variant={getRAGVariant(wo.wo_status)} size="sm">
                                          {wo.wo_status.replace(/_/g, " ").toUpperCase()}
                                        </Badge>
                                      </td>
                                      <td className="py-2 px-2 text-right font-mono font-bold text-emerald-600">
                                        {wo.ok_completed}
                                      </td>
                                      <td className="py-2 px-2 text-right font-mono font-bold text-rose-600">
                                        {wo.rejected}
                                      </td>
                                      <td className="py-2 px-2 text-right font-mono font-bold text-purple-600">
                                        {wo.movable_wip}
                                      </td>
                                      <td className="py-2 px-2 text-right font-mono font-bold text-zinc-600 dark:text-zinc-400">
                                        {wo.dispatched_qty}
                                      </td>
                                      <td className="py-2 px-2">
                                        <Link
                                          href={`/production/tracking?wo=${wo.wo_number}`}
                                          className="inline-flex items-center gap-1 text-blue-600 hover:underline font-bold"
                                        >
                                          <span>Detail</span>
                                          <ArrowRight className="h-3 w-3" />
                                        </Link>
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}

                {oars.length === 0 && !loading && (
                  <tr>
                    <td colSpan={10} className="py-10 text-center text-zinc-400">
                      <div className="flex flex-col items-center gap-2">
                        <FileSpreadsheet className="h-8 w-8 text-zinc-300 dark:text-zinc-700" />
                        <span>No OARs match your search.</span>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

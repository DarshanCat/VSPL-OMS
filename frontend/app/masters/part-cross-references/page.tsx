"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getPartCrossReferences,
  getMasterCustomers,
  getParts,
  CustomerPartCrossReferenceOut,
  MasterCustomer,
  AdminPart,
} from "@/lib/api";
import { Link2, Search, Filter, CheckCircle2, AlertTriangle, Building, Layers } from "lucide-react";

export default function PartCrossReferenceMasterPage() {
  const [crossRefs, setCrossRefs] = useState<CustomerPartCrossReferenceOut[]>([]);
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [parts, setParts] = useState<AdminPart[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [search, setSearch] = useState("");
  const [customerFilter, setCustomerFilter] = useState("");

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [refsData, custsData, partsData] = await Promise.all([
        getPartCrossReferences({
          search: search.trim() || undefined,
          customer_code: customerFilter || undefined,
          limit: 200,
        }),
        getMasterCustomers().catch(() => []),
        getParts().catch(() => []),
      ]);
      setCrossRefs(refsData);
      setCustomers(custsData);
      setParts(partsData);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not load part cross-references.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [customerFilter]);

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    loadData();
  };

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Master Data
              </span>
              <span className="text-xs text-zinc-400">Customer Specific</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1 flex items-center gap-2">
              <Link2 className="h-6 w-6 text-blue-600" />
              <span>Customer Part Cross-Reference Master</span>
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Authoritative Customer + Customer Part No &rarr; Internal Part mapping layer.
            </p>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Filters */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <form onSubmit={handleSearchSubmit} className="flex flex-col sm:flex-row gap-3">
            <div className="flex-1 relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search Customer Part No, Internal Part, Customer..."
                className="w-full pl-9 pr-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="w-full sm:w-56">
              <select
                value={customerFilter}
                onChange={(e) => setCustomerFilter(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                <option value="">All Customers</option>
                {customers.map((c) => (
                  <option key={c.customer_code} value={c.customer_code}>
                    {c.customer_code} — {c.name}
                  </option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-bold transition-colors shrink-0"
            >
              Filter / Search
            </button>
          </form>
        </div>

        {/* Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
              Active Cross-Reference Mappings ({crossRefs.length})
            </h3>
            <span className="text-[11px] text-zinc-400">Customer-Specific Lookup Layer</span>
          </div>

          {loading ? (
            <div className="p-8 text-center text-xs text-zinc-500">Loading cross-references...</div>
          ) : crossRefs.length === 0 ? (
            <div className="p-8 text-center text-xs text-zinc-500">
              No cross-reference mappings found matching the criteria.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="bg-zinc-50/70 dark:bg-zinc-950/40 border-b border-zinc-100 dark:border-zinc-800 text-[11px] font-bold text-zinc-500 uppercase tracking-wider">
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Customer Part No</th>
                    <th className="px-4 py-3">Internal Part Code</th>
                    <th className="px-4 py-3">Description / Grade</th>
                    <th className="px-4 py-3">Source</th>
                    <th className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800 font-medium text-zinc-700 dark:text-zinc-300">
                  {crossRefs.map((ref) => (
                    <tr key={ref.id} className="hover:bg-zinc-50 dark:hover:bg-zinc-800/40 transition-colors">
                      <td className="px-4 py-3">
                        <span className="font-bold text-zinc-900 dark:text-zinc-100 font-mono">
                          {ref.customer_code}
                        </span>
                        <span className="text-[11px] text-zinc-400 block truncate max-w-[180px]">
                          {ref.customer_name}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono font-bold text-blue-600 dark:text-blue-400">
                        {ref.customer_part_no}
                      </td>
                      <td className="px-4 py-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {ref.internal_part_code}
                      </td>
                      <td className="px-4 py-3">
                        <span className="block text-zinc-900 dark:text-zinc-100">
                          {ref.part_description || "-"}
                        </span>
                        {ref.part_grade && (
                          <span className="text-[10px] text-zinc-400 block font-mono">
                            Grade: {ref.part_grade}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[11px] text-zinc-500">
                        {ref.source || "-"}
                      </td>
                      <td className="px-4 py-3">
                        {ref.is_active ? (
                          <span className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400">
                            <CheckCircle2 className="h-3 w-3" />
                            Active
                          </span>
                        ) : (
                          <span className="text-[11px] font-bold text-zinc-400">Inactive</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

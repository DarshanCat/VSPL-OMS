"use client";
import React, { useEffect, useState, useMemo } from "react";
import Link from "next/link";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getMasterParts,
  getMasterPartKPIs,
  getMasterCustomers,
  createMasterPart,
  updateMasterPart,
  MasterPart,
  MasterPartKPIs,
  MasterCustomer,
} from "@/lib/api";
import {
  Layers,
  Plus,
  Search,
  Filter,
  RefreshCw,
  Building2,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  ExternalLink,
  Edit2,
  X,
  Info,
} from "lucide-react";

export default function PartMasterPage() {
  const [parts, setParts] = useState<MasterPart[]>([]);
  const [kpis, setKpis] = useState<MasterPartKPIs>({
    total_parts: 0,
    active_parts: 0,
    total_customers: 0,
    new_parts_this_month: 0,
  });
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [loading, setLoading] = useState(true);
  const [kpiLoading, setKpiLoading] = useState(true);
  const [listError, setListError] = useState("");

  // Filter state
  const [search, setSearch] = useState("");
  const [selectedCustomer, setSelectedCustomer] = useState("");
  const [selectedStatus, setSelectedStatus] = useState("ALL");
  const [page, setPage] = useState(1);
  const [totalCount, setTotalCount] = useState(0);
  const limit = 50;

  // Add Part Modal state
  const [showAddModal, setShowAddModal] = useState(false);
  const [addCustomerCode, setAddCustomerCode] = useState("");
  const [addCustomerPartNo, setAddCustomerPartNo] = useState("");
  const [addStatus, setAddStatus] = useState("Active");
  const [addDescription, setAddDescription] = useState("");
  const [addError, setAddError] = useState("");
  const [adding, setAdding] = useState(false);
  const [successCreated, setSuccessCreated] = useState<MasterPart | null>(null);

  // Edit Part Modal state
  const [editingPart, setEditingPart] = useState<MasterPart | null>(null);
  const [editCustomerPartNo, setEditCustomerPartNo] = useState("");
  const [editStatus, setEditStatus] = useState("Active");
  const [editDescription, setEditDescription] = useState("");
  const [editError, setEditError] = useState("");
  const [saving, setSaving] = useState(false);

  // Load KPI data
  async function loadKPIs() {
    setKpiLoading(true);
    try {
      const data = await getMasterPartKPIs();
      setKpis(data);
    } catch {
      // Fallback
    } finally {
      setKpiLoading(false);
    }
  }

  // Load customers for dropdowns
  async function loadCustomers() {
    try {
      const data = await getMasterCustomers();
      setCustomers(data);
    } catch {
      // ignore
    }
  }

  // Load parts list with filters
  async function loadParts() {
    setLoading(true);
    setListError("");
    try {
      const res = await getMasterParts({
        customer_code: selectedCustomer || undefined,
        status: selectedStatus !== "ALL" ? selectedStatus : undefined,
        search: search.trim() || undefined,
        page,
        limit,
      });
      setParts(res.items);
      setTotalCount(res.total);
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load parts.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadKPIs();
    loadCustomers();
  }, []);

  useEffect(() => {
    loadParts();
  }, [selectedCustomer, selectedStatus, search, page]);

  // Selected customer object for Add form
  const currentAddCustomer = useMemo(() => {
    return customers.find((c) => c.customer_code === addCustomerCode);
  }, [customers, addCustomerCode]);

  async function handleCreatePart(e: React.FormEvent) {
    e.preventDefault();
    setAddError("");
    setAdding(true);
    try {
      const created = await createMasterPart({
        customer_code: addCustomerCode,
        customer_part_number: addCustomerPartNo.trim(),
        status: addStatus,
        description: addDescription.trim() || undefined,
      });
      setSuccessCreated(created);
      setAddCustomerPartNo("");
      setAddDescription("");
      loadKPIs();
      loadParts();
    } catch (err: any) {
      setAddError(err?.response?.data?.detail || "Could not create part.");
    } finally {
      setAdding(false);
    }
  }

  function openEditModal(p: MasterPart) {
    setEditingPart(p);
    setEditCustomerPartNo(p.customer_part_number);
    setEditStatus(p.status);
    setEditDescription(p.description || "");
    setEditError("");
  }

  async function handleUpdatePart(e: React.FormEvent) {
    e.preventDefault();
    if (!editingPart) return;
    setEditError("");
    setSaving(true);
    try {
      await updateMasterPart(editingPart.id, {
        customer_part_number: editCustomerPartNo.trim(),
        status: editStatus,
        description: editDescription.trim() || undefined,
      });
      setEditingPart(null);
      loadKPIs();
      loadParts();
    } catch (err: any) {
      setEditError(err?.response?.data?.detail || "Could not update part.");
    } finally {
      setSaving(false);
    }
  }

  const totalPages = Math.ceil(totalCount / limit) || 1;

  return (
    <AppShell>
      <div className="max-w-7xl mx-auto space-y-6 pb-12">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <span className="rounded-md bg-indigo-600 px-2.5 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Masters
            </span>
            <h1 className="text-2xl font-black tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Part Master
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Authoritative Finished Part Master linking Customer Part Numbers to auto-generated Unique Internal Codes.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                loadKPIs();
                loadParts();
              }}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              onClick={() => {
                setShowAddModal(true);
                setAddError("");
                setSuccessCreated(null);
              }}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 shadow-md shadow-indigo-600/20 transition"
            >
              <Plus className="h-4 w-4" />
              Add New Part
            </button>
          </div>
        </div>

        {/* KPI Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Total Parts</span>
              <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400">
                <Layers className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-3">
              <span className="text-2xl font-black text-zinc-900 dark:text-zinc-50">
                {kpiLoading ? "..." : kpis.total_parts.toLocaleString()}
              </span>
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Active Parts</span>
              <div className="p-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-3">
              <span className="text-2xl font-black text-emerald-600 dark:text-emerald-400">
                {kpiLoading ? "..." : kpis.active_parts.toLocaleString()}
              </span>
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Registered Customers</span>
              <div className="p-2 rounded-xl bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400">
                <Building2 className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-3">
              <span className="text-2xl font-black text-zinc-900 dark:text-zinc-50">
                {kpiLoading ? "..." : kpis.total_customers.toLocaleString()}
              </span>
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">Inactive / Obsolete</span>
              <div className="p-2 rounded-xl bg-amber-50 dark:bg-amber-950/50 text-amber-600 dark:text-amber-400">
                <AlertTriangle className="h-4 w-4" />
              </div>
            </div>
            <div className="mt-3">
              <span className="text-2xl font-black text-amber-600 dark:text-amber-400">
                {kpiLoading ? "..." : (kpis.total_parts - kpis.active_parts).toLocaleString()}
              </span>
            </div>
          </div>
        </div>

        {/* Filters & Search */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {/* Search Input */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-400" />
              <input
                type="text"
                placeholder="Search Customer Part No, Internal Code, Customer..."
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
                className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>

            {/* Customer Filter */}
            <div>
              <select
                value={selectedCustomer}
                onChange={(e) => {
                  setSelectedCustomer(e.target.value);
                  setPage(1);
                }}
                className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                <option value="">All Customers</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.customer_code}>
                    {c.customer_code} — {c.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Status Filter */}
            <div className="flex items-center gap-1.5">
              {["ALL", "Active", "Obsolete", "ECR"].map((st) => (
                <button
                  key={st}
                  onClick={() => {
                    setSelectedStatus(st);
                    setPage(1);
                  }}
                  className={`flex-1 py-2 text-xs font-semibold rounded-xl border transition ${
                    selectedStatus === st
                      ? "bg-indigo-600 border-indigo-600 text-white shadow-sm"
                      : "border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  }`}
                >
                  {st}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Error Banner */}
        {listError && (
          <div className="rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50 dark:bg-rose-950/30 p-4 text-xs font-medium text-rose-700 dark:text-rose-300 flex items-center gap-2">
            <XCircle className="h-4 w-4 shrink-0" />
            {listError}
          </div>
        )}

        {/* Data Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 border-b border-zinc-200 dark:border-zinc-800 text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
                <tr>
                  <th className="py-3 px-4">Unique Internal Code</th>
                  <th className="py-3 px-4">Customer Part No. (Col G)</th>
                  <th className="py-3 px-4">Customer</th>
                  <th className="py-3 px-4">Customer Code</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-zinc-400">
                      <RefreshCw className="h-5 w-5 animate-spin mx-auto mb-2 text-indigo-500" />
                      Loading Part Master records...
                    </td>
                  </tr>
                ) : parts.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-zinc-500">
                      No part records found matching your filters.
                    </td>
                  </tr>
                ) : (
                  parts.map((p) => {
                    const statusLower = (p.status || "").toLowerCase();
                    return (
                      <tr
                        key={p.id}
                        className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/30 transition-colors"
                      >
                        {/* Unique Internal Code */}
                        <td className="py-3 px-4 font-mono font-bold text-indigo-600 dark:text-indigo-400">
                          <span className="px-2.5 py-1 rounded-md bg-indigo-50 dark:bg-indigo-950/60 border border-indigo-200 dark:border-indigo-900">
                            {p.part_number}
                          </span>
                        </td>

                        {/* Customer Part No. */}
                        <td className="py-3 px-4 font-mono font-semibold text-zinc-900 dark:text-zinc-100">
                          {p.customer_part_number}
                        </td>

                        {/* Customer Name */}
                        <td className="py-3 px-4 text-zinc-700 dark:text-zinc-300">
                          {p.customer_name}
                        </td>

                        {/* Customer Code */}
                        <td className="py-3 px-4 font-mono text-zinc-600 dark:text-zinc-400">
                          <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 font-semibold">
                            {p.customer_code}
                          </span>
                        </td>

                        {/* Status */}
                        <td className="py-3 px-4">
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold ${
                              statusLower === "active"
                                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800"
                                : statusLower === "ecr"
                                ? "bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-400 border border-amber-300 dark:border-amber-800"
                                : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-400 border border-zinc-300 dark:border-zinc-700"
                            }`}
                          >
                            {p.status || "Active"}
                          </span>
                        </td>

                        {/* Actions */}
                        <td className="py-3 px-4 text-right">
                          <button
                            onClick={() => openEditModal(p)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition"
                          >
                            <Edit2 className="h-3 w-3 text-zinc-500" />
                            Edit
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination Footer */}
          <div className="flex items-center justify-between px-4 py-3 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900/50">
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              Showing <span className="font-semibold">{parts.length}</span> of{" "}
              <span className="font-semibold">{totalCount.toLocaleString()}</span> parts
            </span>
            <div className="flex items-center gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 disabled:opacity-50 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition"
              >
                Previous
              </button>
              <span className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
                Page {page} of {totalPages}
              </span>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                className="px-3 py-1.5 text-xs font-semibold rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 disabled:opacity-50 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition"
              >
                Next
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ADD PART MODAL */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="w-full max-w-lg rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400">
                  <Layers className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    Add New Part Master Record
                  </h2>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
                    Internal code is auto-generated per customer.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowAddModal(false)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* Success Feedback Alert */}
            {successCreated && (
              <div className="rounded-xl border border-emerald-200 dark:border-emerald-900/50 bg-emerald-50 dark:bg-emerald-950/40 p-3.5 space-y-1">
                <div className="flex items-center gap-2 text-xs font-bold text-emerald-800 dark:text-emerald-300">
                  <CheckCircle2 className="h-4 w-4" />
                  Part Successfully Created!
                </div>
                <p className="text-xs text-emerald-700 dark:text-emerald-400">
                  Generated Unique Internal Code:{" "}
                  <span className="font-mono font-black text-sm text-emerald-900 dark:text-emerald-200 bg-emerald-200/60 dark:bg-emerald-900/60 px-2 py-0.5 rounded">
                    {successCreated.part_number}
                  </span>{" "}
                  for customer {successCreated.customer_code} ({successCreated.customer_part_number}).
                </p>
              </div>
            )}

            {/* Error Alert */}
            {addError && (
              <div className="rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs font-medium text-rose-700 dark:text-rose-300 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {addError}
              </div>
            )}

            <form onSubmit={handleCreatePart} className="space-y-4 text-xs">
              {/* Step 1: Customer Selection */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="font-bold text-zinc-700 dark:text-zinc-300">
                    Step 1: Select Customer <span className="text-rose-500">*</span>
                  </label>
                  <Link
                    href="/masters/customers"
                    className="text-[11px] font-semibold text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 flex items-center gap-1"
                  >
                    <Building2 className="h-3 w-3" />
                    Create Customer
                    <ExternalLink className="h-2.5 w-2.5" />
                  </Link>
                </div>
                <select
                  required
                  value={addCustomerCode}
                  onChange={(e) => setAddCustomerCode(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">-- Choose Existing Customer --</option>
                  {customers.map((c) => (
                    <option key={c.id} value={c.customer_code}>
                      {c.customer_code} — {c.name}
                    </option>
                  ))}
                </select>
                {currentAddCustomer && (
                  <p className="text-[11px] text-zinc-500 mt-1">
                    Customer Name: <span className="font-medium text-zinc-700 dark:text-zinc-300">{currentAddCustomer.name}</span>
                  </p>
                )}
              </div>

              {/* Step 2: Customer Part Number */}
              <div>
                <label className="block font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                  Step 2: Customer Part No. (from Column G) <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. RC47NN135000000092 or H00D035800"
                  value={addCustomerPartNo}
                  onChange={(e) => setAddCustomerPartNo(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-[11px] text-zinc-500 mt-1">
                  Preserve exact casing, hyphens, spaces, and punctuation.
                </p>
              </div>

              {/* Step 3: Status */}
              <div>
                <label className="block font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                  Step 3: Status
                </label>
                <select
                  value={addStatus}
                  onChange={(e) => setAddStatus(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="Active">Active</option>
                  <option value="Obsolete">Obsolete</option>
                  <option value="ECR">ECR (Engg Change)</option>
                </select>
              </div>

              {/* Step 4: Auto-generation Preview (Read-Only) */}
              <div className="rounded-xl border border-indigo-100 dark:border-indigo-950/60 bg-indigo-50/50 dark:bg-indigo-950/20 p-3 space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-bold text-indigo-900 dark:text-indigo-300">
                  <Info className="h-3.5 w-3.5 text-indigo-500" />
                  Step 4: Unique Internal Code Generation
                </div>
                <p className="text-[11px] text-indigo-700 dark:text-indigo-400">
                  {addCustomerCode ? (
                    <>
                      System will automatically compute next sequence for customer{" "}
                      <span className="font-mono font-bold">{addCustomerCode}</span> on submit (e.g.{" "}
                      <span className="font-mono font-bold">{addCustomerCode}X</span>).
                    </>
                  ) : (
                    "Select a customer above to preview sequence."
                  )}
                </p>
                <p className="text-[10px] text-zinc-500 dark:text-zinc-500 italic">
                  Internal code is strictly server-generated and cannot be typed or altered manually.
                </p>
              </div>

              {/* Buttons */}
              <div className="flex items-center justify-end gap-3 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition"
                >
                  Close
                </button>
                <button
                  type="submit"
                  disabled={adding || !addCustomerCode || !addCustomerPartNo.trim()}
                  className="inline-flex items-center gap-1.5 px-5 py-2 text-xs font-bold rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 shadow-md shadow-indigo-600/20 transition"
                >
                  {adding ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                  {adding ? "Generating Part..." : "Create Part Master"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT PART MODAL */}
      {editingPart && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="w-full max-w-lg rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-2xl space-y-5">
            <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                  <Edit2 className="h-5 w-5" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    Edit Part Master Record
                  </h2>
                  <p className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono">
                    Internal Code: {editingPart.part_number}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setEditingPart(null)}
                className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {editError && (
              <div className="rounded-xl border border-rose-200 dark:border-rose-900/50 bg-rose-50 dark:bg-rose-950/40 p-3 text-xs font-medium text-rose-700 dark:text-rose-300 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                {editError}
              </div>
            )}

            <form onSubmit={handleUpdatePart} className="space-y-4 text-xs">
              {/* Unique Internal Code (Read-Only) */}
              <div>
                <label className="block font-bold text-zinc-500 mb-1">
                  Unique Internal Code (Immutable)
                </label>
                <input
                  type="text"
                  disabled
                  value={editingPart.part_number}
                  className="w-full px-3 py-2 text-xs font-mono font-bold rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-800 text-zinc-500 cursor-not-allowed"
                />
              </div>

              {/* Customer (Read-Only) */}
              <div>
                <label className="block font-bold text-zinc-500 mb-1">
                  Customer
                </label>
                <input
                  type="text"
                  disabled
                  value={`${editingPart.customer_code} — ${editingPart.customer_name}`}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-800 text-zinc-500 cursor-not-allowed"
                />
              </div>

              {/* Customer Part Number */}
              <div>
                <label className="block font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                  Customer Part No. <span className="text-rose-500">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={editCustomerPartNo}
                  onChange={(e) => setEditCustomerPartNo(e.target.value)}
                  className="w-full px-3 py-2 text-xs font-mono rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Status */}
              <div>
                <label className="block font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                  Status
                </label>
                <select
                  value={editStatus}
                  onChange={(e) => setEditStatus(e.target.value)}
                  className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="Active">Active</option>
                  <option value="Obsolete">Obsolete</option>
                  <option value="ECR">ECR (Engg Change)</option>
                </select>
              </div>

              {/* Buttons */}
              <div className="flex items-center justify-end gap-3 pt-2 border-t border-zinc-100 dark:border-zinc-800">
                <button
                  type="button"
                  onClick={() => setEditingPart(null)}
                  className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={saving || !editCustomerPartNo.trim()}
                  className="inline-flex items-center gap-1.5 px-5 py-2 text-xs font-bold rounded-xl bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 shadow-md shadow-indigo-600/20 transition"
                >
                  {saving ? <RefreshCw className="h-3.5 w-3.5 animate-spin" /> : null}
                  {saving ? "Saving Changes..." : "Save Changes"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </AppShell>
  );
}

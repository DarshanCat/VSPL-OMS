"use client";

import React, { useEffect, useState, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getPartCrossReferences,
  getMasterCustomers,
  getParts,
  createPartCrossReference,
  updatePartCrossReference,
  CustomerPartCrossReferenceOut,
  MasterCustomer,
  AdminPart,
} from "@/lib/api";
import {
  Layers,
  Building2,
  Search,
  Plus,
  Filter,
  ArrowRight,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileSpreadsheet,
  Check,
  X,
  RefreshCw,
  Edit2,
  ShieldCheck,
  ExternalLink,
} from "lucide-react";
import Link from "next/link";

function PartMasterContent() {
  const searchParams = useSearchParams();
  const initialCustomerCode = searchParams.get("customer_code") || "";

  const [mappings, setMappings] = useState<CustomerPartCrossReferenceOut[]>([]);
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [internalParts, setInternalParts] = useState<AdminPart[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Filters
  const [search, setSearch] = useState("");
  const [customerFilter, setCustomerFilter] = useState(initialCustomerCode);
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "inactive">("all");

  // Add / Edit Modal State
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [formSubmitting, setFormSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const [formCustomerCode, setFormCustomerCode] = useState("");
  const [formCustomerPartNo, setFormCustomerPartNo] = useState("");
  const [formInternalPartCode, setFormInternalPartCode] = useState("");
  const [formIsActive, setFormIsActive] = useState(true);

  // Status toggle in-progress row
  const [busyRowId, setBusyRowId] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError("");
    try {
      const [refsData, custsData, partsData] = await Promise.all([
        getPartCrossReferences({
          search: search.trim() || undefined,
          customer_code: customerFilter || undefined,
          limit: 500,
        }),
        getMasterCustomers().catch(() => []),
        getParts().catch(() => []),
      ]);
      setMappings(refsData);
      setCustomers(custsData);
      setInternalParts(partsData);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not load Part Master data.");
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

  // Selected internal part details preview for modal
  const selectedPartDetails = useMemo(() => {
    if (!formInternalPartCode) return null;
    return internalParts.find(
      (p) => p.part_number.toLowerCase() === formInternalPartCode.trim().toLowerCase()
    );
  }, [formInternalPartCode, internalParts]);

  // Filtered mappings for status filter
  const displayedMappings = useMemo(() => {
    if (statusFilter === "all") return mappings;
    if (statusFilter === "active") return mappings.filter((m) => m.is_active);
    return mappings.filter((m) => !m.is_active);
  }, [mappings, statusFilter]);

  // Statistics
  const stats = useMemo(() => {
    const total = mappings.length;
    const activeCount = mappings.filter((m) => m.is_active).length;
    const distinctCustomers = new Set(mappings.map((m) => m.customer_code)).size;
    const distinctInternalParts = new Set(mappings.map((m) => m.internal_part_code)).size;
    return {
      total,
      activeCount,
      distinctCustomers,
      distinctInternalParts,
    };
  }, [mappings]);

  const openAddModal = () => {
    setIsEditing(false);
    setEditId(null);
    setFormCustomerCode(customerFilter || (customers[0]?.customer_code || ""));
    setFormCustomerPartNo("");
    setFormInternalPartCode("");
    setFormIsActive(true);
    setFormError("");
    setIsModalOpen(true);
  };

  const openEditModal = (item: CustomerPartCrossReferenceOut) => {
    setIsEditing(true);
    setEditId(item.id);
    setFormCustomerCode(item.customer_code);
    setFormCustomerPartNo(item.customer_part_no);
    setFormInternalPartCode(item.internal_part_code);
    setFormIsActive(item.is_active);
    setFormError("");
    setIsModalOpen(true);
  };

  const handleModalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    setFormSubmitting(true);

    try {
      if (isEditing && editId) {
        await updatePartCrossReference(editId, {
          internal_part_code: formInternalPartCode.trim(),
          is_active: formIsActive,
        });
        setSuccessMsg(`Successfully updated Part Master mapping for ${formCustomerPartNo}`);
      } else {
        await createPartCrossReference({
          customer_code: formCustomerCode.trim(),
          customer_part_no: formCustomerPartNo.trim(),
          internal_part_code: formInternalPartCode.trim(),
          is_active: formIsActive,
        });
        setSuccessMsg(`Successfully linked ${formCustomerPartNo} under ${formCustomerCode}`);
      }
      setIsModalOpen(false);
      await loadData();
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || "Failed to save Part Master entry.");
    } finally {
      setFormSubmitting(false);
    }
  };

  const handleToggleStatus = async (item: CustomerPartCrossReferenceOut) => {
    setBusyRowId(item.id);
    try {
      await updatePartCrossReference(item.id, {
        is_active: !item.is_active,
      });
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to update status.");
    } finally {
      setBusyRowId(null);
    }
  };

  return (
    <AppShell>
      <div className="max-w-7xl mx-auto space-y-6">
        {/* Header and Hierarchy Breadcrumb */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Masters
              </span>
              <span className="text-zinc-400 dark:text-zinc-500 text-xs">•</span>
              <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400 font-medium">
                <Link href="/masters/customers" className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
                  Customer Master
                </Link>
                <ArrowRight className="h-3 w-3" />
                <span className="text-zinc-900 dark:text-zinc-100 font-semibold">Part Master</span>
              </div>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 flex items-center gap-2.5">
              <Layers className="h-6 w-6 text-blue-600" />
              Part Master
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              Customer-linked Part Master: Customer Part Numbers mapped to authoritative Internal Parts, auto-populating Grade, Description, and manufacturing routes.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={loadData}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              onClick={openAddModal}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-500 shadow-sm transition-colors"
            >
              <Plus className="h-4 w-4" />
              Link New Part
            </button>
          </div>
        </div>

        {/* Global Notifications */}
        {error && (
          <div className="flex items-start gap-2 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 p-3.5 text-xs text-rose-700 dark:text-rose-300">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        {successMsg && (
          <div className="flex items-start gap-2 rounded-xl bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900/50 p-3.5 text-xs text-emerald-700 dark:text-emerald-300">
            <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{successMsg}</span>
          </div>
        )}

        {/* Statistics Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">Total Customer Parts</div>
            <div className="text-2xl font-black text-zinc-900 dark:text-zinc-50 mt-1">{stats.total.toLocaleString()}</div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">Authoritative active mappings</div>
          </div>
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">Mapped Customers</div>
            <div className="text-2xl font-black text-blue-600 dark:text-blue-400 mt-1">{stats.distinctCustomers}</div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">Customer accounts linked</div>
          </div>
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">Internal Parts Linked</div>
            <div className="text-2xl font-black text-indigo-600 dark:text-indigo-400 mt-1">{stats.distinctInternalParts}</div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">Authoritative Part Master codes</div>
          </div>
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">Active Status</div>
            <div className="text-2xl font-black text-emerald-600 dark:text-emerald-400 mt-1">
              {stats.total > 0 ? `${Math.round((stats.activeCount / stats.total) * 100)}%` : "100%"}
            </div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">{stats.activeCount} active mappings</div>
          </div>
        </div>

        {/* Business Rule / Architecture Banner */}
        <div className="rounded-2xl border border-blue-100 dark:border-blue-900/40 bg-blue-50/60 dark:bg-blue-950/20 p-4 flex items-start gap-3">
          <ShieldCheck className="h-5 w-5 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div className="text-xs text-blue-900 dark:text-blue-200 leading-relaxed">
            <span className="font-bold">Authoritative Part Relationship:</span> Each entry establishes a unique link between a <span className="font-semibold">Customer</span> and their <span className="font-semibold">Customer Part Number</span> to the authoritative <span className="font-semibold">Internal Part</span>. In Order Intake (OAR), selecting a customer and typing the customer part number automatically resolves the route, grade, and description.
          </div>
        </div>

        {/* Filters and Controls */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm space-y-3">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            {/* Search Form */}
            <form onSubmit={handleSearchSubmit} className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by Customer Part No, Internal Part, Description, Grade, or Customer..."
                className="w-full pl-9 pr-20 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-transparent text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
              <button
                type="submit"
                className="absolute right-1.5 top-1.5 px-3 py-1 text-[11px] font-bold rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
              >
                Search
              </button>
            </form>

            {/* Customer Filter */}
            <div className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-zinc-400 shrink-0" />
              <select
                value={customerFilter}
                onChange={(e) => setCustomerFilter(e.target.value)}
                className="py-2 px-3 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              >
                <option value="">All Customers ({customers.length})</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.customer_code}>
                    {c.customer_code} - {c.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Status Filter */}
            <div className="flex items-center rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60 p-0.5 text-xs font-semibold">
              <button
                type="button"
                onClick={() => setStatusFilter("all")}
                className={`px-3 py-1.5 rounded-lg transition-colors ${
                  statusFilter === "all"
                    ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                }`}
              >
                All
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter("active")}
                className={`px-3 py-1.5 rounded-lg transition-colors ${
                  statusFilter === "active"
                    ? "bg-white dark:bg-zinc-900 text-emerald-600 dark:text-emerald-400 shadow-xs"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                }`}
              >
                Active
              </button>
              <button
                type="button"
                onClick={() => setStatusFilter("inactive")}
                className={`px-3 py-1.5 rounded-lg transition-colors ${
                  statusFilter === "inactive"
                    ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                }`}
              >
                Inactive
              </button>
            </div>
          </div>
        </div>

        {/* Data Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-blue-500" />
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                Customer-Linked Parts
              </h3>
              <span className="text-xs text-zinc-400 font-normal">
                ({displayedMappings.length} items listed)
              </span>
            </div>
            {customerFilter && (
              <button
                onClick={() => setCustomerFilter("")}
                className="text-[11px] font-medium text-blue-600 hover:underline flex items-center gap-1"
              >
                Clear filter ({customerFilter})
              </button>
            )}
          </div>

          {loading ? (
            <div className="p-12 text-center text-xs text-zinc-500">
              <RefreshCw className="h-6 w-6 animate-spin mx-auto text-blue-500 mb-2" />
              Loading Part Master records...
            </div>
          ) : displayedMappings.length === 0 ? (
            <div className="p-12 text-center text-xs text-zinc-500">
              No Part Master records found matching your filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                  <tr>
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Customer Part No</th>
                    <th className="px-4 py-3">Internal Part No</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3">Grade</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {displayedMappings.map((m) => (
                    <tr key={m.id} className="hover:bg-zinc-50/70 dark:hover:bg-zinc-800/40 transition-colors">
                      {/* Customer */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold px-2 py-0.5 rounded-md bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 text-[11px]">
                            {m.customer_code}
                          </span>
                          <span className="text-zinc-700 dark:text-zinc-300 font-medium truncate max-w-[150px]">
                            {m.customer_name}
                          </span>
                        </div>
                      </td>

                      {/* Customer Part No */}
                      <td className="px-4 py-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                        {m.customer_part_no}
                      </td>

                      {/* Internal Part No */}
                      <td className="px-4 py-3">
                        <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400">
                          {m.internal_part_code}
                        </span>
                      </td>

                      {/* Description */}
                      <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">
                        {m.part_description || <span className="text-zinc-400 italic">-</span>}
                      </td>

                      {/* Grade */}
                      <td className="px-4 py-3">
                        {m.part_grade ? (
                          <span className="px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 text-[10px] font-bold border border-amber-200 dark:border-amber-900/40">
                            {m.part_grade}
                          </span>
                        ) : (
                          <span className="text-zinc-400 italic">-</span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${
                            m.is_active
                              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400"
                              : "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                          }`}
                        >
                          {m.is_active ? (
                            <>
                              <CheckCircle2 className="h-3 w-3" />
                              Active
                            </>
                          ) : (
                            <>
                              <XCircle className="h-3 w-3" />
                              Inactive
                            </>
                          )}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => openEditModal(m)}
                            className="p-1 rounded-lg text-zinc-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/40 transition-colors"
                            title="Edit Internal Part Mapping"
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                          </button>
                          <button
                            type="button"
                            disabled={busyRowId === m.id}
                            onClick={() => handleToggleStatus(m)}
                            className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                          >
                            {m.is_active ? "Deactivate" : "Activate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Modal: Link / Edit Part Master Entry */}
        {isModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4">
            <div className="w-full max-w-lg rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-2xl p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
                <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50 flex items-center gap-2">
                  <Layers className="h-5 w-5 text-blue-600" />
                  {isEditing ? "Edit Part Master Mapping" : "Link Part to Customer"}
                </h3>
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="p-1 rounded-lg text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {formError && (
                <div className="flex items-start gap-2 rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 p-3 text-xs text-rose-700 dark:text-rose-300">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{formError}</span>
                </div>
              )}

              <form onSubmit={handleModalSubmit} className="space-y-4">
                {/* Customer */}
                <div>
                  <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                    Customer
                  </label>
                  {isEditing ? (
                    <div className="px-3 py-2 text-xs font-bold rounded-xl bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 font-mono">
                      {formCustomerCode}
                    </div>
                  ) : (
                    <select
                      required
                      value={formCustomerCode}
                      onChange={(e) => setFormCustomerCode(e.target.value)}
                      className="w-full py-2 px-3 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                    >
                      <option value="">Select a Customer...</option>
                      {customers.map((c) => (
                        <option key={c.id} value={c.customer_code}>
                          {c.customer_code} - {c.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>

                {/* Customer Part No */}
                <div>
                  <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                    Customer Part Number
                  </label>
                  <input
                    required
                    disabled={isEditing}
                    type="text"
                    value={formCustomerPartNo}
                    onChange={(e) => setFormCustomerPartNo(e.target.value)}
                    placeholder="e.g. 50401234, CUST-BRK-01"
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-transparent text-zinc-900 dark:text-zinc-100 font-mono disabled:bg-zinc-100 dark:disabled:bg-zinc-800 disabled:opacity-75 focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                {/* Internal Part No */}
                <div>
                  <label className="block text-xs font-bold text-zinc-700 dark:text-zinc-300 mb-1">
                    Authoritative Internal Part No
                  </label>
                  <input
                    required
                    type="text"
                    value={formInternalPartCode}
                    onChange={(e) => setFormInternalPartCode(e.target.value)}
                    placeholder="e.g. 1001-A, F1-HUB-01"
                    list="internal-parts-list"
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-transparent text-zinc-900 dark:text-zinc-100 font-mono focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                  <datalist id="internal-parts-list">
                    {internalParts.map((p) => (
                      <option key={p.id} value={p.part_number}>
                        {p.part_number} {p.description ? `- ${p.description}` : ""} {p.grade ? `(${p.grade})` : ""}
                      </option>
                    ))}
                  </datalist>
                </div>

                {/* Part Details Preview */}
                {selectedPartDetails && (
                  <div className="rounded-xl bg-indigo-50/60 dark:bg-indigo-950/30 border border-indigo-100 dark:border-indigo-900/40 p-3 text-xs space-y-1">
                    <div className="font-semibold text-indigo-900 dark:text-indigo-200">
                      Authoritative Part Details:
                    </div>
                    <div className="text-zinc-600 dark:text-zinc-400">
                      Description: <span className="font-medium text-zinc-800 dark:text-zinc-200">{selectedPartDetails.description || "-"}</span>
                    </div>
                    <div className="text-zinc-600 dark:text-zinc-400">
                      Grade: <span className="font-medium text-zinc-800 dark:text-zinc-200">{selectedPartDetails.grade || "-"}</span>
                    </div>
                  </div>
                )}

                {/* Status Toggle */}
                <div className="flex items-center gap-2 pt-1">
                  <input
                    type="checkbox"
                    id="is_active_toggle"
                    checked={formIsActive}
                    onChange={(e) => setFormIsActive(e.target.checked)}
                    className="rounded text-blue-600 focus:ring-blue-500"
                  />
                  <label htmlFor="is_active_toggle" className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                    Active Mapping
                  </label>
                </div>

                <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
                  <button
                    type="button"
                    onClick={() => setIsModalOpen(false)}
                    className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={formSubmitting}
                    className="px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60 transition-colors shadow-sm"
                  >
                    {formSubmitting ? "Saving..." : isEditing ? "Update Mapping" : "Save Part Master Entry"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

export default function PartMasterPage() {
  return (
    <Suspense
      fallback={
        <AppShell>
          <div className="p-12 text-center text-xs text-zinc-500">
            <RefreshCw className="h-6 w-6 animate-spin mx-auto text-blue-500 mb-2" />
            Loading Part Master...
          </div>
        </AppShell>
      }
    >
      <PartMasterContent />
    </Suspense>
  );
}

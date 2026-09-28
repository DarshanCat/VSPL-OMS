"use client";

import React, { useEffect, useState, useMemo, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getMasterParts,
  getMasterPart,
  createMasterPart,
  updateMasterPart,
  getMasterCustomers,
  createPartCrossReference,
  updatePartCrossReference,
  PartMasterItemOut,
  PartMasterStats,
  MasterCustomer,
} from "@/lib/api";
import {
  Layers,
  Building2,
  Search,
  Plus,
  ArrowRight,
  CheckCircle2,
  AlertTriangle,
  FileSpreadsheet,
  Check,
  X,
  RefreshCw,
  Edit2,
  ShieldCheck,
  Link as LinkIcon,
  ChevronRight,
  Eye,
  Tag,
  Package,
} from "lucide-react";
import Link from "next/link";

function PartMasterContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlCustomerCode = searchParams.get("customer_code") || "";
  const urlMappingStatus = (searchParams.get("mapping_status") as "all" | "mapped" | "unmapped") || "all";
  const urlSearch = searchParams.get("search") || "";

  const [parts, setParts] = useState<PartMasterItemOut[]>([]);
  const [totalCount, setTotalCount] = useState<number>(0);
  const [stats, setStats] = useState<PartMasterStats | null>(null);
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Filter States
  const [search, setSearch] = useState(urlSearch);
  const [customerFilter, setCustomerFilter] = useState(urlCustomerCode);
  const [mappingStatus, setMappingStatus] = useState<"all" | "mapped" | "unmapped">(urlMappingStatus);

  // Detail / Drawer State for Selected Part
  const [selectedPart, setSelectedPart] = useState<PartMasterItemOut | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Add / Edit Part Modal State
  const [isPartModalOpen, setIsPartModalOpen] = useState(false);
  const [isEditingPart, setIsEditingPart] = useState(false);
  const [editPartId, setEditPartId] = useState<string | null>(null);
  const [formPartNumber, setFormPartNumber] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formGrade, setFormGrade] = useState("");
  const [partSubmitting, setPartSubmitting] = useState(false);
  const [partError, setPartError] = useState("");

  // Link Customer Part Modal State
  const [isLinkModalOpen, setIsLinkModalOpen] = useState(false);
  const [linkInternalPartCode, setLinkInternalPartCode] = useState("");
  const [linkCustomerCode, setLinkCustomerCode] = useState("");
  const [linkCustomerPartNo, setLinkCustomerPartNo] = useState("");
  const [linkIsActive, setLinkIsActive] = useState(true);
  const [linkSubmitting, setLinkSubmitting] = useState(false);
  const [linkError, setLinkError] = useState("");

  // Row status toggle state
  const [busyRowId, setBusyRowId] = useState<string | null>(null);

  // Sync state when URL query params change (e.g. from Customer Master navigation)
  useEffect(() => {
    const pCust = searchParams.get("customer_code") || "";
    const pStatus = (searchParams.get("mapping_status") as "all" | "mapped" | "unmapped") || "all";
    const pSearch = searchParams.get("search") || "";

    if (pCust !== customerFilter) setCustomerFilter(pCust);
    if (pStatus !== mappingStatus) setMappingStatus(pStatus);
    if (pSearch !== search) setSearch(pSearch);
  }, [searchParams]);

  async function loadData(
    overrideCustomer?: string,
    overrideStatus?: "all" | "mapped" | "unmapped",
    overrideSearch?: string
  ) {
    setLoading(true);
    setError("");

    const activeCust = overrideCustomer !== undefined ? overrideCustomer : customerFilter;
    const activeStatus = overrideStatus !== undefined ? overrideStatus : mappingStatus;
    const activeSearch = overrideSearch !== undefined ? overrideSearch : search;

    try {
      const [partsRes, custsData] = await Promise.all([
        getMasterParts({
          search: activeSearch.trim() || undefined,
          customer_code: activeCust || undefined,
          mapping_status: activeStatus !== "all" ? activeStatus : undefined,
          limit: 500,
        }),
        getMasterCustomers().catch(() => []),
      ]);

      setParts(partsRes.items);
      setTotalCount(partsRes.total);
      if (partsRes.stats) {
        setStats(partsRes.stats);
      }
      setCustomers(custsData);

      // If drawer is open, refresh selected part from new items list
      if (selectedPart) {
        const updated = partsRes.items.find((p) => p.id === selectedPart.id);
        if (updated) setSelectedPart(updated);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not load Part Master data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData(customerFilter, mappingStatus);
  }, [customerFilter, mappingStatus]);

  const updateUrlFilters = (
    newCust: string,
    newStatus: "all" | "mapped" | "unmapped",
    newSearch: string
  ) => {
    const params = new URLSearchParams();
    if (newCust) params.set("customer_code", newCust);
    if (newStatus !== "all") params.set("mapping_status", newStatus);
    if (newSearch.trim()) params.set("search", newSearch.trim());

    const queryString = params.toString();
    const target = queryString ? `/masters/parts?${queryString}` : "/masters/parts";
    router.replace(target, { scroll: false });
  };

  const handleCustomerChange = (newCode: string) => {
    setCustomerFilter(newCode);
    updateUrlFilters(newCode, mappingStatus, search);
  };

  const handleStatusChange = (newStatus: "all" | "mapped" | "unmapped") => {
    setMappingStatus(newStatus);
    updateUrlFilters(customerFilter, newStatus, search);
  };

  const handleSearchSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    updateUrlFilters(customerFilter, mappingStatus, search);
    loadData(customerFilter, mappingStatus, search);
  };

  const handleClearAllFilters = () => {
    setCustomerFilter("");
    setMappingStatus("all");
    setSearch("");
    updateUrlFilters("", "all", "");
    loadData("", "all", "");
  };

  // Open Details Drawer
  const openPartDetails = (part: PartMasterItemOut) => {
    setSelectedPart(part);
    setDrawerOpen(true);
  };

  // Add Part Modal
  const openAddPartModal = () => {
    setIsEditingPart(false);
    setEditPartId(null);
    setFormPartNumber("");
    setFormDescription("");
    setFormGrade("");
    setPartError("");
    setIsPartModalOpen(true);
  };

  // Edit Part Modal
  const openEditPartModal = (part: PartMasterItemOut) => {
    setIsEditingPart(true);
    setEditPartId(part.id);
    setFormPartNumber(part.part_number);
    setFormDescription(part.description || "");
    setFormGrade(part.grade || "");
    setPartError("");
    setIsPartModalOpen(true);
  };

  const handlePartModalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setPartError("");
    setPartSubmitting(true);

    try {
      if (isEditingPart && editPartId) {
        await updateMasterPart(editPartId, {
          description: formDescription.trim() || undefined,
          grade: formGrade.trim() || undefined,
        });
        setSuccessMsg(`Successfully updated Internal Part ${formPartNumber}`);
      } else {
        await createMasterPart({
          part_number: formPartNumber.trim(),
          description: formDescription.trim() || undefined,
          grade: formGrade.trim() || undefined,
        });
        setSuccessMsg(`Successfully created Internal Part ${formPartNumber}`);
      }
      setIsPartModalOpen(false);
      await loadData();
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (err: any) {
      setPartError(err?.response?.data?.detail || "Failed to save Internal Part.");
    } finally {
      setPartSubmitting(false);
    }
  };

  // Open Link Customer Part Modal
  const openLinkModal = (partNumber?: string) => {
    setLinkInternalPartCode(partNumber || selectedPart?.part_number || "");
    setLinkCustomerCode(customerFilter || (customers[0]?.customer_code || ""));
    setLinkCustomerPartNo("");
    setLinkIsActive(true);
    setLinkError("");
    setIsLinkModalOpen(true);
  };

  const handleLinkModalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLinkError("");
    setLinkSubmitting(true);

    try {
      await createPartCrossReference({
        customer_code: linkCustomerCode.trim(),
        customer_part_no: linkCustomerPartNo.trim(),
        internal_part_code: linkInternalPartCode.trim(),
        is_active: linkIsActive,
      });
      setSuccessMsg(
        `Successfully mapped ${linkCustomerPartNo} (${linkCustomerCode}) → ${linkInternalPartCode}`
      );
      setIsLinkModalOpen(false);
      await loadData();
      if (selectedPart) {
        const refreshed = await getMasterPart(selectedPart.id);
        setSelectedPart(refreshed);
      }
      setTimeout(() => setSuccessMsg(""), 5000);
    } catch (err: any) {
      setLinkError(err?.response?.data?.detail || "Failed to link customer part.");
    } finally {
      setLinkSubmitting(false);
    }
  };

  const handleToggleMappingStatus = async (mappingId: string, currentActive: boolean) => {
    setBusyRowId(mappingId);
    try {
      await updatePartCrossReference(mappingId, {
        is_active: !currentActive,
      });
      await loadData();
      if (selectedPart) {
        const refreshed = await getMasterPart(selectedPart.id);
        setSelectedPart(refreshed);
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to toggle mapping status.");
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
                Authoritative Master
              </span>
              <span className="text-zinc-400 dark:text-zinc-500 text-xs">•</span>
              <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400 font-medium">
                <Link
                  href="/masters/customers"
                  className="hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
                >
                  Customer Master
                </Link>
                <ArrowRight className="h-3 w-3" />
                <span className="text-zinc-900 dark:text-zinc-100 font-semibold">Part Master</span>
              </div>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 flex items-center gap-2.5">
              <Layers className="h-6 w-6 text-blue-600" />
              Internal Part Master
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              Authoritative Internal Parts catalog with attached customer-specific part mappings (Grade, Description, and manufacturing routing).
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => loadData()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-700/60 transition-colors disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
            <button
              onClick={openAddPartModal}
              className="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-500 shadow-sm transition-colors"
            >
              <Plus className="h-4 w-4" />
              Add Internal Part
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

        {/* Summary KPI Cards */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">
              Total Internal Parts
            </div>
            <div className="text-2xl font-black text-zinc-900 dark:text-zinc-50 mt-1">
              {stats ? stats.total_parts.toLocaleString() : "..."}
            </div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">
              Authoritative Internal Parts
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">
              Mapped Internal Parts
            </div>
            <div className="text-2xl font-black text-blue-600 dark:text-blue-400 mt-1">
              {stats ? stats.mapped_parts.toLocaleString() : "..."}
            </div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">
              Parts with Customer PO mappings
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">
              Unmapped Internal Parts
            </div>
            <div className="text-2xl font-black text-amber-600 dark:text-amber-400 mt-1">
              {stats ? stats.unmapped_parts.toLocaleString() : "..."}
            </div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">
              Internal-only / unassigned
            </div>
          </div>

          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
            <div className="text-[11px] font-semibold text-zinc-500 dark:text-zinc-400">
              Customer Part Mappings
            </div>
            <div className="text-2xl font-black text-indigo-600 dark:text-indigo-400 mt-1">
              {stats ? stats.total_mappings.toLocaleString() : "..."}
            </div>
            <div className="text-[10px] text-zinc-400 dark:text-zinc-500 mt-0.5">
              Across {stats ? stats.total_customers : "..."} linked customers
            </div>
          </div>
        </div>

        {/* Business Rule / Architecture Banner */}
        <div className="rounded-2xl border border-blue-100 dark:border-blue-900/40 bg-blue-50/60 dark:bg-blue-950/20 p-4 flex items-start gap-3">
          <ShieldCheck className="h-5 w-5 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div className="text-xs text-blue-900 dark:text-blue-200 leading-relaxed">
            <span className="font-bold">Authoritative Architecture:</span> Layer 1 is the Complete <span className="font-semibold">Internal Part Master</span> (5,483 authoritative internal parts). Layer 2 is the <span className="font-semibold">Customer Part Mapping</span> relationship (1,890 cross-references) attached to these parts. In Order Intake, customer part numbers resolve to these internal parts automatically.
          </div>
        </div>

        {/* Filters and Search Toolbar */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm space-y-3">
          <div className="flex flex-col md:flex-row md:items-center gap-3">
            {/* Search Form */}
            <form onSubmit={handleSearchSubmit} className="relative flex-1">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-zinc-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search by Internal Part No, Description, Grade, Customer Part No, or Customer..."
                className="w-full pl-9 pr-20 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-transparent text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
              />
              <button
                type="submit"
                className="absolute right-1.5 top-1.5 px-3 py-1 text-[11px] font-bold rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
              >
                Search
              </button>
            </form>

            {/* Customer Filter Dropdown */}
            <div className="flex items-center gap-2">
              <Building2 className="h-4 w-4 text-zinc-400 shrink-0" />
              <select
                value={customerFilter}
                onChange={(e) => handleCustomerChange(e.target.value)}
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

            {/* Mapping Status Tabs */}
            <div className="flex items-center rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60 p-0.5 text-xs font-semibold">
              <button
                type="button"
                onClick={() => handleStatusChange("all")}
                className={`px-3 py-1.5 rounded-lg transition-colors ${
                  mappingStatus === "all"
                    ? "bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 shadow-xs"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                }`}
              >
                All Parts
              </button>
              <button
                type="button"
                onClick={() => handleStatusChange("mapped")}
                className={`px-3 py-1.5 rounded-lg transition-colors ${
                  mappingStatus === "mapped"
                    ? "bg-white dark:bg-zinc-900 text-blue-600 dark:text-blue-400 shadow-xs"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                }`}
              >
                Mapped
              </button>
              <button
                type="button"
                onClick={() => handleStatusChange("unmapped")}
                className={`px-3 py-1.5 rounded-lg transition-colors ${
                  mappingStatus === "unmapped"
                    ? "bg-white dark:bg-zinc-900 text-amber-600 dark:text-amber-400 shadow-xs"
                    : "text-zinc-600 dark:text-zinc-400 hover:text-zinc-900"
                }`}
              >
                Unmapped
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
                Authoritative Internal Parts
              </h3>
              <span className="text-xs text-zinc-400 font-normal">
                {totalCount > parts.length
                  ? `(Showing ${parts.length} of ${totalCount.toLocaleString()} items)`
                  : `(${totalCount.toLocaleString()} items listed)`}
              </span>
            </div>
            {(customerFilter || mappingStatus !== "all" || search) && (
              <button
                type="button"
                onClick={handleClearAllFilters}
                className="text-[11px] font-medium text-blue-600 hover:underline flex items-center gap-1"
              >
                Reset filters {customerFilter ? `(${customerFilter})` : ""}
              </button>
            )}
          </div>

          {loading ? (
            <div className="p-12 text-center text-xs text-zinc-500">
              <RefreshCw className="h-6 w-6 animate-spin mx-auto text-blue-500 mb-2" />
              Loading Authoritative Part Master records...
            </div>
          ) : parts.length === 0 ? (
            <div className="p-12 text-center text-xs text-zinc-500">
              No Internal Parts found matching your filters.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left">
                <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                  <tr>
                    <th className="px-4 py-3">Internal Part No</th>
                    <th className="px-4 py-3">Description</th>
                    <th className="px-4 py-3">Grade</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Customer Count</th>
                    <th className="px-4 py-3">Customer Part Count</th>
                    <th className="px-4 py-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {parts.map((p) => (
                    <tr
                      key={p.id}
                      className="hover:bg-zinc-50/70 dark:hover:bg-zinc-800/40 transition-colors"
                    >
                      {/* Internal Part No */}
                      <td className="px-4 py-3 font-mono font-bold text-indigo-600 dark:text-indigo-400">
                        <button
                          type="button"
                          onClick={() => openPartDetails(p)}
                          className="hover:underline flex items-center gap-1 text-left"
                        >
                          {p.part_number}
                          <ChevronRight className="h-3 w-3 opacity-60" />
                        </button>
                      </td>

                      {/* Description */}
                      <td className="px-4 py-3 text-zinc-700 dark:text-zinc-300 max-w-xs truncate">
                        {p.description || <span className="text-zinc-400 italic">-</span>}
                      </td>

                      {/* Grade */}
                      <td className="px-4 py-3">
                        {p.grade ? (
                          <span className="px-2 py-0.5 rounded-md bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 text-[10px] font-bold border border-amber-200 dark:border-amber-900/40">
                            {p.grade}
                          </span>
                        ) : (
                          <span className="text-zinc-400 italic">-</span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        <span className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400">
                          <Check className="h-3 w-3" /> Active
                        </span>
                      </td>

                      {/* Customer Count */}
                      <td className="px-4 py-3">
                        {p.customer_count > 0 ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-blue-50 dark:bg-blue-950/60 text-blue-700 dark:text-blue-300 text-[11px] font-semibold">
                            <Building2 className="h-3 w-3" />
                            {p.customer_count} {p.customer_count === 1 ? "customer" : "customers"}
                          </span>
                        ) : (
                          <span className="text-zinc-400 text-[11px]">0 customers</span>
                        )}
                      </td>

                      {/* Customer Part Count */}
                      <td className="px-4 py-3">
                        {p.mapping_count > 0 ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-purple-50 dark:bg-purple-950/60 text-purple-700 dark:text-purple-300 text-[11px] font-semibold">
                            <Tag className="h-3 w-3" />
                            {p.mapping_count} {p.mapping_count === 1 ? "mapping" : "mappings"}
                          </span>
                        ) : (
                          <span className="text-zinc-400 text-[11px]">0 mappings</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => openPartDetails(p)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
                            title="View Customer Mappings"
                          >
                            <Eye className="h-3 w-3" />
                            Mappings ({p.mapping_count})
                          </button>
                          <button
                            type="button"
                            onClick={() => openLinkModal(p.part_number)}
                            className="inline-flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
                            title="Link a customer part number to this internal part"
                          >
                            <LinkIcon className="h-3 w-3" />
                            + Link
                          </button>
                          <button
                            type="button"
                            onClick={() => openEditPartModal(p)}
                            className="inline-flex items-center gap-1 px-2 py-1 text-[11px] font-semibold rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
                            title="Edit Description & Grade"
                          >
                            <Edit2 className="h-3 w-3" />
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

        {/* Selected Part Drawer / Detail View */}
        {drawerOpen && selectedPart && (
          <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-end">
            <div className="bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 w-full max-w-2xl h-full p-6 overflow-y-auto space-y-6 shadow-2xl">
              {/* Header */}
              <div className="flex items-start justify-between border-b border-zinc-100 dark:border-zinc-800 pb-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-xl font-extrabold text-indigo-600 dark:text-indigo-400">
                      {selectedPart.part_number}
                    </span>
                    <span className="rounded-md bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400 px-2 py-0.5 text-[10px] font-bold uppercase">
                      Active
                    </span>
                  </div>
                  <p className="text-xs text-zinc-600 dark:text-zinc-400">
                    Authoritative Internal Part Specification & Linked Customer Mappings
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setDrawerOpen(false)}
                  className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 p-1"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {/* Part Properties */}
              <div className="grid grid-cols-2 gap-3 p-4 rounded-xl bg-zinc-50 dark:bg-zinc-800/50 border border-zinc-100 dark:border-zinc-800 text-xs">
                <div>
                  <span className="text-zinc-400 block text-[11px]">Grade</span>
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100 mt-0.5 inline-block">
                    {selectedPart.grade || "Not Specified"}
                  </span>
                </div>
                <div>
                  <span className="text-zinc-400 block text-[11px]">Description</span>
                  <span className="font-semibold text-zinc-900 dark:text-zinc-100 mt-0.5 inline-block">
                    {selectedPart.description || "-"}
                  </span>
                </div>
              </div>

              {/* Customer Mappings Section */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Building2 className="h-4 w-4 text-blue-600" />
                    <h4 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                      Customer Part Mappings ({selectedPart.customer_mappings.length})
                    </h4>
                  </div>
                  <button
                    type="button"
                    onClick={() => openLinkModal(selectedPart.part_number)}
                    className="inline-flex items-center gap-1 px-3 py-1.5 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-500 transition-colors shadow-xs"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    Link Customer Part
                  </button>
                </div>

                {selectedPart.customer_mappings.length === 0 ? (
                  <div className="p-8 text-center rounded-xl border border-dashed border-zinc-200 dark:border-zinc-800 text-xs text-zinc-400">
                    No customer mappings currently attached to this internal part.
                    <br />
                    Click <span className="font-semibold text-blue-600">+ Link Customer Part</span> to associate a Customer Part Number.
                  </div>
                ) : (
                  <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 overflow-hidden">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 font-semibold border-b border-zinc-100 dark:border-zinc-800">
                        <tr>
                          <th className="px-3 py-2.5">Customer</th>
                          <th className="px-3 py-2.5">Customer Part No</th>
                          <th className="px-3 py-2.5">Source</th>
                          <th className="px-3 py-2.5">Status</th>
                          <th className="px-3 py-2.5 text-right">Action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                        {selectedPart.customer_mappings.map((m) => (
                          <tr key={m.id} className="hover:bg-zinc-50/60 dark:hover:bg-zinc-800/30">
                            <td className="px-3 py-2.5">
                              <span className="font-mono font-bold text-blue-600">
                                {m.customer_code}
                              </span>
                              <span className="text-zinc-500 dark:text-zinc-400 text-[11px] block">
                                {m.customer_name}
                              </span>
                            </td>
                            <td className="px-3 py-2.5 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                              {m.customer_part_no}
                            </td>
                            <td className="px-3 py-2.5 text-zinc-500">{m.source || "Fdata"}</td>
                            <td className="px-3 py-2.5">
                              <span
                                className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${
                                  m.is_active
                                    ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/60 dark:text-emerald-400"
                                    : "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
                                }`}
                              >
                                {m.is_active ? "Active" : "Inactive"}
                              </span>
                            </td>
                            <td className="px-3 py-2.5 text-right">
                              <button
                                type="button"
                                disabled={busyRowId === m.id}
                                onClick={() => handleToggleMappingStatus(m.id, m.is_active)}
                                className="px-2 py-1 text-[10px] font-semibold rounded border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 transition-colors"
                              >
                                {m.is_active ? "Deactivate" : "Activate"}
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* Order Intake Resolution Note */}
              <div className="p-4 rounded-xl bg-indigo-50/60 dark:bg-indigo-950/20 border border-indigo-100 dark:border-indigo-900/40 text-xs text-indigo-900 dark:text-indigo-300">
                <span className="font-bold">Order Intake Behavior:</span> When an intake line is created with any of the mapped customer part numbers above, OMS Engine will automatically resolve to <span className="font-mono font-bold">{selectedPart.part_number}</span> and auto-populate Grade (<span className="font-semibold">{selectedPart.grade || "N/A"}</span>) and Description.
              </div>
            </div>
          </div>
        )}

        {/* Modal: Add / Edit Internal Part */}
        {isPartModalOpen && (
          <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
                <div className="flex items-center gap-2">
                  <Package className="h-5 w-5 text-blue-600" />
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    {isEditingPart ? "Edit Internal Part" : "Add Internal Part"}
                  </h3>
                </div>
                <button
                  onClick={() => setIsPartModalOpen(false)}
                  className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {partError && (
                <div className="rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 p-3 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{partError}</span>
                </div>
              )}

              <form onSubmit={handlePartModalSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                    Internal Part Number
                  </label>
                  <input
                    type="text"
                    value={formPartNumber}
                    disabled={isEditingPart}
                    onChange={(e) => setFormPartNumber(e.target.value)}
                    placeholder="e.g. PMC95 or ACC37"
                    required
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 disabled:opacity-60 font-mono font-bold"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                    Grade
                  </label>
                  <input
                    type="text"
                    value={formGrade}
                    onChange={(e) => setFormGrade(e.target.value)}
                    placeholder="e.g. SG 500-B, CuSn12, PB2"
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                    Description
                  </label>
                  <textarea
                    value={formDescription}
                    onChange={(e) => setFormDescription(e.target.value)}
                    placeholder="Dimensions / Component Description..."
                    rows={3}
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
                  <button
                    type="button"
                    onClick={() => setIsPartModalOpen(false)}
                    className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={partSubmitting}
                    className="px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60 transition-colors shadow-sm"
                  >
                    {partSubmitting ? "Saving..." : isEditingPart ? "Update Part" : "Create Internal Part"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Modal: Link Customer Part */}
        {isLinkModalOpen && (
          <div className="fixed inset-0 z-50 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4">
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
                <div className="flex items-center gap-2">
                  <LinkIcon className="h-5 w-5 text-blue-600" />
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    Link Customer Part Number
                  </h3>
                </div>
                <button
                  onClick={() => setIsLinkModalOpen(false)}
                  className="text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {linkError && (
                <div className="rounded-xl bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 p-3 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{linkError}</span>
                </div>
              )}

              <form onSubmit={handleLinkModalSubmit} className="space-y-4">
                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                    Internal Part Number
                  </label>
                  <input
                    type="text"
                    value={linkInternalPartCode}
                    onChange={(e) => setLinkInternalPartCode(e.target.value)}
                    placeholder="e.g. PMC95"
                    required
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-mono font-bold"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                    Customer
                  </label>
                  <select
                    value={linkCustomerCode}
                    onChange={(e) => setLinkCustomerCode(e.target.value)}
                    required
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500"
                  >
                    <option value="">Select Customer</option>
                    {customers.map((c) => (
                      <option key={c.id} value={c.customer_code}>
                        {c.customer_code} - {c.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300 mb-1">
                    Customer Part Number
                  </label>
                  <input
                    type="text"
                    value={linkCustomerPartNo}
                    onChange={(e) => setLinkCustomerPartNo(e.target.value)}
                    placeholder="e.g. 147 X 103 X 95 - PMC"
                    required
                    className="w-full px-3 py-2 text-xs rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 font-mono"
                  />
                </div>

                <div className="flex items-center gap-2 pt-1">
                  <input
                    type="checkbox"
                    id="link_active_toggle"
                    checked={linkIsActive}
                    onChange={(e) => setLinkIsActive(e.target.checked)}
                    className="rounded text-blue-600 focus:ring-blue-500"
                  />
                  <label
                    htmlFor="link_active_toggle"
                    className="text-xs font-semibold text-zinc-700 dark:text-zinc-300"
                  >
                    Active Mapping
                  </label>
                </div>

                <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
                  <button
                    type="button"
                    onClick={() => setIsLinkModalOpen(false)}
                    className="px-4 py-2 text-xs font-semibold rounded-xl border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={linkSubmitting}
                    className="px-4 py-2 text-xs font-bold rounded-xl bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60 transition-colors shadow-sm"
                  >
                    {linkSubmitting ? "Linking..." : "Save Customer Mapping"}
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
            Loading Authoritative Part Master...
          </div>
        </AppShell>
      }
    >
      <PartMasterContent />
    </Suspense>
  );
}

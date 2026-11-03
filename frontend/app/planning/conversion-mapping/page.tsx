"use client";
import React, { useState, useEffect, useMemo } from "react";
import { Plus, ToggleLeft, ToggleRight, Search, ArrowRight, Layers } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge } from "@/app/components/ui/Badge";
import { getConversionMappings, createConversionMapping, updateConversionMapping, getParts, AdminPart } from "@/lib/api";

export default function ConversionMappingPage() {
  const [mappings, setMappings] = useState<any[]>([]);
  const [parts, setParts] = useState<AdminPart[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [sourcePart, setSourcePart] = useState("");
  const [destPart, setDestPart] = useState("");
  const [sourceSearch, setSourceSearch] = useState("");
  const [destSearch, setDestSearch] = useState("");
  const [tableSearch, setTableSearch] = useState("");
  const [convType, setConvType] = useState<"PART_TO_PART" | "SAME_PART">("PART_TO_PART");
  const [factor, setFactor] = useState<number | "">("");
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [mData, pData] = await Promise.all([getConversionMappings(), getParts()]);
      setMappings(Array.isArray(mData) ? mData : []);
      setParts(Array.isArray(pData) ? pData : []);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to load conversion mappings.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Map of part_number -> AdminPart for quick O(1) enrichment
  const partMap = useMemo(() => {
    const map: Record<string, AdminPart> = {};
    for (const p of parts) {
      map[p.part_number] = p;
    }
    return map;
  }, [parts]);

  // Filtered source part options
  const filteredSourceParts = useMemo(() => {
    if (!sourceSearch.trim()) return parts.slice(0, 300);
    const term = sourceSearch.trim().toLowerCase();
    return parts
      .filter((p) => {
        const custNo = (p.customer_part_number || p.description || "").toLowerCase();
        const mainNo = (p.part_number || "").toLowerCase();
        const custName = (p.customer_name || p.customer_code || "").toLowerCase();
        return custNo.includes(term) || mainNo.includes(term) || custName.includes(term);
      })
      .slice(0, 300);
  }, [parts, sourceSearch]);

  // Filtered destination part options
  const filteredDestParts = useMemo(() => {
    if (!destSearch.trim()) return parts.slice(0, 300);
    const term = destSearch.trim().toLowerCase();
    return parts
      .filter((p) => {
        const custNo = (p.customer_part_number || p.description || "").toLowerCase();
        const mainNo = (p.part_number || "").toLowerCase();
        const custName = (p.customer_name || p.customer_code || "").toLowerCase();
        return custNo.includes(term) || mainNo.includes(term) || custName.includes(term);
      })
      .slice(0, 300);
  }, [parts, destSearch]);

  const selectedSourceObj = partMap[sourcePart];
  const selectedDestObj = partMap[destPart];

  const submitMapping = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormError("");
    if (!sourcePart || !destPart) {
      setFormError("Source and destination part are both required.");
      return;
    }
    if (convType === "SAME_PART" && sourcePart !== destPart) {
      setFormError("SAME_PART requires the source and destination part to be identical.");
      return;
    }
    if (convType === "PART_TO_PART" && sourcePart === destPart) {
      setFormError("PART_TO_PART requires source and destination to differ. Use SAME_PART for an identical part.");
      return;
    }
    setSubmitting(true);
    try {
      await createConversionMapping({
        source_part_number: sourcePart,
        destination_part_number: destPart,
        conversion_type: convType,
        conversion_factor: factor === "" ? undefined : Number(factor)
      });
      setSourcePart("");
      setDestPart("");
      setSourceSearch("");
      setDestSearch("");
      setFactor("");
      await loadData();
    } catch (err: any) {
      setFormError(err?.response?.data?.detail || "Failed to create mapping.");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleActive = async (m: any) => {
    try {
      await updateConversionMapping({ id: m.id, is_active: !m.is_active });
      await loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to update mapping.");
    }
  };

  // Filter mappings for table search
  const filteredMappings = useMemo(() => {
    if (!tableSearch.trim()) return mappings;
    const term = tableSearch.trim().toLowerCase();
    return mappings.filter((m) => {
      const srcCust = (m.source_customer_part_number || partMap[m.source_part_number]?.customer_part_number || "").toLowerCase();
      const srcMain = (m.source_part_number || "").toLowerCase();
      const dstCust = (m.destination_customer_part_number || partMap[m.destination_part_number]?.customer_part_number || "").toLowerCase();
      const dstMain = (m.destination_part_number || "").toLowerCase();
      const type = (m.conversion_type || "").toLowerCase();
      return srcCust.includes(term) || srcMain.includes(term) || dstCust.includes(term) || dstMain.includes(term) || type.includes(term);
    });
  }, [mappings, tableSearch, partMap]);

  return (
    <AppShell>
      <div className="space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-indigo-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Business-Controlled Master
            </span>
            <span className="text-xs text-zinc-400">Authoritative Source → Destination Part Rules</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Conversion Part Mapping
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Identify parts by their <strong>Customer Part Number</strong> and <strong>Main Part Number</strong>. No part converts to another unless an ACTIVE mapping exists here.
          </p>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Add mapping form */}
        <form
          onSubmit={submitMapping}
          className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-4"
        >
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-50 flex items-center gap-2">
            <Plus className="h-4 w-4 text-indigo-600" />
            <span>Define New Mapping</span>
          </h3>

          {formError && (
            <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
              {formError}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* SOURCE PART SELECTOR */}
            <div className="space-y-1.5 p-3.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950/40">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Source Part * <span className="text-[11px] font-normal text-zinc-400">(Customer Part Number / Main Code)</span>
                </label>
              </div>

              {/* Quick Search */}
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-400" />
                <input
                  type="text"
                  placeholder="Filter by customer part no, main code, or customer..."
                  value={sourceSearch}
                  onChange={(e) => setSourceSearch(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              {/* Select Dropdown */}
              <select
                value={sourcePart}
                onChange={(e) => setSourcePart(e.target.value)}
                className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="">Select Source Part...</option>
                {filteredSourceParts.map((p) => {
                  const custNo = p.customer_part_number || p.description || p.part_number;
                  const label = `${custNo} — Main: ${p.part_number}${p.customer_name ? ` (${p.customer_name})` : ""}`;
                  return (
                    <option key={`src-${p.part_number}`} value={p.part_number}>
                      {label}
                    </option>
                  );
                })}
              </select>

              {/* Selected Source Part Preview Card */}
              {selectedSourceObj && (
                <div className="mt-2 p-2.5 rounded-lg border border-indigo-200 dark:border-indigo-900/50 bg-indigo-50/40 dark:bg-indigo-950/20 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold text-indigo-700 dark:text-indigo-300">Selected Source Part</span>
                    <Badge variant="blue" size="sm">Main: {selectedSourceObj.part_number}</Badge>
                  </div>
                  <div className="font-extrabold text-zinc-900 dark:text-zinc-100">
                    {selectedSourceObj.customer_part_number || selectedSourceObj.description || selectedSourceObj.part_number}
                  </div>
                  {selectedSourceObj.customer_name && (
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      Customer: <strong>{selectedSourceObj.customer_name}</strong>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* DESTINATION PART SELECTOR */}
            <div className="space-y-1.5 p-3.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50/50 dark:bg-zinc-950/40">
              <div className="flex items-center justify-between">
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">
                  Destination Part * <span className="text-[11px] font-normal text-zinc-400">(Customer Part Number / Main Code)</span>
                </label>
              </div>

              {/* Quick Search */}
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-400" />
                <input
                  type="text"
                  placeholder="Filter by customer part no, main code, or customer..."
                  value={destSearch}
                  onChange={(e) => setDestSearch(e.target.value)}
                  className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              {/* Select Dropdown */}
              <select
                value={destPart}
                onChange={(e) => setDestPart(e.target.value)}
                className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="">Select Destination Part...</option>
                {filteredDestParts.map((p) => {
                  const custNo = p.customer_part_number || p.description || p.part_number;
                  const label = `${custNo} — Main: ${p.part_number}${p.customer_name ? ` (${p.customer_name})` : ""}`;
                  return (
                    <option key={`dst-${p.part_number}`} value={p.part_number}>
                      {label}
                    </option>
                  );
                })}
              </select>

              {/* Selected Destination Part Preview Card */}
              {selectedDestObj && (
                <div className="mt-2 p-2.5 rounded-lg border border-indigo-200 dark:border-indigo-900/50 bg-indigo-50/40 dark:bg-indigo-950/20 text-xs space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] uppercase font-bold text-indigo-700 dark:text-indigo-300">Selected Destination Part</span>
                    <Badge variant="blue" size="sm">Main: {selectedDestObj.part_number}</Badge>
                  </div>
                  <div className="font-extrabold text-zinc-900 dark:text-zinc-100">
                    {selectedDestObj.customer_part_number || selectedDestObj.description || selectedDestObj.part_number}
                  </div>
                  {selectedDestObj.customer_name && (
                    <div className="text-[11px] text-zinc-500 dark:text-zinc-400">
                      Customer: <strong>{selectedDestObj.customer_name}</strong>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Conversion Type *</label>
              <select
                value={convType}
                onChange={(e) => setConvType(e.target.value as any)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                <option value="PART_TO_PART">PART_TO_PART (Different Source and Destination)</option>
                <option value="SAME_PART">SAME_PART (Part Converts to Itself)</option>
              </select>
            </div>
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Conversion Factor</label>
              <input
                type="number"
                step="any"
                min={0}
                value={factor}
                onChange={(e) => setFactor(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="optional ratio (default: 1.0)"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div className="pt-2">
            <button
              type="submit"
              disabled={submitting}
              className="rounded-xl bg-indigo-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors cursor-pointer"
            >
              {submitting ? "Creating Mapping..." : "Create Mapping"}
            </button>
          </div>
        </form>

        {/* Mapping list */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          {/* Table Header with Search Bar */}
          <div className="p-4 border-b border-zinc-200 dark:border-zinc-800 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-2">
              <Layers className="h-4 w-4 text-indigo-600" />
              <span className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Active Conversion Rules</span>
              <span className="text-xs text-zinc-400">({filteredMappings.length} total)</span>
            </div>
            <div className="relative w-full sm:w-72">
              <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-400" />
              <input
                type="text"
                placeholder="Search mapping table..."
                value={tableSearch}
                onChange={(e) => setTableSearch(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-2.5 px-3">Source Part (Customer & Main)</th>
                  <th className="py-2.5 px-3">Destination Part (Customer & Main)</th>
                  <th className="py-2.5 px-3">Type</th>
                  <th className="py-2.5 px-3 text-right">Factor</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Created By</th>
                  <th className="py-2.5 px-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {loading ? (
                  <tr><td colSpan={7} className="py-10 text-center text-zinc-400">Loading conversion mappings...</td></tr>
                ) : filteredMappings.length === 0 ? (
                  <tr><td colSpan={7} className="py-10 text-center text-zinc-400">No conversion mappings matching your criteria.</td></tr>
                ) : (
                  filteredMappings.map((m) => {
                    const srcObj = partMap[m.source_part_number];
                    const dstObj = partMap[m.destination_part_number];
                    const srcCustPart = m.source_customer_part_number || srcObj?.customer_part_number || srcObj?.description || m.source_part_number;
                    const srcCustName = m.source_customer_name || srcObj?.customer_name;
                    const dstCustPart = m.destination_customer_part_number || dstObj?.customer_part_number || dstObj?.description || m.destination_part_number;
                    const dstCustName = m.destination_customer_name || dstObj?.customer_name;

                    return (
                      <tr key={m.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                        {/* Source Part Cell */}
                        <td className="py-3 px-3">
                          <div className="font-extrabold text-zinc-900 dark:text-zinc-100">
                            {srcCustPart}
                          </div>
                          <div className="text-[11px] text-zinc-500 flex items-center gap-1.5 mt-0.5">
                            <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 px-1.5 py-0.5 rounded">
                              Main: {m.source_part_number}
                            </span>
                            {srcCustName && (
                              <span className="text-zinc-400 truncate max-w-[160px]">
                                • {srcCustName}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* Destination Part Cell */}
                        <td className="py-3 px-3">
                          <div className="font-extrabold text-zinc-900 dark:text-zinc-100">
                            {dstCustPart}
                          </div>
                          <div className="text-[11px] text-zinc-500 flex items-center gap-1.5 mt-0.5">
                            <span className="font-mono font-bold text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 px-1.5 py-0.5 rounded">
                              Main: {m.destination_part_number}
                            </span>
                            {dstCustName && (
                              <span className="text-zinc-400 truncate max-w-[160px]">
                                • {dstCustName}
                              </span>
                            )}
                          </div>
                        </td>

                        <td className="py-3 px-3">
                          <Badge variant={m.conversion_type === "SAME_PART" ? "purple" : "blue"} size="sm">
                            {m.conversion_type}
                          </Badge>
                        </td>

                        <td className="py-3 px-3 text-right font-mono">{m.conversion_factor ?? "1.0"}</td>

                        <td className="py-3 px-3">
                          <Badge variant={m.is_active ? "green" : "gray"} size="sm">
                            {m.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </td>

                        <td className="py-3 px-3 text-zinc-500">{m.created_by_name || "—"}</td>

                        <td className="py-3 px-3">
                          <button
                            onClick={() => toggleActive(m)}
                            className="flex items-center gap-1 text-indigo-600 hover:underline font-bold cursor-pointer"
                          >
                            {m.is_active ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                            <span>{m.is_active ? "Deactivate" : "Activate"}</span>
                          </button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

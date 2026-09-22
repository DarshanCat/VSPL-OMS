"use client";
import React, { useState, useEffect } from "react";
import { Shuffle, Plus, ToggleLeft, ToggleRight } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge } from "@/app/components/ui/Badge";
import { getConversionMappings, createConversionMapping, updateConversionMapping, getParts } from "@/lib/api";

export default function ConversionMappingPage() {
  const [mappings, setMappings] = useState<any[]>([]);
  const [parts, setParts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [sourcePart, setSourcePart] = useState("");
  const [destPart, setDestPart] = useState("");
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
            No part converts to another unless an ACTIVE mapping exists here — including a part converting to itself.
            This list is never auto-populated; every row is an explicit business decision.
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
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Source Part *</label>
              <select
                value={sourcePart}
                onChange={(e) => setSourcePart(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                <option value="">Select...</option>
                {parts.map((p) => (
                  <option key={p.part_number} value={p.part_number}>{p.part_number}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Destination Part *</label>
              <select
                value={destPart}
                onChange={(e) => setDestPart(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                <option value="">Select...</option>
                {parts.map((p) => (
                  <option key={p.part_number} value={p.part_number}>{p.part_number}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Conversion Type *</label>
              <select
                value={convType}
                onChange={(e) => setConvType(e.target.value as any)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                <option value="PART_TO_PART">PART_TO_PART</option>
                <option value="SAME_PART">SAME_PART</option>
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
                placeholder="optional"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={submitting}
            className="rounded-xl bg-indigo-600 px-4 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-indigo-500 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {submitting ? "Creating..." : "Create Mapping"}
          </button>
        </form>

        {/* Mapping list */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950/80 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-2.5 px-3">Source Part</th>
                  <th className="py-2.5 px-3">Destination Part</th>
                  <th className="py-2.5 px-3">Type</th>
                  <th className="py-2.5 px-3 text-right">Factor</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Created By</th>
                  <th className="py-2.5 px-3">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {loading ? (
                  <tr><td colSpan={7} className="py-10 text-center text-zinc-400">Loading...</td></tr>
                ) : mappings.length === 0 ? (
                  <tr><td colSpan={7} className="py-10 text-center text-zinc-400">No conversion mappings defined yet.</td></tr>
                ) : (
                  mappings.map((m) => (
                    <tr key={m.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                      <td className="py-2.5 px-3 font-mono font-bold">{m.source_part_number}</td>
                      <td className="py-2.5 px-3 font-mono font-bold">{m.destination_part_number}</td>
                      <td className="py-2.5 px-3">
                        <Badge variant={m.conversion_type === "SAME_PART" ? "purple" : "blue"} size="sm">
                          {m.conversion_type}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3 text-right font-mono">{m.conversion_factor ?? "—"}</td>
                      <td className="py-2.5 px-3">
                        <Badge variant={m.is_active ? "green" : "gray"} size="sm">
                          {m.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3 text-zinc-500">{m.created_by_name || "—"}</td>
                      <td className="py-2.5 px-3">
                        <button
                          onClick={() => toggleActive(m)}
                          className="flex items-center gap-1 text-indigo-600 hover:underline font-bold cursor-pointer"
                        >
                          {m.is_active ? <ToggleRight className="h-3.5 w-3.5" /> : <ToggleLeft className="h-3.5 w-3.5" />}
                          <span>{m.is_active ? "Deactivate" : "Activate"}</span>
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </AppShell>
  );
}

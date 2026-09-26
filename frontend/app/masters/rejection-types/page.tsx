"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getRejectionTypes, createRejectionType, updateRejectionType, MasterRejectionType } from "@/lib/api";
import { AlertOctagon, AlertTriangle, Search } from "lucide-react";

export default function RejectionTypeMasterPage() {
  const [types, setTypes] = useState<MasterRejectionType[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);

  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  async function loadTypes(includeInactive = showInactive) {
    setLoading(true);
    setListError("");
    try {
      setTypes(await getRejectionTypes(includeInactive));
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load rejection types.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showInactive]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      await createRejectionType({ code, name, description: description || undefined });
      setCode("");
      setName("");
      setDescription("");
      await loadTypes();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Could not create rejection type.");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(t: MasterRejectionType) {
    setRowBusy(t.id);
    try {
      await updateRejectionType({ id: t.id, is_active: !t.is_active });
      await loadTypes();
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not update rejection type.");
    } finally {
      setRowBusy(null);
    }
  }

  const filtered = types.filter(
    (t) => !search || t.code.toLowerCase().includes(search.toLowerCase()) || t.name.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
            Masters — Quality-controlled
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Rejection Type Master
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Selected as the rejection type in Production Entry. Only Quality/Admin may add, edit, or deactivate.
          </p>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <AlertOctagon className="h-4 w-4 text-blue-500" /> Add Rejection Type
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <input required placeholder="Code (e.g. DEF-POROSITY)" value={code} onChange={(e) => setCode(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-mono" />
            <input required placeholder="Name" value={name} onChange={(e) => setName(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <input placeholder="Description" value={description} onChange={(e) => setDescription(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <button type="submit" disabled={creating}
              className="md:col-span-3 justify-self-end rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors">
              {creating ? "Creating..." : "Add Rejection Type"}
            </button>
          </form>
        </div>

        <div className="flex flex-col sm:flex-row gap-3 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search code or name..."
              className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent pl-10 pr-3 py-2 text-xs"
            />
          </div>
          <label className="flex items-center gap-2 text-xs font-semibold text-zinc-600 dark:text-zinc-400">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
            Show inactive
          </label>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center gap-2">
            <AlertOctagon className="h-4 w-4 text-zinc-500" />
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing Rejection Types</h3>
          </div>
          {listError && (
            <div className="m-4 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{listError}</span>
            </div>
          )}
          {loading ? (
            <div className="p-4 text-xs text-zinc-500">Loading...</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400">
                <tr>
                  <th className="text-left px-4 py-2 font-semibold">Code</th>
                  <th className="text-left px-4 py-2 font-semibold">Name</th>
                  <th className="text-left px-4 py-2 font-semibold">Description</th>
                  <th className="text-left px-4 py-2 font-semibold">Created By</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-right px-4 py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.id} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-4 py-2 font-mono">{t.code}</td>
                    <td className="px-4 py-2">{t.name}</td>
                    <td className="px-4 py-2">{t.description || "-"}</td>
                    <td className="px-4 py-2">{t.created_by || "-"}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${t.is_active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400" : "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"}`}>
                        {t.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button type="button" disabled={rowBusy === t.id} onClick={() => handleToggleActive(t)}
                        className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors">
                        {t.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
                {filtered.length === 0 && !loading && (
                  <tr><td colSpan={6} className="px-4 py-6 text-center text-zinc-400">No rejection types found.</td></tr>
                )}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </AppShell>
  );
}

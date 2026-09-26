"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getOperators, createOperator, updateOperator, MasterOperator } from "@/lib/api";
import { UserCircle, AlertTriangle } from "lucide-react";

export default function OperatorMasterPage() {
  const [operators, setOperators] = useState<MasterOperator[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [displayName, setDisplayName] = useState("");
  const [employeeCode, setEmployeeCode] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  async function loadOperators() {
    setLoading(true);
    setListError("");
    try {
      setOperators(await getOperators());
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load operators.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadOperators();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      await createOperator({ display_name: displayName, employee_code: employeeCode || undefined });
      setDisplayName("");
      setEmployeeCode("");
      await loadOperators();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Could not create operator.");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleActive(o: MasterOperator) {
    setRowBusy(o.id);
    try {
      await updateOperator({ id: o.id, is_active: !o.is_active });
      await loadOperators();
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not update operator.");
    } finally {
      setRowBusy(null);
    }
  }

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
            Masters
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Operator Master
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Used for operator selection in production entry. Links to an existing authenticated user where one exists -- never duplicates an identity.
          </p>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <UserCircle className="h-4 w-4 text-blue-500" /> Add Operator
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <input required placeholder="Display name" value={displayName} onChange={(e) => setDisplayName(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            <input placeholder="Employee code" value={employeeCode} onChange={(e) => setEmployeeCode(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-mono" />
            <button type="submit" disabled={creating}
              className="justify-self-end rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors">
              {creating ? "Creating..." : "Add Operator"}
            </button>
          </form>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center gap-2">
            <UserCircle className="h-4 w-4 text-zinc-500" />
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing Operators</h3>
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
                  <th className="text-left px-4 py-2 font-semibold">Name</th>
                  <th className="text-left px-4 py-2 font-semibold">Employee Code</th>
                  <th className="text-left px-4 py-2 font-semibold">Linked User</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-right px-4 py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {operators.map((o) => (
                  <tr key={o.id} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-4 py-2">{o.display_name}</td>
                    <td className="px-4 py-2 font-mono">{o.employee_code || "-"}</td>
                    <td className="px-4 py-2">{o.user_id ? "Yes" : "No"}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${o.is_active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400" : "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"}`}>
                        {o.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right">
                      <button type="button" disabled={rowBusy === o.id} onClick={() => handleToggleActive(o)}
                        className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors">
                        {o.is_active ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </AppShell>
  );
}

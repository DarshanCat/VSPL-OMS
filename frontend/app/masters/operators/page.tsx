"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getOperators,
  createOperator,
  updateOperator,
  deleteOperator,
  MasterOperator,
} from "@/lib/api";
import {
  UserCircle,
  AlertTriangle,
  Search,
  Filter,
  Edit3,
  Trash2,
  X,
  CheckCircle2,
  Plus,
} from "lucide-react";

export default function OperatorMasterPage() {
  const [operators, setOperators] = useState<MasterOperator[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  // Create form state
  const [displayName, setDisplayName] = useState("");
  const [employeeCode, setEmployeeCode] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  // Search & Filter state
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "ACTIVE" | "INACTIVE">("ALL");

  // Edit modal state
  const [editingOperator, setEditingOperator] = useState<MasterOperator | null>(null);
  const [editDisplayName, setEditDisplayName] = useState("");
  const [editEmployeeCode, setEditEmployeeCode] = useState("");
  const [editIsActive, setEditIsActive] = useState(true);
  const [editError, setEditError] = useState("");
  const [savingEdit, setSavingEdit] = useState(false);

  // Delete confirmation state
  const [deletingOperator, setDeletingOperator] = useState<MasterOperator | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");

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
      await createOperator({
        display_name: displayName.trim(),
        employee_code: employeeCode.trim() || undefined,
      });
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
      setListError(err?.response?.data?.detail || "Could not update operator status.");
    } finally {
      setRowBusy(null);
    }
  }

  function openEditModal(o: MasterOperator) {
    setEditingOperator(o);
    setEditDisplayName(o.display_name);
    setEditEmployeeCode(o.employee_code || "");
    setEditIsActive(o.is_active);
    setEditError("");
  }

  function closeEditModal() {
    setEditingOperator(null);
    setEditError("");
  }

  async function handleSaveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editingOperator) return;
    setSavingEdit(true);
    setEditError("");
    try {
      await updateOperator({
        id: editingOperator.id,
        display_name: editDisplayName.trim(),
        employee_code: editEmployeeCode.trim() || undefined,
        is_active: editIsActive,
      });
      closeEditModal();
      await loadOperators();
    } catch (err: any) {
      setEditError(err?.response?.data?.detail || "Could not save operator changes.");
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleConfirmDelete() {
    if (!deletingOperator) return;
    setDeleting(true);
    setDeleteError("");
    try {
      await deleteOperator(deletingOperator.id);
      setDeletingOperator(null);
      await loadOperators();
    } catch (err: any) {
      setDeleteError(err?.response?.data?.detail || "Could not delete operator.");
    } finally {
      setDeleting(false);
    }
  }

  const filteredOperators = operators.filter((o) => {
    if (statusFilter === "ACTIVE" && !o.is_active) return false;
    if (statusFilter === "INACTIVE" && o.is_active) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      const matchName = o.display_name.toLowerCase().includes(q);
      const matchCode = o.employee_code?.toLowerCase().includes(q);
      if (!matchName && !matchCode) return false;
    }
    return true;
  });

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
            Manage production floor operators for logging shop-floor transactions. Operators can be edited, deactivated, or deleted.
          </p>
        </div>

        {/* Add Operator Form */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <Plus className="h-4 w-4 text-blue-500" /> Add Operator
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block mb-1">
                Display Name <span className="text-rose-500">*</span>
              </label>
              <input
                required
                placeholder="e.g. Ramesh Kumar"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
              />
            </div>
            <div>
              <label className="text-[10px] font-bold text-zinc-500 uppercase tracking-wider block mb-1">
                Employee Code (Optional)
              </label>
              <input
                placeholder="e.g. OP-101"
                value={employeeCode}
                onChange={(e) => setEmployeeCode(e.target.value)}
                className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-mono"
              />
            </div>
            <div className="flex items-end">
              <button
                type="submit"
                disabled={creating}
                className="w-full md:w-auto rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors"
              >
                {creating ? "Adding..." : "Add Operator"}
              </button>
            </div>
          </form>
        </div>

        {/* Existing Operators List */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <UserCircle className="h-5 w-5 text-zinc-500" />
                <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                  Existing Operators ({filteredOperators.length} of {operators.length})
                </h3>
              </div>
            </div>

            {/* Filter and Search Bar */}
            <div className="flex flex-col sm:flex-row gap-3">
              <div className="relative flex-1">
                <input
                  type="text"
                  placeholder="Search operators by name or code..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent pl-8 pr-8 py-2 text-xs text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400"
                />
                <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-400 pointer-events-none" />
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery("")}
                    className="absolute right-2 top-2 p-0.5 text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <Filter className="h-3.5 w-3.5 text-zinc-400 shrink-0" />
                <select
                  value={statusFilter}
                  onChange={(e: any) => setStatusFilter(e.target.value)}
                  className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100"
                >
                  <option value="ALL">All Statuses</option>
                  <option value="ACTIVE">Active Only</option>
                  <option value="INACTIVE">Inactive Only</option>
                </select>
              </div>
            </div>
          </div>

          {listError && (
            <div className="m-4 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{listError}</span>
            </div>
          )}

          {loading ? (
            <div className="p-4 text-xs text-zinc-500">Loading operators...</div>
          ) : filteredOperators.length === 0 ? (
            <div className="p-8 text-center text-xs text-zinc-500">
              {operators.length === 0 ? "No operators registered yet." : "No operators match your filter or search."}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="bg-zinc-50 dark:bg-zinc-800/50 text-zinc-500 dark:text-zinc-400 border-b border-zinc-100 dark:border-zinc-800">
                  <tr>
                    <th className="text-left px-4 py-2.5 font-semibold">Operator Name</th>
                    <th className="text-left px-4 py-2.5 font-semibold">Employee Code</th>
                    <th className="text-left px-4 py-2.5 font-semibold">Linked User</th>
                    <th className="text-left px-4 py-2.5 font-semibold">Status</th>
                    <th className="text-right px-4 py-2.5 font-semibold">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {filteredOperators.map((o) => (
                    <tr key={o.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/20 transition-colors">
                      <td className="px-4 py-2.5 font-medium text-zinc-900 dark:text-zinc-100">
                        {o.display_name}
                      </td>
                      <td className="px-4 py-2.5 font-mono text-zinc-600 dark:text-zinc-300">
                        {o.employee_code || "—"}
                      </td>
                      <td className="px-4 py-2.5 text-zinc-500">
                        {o.user_id ? "Yes (Account Linked)" : "No"}
                      </td>
                      <td className="px-4 py-2.5">
                        <span
                          className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${
                            o.is_active
                              ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400"
                              : "bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                          }`}
                        >
                          {o.is_active ? "Active" : "Inactive"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 text-right">
                        <div className="inline-flex items-center gap-1.5">
                          {/* Edit Button */}
                          <button
                            type="button"
                            onClick={() => openEditModal(o)}
                            className="inline-flex items-center gap-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-200 hover:bg-zinc-200 dark:hover:bg-zinc-700 transition-colors"
                          >
                            <Edit3 className="h-3 w-3 text-blue-500" /> Edit
                          </button>

                          {/* Toggle Active Button */}
                          <button
                            type="button"
                            disabled={rowBusy === o.id}
                            onClick={() => handleToggleActive(o)}
                            className={`rounded-lg px-2 py-1 text-[11px] font-semibold transition-colors disabled:opacity-50 ${
                              o.is_active
                                ? "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400 hover:bg-amber-100"
                                : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400 hover:bg-emerald-100"
                            }`}
                          >
                            {o.is_active ? "Deactivate" : "Activate"}
                          </button>

                          {/* Delete Button */}
                          <button
                            type="button"
                            onClick={() => setDeletingOperator(o)}
                            className="inline-flex items-center gap-1 rounded-lg bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400 px-2 py-1 text-[11px] font-semibold hover:bg-rose-100 dark:hover:bg-rose-900/40 transition-colors"
                          >
                            <Trash2 className="h-3 w-3" /> Delete
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

        {/* Edit Modal */}
        {editingOperator && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <div className="w-full max-w-md rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
                <div className="flex items-center gap-2">
                  <Edit3 className="h-5 w-5 text-blue-600" />
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    Edit Operator
                  </h3>
                </div>
                <button
                  type="button"
                  onClick={closeEditModal}
                  className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800"
                >
                  <X className="h-5 w-5" />
                </button>
              </div>

              {editError && (
                <div className="flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 p-3 text-xs font-medium text-rose-600 dark:text-rose-400">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{editError}</span>
                </div>
              )}

              <form onSubmit={handleSaveEdit} className="space-y-3">
                <div>
                  <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider block mb-1">
                    Display Name <span className="text-rose-500">*</span>
                  </label>
                  <input
                    required
                    value={editDisplayName}
                    onChange={(e) => setEditDisplayName(e.target.value)}
                    className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100"
                  />
                </div>

                <div>
                  <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider block mb-1">
                    Employee Code
                  </label>
                  <input
                    value={editEmployeeCode}
                    onChange={(e) => setEditEmployeeCode(e.target.value)}
                    className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-100"
                  />
                </div>

                <div>
                  <label className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider block mb-1">
                    Status
                  </label>
                  <select
                    value={editIsActive ? "active" : "inactive"}
                    onChange={(e) => setEditIsActive(e.target.value === "active")}
                    className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-medium text-zinc-900 dark:text-zinc-100"
                  >
                    <option value="active">Active</option>
                    <option value="inactive">Inactive</option>
                  </select>
                </div>

                <div className="flex items-center justify-end gap-2 border-t border-zinc-100 dark:border-zinc-800 pt-3">
                  <button
                    type="button"
                    onClick={closeEditModal}
                    className="rounded-xl border border-zinc-200 dark:border-zinc-700 px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={savingEdit}
                    className="rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors"
                  >
                    {savingEdit ? "Saving..." : "Save Changes"}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Delete Confirmation Modal */}
        {deletingOperator && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <div className="w-full max-w-sm rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-2xl space-y-4">
              <div className="flex items-center gap-3">
                <div className="p-2.5 rounded-full bg-rose-100 dark:bg-rose-950/60 text-rose-600">
                  <Trash2 className="h-5 w-5" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                    Delete Operator?
                  </h3>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                    Are you sure you want to delete <span className="font-semibold text-zinc-900 dark:text-zinc-100">{deletingOperator.display_name}</span> ({deletingOperator.employee_code || "no code"})?
                  </p>
                </div>
              </div>

              {deleteError && (
                <div className="rounded-lg bg-rose-50 dark:bg-rose-950/40 p-2.5 text-xs text-rose-600 dark:text-rose-400">
                  {deleteError}
                </div>
              )}

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  type="button"
                  disabled={deleting}
                  onClick={() => setDeletingOperator(null)}
                  className="rounded-xl border border-zinc-200 dark:border-zinc-700 px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={deleting}
                  onClick={handleConfirmDelete}
                  className="rounded-xl bg-rose-600 px-4 py-2 text-xs font-bold text-white hover:bg-rose-500 disabled:opacity-60 transition-colors"
                >
                  {deleting ? "Deleting..." : "Delete Permanently"}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

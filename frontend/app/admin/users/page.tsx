"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getUsers,
  createUser,
  resetUserPassword,
  setUserStatus,
  AdminUser,
  TemporaryPasswordResult,
} from "@/lib/api";
import { UserPlus, KeyRound, Copy, CheckCircle2, AlertTriangle, ShieldAlert } from "lucide-react";

const ROLES = [
  "admin", "ceo", "production_manager", "planner", "qa",
  "dispatch", "machine_operator", "operator", "packing", "store", "sales", "data_analyst",
];

function roleLabel(role: string) {
  return role
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [department, setDepartment] = useState("");
  const [role, setRole] = useState("planner");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  const [tempResult, setTempResult] = useState<TemporaryPasswordResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [rowBusy, setRowBusy] = useState<string | null>(null);

  async function loadUsers() {
    setLoading(true);
    setListError("");
    try {
      const data = await getUsers();
      setUsers(data);
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load users.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadUsers();
  }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      const result = await createUser({ full_name: fullName, email, department, role });
      setTempResult(result);
      setFullName("");
      setEmail("");
      setDepartment("");
      setRole("planner");
      await loadUsers();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Could not create user.");
    } finally {
      setCreating(false);
    }
  }

  async function handleReset(user: AdminUser) {
    setRowBusy(user.id);
    try {
      const result = await resetUserPassword(user.id);
      setTempResult(result);
      await loadUsers();
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not reset password.");
    } finally {
      setRowBusy(null);
    }
  }

  async function handleToggleActive(user: AdminUser) {
    setRowBusy(user.id);
    try {
      await setUserStatus(user.id, !user.is_active);
      await loadUsers();
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not update status.");
    } finally {
      setRowBusy(null);
    }
  }

  function copyTempPassword() {
    if (!tempResult) return;
    navigator.clipboard.writeText(tempResult.temporary_password).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Administration
            </span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            User Accounts
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Create accounts, generate temporary passwords, and manage account status. Every
            new account must set its own permanent password on first login.
          </p>
        </div>

        {/* Create User */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-blue-500" /> Create User
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 grid grid-cols-1 md:grid-cols-4 gap-3">
            <input
              required
              placeholder="Full name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            />
            <input
              required
              type="email"
              placeholder="Company email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            />
            <input
              placeholder="Department"
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            />
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>{roleLabel(r)}</option>
              ))}
            </select>
            <button
              type="submit"
              disabled={creating}
              className="md:col-span-4 justify-self-end rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors"
            >
              {creating ? "Creating..." : "Generate Temporary Password & Create User"}
            </button>
          </form>
        </div>

        {/* One-time temp password result */}
        {tempResult && (
          <div className="rounded-2xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/30 p-5 shadow-sm">
            <h3 className="text-sm font-bold text-emerald-800 dark:text-emerald-300 flex items-center gap-2">
              <KeyRound className="h-4 w-4" /> Temporary Password (shown once)
            </h3>
            <div className="mt-2 text-xs text-emerald-900 dark:text-emerald-200 space-y-1">
              <p><span className="font-semibold">Email:</span> {tempResult.user.email}</p>
              <p><span className="font-semibold">Department:</span> {tempResult.user.department || "-"}</p>
              <p><span className="font-semibold">Role:</span> {roleLabel(tempResult.user.role)}</p>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <code className="flex-1 rounded-lg bg-white dark:bg-zinc-900 border border-emerald-300 dark:border-emerald-800 px-3 py-2 text-xs font-mono text-emerald-900 dark:text-emerald-200">
                {tempResult.temporary_password}
              </code>
              <button
                type="button"
                onClick={copyTempPassword}
                className="flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-2 text-[11px] font-bold text-white hover:bg-emerald-500 transition-colors"
              >
                {copied ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
            <p className="mt-2 text-[10px] text-emerald-700 dark:text-emerald-400">
              This will not be shown again. Share it with the user through a secure channel; they
              will be required to set a permanent password on first login.
            </p>
            <button
              type="button"
              onClick={() => setTempResult(null)}
              className="mt-3 text-[11px] font-semibold text-emerald-700 dark:text-emerald-400 hover:underline"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Users list */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800">
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing Users</h3>
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
                  <th className="text-left px-4 py-2 font-semibold">Email</th>
                  <th className="text-left px-4 py-2 font-semibold">Department</th>
                  <th className="text-left px-4 py-2 font-semibold">Role</th>
                  <th className="text-left px-4 py-2 font-semibold">Status</th>
                  <th className="text-left px-4 py-2 font-semibold">Password</th>
                  <th className="text-right px-4 py-2 font-semibold">Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-4 py-2">{u.full_name}</td>
                    <td className="px-4 py-2">{u.email}</td>
                    <td className="px-4 py-2">{u.department || "-"}</td>
                    <td className="px-4 py-2">{roleLabel(u.role)}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${u.is_active ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400" : "bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"}`}>
                        {u.is_active ? "Active" : "Inactive"}
                      </span>
                    </td>
                    <td className="px-4 py-2">
                      {u.must_change_password && (
                        <span className="inline-flex items-center gap-1 rounded-md bg-amber-100 dark:bg-amber-950/50 px-2 py-0.5 text-[10px] font-bold uppercase text-amber-700 dark:text-amber-400">
                          <ShieldAlert className="h-3 w-3" /> Force Change
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-2 text-right space-x-2">
                      <button
                        type="button"
                        disabled={rowBusy === u.id}
                        onClick={() => handleReset(u)}
                        className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                      >
                        Reset Password
                      </button>
                      <button
                        type="button"
                        disabled={rowBusy === u.id}
                        onClick={() => handleToggleActive(u)}
                        className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-50 transition-colors"
                      >
                        {u.is_active ? "Deactivate" : "Activate"}
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

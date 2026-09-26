"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getRoles, RoleInfo } from "@/lib/api";
import { ShieldCheck, AlertTriangle } from "lucide-react";

export default function RolesResponsibilitiesPage() {
  const [roles, setRoles] = useState<RoleInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      setLoading(true);
      setError("");
      try {
        setRoles(await getRoles());
      } catch (err: any) {
        setError(err?.response?.data?.detail || "Could not load role reference data.");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  return (
    <AppShell>
      <div className="max-w-5xl mx-auto space-y-6">
        <div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-blue-500" />
            <span className="text-xs text-zinc-400">Read-only reference</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            Roles &amp; Responsibilities
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Informational only -- actual authorization is always enforced by the backend (app/core/roles.py), independent of this page.
          </p>
        </div>

        {error && (
          <div className="flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <div className="text-xs text-zinc-500">Loading...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {roles.map((r) => (
              <div key={r.role} className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">{r.display_name}</span>
                  <span className="text-[10px] font-semibold text-zinc-400 uppercase">{r.department}</span>
                </div>
                <div className="mt-3">
                  <p className="text-[10px] font-bold uppercase text-zinc-400 mb-1">Permissions</p>
                  <ul className="text-xs text-zinc-700 dark:text-zinc-300 space-y-0.5 list-disc list-inside">
                    {r.permissions.map((p, i) => <li key={i}>{p}</li>)}
                  </ul>
                </div>
                <div className="mt-3">
                  <p className="text-[10px] font-bold uppercase text-zinc-400 mb-1">Allowed Modules</p>
                  <div className="flex flex-wrap gap-1.5">
                    {r.allowed_modules.map((m, i) => (
                      <span key={i} className="rounded-full bg-zinc-100 dark:bg-zinc-800 px-2.5 py-0.5 text-[10px] font-semibold text-zinc-600 dark:text-zinc-300">{m}</span>
                    ))}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </AppShell>
  );
}

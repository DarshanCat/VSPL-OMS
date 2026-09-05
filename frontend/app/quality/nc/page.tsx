"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Search,
  CheckCircle2,
  Plus,
  RefreshCw,
  Clock,
  ShieldAlert,
  FileText
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import { getNCRecords, createNCRecord, updateNCRecord, getWorkOrders } from "@/lib/api";

const DEFECT_CODES = [
  { code: "DEF-POROSITY", label: "DEF-POROSITY — Casting Gas Porosity" },
  { code: "DEF-SURF-BLOW", label: "DEF-SURF-BLOW — Surface Blowholes / Pits" },
  { code: "DEF-DIM-OUT", label: "DEF-DIM-OUT — Dimensional Tolerance Out" },
  { code: "DEF-INCLUSION", label: "DEF-INCLUSION — Slag / Oxide Inclusion" },
  { code: "DEF-CRACK", label: "DEF-CRACK — Thermal Stress Crack" },
  { code: "DEF-FINISH", label: "DEF-FINISH — Surface Roughness (Ra) High" },
];

export default function NCQualityPage() {
  const [records, setRecords] = useState<any[]>([]);
  const [wos, setWos] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [error, setError] = useState("");

  // Create NC Modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newWO, setNewWO] = useState("");
  const [newStage, setNewStage] = useState("F2");
  const [newDefect, setNewDefect] = useState("DEF-POROSITY");
  const [newQty, setNewQty] = useState<number | "">(5);
  const [newRootCause, setNewRootCause] = useState("");
  const [newDisposition, setNewDisposition] = useState("Scrap");
  const [newResponsibility, setNewResponsibility] = useState("Production");
  const [newRemarks, setNewRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);

  // Edit NC Modal
  const [editItem, setEditItem] = useState<any>(null);
  const [editStatus, setEditStatus] = useState("Closed");
  const [editRootCause, setEditRootCause] = useState("");
  const [editDisposition, setEditDisposition] = useState("Scrap & Re-melt");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [ncData, wData] = await Promise.all([getNCRecords(), getWorkOrders()]);
      setRecords(ncData);
      setWos(wData);
      if (wData.length > 0 && !newWO) {
        setNewWO(wData[0].wo_number);
      }
    } catch (err: any) {
      setError("Failed to fetch NC records from server.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleCreateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newWO || Number(newQty) <= 0) return;

    setSubmitting(true);
    try {
      await createNCRecord({
        wo_number: newWO,
        stage: newStage,
        defect_code: newDefect,
        qty: Number(newQty),
        root_cause: newRootCause || undefined,
        disposition: newDisposition,
        responsibility: newResponsibility,
        remarks: newRemarks || undefined,
      });

      setShowCreateModal(false);
      loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to log NC Record.");
    } finally {
      setSubmitting(false);
    }
  };

  const handleUpdateSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!editItem) return;

    setSubmitting(true);
    try {
      await updateNCRecord({
        nc_number: editItem.nc_number,
        status: editStatus,
        root_cause: editRootCause,
        disposition: editDisposition,
      });

      setEditItem(null);
      loadData();
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Failed to update NC Record.");
    } finally {
      setSubmitting(false);
    }
  };

  const openEdit = (item: any) => {
    setEditItem(item);
    setEditStatus(item.status);
    setEditRootCause(item.root_cause || "");
    setEditDisposition(item.disposition || "Scrap & Re-melt");
  };

  const filteredRecords = records.filter((r) => {
    const matchesSearch =
      !search ||
      r.nc_number.toLowerCase().includes(search.toLowerCase()) ||
      r.wo_number.toLowerCase().includes(search.toLowerCase()) ||
      r.defect_code.toLowerCase().includes(search.toLowerCase()) ||
      r.part_number.toLowerCase().includes(search.toLowerCase());

    const matchesStatus = statusFilter === "ALL" || r.status.toUpperCase() === statusFilter.toUpperCase();

    return matchesSearch && matchesStatus;
  });

  const openNCCount = records.filter((r) => r.status === "Open" || r.status === "In-Review").length;

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-rose-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Quality Assurance
              </span>
              <span className="text-xs text-zinc-400">Non-Conformance & MRB</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              NC Quality & Rejection Tracker
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Log defect occurrences, track aging days, assign root cause dispositions, and govern MRB gates.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowCreateModal(true)}
              className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-rose-500 transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
              <span>Log Non-Conformance</span>
            </button>
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Top Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 border-t-4 border-t-rose-500">
            <p className="text-xs font-bold text-zinc-400 uppercase">Active Open NCs</p>
            <h3 className="text-2xl font-extrabold text-rose-600 dark:text-rose-400 mt-1">{openNCCount} Items</h3>
            <p className="text-[11px] text-zinc-500 mt-0.5">Awaiting QA disposition or closure</p>
          </div>
          <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 border-t-4 border-t-amber-500">
            <p className="text-xs font-bold text-zinc-400 uppercase">Total Defects Logged</p>
            <h3 className="text-2xl font-extrabold text-zinc-900 dark:text-zinc-100 mt-1">{records.length} Incidents</h3>
            <p className="text-[11px] text-zinc-500 mt-0.5">All manufacturing stages</p>
          </div>
          <div className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 border-t-4 border-t-emerald-500">
            <p className="text-xs font-bold text-zinc-400 uppercase">MRB Gate Protocol</p>
            <h3 className="text-2xl font-extrabold text-emerald-600 mt-1">100% Traceable</h3>
            <p className="text-[11px] text-zinc-500 mt-0.5">Integrated with OMS calculation formula</p>
          </div>
        </div>

        {/* Search & Filter */}
        <div className="flex flex-col sm:flex-row gap-3 rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4 shadow-sm">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-3 h-4 w-4 text-zinc-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search NC Number, Work Order, Defect Code, or Part..."
              className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 pl-10 pr-4 py-2 text-xs text-zinc-900 dark:text-zinc-100 placeholder-zinc-400 focus:border-blue-500 focus:outline-none"
            />
          </div>

          <div>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
            >
              <option value="ALL">All Statuses</option>
              <option value="OPEN">Open</option>
              <option value="IN-REVIEW">In-Review</option>
              <option value="CLOSED">Closed</option>
            </select>
          </div>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* NC Table */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                <tr>
                  <th className="py-3 px-3">NC Number</th>
                  <th className="py-3 px-3">Work Order</th>
                  <th className="py-3 px-3">Stage</th>
                  <th className="py-3 px-3">Defect Code</th>
                  <th className="py-3 px-3 text-right">Defect Qty</th>
                  <th className="py-3 px-3 text-center">Days Open</th>
                  <th className="py-3 px-3">Disposition</th>
                  <th className="py-3 px-3">Status</th>
                  <th className="py-3 px-3 text-center">Action</th>
                </tr>
              </thead>

              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                {filteredRecords.map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                    <td className="py-3 px-3 font-mono font-bold text-rose-600 dark:text-rose-400">{r.nc_number}</td>
                    <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                      <Link href={`/production/tracking?wo=${r.wo_number}`} className="hover:underline">
                        {r.wo_number}
                      </Link>
                    </td>
                    <td className="py-3 px-3 font-mono font-semibold">{r.stage}</td>
                    <td className="py-3 px-3 font-semibold text-zinc-800 dark:text-zinc-200">{r.defect_code}</td>
                    <td className="py-3 px-3 text-right font-mono font-bold text-rose-600">{r.qty} pcs</td>
                    <td className="py-3 px-3 text-center font-mono font-bold">
                      <span className={`px-2 py-0.5 rounded-full text-[11px] ${r.days_open > 2 && r.status === "Open" ? "bg-rose-500/10 text-rose-600" : "text-zinc-500"}`}>
                        {r.days_open}d
                      </span>
                    </td>
                    <td className="py-3 px-3 text-zinc-600 dark:text-zinc-400">{r.disposition || "—"}</td>
                    <td className="py-3 px-3">
                      <Badge variant={r.status === "Closed" ? "green" : r.status === "Open" ? "red" : "amber"} size="sm">
                        {r.status}
                      </Badge>
                    </td>
                    <td className="py-3 px-3 text-center">
                      <button
                        type="button"
                        onClick={() => openEdit(r)}
                        className="rounded-lg border border-zinc-200 dark:border-zinc-800 px-2.5 py-1 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      >
                        Update / Close
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create NC Modal */}
        <Modal
          isOpen={showCreateModal}
          onClose={() => setShowCreateModal(false)}
          title="Log Non-Conformance (NC)"
          subtitle="Raise official defect record for QA MRB investigation"
        >
          <form onSubmit={handleCreateSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Work Order *</label>
                <select
                  value={newWO}
                  onChange={(e) => setNewWO(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  {wos.map((w) => (
                    <option key={w.wo_number} value={w.wo_number}>
                      {w.wo_number} — {w.current_stage}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Occurred at Stage *</label>
                <select
                  value={newStage}
                  onChange={(e) => setNewStage(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-semibold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  {["F1", "F2", "F3", "SP", "FI"].map((s) => (
                    <option key={s} value={s}>
                      Stage {s}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Defect Code Category *</label>
                <select
                  value={newDefect}
                  onChange={(e) => setNewDefect(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-rose-600 font-bold focus:outline-none"
                >
                  {DEFECT_CODES.map((d) => (
                    <option key={d.code} value={d.code}>
                      {d.label}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">Defective Quantity (pcs) *</label>
                <input
                  type="number"
                  required
                  min={1}
                  value={newQty}
                  onChange={(e) => setNewQty(e.target.value === "" ? "" : Number(e.target.value))}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-rose-600 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Initial Root Cause Assessment</label>
              <input
                type="text"
                value={newRootCause}
                onChange={(e) => setNewRootCause(e.target.value)}
                placeholder="e.g. Mold pouring temperature variation detected during heat #4"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Preliminary Disposition</label>
                <select
                  value={newDisposition}
                  onChange={(e) => setNewDisposition(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  <option value="Scrap & Melt">Scrap & Melt</option>
                  <option value="Rework / Re-cut">Rework / Re-cut</option>
                  <option value="Use As Is (Concession)">Use As Is (Concession)</option>
                  <option value="Quarantine Pending MRB">Quarantine Pending MRB</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Responsible Cell</label>
                <input
                  type="text"
                  value={newResponsibility}
                  onChange={(e) => setNewResponsibility(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setShowCreateModal(false)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-xl bg-rose-600 px-5 py-2 text-xs font-bold text-white hover:bg-rose-500 transition-colors"
              >
                {submitting ? "Logging..." : "Create NC Incident"}
              </button>
            </div>
          </form>
        </Modal>

        {/* Edit / Close NC Modal */}
        <Modal
          isOpen={!!editItem}
          onClose={() => setEditItem(null)}
          title={`Update NC Record — ${editItem?.nc_number}`}
          subtitle={`WO: ${editItem?.wo_number} | Stage: ${editItem?.stage} | Defect: ${editItem?.defect_code}`}
        >
          <form onSubmit={handleUpdateSubmit} className="space-y-4">
            <div>
              <label className="text-xs font-bold text-zinc-700 dark:text-zinc-300">NC Status *</label>
              <select
                value={editStatus}
                onChange={(e) => setEditStatus(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
              >
                <option value="Open">Open</option>
                <option value="In-Review">In-Review</option>
                <option value="Closed">Closed</option>
              </select>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Final MRB Disposition</label>
              <input
                type="text"
                value={editDisposition}
                onChange={(e) => setEditDisposition(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">Root Cause & Corrective Action (CAPA)</label>
              <textarea
                rows={3}
                value={editRootCause}
                onChange={(e) => setEditRootCause(e.target.value)}
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 p-3 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setEditItem(null)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2 text-xs font-semibold text-zinc-700 dark:text-zinc-300"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white hover:bg-blue-500 transition-colors"
              >
                {submitting ? "Updating..." : "Save QA Resolution"}
              </button>
            </div>
          </form>
        </Modal>
      </div>
    </AppShell>
  );
}

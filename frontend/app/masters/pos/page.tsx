"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getMasterCustomers,
  getPOMasters,
  createPOMaster,
  updatePOMaster,
  MasterCustomer,
  POMasterOut,
  POLineOut,
  POLineOrderSummary,
} from "@/lib/api";
import {
  FilePlus,
  AlertTriangle,
  FileSpreadsheet,
  Trash2,
  Plus,
  Edit3,
  Lock,
  X,
  CheckCircle2,
  Info,
} from "lucide-react";

interface LineDraft {
  id?: string;
  customer_part_number?: string;
  part_number: string;
  po_qty: string;
  allocated_qty?: number;
  available_qty?: number;
  required_date: string;
}

const PO_COVERAGE_LABELS: Record<string, { label: string; className: string }> = {
  PO_MATCHED: { label: "PO Matched", className: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300" },
  SCHEDULED_AWAITING_PO: { label: "Awaiting PO", className: "bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300" },
  COMMERCIAL_PO_PENDING: { label: "PO Pending Match", className: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300" },
  UNCONFIRMED: { label: "Unconfirmed", className: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400" },
};

const WO_RELEASE_LABELS: Record<string, string> = {
  AWAITING_ENG_RELEASE: "Awaiting Eng. Release",
  AWAITING_MFG_RELEASE: "Awaiting Mfg. Release",
  AWAITING_WO_RELEASE: "WO Created - Not Released",
  RELEASED: "Released",
};

/** Truthful PO -> OAR -> WO traceability for one PO line. Never fabricates a record:
 * an empty `orders` array renders "OAR not created", and each OAR with no work orders
 * renders "WO not created" -- the real, current linkage state, nothing inferred. */
function POLineTraceability({ orders }: { orders: POLineOrderSummary[] }) {
  if (!orders || orders.length === 0) {
    return <span className="text-zinc-400 italic">OAR not created</span>;
  }
  return (
    <div className="space-y-1.5">
      {orders.map((o) => {
        const coverage = PO_COVERAGE_LABELS[o.po_coverage_status] || PO_COVERAGE_LABELS.UNCONFIRMED;
        return (
          <div key={o.oar_id} className="flex flex-col gap-0.5">
            <div className="flex items-center gap-1.5">
              <span className="font-mono font-medium">{o.oar_number || "(OAR)"}</span>
              <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${coverage.className}`}>
                {coverage.label}
              </span>
            </div>
            {o.work_orders.length === 0 ? (
              <span className="text-zinc-400 italic text-[11px] pl-1">WO not created</span>
            ) : (
              <div className="flex flex-wrap gap-1 pl-1">
                {o.work_orders.map((wo) => (
                  <span
                    key={wo.wo_id}
                    className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-[10px] font-mono"
                    title={WO_RELEASE_LABELS[wo.release_status] || wo.release_status}
                  >
                    {wo.wo_number} - {WO_RELEASE_LABELS[wo.release_status] || wo.release_status}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function emptyLine(): LineDraft {
  return { customer_part_number: "", part_number: "", po_qty: "", required_date: "" };
}

export default function POMasterPage() {
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [pos, setPOs] = useState<POMasterOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  // Create form state
  const [poNumber, setPoNumber] = useState("");
  const [customerCode, setCustomerCode] = useState("");
  const [poDate, setPoDate] = useState("");
  const [validityDate, setValidityDate] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  // Edit modal state
  const [editingPO, setEditingPO] = useState<POMasterOut | null>(null);
  const [editPoNumber, setEditPoNumber] = useState("");
  const [editPoDate, setEditPoDate] = useState("");
  const [editValidityDate, setEditValidityDate] = useState("");
  const [editStatus, setEditStatus] = useState("open");
  const [editLines, setEditLines] = useState<LineDraft[]>([]);
  const [editError, setEditError] = useState("");
  const [editSuccess, setEditSuccess] = useState("");
  const [updating, setUpdating] = useState(false);

  async function loadAll() {
    setLoading(true);
    setListError("");
    try {
      const [c, p] = await Promise.all([getMasterCustomers(), getPOMasters()]);
      setCustomers(c);
      setPOs(p);
      if (!customerCode && c.length) setCustomerCode(c[0].customer_code);
    } catch (err: any) {
      setListError(err?.response?.data?.detail || "Could not load PO data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function updateLine(idx: number, field: keyof LineDraft, value: string) {
    setLines((prev) => prev.map((l, i) => (i === idx ? { ...l, [field]: value } : l)));
  }

  function updateEditLine(idx: number, field: keyof LineDraft, value: string) {
    setEditLines((prev) =>
      prev.map((l, i) => {
        if (i !== idx) return l;
        const updated = { ...l, [field]: value };
        if (field === "po_qty") {
          const qty = Number(value) || 0;
          const alloc = l.allocated_qty || 0;
          updated.available_qty = Math.max(0, qty - alloc);
        }
        return updated;
      })
    );
  }

  function openEditModal(po: POMasterOut) {
    setEditingPO(po);
    setEditPoNumber(po.po_number);
    setEditPoDate(po.po_date || "");
    setEditValidityDate(po.validity_date || "");
    setEditStatus(po.status);
    setEditLines(
      po.lines.map((l: POLineOut) => ({
        id: l.id,
        customer_part_number: l.customer_part_number || "",
        part_number: l.part_number,
        po_qty: String(l.po_qty),
        allocated_qty: l.allocated_qty,
        available_qty: l.available_qty,
        required_date: l.required_date || "",
      }))
    );
    setEditError("");
    setEditSuccess("");
  }

  function closeEditModal() {
    setEditingPO(null);
    setEditError("");
    setEditSuccess("");
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setCreateError("");
    setCreating(true);
    try {
      await createPOMaster({
        po_number: poNumber,
        customer_code: customerCode,
        po_date: poDate || undefined,
        validity_date: validityDate || undefined,
        lines: lines
          .filter((l) => (l.customer_part_number?.trim() || l.part_number?.trim()) && l.po_qty)
          .map((l) => ({
            customer_part_number: l.customer_part_number?.trim() || undefined,
            part_number: l.part_number?.trim() || undefined,
            po_qty: Number(l.po_qty),
            required_date: l.required_date || undefined,
          })),
      });
      setPoNumber("");
      setPoDate("");
      setValidityDate("");
      setLines([emptyLine()]);
      await loadAll();
    } catch (err: any) {
      setCreateError(err?.response?.data?.detail || "Could not create PO.");
    } finally {
      setCreating(false);
    }
  }

  async function handleUpdate(e: React.FormEvent) {
    e.preventDefault();
    if (!editingPO) return;
    setEditError("");
    setEditSuccess("");
    setUpdating(true);

    try {
      const validLines = editLines.filter(
        (l) => (l.customer_part_number?.trim() || l.part_number.trim()) && Number(l.po_qty) > 0
      );
      if (validLines.length === 0) {
        throw new Error("PO must have at least one valid line with positive quantity.");
      }

      await updatePOMaster(editingPO.id, {
        po_number: editPoNumber.trim(),
        customer_code: editingPO.customer_code,
        po_date: editPoDate || undefined,
        validity_date: editValidityDate || undefined,
        status: editStatus,
        lines: validLines.map((l) => ({
          id: l.id || undefined,
          customer_part_number: l.customer_part_number?.trim() || undefined,
          part_number: l.part_number.trim() || undefined,
          po_qty: Number(l.po_qty),
          required_date: l.required_date || undefined,
        })),
      });

      setEditSuccess("Purchase Order updated successfully.");
      await loadAll();
      setTimeout(() => {
        closeEditModal();
      }, 1200);
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || "Could not update PO.";
      setEditError(detail);
    } finally {
      setUpdating(false);
    }
  }

  const isPoAllocated = editingPO ? editingPO.lines.some((l) => l.allocated_qty > 0) : false;

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-6">
        <div>
          <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
            Masters
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            PO Master
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Confirmed customer purchase orders. Each line tracks allocated vs. available quantity
            as OARs are raised against it.
          </p>
        </div>

        {/* Add PO Section */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <FilePlus className="h-4 w-4 text-blue-500" /> Add PO
          </h3>
          {createError && (
            <div className="mt-3 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{createError}</span>
            </div>
          )}
          <form onSubmit={handleCreate} className="mt-3 space-y-3">
            <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
              <input
                required
                placeholder="PO number"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
              />
              <select
                required
                value={customerCode}
                onChange={(e) => setCustomerCode(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
              >
                <option value="" disabled>Select customer</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.customer_code}>{c.customer_code} — {c.name}</option>
                ))}
              </select>
              <input
                type="date"
                placeholder="PO date"
                value={poDate}
                onChange={(e) => setPoDate(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
              />
              <input
                type="date"
                placeholder="Validity date"
                value={validityDate}
                onChange={(e) => setValidityDate(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
              />
            </div>

            <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 p-3 space-y-2">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1">
                <p className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">PO Lines</p>
                <span className="text-[10px] text-zinc-400">
                  Enter Customer Part Number (internal part will be mapped or auto-generated)
                </span>
              </div>
              {lines.map((l, idx) => (
                <div key={idx} className="grid grid-cols-1 md:grid-cols-5 gap-2 items-center">
                  <input
                    placeholder="Customer Part No (e.g. RC47NN135000000092)"
                    value={l.customer_part_number || ""}
                    onChange={(e) => updateLine(idx, "customer_part_number", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-mono font-medium"
                  />
                  <input
                    placeholder="Internal Part No (optional)"
                    value={l.part_number}
                    onChange={(e) => updateLine(idx, "part_number", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs font-mono"
                  />
                  <input
                    required
                    type="number"
                    min={1}
                    placeholder="PO qty"
                    value={l.po_qty}
                    onChange={(e) => updateLine(idx, "po_qty", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
                  />
                  <input
                    type="date"
                    value={l.required_date}
                    onChange={(e) => updateLine(idx, "required_date", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
                  />
                  <button
                    type="button"
                    onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}
                    disabled={lines.length === 1}
                    className="flex items-center justify-center gap-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1.5 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-40 transition-colors"
                  >
                    <Trash2 className="h-3.5 w-3.5" /> Remove
                  </button>
                </div>
              ))}
              <button
                type="button"
                onClick={() => setLines((prev) => [...prev, emptyLine()])}
                className="flex items-center gap-1 rounded-lg bg-blue-50 dark:bg-blue-950/40 px-2.5 py-1.5 text-[11px] font-semibold text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" /> Add Line
              </button>
            </div>

            <button
              type="submit"
              disabled={creating}
              className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors"
            >
              {creating ? "Creating..." : "Create PO"}
            </button>
          </form>
        </div>

        {/* Existing POs List */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-zinc-500" />
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing POs</h3>
            </div>
          </div>
          {listError && (
            <div className="m-4 flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-2.5 py-1.5 text-[11px] font-medium text-rose-600 dark:text-rose-400">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5" />
              <span>{listError}</span>
            </div>
          )}
          {loading ? (
            <div className="p-4 text-xs text-zinc-500">Loading...</div>
          ) : pos.length === 0 ? (
            <div className="p-4 text-xs text-zinc-500">No POs yet.</div>
          ) : (
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {pos.map((po) => (
                <div key={po.id} className="p-4">
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <p className="text-xs font-bold text-zinc-900 dark:text-zinc-100">{po.po_number}</p>
                        <span className="rounded-md bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400 px-2 py-0.5 text-[10px] font-bold uppercase">
                          {po.status}
                        </span>
                      </div>
                      <p className="text-[11px] text-zinc-500 mt-0.5">{po.customer_code} — {po.customer_name}</p>
                      <div className="flex items-center gap-4 text-[10px] text-zinc-400 mt-1">
                        <span>PO Date: {po.po_date || "—"}</span>
                        <span>Validity: {po.validity_date || "—"}</span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => openEditModal(po)}
                      className="flex items-center gap-1.5 rounded-lg bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 px-3 py-1.5 text-xs font-semibold text-zinc-800 dark:text-zinc-200 transition-colors"
                    >
                      <Edit3 className="h-3.5 w-3.5 text-blue-500" /> Edit PO
                    </button>
                  </div>
                  <table className="w-full text-xs mt-3">
                    <thead className="text-zinc-500 dark:text-zinc-400">
                      <tr>
                        <th className="text-left py-1 font-semibold">Customer Part</th>
                        <th className="text-left py-1 font-semibold">Internal Part</th>
                        <th className="text-right py-1 font-semibold">PO Qty</th>
                        <th className="text-right py-1 font-semibold">Allocated</th>
                        <th className="text-right py-1 font-semibold">Available</th>
                        <th className="text-left py-1 font-semibold">Required Date</th>
                        <th className="text-left py-1 font-semibold">OAR / WO</th>
                      </tr>
                    </thead>
                    <tbody>
                      {po.lines.map((l) => (
                        <tr key={l.id} className="border-t border-zinc-100 dark:border-zinc-800 align-top">
                          <td className="py-1.5 font-mono text-zinc-900 dark:text-zinc-100 font-medium">
                            {l.customer_part_number || "—"}
                          </td>
                          <td className="py-1.5 font-mono text-zinc-500">{l.part_number}</td>
                          <td className="py-1.5 text-right font-medium">{l.po_qty}</td>
                          <td className="py-1.5 text-right font-medium text-amber-600 dark:text-amber-400">{l.allocated_qty}</td>
                          <td
                            className={`py-1.5 text-right font-semibold ${
                              l.available_qty === 0 ? "text-zinc-400" : "text-emerald-600 dark:text-emerald-400"
                            }`}
                          >
                            {l.available_qty}
                          </td>
                          <td className="py-1.5 text-zinc-500">{l.required_date || "-"}</td>
                          <td className="py-1.5">
                            <POLineTraceability orders={l.orders} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Edit PO Modal */}
        {editingPO && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
            <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-2xl space-y-4">
              <div className="flex items-center justify-between border-b border-zinc-100 dark:border-zinc-800 pb-3">
                <div className="flex items-center gap-2">
                  <Edit3 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                  <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100">
                    Edit Purchase Order — <span className="font-mono">{editingPO.po_number}</span>
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
                <div className="flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 p-3 text-xs font-medium text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/50">
                  <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{editError}</span>
                </div>
              )}

              {editSuccess && (
                <div className="flex items-start gap-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 p-3 text-xs font-medium text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-900/50">
                  <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
                  <span>{editSuccess}</span>
                </div>
              )}

              <form onSubmit={handleUpdate} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* Customer (Immutable) */}
                  <div>
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                      <Lock className="h-3 w-3 text-zinc-400" /> Customer (Immutable)
                    </label>
                    <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/60 px-3 py-2 text-xs font-medium text-zinc-600 dark:text-zinc-300">
                      {editingPO.customer_code} — {editingPO.customer_name}
                    </div>
                  </div>

                  {/* PO Number */}
                  <div>
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider flex items-center gap-1 mb-1">
                      {isPoAllocated && <Lock className="h-3 w-3 text-amber-500" />} PO Number
                      {isPoAllocated && <span className="text-[10px] text-amber-600 font-normal lowercase">(locked: orders linked)</span>}
                    </label>
                    <input
                      type="text"
                      required
                      disabled={isPoAllocated}
                      value={editPoNumber}
                      onChange={(e) => setEditPoNumber(e.target.value)}
                      title={isPoAllocated ? "Cannot modify PO number because downstream orders (OARs) are linked." : ""}
                      className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs disabled:bg-zinc-100 dark:disabled:bg-zinc-800/60 disabled:text-zinc-400"
                    />
                  </div>

                  {/* PO Date */}
                  <div>
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider block mb-1">
                      PO Date
                    </label>
                    <input
                      type="date"
                      value={editPoDate}
                      onChange={(e) => setEditPoDate(e.target.value)}
                      className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
                    />
                  </div>

                  {/* Validity Date */}
                  <div>
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider block mb-1">
                      Validity Date
                    </label>
                    <input
                      type="date"
                      value={editValidityDate}
                      onChange={(e) => setEditValidityDate(e.target.value)}
                      className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
                    />
                  </div>

                  {/* Status */}
                  <div className="md:col-span-2">
                    <label className="text-[11px] font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider block mb-1">
                      Status
                    </label>
                    <select
                      value={editStatus}
                      onChange={(e) => setEditStatus(e.target.value)}
                      className="w-full rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
                    >
                      <option value="open">open</option>
                      <option value="partially_allocated">partially_allocated</option>
                      <option value="closed">closed</option>
                      <option value="cancelled">cancelled</option>
                    </select>
                  </div>
                </div>

                {/* PO Lines Table */}
                <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">
                      PO Lines & Allocations
                    </p>
                    <span className="text-[10px] text-zinc-400">
                      Line qty cannot be reduced below allocated qty
                    </span>
                  </div>

                  <div className="space-y-2">
                    {editLines.map((l, idx) => {
                      const isAllocated = (l.allocated_qty || 0) > 0;
                      return (
                        <div
                          key={idx}
                          className="grid grid-cols-1 md:grid-cols-12 gap-2 items-center rounded-lg border border-zinc-100 dark:border-zinc-800 p-2 bg-zinc-50/50 dark:bg-zinc-800/30 text-xs"
                        >
                          <div className="md:col-span-3">
                            <label className="text-[10px] text-zinc-400 block md:hidden">Customer Part</label>
                            <input
                              type="text"
                              disabled={Boolean(l.id && isAllocated)}
                              placeholder="Customer Part No"
                              value={l.customer_part_number || ""}
                              onChange={(e) => updateEditLine(idx, "customer_part_number", e.target.value)}
                              className="w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-transparent px-2.5 py-1.5 font-mono text-xs font-medium disabled:bg-zinc-100 dark:disabled:bg-zinc-800 disabled:text-zinc-400"
                            />
                          </div>

                          <div className="md:col-span-2">
                            <label className="text-[10px] text-zinc-400 block md:hidden">Internal Part</label>
                            <input
                              type="text"
                              disabled={Boolean(l.id && isAllocated)}
                              placeholder="Internal Part No"
                              value={l.part_number}
                              onChange={(e) => updateEditLine(idx, "part_number", e.target.value)}
                              className="w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-transparent px-2.5 py-1.5 font-mono text-xs disabled:bg-zinc-100 dark:disabled:bg-zinc-800 disabled:text-zinc-400"
                            />
                          </div>

                          <div className="md:col-span-2">
                            <label className="text-[10px] text-zinc-400 block md:hidden">PO Qty</label>
                            <input
                              type="number"
                              required
                              min={l.allocated_qty || 1}
                              placeholder="PO Qty"
                              value={l.po_qty}
                              onChange={(e) => updateEditLine(idx, "po_qty", e.target.value)}
                              className="w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-transparent px-2.5 py-1.5 text-xs text-right"
                            />
                          </div>

                          <div className="md:col-span-1 text-center md:text-right">
                            <label className="text-[10px] text-zinc-400 block md:hidden">Allocated</label>
                            <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-400">
                              {l.allocated_qty || 0} alloc
                            </span>
                          </div>

                          <div className="md:col-span-1 text-center md:text-right">
                            <label className="text-[10px] text-zinc-400 block md:hidden">Available</label>
                            <span className="inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400">
                              {l.available_qty !== undefined
                                ? l.available_qty
                                : Math.max(0, (Number(l.po_qty) || 0) - (l.allocated_qty || 0))}{" "}
                              avail
                            </span>
                          </div>

                          <div className="md:col-span-2">
                            <label className="text-[10px] text-zinc-400 block md:hidden">Req Date</label>
                            <input
                              type="date"
                              value={l.required_date}
                              onChange={(e) => updateEditLine(idx, "required_date", e.target.value)}
                              className="w-full rounded-md border border-zinc-200 dark:border-zinc-700 bg-transparent px-2 py-1.5 text-xs"
                            />
                          </div>

                          <div className="md:col-span-1 flex justify-end">
                            <button
                              type="button"
                              onClick={() => setEditLines((prev) => prev.filter((_, i) => i !== idx))}
                              disabled={Boolean(l.id && isAllocated) || editLines.length === 1}
                              title={
                                l.id && isAllocated
                                  ? "Cannot delete line with allocated orders"
                                  : editLines.length === 1
                                  ? "PO must have at least one line"
                                  : "Remove line"
                              }
                              className="p-1.5 rounded-lg text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-950/50 disabled:opacity-30 disabled:pointer-events-none"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <button
                    type="button"
                    onClick={() => setEditLines((prev) => [...prev, emptyLine()])}
                    className="flex items-center gap-1 rounded-lg bg-blue-50 dark:bg-blue-950/40 px-2.5 py-1.5 text-[11px] font-semibold text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
                  >
                    <Plus className="h-3.5 w-3.5" /> Add Line
                  </button>
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
                    disabled={updating}
                    className="rounded-xl bg-blue-600 px-5 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors"
                  >
                    {updating ? "Saving..." : "Save Changes"}
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

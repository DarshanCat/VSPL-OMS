"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getMasterCustomers, getPOMasters, createPOMaster, MasterCustomer, POMasterOut } from "@/lib/api";
import { FilePlus, AlertTriangle, FileSpreadsheet, Trash2, Plus } from "lucide-react";

interface LineDraft {
  part_number: string;
  po_qty: string;
  required_date: string;
}

function emptyLine(): LineDraft {
  return { part_number: "", po_qty: "", required_date: "" };
}

export default function POMasterPage() {
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [pos, setPOs] = useState<POMasterOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState("");

  const [poNumber, setPoNumber] = useState("");
  const [customerCode, setCustomerCode] = useState("");
  const [poDate, setPoDate] = useState("");
  const [validityDate, setValidityDate] = useState("");
  const [lines, setLines] = useState<LineDraft[]>([emptyLine()]);
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

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
          .filter((l) => l.part_number && l.po_qty)
          .map((l) => ({
            part_number: l.part_number,
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
              <input required placeholder="PO number" value={poNumber} onChange={(e) => setPoNumber(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
              <select required value={customerCode} onChange={(e) => setCustomerCode(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs">
                <option value="" disabled>Select customer</option>
                {customers.map((c) => (
                  <option key={c.id} value={c.customer_code}>{c.customer_code} — {c.name}</option>
                ))}
              </select>
              <input type="date" placeholder="PO date" value={poDate} onChange={(e) => setPoDate(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
              <input type="date" placeholder="Validity date" value={validityDate} onChange={(e) => setValidityDate(e.target.value)}
                className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
            </div>

            <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 p-3 space-y-2">
              <p className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">PO Lines</p>
              {lines.map((l, idx) => (
                <div key={idx} className="grid grid-cols-1 md:grid-cols-4 gap-2 items-center">
                  <input required placeholder="Part number" value={l.part_number}
                    onChange={(e) => updateLine(idx, "part_number", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
                  <input required type="number" min={1} placeholder="PO qty" value={l.po_qty}
                    onChange={(e) => updateLine(idx, "po_qty", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
                  <input type="date" value={l.required_date}
                    onChange={(e) => updateLine(idx, "required_date", e.target.value)}
                    className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs" />
                  <button type="button" onClick={() => setLines((prev) => prev.filter((_, i) => i !== idx))}
                    disabled={lines.length === 1}
                    className="flex items-center justify-center gap-1 rounded-lg bg-zinc-100 dark:bg-zinc-800 px-2.5 py-1.5 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700 disabled:opacity-40 transition-colors">
                    <Trash2 className="h-3.5 w-3.5" /> Remove
                  </button>
                </div>
              ))}
              <button type="button" onClick={() => setLines((prev) => [...prev, emptyLine()])}
                className="flex items-center gap-1 rounded-lg bg-blue-50 dark:bg-blue-950/40 px-2.5 py-1.5 text-[11px] font-semibold text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors">
                <Plus className="h-3.5 w-3.5" /> Add Line
              </button>
            </div>

            <button type="submit" disabled={creating}
              className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors">
              {creating ? "Creating..." : "Create PO"}
            </button>
          </form>
        </div>

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
          <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center gap-2">
            <FileSpreadsheet className="h-4 w-4 text-zinc-500" />
            <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">Existing POs</h3>
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
                      <p className="text-xs font-bold text-zinc-900 dark:text-zinc-100">{po.po_number}</p>
                      <p className="text-[11px] text-zinc-500">{po.customer_code} — {po.customer_name}</p>
                    </div>
                    <span className="rounded-md bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400 px-2 py-0.5 text-[10px] font-bold uppercase">
                      {po.status}
                    </span>
                  </div>
                  <table className="w-full text-xs mt-3">
                    <thead className="text-zinc-500 dark:text-zinc-400">
                      <tr>
                        <th className="text-left py-1 font-semibold">Part</th>
                        <th className="text-right py-1 font-semibold">PO Qty</th>
                        <th className="text-right py-1 font-semibold">Allocated</th>
                        <th className="text-right py-1 font-semibold">Available</th>
                        <th className="text-left py-1 font-semibold">Required Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {po.lines.map((l) => (
                        <tr key={l.id} className="border-t border-zinc-100 dark:border-zinc-800">
                          <td className="py-1.5 font-mono">{l.part_number}</td>
                          <td className="py-1.5 text-right">{l.po_qty}</td>
                          <td className="py-1.5 text-right">{l.allocated_qty}</td>
                          <td className={`py-1.5 text-right font-semibold ${l.available_qty === 0 ? "text-zinc-400" : "text-emerald-600 dark:text-emerald-400"}`}>
                            {l.available_qty}
                          </td>
                          <td className="py-1.5">{l.required_date || "-"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}

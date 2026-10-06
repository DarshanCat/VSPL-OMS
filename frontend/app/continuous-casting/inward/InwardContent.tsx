"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { PackageCheck, Plus, X } from "lucide-react";
import { Modal } from "@/app/components/ui/Modal";
import { CCActionForm } from "@/app/components/cc/CCActionForm";
import { CCConfirmModal } from "@/app/components/cc/CCConfirmModal";
import { CCErrorBanner } from "@/app/components/cc/CCErrorBanner";
import { CCFilterBar } from "@/app/components/cc/CCFilterBar";
import { CCLengthCell } from "@/app/components/cc/CCLengthCell";
import { CCPagedTable, CCColumn } from "@/app/components/cc/CCPagedTable";
import { CCRoleGate } from "@/app/components/cc/CCRoleGate";
import { CCStatusBadge } from "@/app/components/cc/CCStatusBadge";
import { CCTxnNumber } from "@/app/components/cc/CCTxnNumber";
import {
  ccCreateInward, ccDecideInwardQA, ccErrorMessage, ccGetInward, ccListInwards, ccListMaterials, ccListStockUnits,
  CCInwardDetail, CCInwardQADecisionResult, CCInwardResult, CCInwardStockOut, CCMaterialOut, CCQADecision, CCQAStatus,
  CCStockUnitOut,
} from "@/lib/continuousCastingApi";
import { CC_INWARD_ROLES, CC_QA_ROLES } from "@/lib/continuousCastingRoles";
import {
  expandUnitLengths, formatMetres, isBlankGroup, LengthGroupInput, summarizeGroups, validateLengthGroups,
} from "@/lib/continuousCastingInwardGroups";
import {
  ccInputCls, ccLabelCls, ccPrimaryBtnCls, ccSecondaryBtnCls, fmtDateTime, parseOptionalPositiveInt,
} from "@/lib/continuousCastingForm";

const PAGE_SIZE = 50;
const UNIT_PAGE = 500; // the backend maximum page size

interface Filters { inward_number: string; material_id: string; qa_status: "" | CCQAStatus; has_free_stock: "" | "true" | "false" }
const NO_FILTERS: Filters = { inward_number: "", material_id: "", qa_status: "", has_free_stock: "" };

const httpStatus = (err: unknown) => (err as { response?: { status?: number } })?.response?.status;

export default function InwardContent() {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCInwardStockOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [materials, setMaterials] = useState<CCMaterialOut[]>([]);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const reqSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    try {
      const page = await ccListInwards({
        inward_number: applied.inward_number, material_id: applied.material_id,
        qa_status: applied.qa_status === "" ? undefined : applied.qa_status,
        has_free_stock: applied.has_free_stock === "" ? undefined : applied.has_free_stock === "true",
        limit: PAGE_SIZE, offset,
      });
      if (seq !== reqSeq.current) return;
      setRows(page.items);
      setTotal(page.total);
      setListError(null);
    } catch (err) {
      if (seq !== reqSeq.current) return;
      setListError(ccErrorMessage(err));
    } finally {
      if (seq === reqSeq.current) setLoading(false);
    }
  }, [applied, offset]);

  useEffect(() => { void load(); }, [load]);

  const loadMaterials = useCallback(async () => {
    try {
      setMaterials((await ccListMaterials({ limit: UNIT_PAGE })).items);
    } catch {
      /* the inward list still works; the create form reports its own load error */
    }
  }, []);
  useEffect(() => { void loadMaterials(); }, [loadMaterials]);

  const columns: CCColumn<CCInwardStockOut>[] = [
    {
      header: "Inward no.",
      render: (r) => (
        <button type="button" onClick={() => setSelectedId(r.inward_id)}
          className="font-mono font-semibold text-blue-600 hover:underline dark:text-blue-400">
          {r.inward_number}
        </button>
      ),
    },
    { header: "Material", render: (r) => <span><span className="font-mono">{r.material_code}</span><br /><span className="text-zinc-400">{r.grade} / {r.section}</span></span> },
    { header: "Received", render: (r) => fmtDateTime(r.received_at) },
    { header: "QA", render: (r) => <CCStatusBadge status={r.qa_status} /> },
    { header: "Units", className: "text-right font-mono", render: (r) => r.unit_count },
    { header: "Received pcs", className: "text-right font-mono", render: (r) => r.received_piece_count },
    { header: "Received length", className: "text-right", render: (r) => <CCLengthCell mm={r.received_total_length_mm} /> },
    { header: "Remaining", className: "text-right", render: (r) => <CCLengthCell mm={r.remaining_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (r) => <CCLengthCell mm={r.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (r) => <CCLengthCell mm={r.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (r) => <CCLengthCell mm={r.consumed_length_mm} /> },
    { header: "Scrapped", className: "text-right", render: (r) => <CCLengthCell mm={r.scrapped_length_mm} /> },
    { header: "Free", className: "text-right font-semibold", render: (r) => <CCLengthCell mm={r.free_length_mm} /> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
            <PackageCheck className="h-3.5 w-3.5" /> Continuous Casting
          </p>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Inward &amp; QA</h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            Receive continuous casting bars, then record the QA decision. Quantities are shown exactly as the backend reports them.
          </p>
        </div>
        <CCRoleGate allowed={CC_INWARD_ROLES}>
          <button type="button" onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700">
            <Plus className="h-3.5 w-3.5" /> New inward
          </button>
        </CCRoleGate>
      </div>

      {selectedId && (
        <InwardDetailPanel
          inwardId={selectedId}
          onClose={() => setSelectedId(null)}
          onChanged={() => void load()}
        />
      )}

      <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setApplied(filters); }}>
        <CCFilterBar onClear={() => { setFilters(NO_FILTERS); setApplied(NO_FILTERS); setOffset(0); }}>
          <div>
            <label className={ccLabelCls}>Inward no.</label>
            <input className={ccInputCls} value={filters.inward_number} onChange={(e) => setFilters({ ...filters, inward_number: e.target.value })} />
          </div>
          <div>
            <label className={ccLabelCls}>Material</label>
            <select className={ccInputCls} value={filters.material_id} onChange={(e) => setFilters({ ...filters, material_id: e.target.value })}>
              <option value="">All</option>
              {materials.map((m) => <option key={m.material_id} value={m.material_id}>{m.material_code}</option>)}
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>QA status</label>
            <select className={ccInputCls} value={filters.qa_status} onChange={(e) => setFilters({ ...filters, qa_status: e.target.value as Filters["qa_status"] })}>
              <option value="">All</option>
              <option value="PENDING_QA">PENDING_QA</option>
              <option value="ACCEPTED">ACCEPTED</option>
              <option value="REJECTED">REJECTED</option>
              <option value="ON_HOLD">ON_HOLD</option>
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>Free stock</label>
            <select className={ccInputCls} value={filters.has_free_stock} onChange={(e) => setFilters({ ...filters, has_free_stock: e.target.value as Filters["has_free_stock"] })}>
              <option value="">All</option>
              <option value="true">Has free stock</option>
              <option value="false">No free stock</option>
            </select>
          </div>
          <button type="submit" className={ccSecondaryBtnCls}>Apply</button>
        </CCFilterBar>
      </form>

      <CCPagedTable
        columns={columns} items={rows} total={total} limit={PAGE_SIZE} offset={offset}
        onPageChange={setOffset} rowKey={(r) => r.inward_id} loading={loading} error={listError}
        emptyText="No inwards found."
      />

      <CreateInwardModal
        isOpen={createOpen}
        materials={materials.filter((m) => m.is_active)}
        onClose={() => setCreateOpen(false)}
        onCreated={(res) => { setOffset(0); void load(); setSelectedId(res.inward_id); }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ create inward
// ONE inward = ONE material (its grade, section and dimensions come from the material master and are shown read-only)
// with one or more LENGTH GROUPS (length + number of bars). The groups are expanded into the flat unit_lengths_mm list
// only at submit time; the backend creates one stock unit per physical bar. A receipt with several materials or
// dimensions is posted as several inwards (they may share a GRN reference).
function CreateInwardModal({ isOpen, materials, onClose, onCreated }: {
  isOpen: boolean; materials: CCMaterialOut[]; onClose: () => void; onCreated: (res: CCInwardResult) => void;
}) {
  const [materialId, setMaterialId] = useState("");
  const [groups, setGroups] = useState<LengthGroupInput[]>([{ length: "", count: "" }]);
  const [grn, setGrn] = useState("");
  const [location, setLocation] = useState("");
  const [remarks, setRemarks] = useState("");
  const [declPieces, setDeclPieces] = useState("");
  const [declTotal, setDeclTotal] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CCInwardResult | null>(null);
  const lengthRefs = useRef<(HTMLInputElement | null)[]>([]);
  const countRefs = useRef<(HTMLInputElement | null)[]>([]);
  const focusLengthOf = useRef<number | null>(null);
  const inFlight = useRef(false); // the inward API has no idempotency key, so a second request must never start

  useEffect(() => {
    if (!isOpen) return;
    setMaterialId(""); setGroups([{ length: "", count: "" }]); setGrn(""); setLocation("");
    setRemarks(""); setDeclPieces(""); setDeclTotal("");
    setError(null); setResult(null);
  }, [isOpen]);

  useEffect(() => {
    if (focusLengthOf.current !== null) {
      lengthRefs.current[focusLengthOf.current]?.focus();
      focusLengthOf.current = null;
    }
  }, [groups]);

  const material = materials.find((m) => m.material_id === materialId) ?? null;
  const summary = summarizeGroups(groups); // entry convenience only; the backend is authoritative

  const setRow = (i: number, patch: Partial<LengthGroupInput>) =>
    setGroups(groups.map((g, j) => (j === i ? { ...g, ...patch } : g)));
  const removeRow = (i: number) => setGroups(groups.length === 1 ? [{ length: "", count: "" }] : groups.filter((_, j) => j !== i));
  const addRow = () => { focusLengthOf.current = groups.length; setGroups([...groups, { length: "", count: "" }]); };

  // Enter: length -> bars; bars -> next row (a new one after the last); Enter on an empty final row submits.
  const onLengthKey = (e: React.KeyboardEvent<HTMLInputElement>, i: number) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const last = i === groups.length - 1;
    if (isBlankGroup(groups[i]) && last && summary.bars > 0) void submit();
    else countRefs.current[i]?.focus();
  };
  const onCountKey = (e: React.KeyboardEvent<HTMLInputElement>, i: number) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    if (groups[i].length.trim() === "" || groups[i].count.trim() === "") return;
    if (i === groups.length - 1) addRow();
    else lengthRefs.current[i + 1]?.focus();
  };

  const submit = async () => {
    if (inFlight.current) return;
    if (!materialId) return setError("Select a material.");
    const check = validateLengthGroups(groups);
    if (!check.ok) return setError(check.error);
    const pieces = parseOptionalPositiveInt(declPieces);
    const totalMm = parseOptionalPositiveInt(declTotal);
    if ([pieces, totalMm].some((n) => n !== null && Number.isNaN(n))) {
      return setError("Declared piece count and total length must be whole numbers greater than 0, or empty.");
    }
    inFlight.current = true;
    setBusy(true);
    setError(null);
    try {
      const res = await ccCreateInward({
        material_id: materialId,
        unit_lengths_mm: expandUnitLengths(check.groups), // one entry per physical bar, built only now
        received_piece_count: pieces, received_total_length_mm: totalMm,
        grn_reference: grn.trim() || null, location: location.trim() || null, remarks: remarks.trim() || null,
      });
      setResult(res);
      onCreated(res);
    } catch (err) {
      setError(ccErrorMessage(err)); // never retried automatically
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={busy ? () => {} : onClose} title="New inward" subtitle="One material, one or more length groups" maxWidth="2xl">
      <div className="max-h-[75vh] overflow-y-auto px-6 py-4 text-xs">
        {result ? (
          <div className="space-y-3">
            <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-emerald-700 dark:text-emerald-300">
              {result.message}
            </div>
            <dl className="grid grid-cols-2 gap-3">
              <div><dt className="text-zinc-500">Inward number</dt><dd><CCTxnNumber value={result.inward_number} /></dd></div>
              <div><dt className="text-zinc-500">QA status</dt><dd><CCStatusBadge status={result.qa_status} /></dd></div>
              <div><dt className="text-zinc-500">Physical units</dt><dd className="font-mono">{result.units.length}</dd></div>
              <div><dt className="text-zinc-500">Total received length</dt><dd><CCLengthCell mm={result.received_total_length_mm} /></dd></div>
              <div><dt className="text-zinc-500">Reconciled by backend</dt><dd>{result.reconciled ? "Yes" : "No"}</dd></div>
              <div><dt className="text-zinc-500">Allocation eligible</dt>
                <dd>{result.allocation_eligible ? "Yes" : `No${result.allocation_ineligible_reason ? ` - ${result.allocation_ineligible_reason}` : ""}`}</dd></div>
            </dl>
            <div className="max-h-40 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800">
              <table className="w-full">
                <thead className="bg-zinc-50 text-left text-zinc-500 dark:bg-zinc-800/50"><tr><th className="px-2 py-1">Unit</th><th className="px-2 py-1">Ledger txn</th><th className="px-2 py-1 text-right">Length</th></tr></thead>
                <tbody>{result.units.map((u) => (
                  <tr key={u.unit_number}><td className="px-2 py-1"><CCTxnNumber value={u.unit_number} /></td>
                    <td className="px-2 py-1"><CCTxnNumber value={u.ledger_transaction_number} /></td>
                    <td className="px-2 py-1 text-right"><CCLengthCell mm={u.original_length_mm} /></td></tr>
                ))}</tbody>
              </table>
            </div>
            <p className="text-zinc-500">QA is decided per inward. Another material or dimension is received as a separate inward (it may share the GRN reference).</p>
            <div className="flex justify-end"><button type="button" onClick={onClose} className={ccPrimaryBtnCls}>Close</button></div>
          </div>
        ) : (
          <CCActionForm onSubmit={submit} busy={busy} error={error} submitLabel="Create inward">
            <div>
              <label className={ccLabelCls}>Material *</label>
              <select className={ccInputCls} value={materialId} onChange={(e) => setMaterialId(e.target.value)}>
                <option value="">Select active material...</option>
                {materials.map((m) => (
                  <option key={m.material_id} value={m.material_id}>
                    {m.material_code} — {m.grade} — {m.stock_dimension_a_mm}{m.stock_dimension_b_mm ? ` × ${m.stock_dimension_b_mm}` : ""} mm
                  </option>
                ))}
              </select>
              {material && (
                <dl className="mt-2 grid grid-cols-2 gap-2 rounded-lg border border-zinc-200 bg-zinc-50 p-2 dark:border-zinc-800 dark:bg-zinc-800/30 sm:grid-cols-4">
                  <div><dt className="text-zinc-500">Grade</dt><dd>{material.grade}</dd></div>
                  <div><dt className="text-zinc-500">Section</dt><dd>{material.section}</dd></div>
                  <div><dt className="text-zinc-500">Dimension A</dt><dd className="font-mono">{material.stock_dimension_a_mm} mm</dd></div>
                  <div><dt className="text-zinc-500">Dimension B</dt><dd className="font-mono">{material.stock_dimension_b_mm ? `${material.stock_dimension_b_mm} mm` : "-"}</dd></div>
                  <p className="col-span-2 text-[11px] text-zinc-400 sm:col-span-4">Dimensions come from the material master and cannot be changed here.</p>
                </dl>
              )}
            </div>

            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <span className="font-semibold">Length groups</span>
                <span className="text-zinc-500">
                  Physical bars: <b className="font-mono">{summary.bars.toLocaleString("en-US")}</b> | Total length:{" "}
                  <b className="font-mono">{summary.totalMm.toLocaleString("en-US")} mm</b> ({formatMetres(summary.totalMm)} m)
                </span>
              </div>
              <table className="w-full">
                <thead className="text-left text-zinc-500">
                  <tr><th className="px-1 py-1 font-medium">Length (mm)</th><th className="px-1 py-1 font-medium">No. of bars</th><th className="w-16 px-1 py-1 font-medium">Action</th></tr>
                </thead>
                <tbody>
                  {groups.map((g, i) => (
                    <tr key={i}>
                      <td className="px-1 py-0.5">
                        <input ref={(el) => { lengthRefs.current[i] = el; }} className={ccInputCls} inputMode="numeric" value={g.length}
                          onChange={(e) => setRow(i, { length: e.target.value })} onKeyDown={(e) => onLengthKey(e, i)} aria-label={`Group ${i + 1} length in mm`} />
                      </td>
                      <td className="px-1 py-0.5">
                        <input ref={(el) => { countRefs.current[i] = el; }} className={ccInputCls} inputMode="numeric" value={g.count}
                          onChange={(e) => setRow(i, { count: e.target.value })} onKeyDown={(e) => onCountKey(e, i)} aria-label={`Group ${i + 1} number of bars`} />
                      </td>
                      <td className="px-1 py-0.5">
                        <button type="button" onClick={() => removeRow(i)} className="text-zinc-500 hover:text-rose-600">Remove</button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <button type="button" onClick={addRow} className="mt-2 text-blue-600 hover:underline dark:text-blue-400">+ Add length group</button>
              <p className="mt-1 text-[11px] text-zinc-400">
                Each length appears once: use 1000 × 105, not 1000 × 50 and 1000 × 55. Enter moves length → bars → next group; Enter on an empty last row submits.
                The totals are an entry aid; the backend is authoritative and creates one stock unit per bar.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div><label className={ccLabelCls}>GRN reference</label><input className={ccInputCls} maxLength={100} value={grn} onChange={(e) => setGrn(e.target.value)} /></div>
              <div><label className={ccLabelCls}>Location</label><input className={ccInputCls} maxLength={100} value={location} onChange={(e) => setLocation(e.target.value)} /></div>
              <div />
              <div className="col-span-3"><label className={ccLabelCls}>Remarks</label><textarea className={ccInputCls} rows={2} maxLength={2000} value={remarks} onChange={(e) => setRemarks(e.target.value)} /></div>
            </div>

            <details className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <summary className="cursor-pointer font-semibold">Declared GRN figures (optional cross-check)</summary>
              <p className="mt-1 text-[11px] text-zinc-500">The backend only cross-checks these against the length groups; the groups are authoritative.</p>
              <div className="mt-2 grid grid-cols-2 gap-3">
                <div><label className={ccLabelCls}>Declared pieces</label><input className={ccInputCls} inputMode="numeric" value={declPieces} onChange={(e) => setDeclPieces(e.target.value)} /></div>
                <div><label className={ccLabelCls}>Declared total (mm)</label><input className={ccInputCls} inputMode="numeric" value={declTotal} onChange={(e) => setDeclTotal(e.target.value)} /></div>
              </div>
            </details>
          </CCActionForm>
        )}
      </div>
    </Modal>
  );
}

// ------------------------------------------------------------------ inward detail + QA
function InwardDetailPanel({ inwardId, onClose, onChanged }: {
  inwardId: string; onClose: () => void; onChanged: () => void;
}) {
  const [inward, setInward] = useState<CCInwardDetail | null>(null);
  const [units, setUnits] = useState<CCStockUnitOut[]>([]);
  const [unitsTotal, setUnitsTotal] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [decision, setDecision] = useState<CCQADecision | "">("");
  const [reason, setReason] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [qaError, setQaError] = useState<string | null>(null);
  const [qaResult, setQaResult] = useState<CCInwardQADecisionResult | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [detail, unitPage] = await Promise.all([
        ccGetInward(inwardId),
        ccListStockUnits({ inward_id: inwardId, limit: UNIT_PAGE }),
      ]);
      setInward(detail);
      setUnits(unitPage.items);
      setUnitsTotal(unitPage.total);
      setLoadError(null);
    } catch (err) {
      setLoadError(ccErrorMessage(err));
    }
  }, [inwardId]);

  useEffect(() => {
    setInward(null); setUnits([]); setDecision(""); setReason(""); setQaError(null); setQaResult(null);
    void refresh();
  }, [inwardId, refresh]);

  const reasonRequired = decision === "REJECTED" || decision === "ON_HOLD";

  const askConfirm = () => {
    if (!decision) return setQaError("Choose a decision.");
    if (reasonRequired && reason.trim() === "") return setQaError(`A reason is required for a ${decision} decision.`);
    setQaError(null);
    setConfirmOpen(true);
  };

  const submitQA = async () => {
    if (!decision || busy) return;
    setBusy(true);
    setQaError(null);
    try {
      const res = await ccDecideInwardQA(inwardId, { decision, reason: reason.trim() === "" ? null : reason.trim() });
      setQaResult(res);
      setConfirmOpen(false);
      setDecision(""); setReason("");
      await refresh();
      onChanged();
    } catch (err) {
      // Show the backend's message, then re-read the inward so the screen shows the real status. Not retried.
      setQaError(ccErrorMessage(err));
      setConfirmOpen(false);
      if (httpStatus(err) !== 401) { await refresh(); onChanged(); }
    } finally {
      setBusy(false);
    }
  };

  const unitColumns: CCColumn<CCStockUnitOut>[] = [
    { header: "Unit", render: (u) => <CCTxnNumber value={u.unit_number} /> },
    { header: "Parent", render: (u) => (u.parent_unit_number ? <span className="font-mono">{u.parent_unit_number}</span> : "-") },
    { header: "Original", className: "text-right", render: (u) => <CCLengthCell mm={u.original_length_mm} /> },
    { header: "Remaining", className: "text-right", render: (u) => <CCLengthCell mm={u.remaining_length_mm} /> },
    { header: "Reserved", className: "text-right", render: (u) => <CCLengthCell mm={u.reserved_length_mm} /> },
    { header: "Issued", className: "text-right", render: (u) => <CCLengthCell mm={u.issued_length_mm} /> },
    { header: "Consumed", className: "text-right", render: (u) => <CCLengthCell mm={u.consumed_length_mm} /> },
    { header: "Scrapped", className: "text-right", render: (u) => <CCLengthCell mm={u.scrapped_length_mm} /> },
    { header: "Free", className: "text-right font-semibold", render: (u) => <CCLengthCell mm={u.free_length_mm} /> },
    { header: "Status", render: (u) => <CCStatusBadge status={u.status} /> },
    { header: "Location", render: (u) => u.location ?? "-" },
    {
      header: "Allocation eligible",
      render: (u) => (u.allocation_eligible ? "Yes" : <span title={u.allocation_ineligible_reason ?? ""}>No{u.allocation_ineligible_reason ? ` - ${u.allocation_ineligible_reason}` : ""}</span>),
    },
  ];

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  return (
    <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
          Inward detail {inward && <span className="ml-1 font-mono">{inward.inward_number}</span>}
        </h2>
        <button type="button" onClick={onClose} aria-label="Close detail" className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200"><X className="h-4 w-4" /></button>
      </div>
      <CCErrorBanner message={loadError} />

      {inward && (
        <>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {kv("Inward number", <CCTxnNumber value={inward.inward_number} />)}
            {kv("Material", <span className="font-mono">{inward.material_code}</span>)}
            {kv("Grade / section", `${inward.grade} / ${inward.section}`)}
            {kv("Dimensions (mm)", `${inward.stock_dimension_a_mm}${inward.stock_dimension_b_mm ? ` x ${inward.stock_dimension_b_mm}` : ""}`)}
            {kv("Received", fmtDateTime(inward.received_at))}
            {kv("GRN reference", inward.grn_reference ?? "-")}
            {kv("Location", inward.location ?? "-")}
            {kv("QA status", <CCStatusBadge status={inward.qa_status} />)}
            {kv("Physical piece count", inward.physical_piece_count)}
            {kv("Received piece count", inward.received_piece_count)}
            {kv("Original received length", <CCLengthCell mm={inward.original_received_length_mm} />)}
            {kv("Received total length", <CCLengthCell mm={inward.received_total_length_mm} />)}
            {kv("Unit count", inward.unit_count)}
            {kv("Remaining", <CCLengthCell mm={inward.remaining_length_mm} />)}
            {kv("Reserved", <CCLengthCell mm={inward.reserved_length_mm} />)}
            {kv("Issued", <CCLengthCell mm={inward.issued_length_mm} />)}
            {kv("Consumed", <CCLengthCell mm={inward.consumed_length_mm} />)}
            {kv("Scrapped", <CCLengthCell mm={inward.scrapped_length_mm} />)}
            {kv("Free", <b><CCLengthCell mm={inward.free_length_mm} /></b>)}
            {kv("Created / updated by", `${inward.created_by ?? "-"} / ${inward.updated_by ?? "-"}`)}
            {inward.remarks && <div className="col-span-2 sm:col-span-4"><dt className="text-zinc-500">Remarks</dt><dd>{inward.remarks}</dd></div>}
          </dl>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-1 font-semibold">QA decision</p>
              {inward.qa_decision ? (
                <dl className="grid grid-cols-2 gap-2">
                  {kv("Decision", <CCStatusBadge status={inward.qa_decision.decision} />)}
                  {kv("Previous status", inward.qa_decision.previous_qa_status ?? "-")}
                  {kv("Decided by", inward.qa_decision.decided_by ?? "-")}
                  {kv("Decided at", fmtDateTime(inward.qa_decision.decided_at))}
                  <div className="col-span-2"><dt className="text-zinc-500">Reason</dt><dd>{inward.qa_decision.reason ?? "-"}</dd></div>
                </dl>
              ) : <p className="text-zinc-500">No QA decision recorded yet.</p>}
            </div>
            <div className="rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
              <p className="mb-1 font-semibold">Conservation (reported by backend)</p>
              <dl className="grid grid-cols-2 gap-2">
                {kv("Accounted length", <CCLengthCell mm={inward.conservation.accounted_length_mm} />)}
                {kv("Expected length", <CCLengthCell mm={inward.conservation.expected_length_mm} />)}
                {kv("Adjustments in", <CCLengthCell mm={inward.conservation.adjustments_in_mm} />)}
                {kv("Adjustments out", <CCLengthCell mm={inward.conservation.adjustments_out_mm} />)}
                {kv("Consistent", <CCStatusBadge status={inward.conservation.consistent ? "RECONCILED" : "VARIANCE"} />)}
              </dl>
            </div>
          </div>

          {qaResult && (
            <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-emerald-700 dark:text-emerald-300">
              {qaResult.message} Status {qaResult.previous_qa_status} → {qaResult.qa_status}, by {qaResult.decided_by}.
              {" "}Backend says QA {qaResult.qa_allows_allocation ? "allows" : "does not allow"} allocation
              {qaResult.qa_block_reason ? `: ${qaResult.qa_block_reason}` : "."}
            </div>
          )}

          <CCErrorBanner message={qaError} />

          <CCRoleGate allowed={CC_QA_ROLES}>
            {inward.qa_status === "PENDING_QA" ? (
              <div className="space-y-2 rounded-lg border border-zinc-200 p-3 dark:border-zinc-800">
                <p className="font-semibold">Record QA decision</p>
                <p className="text-[11px] text-zinc-500">
                  ACCEPTED only means this inward passes the allocation QA condition. It does not allocate or reserve any stock.
                </p>
                <div className="flex flex-wrap gap-2">
                  {(["ACCEPTED", "REJECTED", "ON_HOLD"] as CCQADecision[]).map((d) => (
                    <button key={d} type="button" onClick={() => { setDecision(d); setQaError(null); }}
                      className={`rounded-lg border px-3 py-1.5 font-semibold ${decision === d ? "border-blue-600 bg-blue-600 text-white" : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"}`}>
                      {d.replace("_", " ")}
                    </button>
                  ))}
                </div>
                <div>
                  <label className={ccLabelCls}>Reason{reasonRequired ? " *" : " (optional)"}</label>
                  <textarea className={ccInputCls} rows={2} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
                </div>
                <button type="button" disabled={busy || !decision} onClick={askConfirm} className={ccPrimaryBtnCls}>Review decision</button>
              </div>
            ) : (
              <p className="text-zinc-500">QA decision already recorded; it cannot be changed here.</p>
            )}
          </CCRoleGate>

          <div>
            <p className="mb-1 font-semibold">Physical units ({unitsTotal})</p>
            <CCPagedTable
              columns={unitColumns} items={units} total={unitsTotal} limit={UNIT_PAGE} offset={0}
              onPageChange={() => {}} rowKey={(u) => u.unit_id} emptyText="No units."
            />
            {unitsTotal > units.length && <p className="text-[11px] text-amber-600">Showing the first {units.length} of {unitsTotal} units.</p>}
          </div>
        </>
      )}

      <CCConfirmModal
        isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} onConfirm={submitQA}
        title={`Confirm QA decision: ${decision.replace("_", " ")}`} confirmLabel="Record decision" busy={busy}
      >
        <p>
          Record <b>{decision}</b> for inward <span className="font-mono">{inward?.inward_number}</span>?
          A QA decision cannot be changed afterwards from this screen.
        </p>
        {reason.trim() && <p className="text-zinc-500">Reason: {reason.trim()}</p>}
      </CCConfirmModal>
    </section>
  );
}

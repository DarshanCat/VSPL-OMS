"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Layers, Plus } from "lucide-react";
import { Modal } from "@/app/components/ui/Modal";
import { CCActionForm } from "@/app/components/cc/CCActionForm";
import { CCErrorBanner } from "@/app/components/cc/CCErrorBanner";
import { CCFilterBar } from "@/app/components/cc/CCFilterBar";
import { CCPagedTable, CCColumn } from "@/app/components/cc/CCPagedTable";
import { CCRoleGate } from "@/app/components/cc/CCRoleGate";
import { CCStatusBadge } from "@/app/components/cc/CCStatusBadge";
import { CCTxnNumber } from "@/app/components/cc/CCTxnNumber";
import {
  ccCreateMaterial, ccErrorMessage, ccGetMaterial, ccListMaterials, ccUpdateMaterial,
  CCMaterialOut, CCMaterialPatch, CCMaterialResult,
} from "@/lib/continuousCastingApi";
import { CC_MATERIAL_MASTER_ROLES } from "@/lib/continuousCastingRoles";
import {
  ccInputCls, ccLabelCls, ccSecondaryBtnCls, fmtDateTime, parseOptionalPositiveInt, parsePositiveInt,
} from "@/lib/continuousCastingForm";

const PAGE_SIZE = 50;

interface Filters { search: string; active: "" | "true" | "false"; grade: string; section: string }
const NO_FILTERS: Filters = { search: "", active: "", grade: "", section: "" };

interface FormState {
  material_code: string; grade: string; section: string;
  stock_dimension_a_mm: string; stock_dimension_b_mm: string; description: string; is_active: boolean;
}
const EMPTY_FORM: FormState = {
  material_code: "", grade: "", section: "", stock_dimension_a_mm: "", stock_dimension_b_mm: "",
  description: "", is_active: true,
};

const fromMaterial = (m: CCMaterialResult): FormState => ({
  material_code: m.material_code, grade: m.grade, section: m.section,
  stock_dimension_a_mm: String(m.stock_dimension_a_mm),
  stock_dimension_b_mm: m.stock_dimension_b_mm === null ? "" : String(m.stock_dimension_b_mm),
  description: m.description ?? "", is_active: m.is_active,
});

export default function MaterialsContent() {
  const [filters, setFilters] = useState<Filters>(NO_FILTERS);
  const [applied, setApplied] = useState<Filters>(NO_FILTERS);
  const [offset, setOffset] = useState(0);
  const [rows, setRows] = useState<CCMaterialOut[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const reqSeq = useRef(0);

  const [createOpen, setCreateOpen] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const seq = ++reqSeq.current;
    setLoading(true);
    try {
      const page = await ccListMaterials({
        search: applied.search, grade: applied.grade, section: applied.section,
        is_active: applied.active === "" ? undefined : applied.active === "true",
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

  const columns: CCColumn<CCMaterialOut>[] = [
    {
      header: "Material code",
      render: (m) => (
        <button type="button" onClick={() => setDetailId(m.material_id)}
          className="font-mono font-semibold text-blue-600 hover:underline dark:text-blue-400">
          {m.material_code}
        </button>
      ),
    },
    { header: "Grade", render: (m) => m.grade },
    { header: "Section", render: (m) => m.section },
    { header: "Dim A (mm)", className: "text-right font-mono", render: (m) => m.stock_dimension_a_mm },
    { header: "Dim B (mm)", className: "text-right font-mono", render: (m) => m.stock_dimension_b_mm ?? "-" },
    { header: "Description", render: (m) => m.description ?? "-" },
    { header: "Status", render: (m) => <CCStatusBadge status={m.is_active ? "ACTIVE" : "INACTIVE"} /> },
    { header: "Created", render: (m) => <span>{fmtDateTime(m.created_at)}<br />{m.created_by ?? ""}</span> },
    { header: "Updated", render: (m) => <span>{fmtDateTime(m.updated_at)}<br />{m.updated_by ?? ""}</span> },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
            <Layers className="h-3.5 w-3.5" /> Continuous Casting
          </p>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Materials</h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">Continuous casting material master.</p>
        </div>
        <CCRoleGate allowed={CC_MATERIAL_MASTER_ROLES}>
          <button type="button" onClick={() => setCreateOpen(true)}
            className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700">
            <Plus className="h-3.5 w-3.5" /> New material
          </button>
        </CCRoleGate>
      </div>

      {notice && (
        <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
          {notice}
        </div>
      )}

      <form onSubmit={(e) => { e.preventDefault(); setOffset(0); setApplied(filters); }}>
        <CCFilterBar onClear={() => { setFilters(NO_FILTERS); setApplied(NO_FILTERS); setOffset(0); }}>
          <div>
            <label className={ccLabelCls}>Search</label>
            <input className={ccInputCls} value={filters.search} placeholder="code / grade / section"
              onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
          </div>
          <div>
            <label className={ccLabelCls}>Status</label>
            <select className={ccInputCls} value={filters.active}
              onChange={(e) => setFilters({ ...filters, active: e.target.value as Filters["active"] })}>
              <option value="">All</option>
              <option value="true">Active</option>
              <option value="false">Inactive</option>
            </select>
          </div>
          <div>
            <label className={ccLabelCls}>Grade</label>
            <input className={ccInputCls} value={filters.grade} onChange={(e) => setFilters({ ...filters, grade: e.target.value })} />
          </div>
          <div>
            <label className={ccLabelCls}>Section</label>
            <input className={ccInputCls} value={filters.section} onChange={(e) => setFilters({ ...filters, section: e.target.value })} />
          </div>
          <button type="submit" className={ccSecondaryBtnCls}>Apply</button>
        </CCFilterBar>
      </form>

      <CCPagedTable
        columns={columns} items={rows} total={total} limit={PAGE_SIZE} offset={offset}
        onPageChange={setOffset} rowKey={(m) => m.material_id} loading={loading} error={listError}
        emptyText="No materials found."
      />

      <MaterialFormModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        onDone={(msg) => { setCreateOpen(false); setNotice(msg); void load(); }}
      />
      <MaterialDetailModal
        materialId={detailId}
        onClose={() => setDetailId(null)}
        onChanged={(msg) => { setNotice(msg); void load(); }}
      />
    </div>
  );
}

// ------------------------------------------------------------------ create
function MaterialFormModal({ isOpen, onClose, onDone }: {
  isOpen: boolean; onClose: () => void; onDone: (message: string) => void;
}) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (isOpen) { setForm(EMPTY_FORM); setError(null); } }, [isOpen]);

  const submit = async () => {
    const a = parsePositiveInt(form.stock_dimension_a_mm);
    const b = parseOptionalPositiveInt(form.stock_dimension_b_mm);
    if (!form.material_code.trim() || !form.grade.trim() || !form.section.trim()) {
      return setError("Material code, grade and section are required.");
    }
    if (Number.isNaN(a)) return setError("Stock dimension A must be a whole number of mm greater than 0.");
    if (b !== null && Number.isNaN(b)) return setError("Stock dimension B must be a whole number of mm greater than 0, or empty.");
    setBusy(true);
    setError(null);
    try {
      const res = await ccCreateMaterial({
        material_code: form.material_code.trim(), grade: form.grade.trim(), section: form.section.trim(),
        stock_dimension_a_mm: a, stock_dimension_b_mm: b,
        description: form.description.trim() === "" ? null : form.description.trim(),
      });
      onDone(`${res.message} Material ${res.material_code} (id ${res.material_id}).`);
    } catch (err) {
      setError(ccErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={busy ? () => {} : onClose} title="New material" maxWidth="lg">
      <div className="px-6 py-4">
        <CCActionForm onSubmit={submit} busy={busy} error={error} submitLabel="Create material">
          <MaterialFields form={form} setForm={setForm} showActive={false} />
        </CCActionForm>
      </div>
    </Modal>
  );
}

function MaterialFields({ form, setForm, showActive }: {
  form: FormState; setForm: (f: FormState) => void; showActive: boolean;
}) {
  const set = (k: keyof FormState, v: string | boolean) => setForm({ ...form, [k]: v });
  return (
    <div className="grid grid-cols-2 gap-3">
      <div>
        <label className={ccLabelCls}>Material code *</label>
        <input className={ccInputCls} maxLength={100} value={form.material_code} onChange={(e) => set("material_code", e.target.value)} autoFocus />
      </div>
      <div>
        <label className={ccLabelCls}>Grade *</label>
        <input className={ccInputCls} maxLength={100} value={form.grade} onChange={(e) => set("grade", e.target.value)} />
      </div>
      <div>
        <label className={ccLabelCls}>Section *</label>
        <input className={ccInputCls} maxLength={100} value={form.section} onChange={(e) => set("section", e.target.value)} />
      </div>
      <div />
      <div>
        <label className={ccLabelCls}>Stock dimension A (mm) *</label>
        <input className={ccInputCls} inputMode="numeric" value={form.stock_dimension_a_mm} onChange={(e) => set("stock_dimension_a_mm", e.target.value)} />
      </div>
      <div>
        <label className={ccLabelCls}>Stock dimension B (mm)</label>
        <input className={ccInputCls} inputMode="numeric" value={form.stock_dimension_b_mm} onChange={(e) => set("stock_dimension_b_mm", e.target.value)} />
      </div>
      <div className="col-span-2">
        <label className={ccLabelCls}>Description</label>
        <textarea className={ccInputCls} rows={2} maxLength={500} value={form.description} onChange={(e) => set("description", e.target.value)} />
      </div>
      {showActive && (
        <label className="col-span-2 flex items-center gap-2 text-xs">
          <input type="checkbox" checked={form.is_active} onChange={(e) => set("is_active", e.target.checked)} />
          Active
        </label>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ detail + edit
function MaterialDetailModal({ materialId, onClose, onChanged }: {
  materialId: string | null; onClose: () => void; onChanged: (message: string) => void;
}) {
  const [material, setMaterial] = useState<CCMaterialResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMaterial = useCallback(async (id: string) => {
    try {
      const m = await ccGetMaterial(id);
      setMaterial(m);
      setLoadError(null);
      return m;
    } catch (err) {
      setLoadError(ccErrorMessage(err));
      return null;
    }
  }, []);

  useEffect(() => {
    setMaterial(null); setLoadError(null); setEditing(false); setError(null);
    if (materialId) void fetchMaterial(materialId);
  }, [materialId, fetchMaterial]);

  const startEdit = () => { if (material) { setForm(fromMaterial(material)); setError(null); setEditing(true); } };

  const save = async () => {
    if (!material || !materialId) return;
    const a = parsePositiveInt(form.stock_dimension_a_mm);
    const b = parseOptionalPositiveInt(form.stock_dimension_b_mm);
    if (!form.material_code.trim() || !form.grade.trim() || !form.section.trim()) {
      return setError("Material code, grade and section are required.");
    }
    if (Number.isNaN(a)) return setError("Stock dimension A must be a whole number of mm greater than 0.");
    if (b !== null && Number.isNaN(b)) return setError("Stock dimension B must be a whole number of mm greater than 0, or empty.");

    // Send only the fields the user actually changed; the backend decides what may change.
    const orig = fromMaterial(material);
    const patch: CCMaterialPatch = {};
    if (form.material_code.trim() !== orig.material_code) patch.material_code = form.material_code.trim();
    if (form.grade.trim() !== orig.grade) patch.grade = form.grade.trim();
    if (form.section.trim() !== orig.section) patch.section = form.section.trim();
    if (a !== material.stock_dimension_a_mm) patch.stock_dimension_a_mm = a;
    if (b !== material.stock_dimension_b_mm) patch.stock_dimension_b_mm = b;
    if (form.description.trim() !== orig.description.trim()) {
      patch.description = form.description.trim() === "" ? null : form.description.trim();
    }
    if (form.is_active !== material.is_active) patch.is_active = form.is_active;
    if (Object.keys(patch).length === 0) return setError("Nothing was changed.");

    setBusy(true);
    setError(null);
    try {
      const res = await ccUpdateMaterial(materialId, patch);
      setMaterial(res);
      setEditing(false);
      onChanged(`${res.message} Material ${res.material_code}.`);
    } catch (err) {
      setError(ccErrorMessage(err));
      // Keep the form open with the backend message; re-fetch so the displayed record is current.
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409 || status === 404) await fetchMaterial(materialId);
    } finally {
      setBusy(false);
    }
  };

  const dl = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="font-mono text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  return (
    <Modal isOpen={!!materialId} onClose={busy ? () => {} : onClose} title={material ? `Material ${material.material_code}` : "Material"} maxWidth="lg">
      <div className="space-y-3 px-6 py-4 text-xs">
        <CCErrorBanner message={loadError} />
        {material && !editing && (
          <>
            <dl className="grid grid-cols-2 gap-3">
              {dl("Material id", <CCTxnNumber value={material.material_id} />)}
              {dl("Material code", material.material_code)}
              {dl("Grade", material.grade)}
              {dl("Section", material.section)}
              {dl("Stock dimension A (mm)", material.stock_dimension_a_mm)}
              {dl("Stock dimension B (mm)", material.stock_dimension_b_mm ?? "-")}
              {dl("Status", <CCStatusBadge status={material.is_active ? "ACTIVE" : "INACTIVE"} />)}
              {dl("Referenced", material.referenced ? "Yes (identity frozen by backend)" : "No")}
              {dl("Inwards", material.inward_count)}
              {dl("Routings", material.routing_count)}
              {dl("Created by", material.created_by ?? "-")}
              {dl("Updated by", material.updated_by ?? "-")}
              <div className="col-span-2"><dt className="text-zinc-500">Description</dt><dd>{material.description ?? "-"}</dd></div>
            </dl>
            <div className="flex justify-end gap-2">
              <CCRoleGate allowed={CC_MATERIAL_MASTER_ROLES}>
                <button type="button" onClick={startEdit} className={ccSecondaryBtnCls}>Edit</button>
              </CCRoleGate>
              <button type="button" onClick={onClose} className={ccSecondaryBtnCls}>Close</button>
            </div>
          </>
        )}
        {material && editing && (
          <CCActionForm onSubmit={save} busy={busy} error={error} submitLabel="Save changes">
            <MaterialFields form={form} setForm={setForm} showActive />
            <p className="text-[11px] text-zinc-500">
              Once an inward or routing refers to a material the backend only allows description and active state to change.
            </p>
            <button type="button" onClick={() => setEditing(false)} disabled={busy} className={ccSecondaryBtnCls}>Cancel</button>
          </CCActionForm>
        )}
      </div>
    </Modal>
  );
}

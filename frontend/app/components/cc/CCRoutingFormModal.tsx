"use client";
import React, { useEffect, useRef, useState } from "react";
import { Modal } from "@/app/components/ui/Modal";
import { CCActionForm } from "./CCActionForm";
import { CCLengthCell } from "./CCLengthCell";
import { CCStatusBadge } from "./CCStatusBadge";
import { CCTxnNumber } from "./CCTxnNumber";
import {
  ccCreateRouting, ccErrorMessage, ccSupersedeRouting, CCMaterialOut, CCRoutingOut, CCRoutingResult,
} from "@/lib/continuousCastingApi";
import {
  ccInputCls, ccLabelCls, ccPrimaryBtnCls, parseNonNegativeInt, parseOptionalPositiveInt, parsePositiveInt,
} from "@/lib/continuousCastingForm";

interface Fields {
  materialId: string; grade: string; section: string;
  dimA: string; dimB: string; axial: string; stockA: string; stockB: string;
  blanks: string; cuts: string; kerf: string; trim: string; reason: string;
}
const EMPTY: Fields = {
  materialId: "", grade: "", section: "", dimA: "", dimB: "", axial: "", stockA: "", stockB: "",
  blanks: "", cuts: "", kerf: "", trim: "", reason: "",
};
const s = (n: number | null | undefined) => (n === null || n === undefined ? "" : String(n));

// The supersede form starts from the ACTIVE routing's own values; the planner may change any of them.
const fromRouting = (r: CCRoutingOut): Fields => ({
  materialId: r.validated_material_id ?? "", grade: r.required_grade ?? "", section: r.required_section ?? "",
  dimA: s(r.finished_dimension_a_mm), dimB: s(r.finished_dimension_b_mm), axial: s(r.finished_axial_length_mm),
  stockA: s(r.machining_stock_a_mm), stockB: s(r.machining_stock_b_mm),
  blanks: s(r.planned_blanks), cuts: s(r.planned_cuts), kerf: s(r.kerf_mm), trim: s(r.end_trim_mm), reason: "",
});

// Create (first routing / none active) or Supersede (replace the ACTIVE routing) for an existing Work Order.
// Only basic input checks happen here. blank length and gross required length are never computed in the
// browser: they appear only in the backend's response.
export function CCRoutingFormModal({ mode, isOpen, woNumber, materials, activeRouting, onClose, onSuccess, onStale }: {
  mode: "create" | "supersede";
  isOpen: boolean;
  woNumber: string;
  materials: CCMaterialOut[]; // active materials only
  activeRouting?: CCRoutingOut | null;
  onClose: () => void;
  onSuccess: () => void; // the caller reloads history, active routing and gate status
  onStale: () => void; // after a 409/404: reload so the screen shows the real state
}) {
  const [f, setF] = useState<Fields>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CCRoutingResult | null>(null);

  // Reset only when the dialog opens. The parent reloads the routing list after a success, which hands in a
  // new activeRouting; that must not wipe the result panel, so the latest value is read through a ref.
  const activeRef = useRef(activeRouting);
  activeRef.current = activeRouting;
  useEffect(() => {
    if (!isOpen) return;
    setF(mode === "supersede" && activeRef.current ? fromRouting(activeRef.current) : EMPTY);
    setError(null);
    setResult(null);
  }, [isOpen, mode]);

  const set = (patch: Partial<Fields>) => setF({ ...f, ...patch });

  // UX default only: copy the chosen material's grade and section into the editable fields.
  const pickMaterial = (id: string) => {
    const m = materials.find((x) => x.material_id === id);
    set(m ? { materialId: id, grade: m.grade, section: m.section } : { materialId: id });
  };

  const submit = async () => {
    if (busy) return;
    if (!f.materialId) return setError("Select a material.");
    if (!f.grade.trim() || !f.section.trim()) return setError("Required grade and section are required.");
    const dimA = parsePositiveInt(f.dimA);
    const dimB = parseOptionalPositiveInt(f.dimB);
    const axial = parsePositiveInt(f.axial);
    const blanks = parsePositiveInt(f.blanks);
    const nonNeg = { stockA: parseNonNegativeInt(f.stockA), stockB: parseNonNegativeInt(f.stockB), cuts: parseNonNegativeInt(f.cuts), kerf: parseNonNegativeInt(f.kerf), trim: parseNonNegativeInt(f.trim) };
    if (Number.isNaN(dimA)) return setError("Finished dimension A must be a whole number of mm greater than 0.");
    if (dimB !== null && Number.isNaN(dimB)) return setError("Finished dimension B must be a whole number of mm greater than 0, or empty.");
    if (Number.isNaN(axial)) return setError("Finished axial length must be a whole number of mm greater than 0.");
    if (Number.isNaN(blanks)) return setError("Planned blanks must be a whole number greater than 0.");
    if (Object.values(nonNeg).some((n) => Number.isNaN(n))) {
      return setError("Machining stock A/B, planned cuts, kerf and end trim must be whole numbers (0 or more).");
    }
    if (mode === "supersede" && !f.reason.trim()) return setError("A reason is required to supersede a routing.");

    const body = {
      wo_number: woNumber, validated_material_id: f.materialId,
      required_grade: f.grade.trim(), required_section: f.section.trim(),
      finished_dimension_a_mm: dimA, finished_dimension_b_mm: dimB, finished_axial_length_mm: axial,
      machining_stock_a_mm: nonNeg.stockA, machining_stock_b_mm: nonNeg.stockB,
      planned_blanks: blanks, planned_cuts: nonNeg.cuts, kerf_mm: nonNeg.kerf, end_trim_mm: nonNeg.trim,
    };
    setBusy(true);
    setError(null);
    try {
      const res = mode === "create" ? await ccCreateRouting(body) : await ccSupersedeRouting({ ...body, reason: f.reason.trim() });
      setResult(res);
      onSuccess();
    } catch (err) {
      setError(ccErrorMessage(err)); // backend text verbatim; never retried
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 409 || status === 404) onStale();
    } finally {
      setBusy(false);
    }
  };

  const num = (label: string, key: keyof Fields, opt = false, hint?: string) => (
    <div>
      <label className={ccLabelCls}>{label}{opt ? "" : " *"}</label>
      <input className={ccInputCls} inputMode="numeric" value={f[key]} onChange={(e) => set({ [key]: e.target.value } as Partial<Fields>)} />
      {hint && <p className="mt-0.5 text-[10px] text-zinc-400">{hint}</p>}
    </div>
  );

  const title = mode === "create" ? "Create Continuous Casting Routing" : "Supersede Routing";
  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd>{v}</dd></div>
  );

  return (
    <Modal isOpen={isOpen} onClose={busy ? () => {} : onClose} title={title} subtitle={`Work Order ${woNumber}`} maxWidth="2xl">
      <div className="max-h-[75vh] overflow-y-auto px-6 py-4 text-xs">
        {result ? (
          <div className="space-y-3">
            <div role="status" className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-emerald-700 dark:text-emerald-300">
              {result.message}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3">
                <p className="text-zinc-500">Blank length (from backend)</p>
                <p className="text-lg font-bold"><CCLengthCell mm={result.blank_length_mm} /></p>
              </div>
              <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 p-3">
                <p className="text-zinc-500">Gross required (from backend)</p>
                <p className="text-lg font-bold"><CCLengthCell mm={result.gross_required_length_mm} /></p>
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {kv("Routing id", <CCTxnNumber value={result.routing_id} />)}
              {kv("Version", <b className="font-mono">v{result.version}</b>)}
              {kv("Status", <CCStatusBadge status={result.status} />)}
              {kv("Material source", result.material_source)}
              {kv("Material", <span className="font-mono">{result.validated_material_code}</span>)}
              {kv("Planned blanks", <span className="font-mono">{result.planned_blanks}</span>)}
              {kv("Planned cuts", <span className="font-mono">{result.planned_cuts}</span>)}
              {kv("Kerf", <CCLengthCell mm={result.kerf_mm} />)}
              {kv("End trim", <CCLengthCell mm={result.end_trim_mm} />)}
              {result.superseded_version !== null && kv("Superseded version", <span className="font-mono">v{result.superseded_version}</span>)}
            </dl>
            {mode === "supersede" && (
              <p className="text-zinc-500">Allocations and reservations on the old routing are unchanged until they are explicitly released.</p>
            )}
            <div className="flex justify-end"><button type="button" onClick={onClose} className={ccPrimaryBtnCls}>Close</button></div>
          </div>
        ) : (
          <CCActionForm onSubmit={submit} busy={busy} error={error}
            submitLabel={mode === "create" ? "Create routing" : "Supersede and issue new version"}>
            {mode === "supersede" && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-800 dark:text-amber-200">
                <p className="font-semibold">The current routing will become SUPERSEDED and a new routing version will become ACTIVE.</p>
                <p className="mt-1">Existing allocations and reservations on the old routing remain unchanged until explicitly released.</p>
              </div>
            )}
            <div>
              <label className={ccLabelCls}>Material (active only) *</label>
              <select className={ccInputCls} value={f.materialId} onChange={(e) => pickMaterial(e.target.value)} autoFocus>
                <option value="">Select material...</option>
                {materials.map((m) => (
                  <option key={m.material_id} value={m.material_id}>{m.material_code} - {m.grade} / {m.section}</option>
                ))}
              </select>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={ccLabelCls}>Required grade *</label>
                <input className={ccInputCls} maxLength={100} value={f.grade} onChange={(e) => set({ grade: e.target.value })} />
              </div>
              <div>
                <label className={ccLabelCls}>Required section *</label>
                <input className={ccInputCls} maxLength={100} value={f.section} onChange={(e) => set({ section: e.target.value })} />
              </div>
              <p className="col-span-2 -mt-1 text-[10px] text-zinc-400">Defaults come from the selected material and can be edited. The backend decides whether the routing is valid.</p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {num("Finished dimension A (mm)", "dimA")}
              {num("Finished dimension B (mm)", "dimB", true)}
              {num("Finished axial length (mm)", "axial")}
              {num("Machining stock A (mm)", "stockA", false, "0 or more")}
              {num("Machining stock B (mm)", "stockB", false, "0 or more")}
              <div />
              {num("Planned blanks", "blanks")}
              {num("Planned cuts", "cuts", false, "entered, not derived")}
              {num("Kerf (mm)", "kerf", false, "0 or more")}
              {num("End trim, total (mm)", "trim", false, "0 or more")}
            </div>
            <p className="text-[11px] text-zinc-500">Blank length and gross required length are calculated by the backend and shown after the routing is saved.</p>
            {mode === "supersede" && (
              <div>
                <label className={ccLabelCls}>Reason for superseding *</label>
                <textarea className={ccInputCls} rows={2} maxLength={500} value={f.reason} onChange={(e) => set({ reason: e.target.value })} />
              </div>
            )}
          </CCActionForm>
        )}
      </div>
    </Modal>
  );
}

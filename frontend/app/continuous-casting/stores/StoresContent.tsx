"use client";
import React, { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowRightLeft } from "lucide-react";
import { CCActionForm } from "@/app/components/cc/CCActionForm";
import { CCConfirmModal } from "@/app/components/cc/CCConfirmModal";
import { CCErrorBanner } from "@/app/components/cc/CCErrorBanner";
import { CCLedgerTable } from "@/app/components/cc/CCLedgerTable";
import { CCLengthCell } from "@/app/components/cc/CCLengthCell";
import { CCStatusBadge } from "@/app/components/cc/CCStatusBadge";
import { CCTxnNumber } from "@/app/components/cc/CCTxnNumber";
import { CCUnitBalances } from "@/app/components/cc/CCUnitBalances";
import { CCUnitList } from "@/app/components/cc/CCUnitList";
import { getCurrentUserRole } from "@/lib/api";
import {
  ccAdjustIn, ccAdjustOut, ccErrorMessage, ccGetStockUnit, ccHold, ccIssue, ccNewRequestId, ccReleaseHold, ccReturn,
  ccScrap, ccSplit, CCAllocationOut, CCSplitResult, CCStockMovementResult, CCStockUnitDetail, CCUnitMovementResult,
} from "@/lib/continuousCastingApi";
import {
  CC_ADJUSTMENT_ROLES, CC_HOLD_RELEASE_ROLES, CC_HOLD_ROLES, CC_ISSUE_ROLES, CC_SCRAP_ROLES, ccRoleAllowed, CCRoleTuple,
} from "@/lib/continuousCastingRoles";
import { ccInputCls, ccLabelCls, ccSecondaryBtnCls, parsePositiveInt } from "@/lib/continuousCastingForm";

type Kind = "issue" | "return" | "split" | "hold" | "release" | "scrap" | "adjust_out" | "adjust_in";

interface TabDef { kind: Kind; label: string; roles: CCRoleTuple; note: string }
const TABS: TabDef[] = [
  { kind: "issue", label: "Issue", roles: CC_ISSUE_ROLES,
    note: "Hands RESERVED stock of the chosen allocation to production. The backend decides whether the issue is allowed." },
  { kind: "return", label: "Return", roles: CC_ISSUE_ROLES,
    note: "Hands ISSUED, not-yet-cut stock back to the store. A return only reduces the issued quantity; it does not restore remaining physical length." },
  { kind: "split", label: "Split", roles: CC_ISSUE_ROLES,
    note: "Creates one child stock unit (a retained remnant) from free physical length of this bar. It does not create another physical piece." },
  { kind: "hold", label: "Hold", roles: CC_HOLD_ROLES,
    note: "Quarantines the unit. A hold changes status only: it does not consume, reserve or change any balance." },
  { kind: "release", label: "Release hold", roles: CC_HOLD_RELEASE_ROLES,
    note: "Lifts a quarantine. Status change only; no balance changes." },
  { kind: "scrap", label: "Scrap", roles: CC_SCRAP_ROLES,
    note: "Disposes of physical length. Destructive: the backend reduces remaining and increases scrapped. The NC Tracker stays the disposition authority." },
  { kind: "adjust_out", label: "Adjustment out", roles: CC_ADJUSTMENT_ROLES,
    note: "Admin correction of the recorded physical length of the unit (downwards). Irreversible; the backend decides validity." },
  { kind: "adjust_in", label: "Adjustment in", roles: CC_ADJUSTMENT_ROLES,
    note: "Admin correction of the recorded physical length of the unit (upwards). Irreversible; the backend decides validity." },
];

type TxnResult =
  | { kind: "movement"; data: CCStockMovementResult }
  | { kind: "split"; data: CCSplitResult }
  | { kind: "unit"; data: CCUnitMovementResult };

export default function StoresContent() {
  const params = useSearchParams();
  const [unitId, setUnitId] = useState<string | null>(params.get("unit"));
  const [unit, setUnit] = useState<CCStockUnitDetail | null>(null);
  const [unitError, setUnitError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [role, setRole] = useState<string | null>(null);
  const [tab, setTab] = useState<Kind | null>(null);
  const [result, setResult] = useState<TxnResult | null>(null);

  useEffect(() => setRole(getCurrentUserRole()), []);

  const loadUnit = useCallback(async (id: string) => {
    try {
      setUnit(await ccGetStockUnit(id));
      setUnitError(null);
    } catch (err) {
      setUnitError(ccErrorMessage(err));
    }
  }, []);

  useEffect(() => {
    setUnit(null);
    if (unitId) void loadUnit(unitId);
  }, [unitId, loadUnit]);

  // UX-only: tabs the current role could use. Hold release is offered only while the backend reports ON_HOLD.
  const tabs = TABS.filter((t) => ccRoleAllowed(role, t.roles) && (t.kind !== "release" || unit?.status === "ON_HOLD"));
  const activeTab = tabs.find((t) => t.kind === tab) ?? tabs[0] ?? null;

  const afterMutation = async (r: TxnResult) => {
    setResult(r);
    setRefreshKey((k) => k + 1);
    if (unitId) await loadUnit(unitId);
  };

  const selectUnit = (id: string) => { setUnitId(id); setResult(null); };

  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
          <ArrowRightLeft className="h-3.5 w-3.5" /> Continuous Casting
        </p>
        <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Stores Transactions</h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          A transaction workspace: pick a bar, review the backend&apos;s current figures, then act. Every result shown comes from the backend.
        </p>
      </div>

      <details open={!unitId} className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <summary className="cursor-pointer text-xs font-semibold">1. Select stock unit</summary>
        <div className="mt-2">
          <CCUnitList onSelect={(u) => selectUnit(u.unit_id)} selectedId={unitId} refreshKey={refreshKey} pageSize={10} />
        </div>
      </details>

      {unitId && (
        <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">2. Current state</h2>
          <CCErrorBanner message={unitError} />
          {unit && <CCUnitBalances unit={unit} />}
        </section>
      )}

      {result && <ResultBanner result={result} onOpenUnit={selectUnit} onDismiss={() => setResult(null)} />}

      {unit && (
        <section className="space-y-3 rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
          <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">3. Transaction</h2>
          {tabs.length === 0 || !activeTab ? (
            <p className="text-zinc-500">Your role has read-only access to stores transactions for this unit.</p>
          ) : (
            <>
              <div className="flex flex-wrap gap-1.5">
                {tabs.map((t) => (
                  <button key={t.kind} type="button" onClick={() => { setTab(t.kind); setResult(null); }}
                    className={`rounded-lg border px-3 py-1.5 font-semibold ${activeTab.kind === t.kind ? "border-blue-600 bg-blue-600 text-white" : "border-zinc-300 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"}`}>
                    {t.label}
                  </button>
                ))}
              </div>
              <p className="text-zinc-500">{activeTab.note}</p>
              <ActionPanel
                key={`${activeTab.kind}:${unit.unit_id}`}
                kind={activeTab.kind}
                unit={unit}
                onSuccess={afterMutation}
                onConflict={() => unitId && void loadUnit(unitId)}
              />
            </>
          )}
        </section>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Ledger</h2>
        <CCLedgerTable unitId={unitId} refreshKey={refreshKey} />
      </section>
    </div>
  );
}

// ------------------------------------------------------------------ action panel
interface Fields { allocationId: string; length: string; reason: string; reference: string; ncId: string }
const NO_FIELDS: Fields = { allocationId: "", length: "", reason: "", reference: "", ncId: "" };

const DESTRUCTIVE: Kind[] = ["scrap", "adjust_out", "adjust_in"];
const UNIT_ONLY: Kind[] = ["hold", "release"]; // no length
const NEEDS_ALLOCATION: Kind[] = ["issue", "return"];

function ActionPanel({ kind, unit, onSuccess, onConflict }: {
  kind: Kind; unit: CCStockUnitDetail; onSuccess: (r: TxnResult) => Promise<void>; onConflict: () => void;
}) {
  const [f, setF] = useState<Fields>(NO_FIELDS);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  // One replay key per intended submission. It is kept across a retry of the SAME entries and dropped as soon as
  // any field changes or the operation succeeds, so unrelated submissions never share a key.
  const [requestId, setRequestId] = useState<string | null>(null);

  const update = (patch: Partial<Fields>) => { setF({ ...f, ...patch }); setRequestId(null); };

  const allocation: CCAllocationOut | undefined = unit.allocations.find((a) => a.allocation_id === f.allocationId);
  const needsLength = !UNIT_ONLY.includes(kind);
  const needsReference = kind === "scrap" || kind === "adjust_out" || kind === "adjust_in";
  const reasonRequired = kind === "hold" || kind === "release" || needsReference;

  // Basic UX validation only; the backend decides everything else.
  const validate = (): string | null => {
    if (NEEDS_ALLOCATION.includes(kind) && !allocation) return "Select an allocation.";
    if (needsLength && Number.isNaN(parsePositiveInt(f.length))) return "Length must be a whole number of mm greater than 0.";
    if (reasonRequired && f.reason.trim() === "") return "A reason is required.";
    if (needsReference && f.reference.trim() === "") return "A reference is required.";
    return null;
  };

  const run = async (reqId: string | null) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const length = needsLength ? parsePositiveInt(f.length) : 0;
      const reason = f.reason.trim();
      const reference = f.reference.trim();
      let r: TxnResult;
      if (kind === "issue" || kind === "return") {
        const body = {
          routing_id: allocation!.routing_id, allocation_id: allocation!.allocation_id,
          stock_unit_id: unit.unit_id, length_mm: length, reason: reason || null,
        };
        const data = kind === "issue" ? await ccIssue(body) : await ccReturn({ ...body, inward_id: unit.inward_id });
        r = { kind: "movement", data };
      } else if (kind === "split") {
        r = { kind: "split", data: await ccSplit({ stock_unit_id: unit.unit_id, inward_id: unit.inward_id, length_mm: length, reason: reason || null }) };
      } else if (kind === "hold" || kind === "release") {
        const body = { stock_unit_id: unit.unit_id, inward_id: unit.inward_id, reason, reference: reference || null };
        r = { kind: "unit", data: kind === "hold" ? await ccHold(body) : await ccReleaseHold(body) };
      } else if (kind === "scrap") {
        r = {
          kind: "unit",
          data: await ccScrap({
            stock_unit_id: unit.unit_id, inward_id: unit.inward_id, length_mm: length, reason, reference,
            nc_record_id: f.ncId.trim() || null, client_request_id: reqId ?? ccNewRequestId(),
          }),
        };
      } else {
        const body = {
          stock_unit_id: unit.unit_id, inward_id: unit.inward_id, length_mm: length, reason, reference,
          client_request_id: reqId ?? ccNewRequestId(),
        };
        r = { kind: "unit", data: kind === "adjust_out" ? await ccAdjustOut(body) : await ccAdjustIn(body) };
      }
      setConfirmOpen(false);
      setF(NO_FIELDS);
      setRequestId(null);
      await onSuccess(r);
    } catch (err) {
      setError(ccErrorMessage(err));
      setConfirmOpen(false);
      if ((err as { response?: { status?: number } })?.response?.status === 409) onConflict(); // show current state; never retry
    } finally {
      setBusy(false);
    }
  };

  const submit = () => {
    const problem = validate();
    if (problem) return setError(problem);
    setError(null);
    if (DESTRUCTIVE.includes(kind)) {
      const key = requestId ?? ccNewRequestId();
      setRequestId(key);
      setConfirmOpen(true);
    } else {
      void run(null);
    }
  };

  const label = TABS.find((t) => t.kind === kind)?.label ?? "";

  return (
    <>
      <CCActionForm onSubmit={submit} busy={busy} error={confirmOpen ? null : error} submitLabel={DESTRUCTIVE.includes(kind) ? `Review ${label.toLowerCase()}` : label}>
        {NEEDS_ALLOCATION.includes(kind) && (
          <div className="space-y-2">
            <div>
              <label className={ccLabelCls}>Allocation *</label>
              <select className={ccInputCls} value={f.allocationId} onChange={(e) => update({ allocationId: e.target.value })} autoFocus>
                <option value="">{unit.allocations.length === 0 ? "This unit has no allocations" : "Select allocation..."}</option>
                {unit.allocations.map((a) => (
                  <option key={a.allocation_id} value={a.allocation_id}>
                    {a.allocation_number} - WO {a.wo_number} - routing v{a.routing_version} ({a.routing_status})
                  </option>
                ))}
              </select>
            </div>
            {allocation && (
              <dl className="grid grid-cols-2 gap-2 rounded-lg border border-zinc-200 p-2 dark:border-zinc-800 sm:grid-cols-6">
                <div><dt className="text-zinc-500">WO</dt><dd className="font-mono">{allocation.wo_number}</dd></div>
                <div><dt className="text-zinc-500">Allocation status</dt><dd><CCStatusBadge status={allocation.status} /></dd></div>
                <div><dt className="text-zinc-500">Planned</dt><dd><CCLengthCell mm={allocation.planned_length_mm} /></dd></div>
                <div><dt className="text-zinc-500">Reserved</dt><dd><CCLengthCell mm={allocation.reserved_length_mm} /></dd></div>
                <div><dt className="text-zinc-500">Issued</dt><dd><CCLengthCell mm={allocation.issued_length_mm} /></dd></div>
                <div><dt className="text-zinc-500">Consumed</dt><dd><CCLengthCell mm={allocation.consumed_length_mm} /></dd></div>
              </dl>
            )}
          </div>
        )}

        {needsLength && (
          <div className="w-48">
            <label className={ccLabelCls}>{kind === "split" ? "Split length (mm) *" : kind === "return" ? "Return length (mm) *" : "Length (mm) *"}</label>
            <input className={ccInputCls} inputMode="numeric" value={f.length} onChange={(e) => update({ length: e.target.value })}
              autoFocus={!NEEDS_ALLOCATION.includes(kind)} />
          </div>
        )}

        <div>
          <label className={ccLabelCls}>Reason{reasonRequired ? " *" : " (optional)"}</label>
          <textarea className={ccInputCls} rows={2} maxLength={500} value={f.reason} onChange={(e) => update({ reason: e.target.value })}
            autoFocus={UNIT_ONLY.includes(kind)} />
        </div>

        {(needsReference || kind === "hold" || kind === "release") && (
          <div>
            <label className={ccLabelCls}>Reference{needsReference ? " *" : " (optional, e.g. NCR / QA note)"}</label>
            <input className={ccInputCls} maxLength={200} value={f.reference} onChange={(e) => update({ reference: e.target.value })} />
          </div>
        )}

        {kind === "scrap" && (
          <div>
            <label className={ccLabelCls}>NC record id (optional pointer)</label>
            <input className={`${ccInputCls} font-mono`} value={f.ncId} onChange={(e) => update({ ncId: e.target.value })} placeholder="uuid" />
          </div>
        )}
      </CCActionForm>

      <CCConfirmModal
        isOpen={confirmOpen} onClose={() => setConfirmOpen(false)} onConfirm={() => void run(requestId)}
        title={`Confirm ${label.toLowerCase()}`} confirmLabel={`Confirm ${label.toLowerCase()}`} busy={busy} error={error}
      >
        <dl className="grid grid-cols-2 gap-2 text-xs">
          <div><dt className="text-zinc-500">Unit</dt><dd className="font-mono">{unit.unit_number}</dd></div>
          <div><dt className="text-zinc-500">Length</dt><dd><CCLengthCell mm={parsePositiveInt(f.length)} /></dd></div>
          <div><dt className="text-zinc-500">Current remaining (backend)</dt><dd><CCLengthCell mm={unit.remaining_length_mm} /></dd></div>
          <div><dt className="text-zinc-500">Current free (backend)</dt><dd><CCLengthCell mm={unit.free_length_mm} /></dd></div>
          <div className="col-span-2"><dt className="text-zinc-500">Reason</dt><dd>{f.reason.trim()}</dd></div>
          <div className="col-span-2"><dt className="text-zinc-500">Reference</dt><dd>{f.reference.trim() || "-"}</dd></div>
          {kind === "scrap" && <div className="col-span-2"><dt className="text-zinc-500">NC record</dt><dd className="font-mono">{f.ncId.trim() || "-"}</dd></div>}
        </dl>
        <p className="text-zinc-500">The backend validates this and reports the resulting figures. This cannot be undone from here.</p>
      </CCConfirmModal>
    </>
  );
}

// ------------------------------------------------------------------ result banner
function ResultBanner({ result, onOpenUnit, onDismiss }: {
  result: TxnResult; onOpenUnit: (id: string) => void; onDismiss: () => void;
}) {
  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-emerald-800/70 dark:text-emerald-300/70">{k}</dt><dd className="font-mono">{v}</dd></div>
  );
  return (
    <div role="status" className="space-y-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-900 dark:text-emerald-200">
      <div className="flex items-start justify-between gap-2">
        <p className="font-semibold">{result.data.message}</p>
        <button type="button" onClick={onDismiss} className="text-emerald-700 hover:underline dark:text-emerald-300">Dismiss</button>
      </div>

      {result.kind === "movement" && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {kv("Transaction", <CCTxnNumber value={result.data.ledger_transaction_number} />)}
          {kv("Movement", result.data.movement_type)}
          {kv("Unit", result.data.stock_unit_number)}
          {kv("Length", <CCLengthCell mm={result.data.length_mm} />)}
          {kv("Allocation", result.data.allocation_number)}
          {kv("WO / routing", `${result.data.wo_number} / v${result.data.routing_version}`)}
          {kv("Allocation status", result.data.allocation_status)}
          {kv("Reconciled", result.data.reconciled ? "Yes" : "No")}
          {kv("Unit remaining", <CCLengthCell mm={result.data.unit_remaining_length_mm} />)}
          {kv("Unit reserved", <CCLengthCell mm={result.data.unit_reserved_length_mm} />)}
          {kv("Unit issued", <CCLengthCell mm={result.data.unit_issued_length_mm} />)}
          {kv("Unit free", <CCLengthCell mm={result.data.unit_free_length_mm} />)}
          {kv("Alloc. reserved", <CCLengthCell mm={result.data.allocation_reserved_length_mm} />)}
          {kv("Alloc. issued", <CCLengthCell mm={result.data.allocation_issued_length_mm} />)}
          {kv("Alloc. consumed", <CCLengthCell mm={result.data.allocation_consumed_length_mm} />)}
        </dl>
      )}

      {result.kind === "unit" && (
        <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {kv("Transaction", <CCTxnNumber value={result.data.ledger_transaction_number} />)}
          {kv("Movement", result.data.movement_type)}
          {kv("Unit", result.data.stock_unit_number)}
          {kv("Length", <CCLengthCell mm={result.data.length_mm} />)}
          {kv("Unit status", result.data.unit_status)}
          {kv("Replayed", result.data.replayed ? "Yes (original result returned)" : "No")}
          {kv("Reconciled", result.data.reconciled ? "Yes" : "No")}
          {kv("Net adjustment", <CCLengthCell mm={result.data.unit_net_adjustment_mm} />)}
          {kv("Unit remaining", <CCLengthCell mm={result.data.unit_remaining_length_mm} />)}
          {kv("Unit reserved", <CCLengthCell mm={result.data.unit_reserved_length_mm} />)}
          {kv("Unit issued", <CCLengthCell mm={result.data.unit_issued_length_mm} />)}
          {kv("Unit consumed", <CCLengthCell mm={result.data.unit_consumed_length_mm} />)}
          {kv("Unit scrapped", <CCLengthCell mm={result.data.unit_scrapped_length_mm} />)}
          {kv("Unit free", <CCLengthCell mm={result.data.unit_free_length_mm} />)}
        </dl>
      )}

      {result.kind === "split" && (
        <>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {kv("Split-out txn", <CCTxnNumber value={result.data.split_out_transaction_number} />)}
            {kv("Split-in txn", <CCTxnNumber value={result.data.split_in_transaction_number} />)}
            {kv("Length", <CCLengthCell mm={result.data.length_mm} />)}
            {kv("Reconciled", result.data.reconciled ? "Yes" : "No")}
            {kv("Parent unit", `${result.data.parent_unit_number} (${result.data.parent_status})`)}
            {kv("Parent remaining", <CCLengthCell mm={result.data.parent_remaining_length_mm} />)}
            {kv("Parent reserved", <CCLengthCell mm={result.data.parent_reserved_length_mm} />)}
            {kv("Parent issued", <CCLengthCell mm={result.data.parent_issued_length_mm} />)}
            {kv("Parent free", <CCLengthCell mm={result.data.parent_free_length_mm} />)}
            {kv("Child unit", `${result.data.child_unit_number} (${result.data.child_status})`)}
            {kv("Child length", <CCLengthCell mm={result.data.child_original_length_mm} />)}
            {kv("Child free", <CCLengthCell mm={result.data.child_free_length_mm} />)}
            {kv("Child allocation eligible", result.data.child_allocation_eligible ? "Yes" : `No${result.data.child_allocation_ineligible_reason ? ` - ${result.data.child_allocation_ineligible_reason}` : ""}`)}
          </dl>
          <div className="flex gap-2">
            <button type="button" onClick={() => onOpenUnit((result.data as CCSplitResult).parent_unit_id)} className={ccSecondaryBtnCls}>Open parent</button>
            <button type="button" onClick={() => onOpenUnit((result.data as CCSplitResult).child_unit_id)} className={ccSecondaryBtnCls}>Open child</button>
          </div>
        </>
      )}
    </div>
  );
}

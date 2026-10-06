"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { Cog, RefreshCw } from "lucide-react";
import { CCAllocationList } from "@/app/components/cc/CCAllocationList";
import { CCCutResultPanel } from "@/app/components/cc/CCCutResultPanel";
import { CCCutConsumePanel } from "@/app/components/cc/CCCutConsumePanel";
import { CCAvailableCutList } from "@/app/components/cc/CCAvailableCutList";
import { CCCutResultList } from "@/app/components/cc/CCCutResultList";
import { CCErrorBanner } from "@/app/components/cc/CCErrorBanner";
import { CCGateStatusPanel } from "@/app/components/cc/CCGateStatusPanel";
import { CCRoleGate } from "@/app/components/cc/CCRoleGate";
import { CCRoutingVersionHistory } from "@/app/components/cc/CCRoutingVersionHistory";
import { CCWorkOrderSelector } from "@/app/components/cc/CCWorkOrderSelector";
import {
  ccErrorMessage, ccGetGateStatus, ccListRoutings, CCAllocationOut, CCCutAvailableOut, CCGateStatus, CCRoutingOut, CCWorkOrderListItem,
} from "@/lib/continuousCastingApi";
import { CC_CUT_ROLES } from "@/lib/continuousCastingRoles";
import { ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

// Cutting: for an existing Work Order it shows the backend's gate status, its China routing, its allocations, the
// CUT_CONSUME operations still waiting for a result, and the recorded cut results. Cut roles can start a cut
// consumption from an allocation of an ACTIVE routing (11D-E-2) and record the cut result of an awaiting CUT_CONSUME
// (11D-E-3).
// No value is calculated in the browser.
export default function CuttingContent() {
  const [wo, setWo] = useState<CCWorkOrderListItem | null>(null);
  const [routings, setRoutings] = useState<CCRoutingOut[] | null>(null);
  const [routingError, setRoutingError] = useState<string | null>(null);
  const [gate, setGate] = useState<CCGateStatus | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [listsRefresh, setListsRefresh] = useState(0);
  const [allocRows, setAllocRows] = useState<CCAllocationOut[]>([]);
  const [cutTarget, setCutTarget] = useState<CCAllocationOut | null>(null);
  const [resultTarget, setResultTarget] = useState<CCCutAvailableOut | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (woNumber: string) => {
    const mine = ++seq.current;
    setLoading(true);
    const [r, g] = await Promise.allSettled([
      ccListRoutings({ wo_number: woNumber, limit: 500 }),
      ccGetGateStatus(woNumber),
    ]);
    if (mine !== seq.current) return; // an older WO load finished after a newer selection: ignore it
    if (r.status === "fulfilled") { setRoutings(r.value.items); setRoutingError(null); }
    else { setRoutings(null); setRoutingError(ccErrorMessage(r.reason)); }
    if (g.status === "fulfilled") { setGate(g.value); setGateError(null); }
    else { setGate(null); setGateError(ccErrorMessage(g.reason)); }
    setLoading(false);
  }, []);

  useEffect(() => {
    setRoutings(null); setGate(null); setRoutingError(null); setGateError(null);
    setCutTarget(null); setAllocRows([]); setResultTarget(null);
    if (wo) void load(wo.wo_number);
  }, [wo, load]);

  const reload = (woNumber: string) => { void load(woNumber); setListsRefresh((k) => k + 1); };

  // The panel always shows the newest backend row for its allocation (falls back to the row it was opened on).
  const cutAllocation = cutTarget
    ? allocRows.find((a) => a.allocation_id === cutTarget.allocation_id) ?? cutTarget
    : null;

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
          <Cog className="h-3.5 w-3.5" /> Continuous Casting
        </p>
        <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Cutting</h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Select an existing Work Order to see its material gate, routing, allocations, cut consumptions awaiting a
          result, and recorded cut results. All figures come from the backend.
        </p>
      </div>

      <details open={!wo} className="rounded-xl border border-zinc-200 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-900">
        <summary className="cursor-pointer text-xs font-semibold">1. Select Work Order</summary>
        <div className="mt-2">
          <CCWorkOrderSelector selectedWoNumber={wo?.wo_number} onSelect={setWo} />
        </div>
      </details>

      {wo && (
        <>
          <section className="rounded-xl border border-zinc-200 bg-white p-4 text-xs dark:border-zinc-800 dark:bg-zinc-900">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">
                Work Order <span className="font-mono">{wo.wo_number}</span>
              </h2>
              <button type="button" disabled={loading} onClick={() => reload(wo.wo_number)} className={`${ccSecondaryBtnCls} inline-flex items-center gap-1`}>
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
              </button>
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {kv("OAR", <span className="font-mono">{wo.oar_number ?? "-"}</span>)}
              {kv("Customer", `${wo.customer_code} ${wo.customer_name}`)}
              {kv("Part", <span><span className="font-mono">{wo.part_number}</span> {wo.part_name ?? ""}</span>)}
              {kv("Grade", wo.grade ?? "-")}
              {kv("WO quantity", <span className="font-mono">{wo.physical_wo_qty}</span>)}
              {kv("Current stage", <span className="font-mono">{wo.current_stage}</span>)}
              {kv("Status", wo.status)}
              {kv("Delivery date", wo.delivery_date ?? "-")}
            </dl>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">OMS material gate</h2>
            <p className="text-xs text-zinc-500">
              Cutting results decide how much first-stage production the OMS will allow. Planned, recorded and usable blanks,
              remaining capacity and the verdict below are the backend&apos;s; only good blanks from RECONCILED results on the
              ACTIVE routing are usable.
            </p>
            <CCErrorBanner message={gateError} />
            <CCGateStatusPanel gate={gate} />
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Routing</h2>
            <CCErrorBanner message={routingError} />
            {routings && <CCRoutingVersionHistory routings={routings} />}
            {!routings && !routingError && <p className="text-xs text-zinc-400">Loading...</p>}
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Allocations</h2>
            {cutTarget && cutAllocation && (
              <CCRoleGate allowed={CC_CUT_ROLES}>
                <CCCutConsumePanel
                  key={cutTarget.allocation_id}
                  allocation={cutAllocation}
                  onClose={() => setCutTarget(null)}
                  onChanged={() => reload(wo.wo_number)}
                />
              </CCRoleGate>
            )}
            <CCAllocationList
              woNumber={wo.wo_number}
              refreshKey={listsRefresh}
              onLoaded={setAllocRows}
              renderActions={(a) =>
                // Offered only while the backend reports the allocation's routing as ACTIVE (visibility only).
                a.routing_status === "ACTIVE" ? (
                  <CCRoleGate allowed={CC_CUT_ROLES}>
                    <button type="button" onClick={() => setCutTarget(a)}
                      className="rounded-md border border-rose-500/50 px-2 py-1 text-[11px] font-semibold text-rose-700 hover:bg-rose-500/10 dark:text-rose-300">
                      Cut
                    </button>
                  </CCRoleGate>
                ) : null
              }
            />
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Cut consumptions awaiting a cut result</h2>
            <p className="text-xs text-zinc-500">
              A CUT_CONSUME is the physical consumption of raw length. Each one needs exactly one cut result.
              A result on a SUPERSEDED routing is never usable for OMS capacity.
            </p>
            {resultTarget && (
              <CCRoleGate allowed={CC_CUT_ROLES}>
                <CCCutResultPanel
                  key={resultTarget.ledger_transaction_number}
                  operation={resultTarget}
                  onClose={() => setResultTarget(null)}
                  onChanged={() => reload(wo.wo_number)}
                />
              </CCRoleGate>
            )}
            <CCAvailableCutList
              woNumber={wo.wo_number}
              refreshKey={listsRefresh}
              renderActions={(op) => (
                // Every row comes from the backend's awaiting list, so each one may receive a result.
                <CCRoleGate allowed={CC_CUT_ROLES}>
                  <button type="button" onClick={() => setResultTarget(op)}
                    className="whitespace-nowrap rounded-md border border-blue-500/50 px-2 py-1 text-[11px] font-semibold text-blue-700 hover:bg-blue-500/10 dark:text-blue-300">
                    Record cut result
                  </button>
                </CCRoleGate>
              )}
            />
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Cut results</h2>
            <p className="text-xs text-zinc-500">
              Good and rejected blanks are shown separately; rejected blanks are never usable capacity. A VARIANCE result is
              permanent and cannot be corrected or replaced.
            </p>
            <CCCutResultList woNumber={wo.wo_number} refreshKey={listsRefresh} />
          </section>
        </>
      )}
    </div>
  );
}

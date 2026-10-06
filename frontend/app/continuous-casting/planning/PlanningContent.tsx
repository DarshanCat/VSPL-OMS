"use client";
import React, { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, RefreshCw } from "lucide-react";
import { CCAllocationList } from "@/app/components/cc/CCAllocationList";
import { CCAllocationPanel } from "@/app/components/cc/CCAllocationPanel";
import { CCReleaseSupersededModal } from "@/app/components/cc/CCReleaseSupersededModal";
import { CCReservationPanel } from "@/app/components/cc/CCReservationPanel";
import { CCErrorBanner } from "@/app/components/cc/CCErrorBanner";
import { CCGateStatusPanel } from "@/app/components/cc/CCGateStatusPanel";
import { CCRoleGate } from "@/app/components/cc/CCRoleGate";
import { CCRoutingFormModal } from "@/app/components/cc/CCRoutingFormModal";
import { CCRoutingVersionHistory } from "@/app/components/cc/CCRoutingVersionHistory";
import { CCWorkOrderSelector } from "@/app/components/cc/CCWorkOrderSelector";
import {
  ccErrorMessage, ccGetGateStatus, ccListMaterials, ccListRoutings, CCAllocationOut, CCGateStatus, CCMaterialOut, CCRoutingOut,
  CCWorkOrderListItem,
} from "@/lib/continuousCastingApi";
import { CC_RESERVE_ROLES, CC_ROUTING_ROLES } from "@/lib/continuousCastingRoles";
import { ccSecondaryBtnCls } from "@/lib/continuousCastingForm";

// Planning: select an existing OMS Work Order, view its China routing versions and the backend's material-gate
// status, create or supersede the routing (routing roles), and plan allocations, reserve and release stock
// (reserve roles). No value is calculated in the browser. No value is calculated in the browser.
export default function PlanningContent() {
  const [wo, setWo] = useState<CCWorkOrderListItem | null>(null);
  const [routings, setRoutings] = useState<CCRoutingOut[] | null>(null);
  const [routingError, setRoutingError] = useState<string | null>(null);
  const [gate, setGate] = useState<CCGateStatus | null>(null);
  const [gateError, setGateError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [materials, setMaterials] = useState<CCMaterialOut[]>([]);
  const [materialsError, setMaterialsError] = useState<string | null>(null);
  const [formMode, setFormMode] = useState<"create" | "supersede" | null>(null);
  const [allocRefresh, setAllocRefresh] = useState(0);
  const [addAllocOpen, setAddAllocOpen] = useState(false);
  const [allocRows, setAllocRows] = useState<CCAllocationOut[]>([]);
  const [reservation, setReservation] = useState<{ mode: "reserve" | "release"; allocation: CCAllocationOut } | null>(null);
  const [releaseTarget, setReleaseTarget] = useState<CCRoutingOut | null>(null);
  const seq = useRef(0);

  const load = useCallback(async (woNumber: string) => {
    const mine = ++seq.current;
    setLoading(true);
    const [r, g] = await Promise.allSettled([
      ccListRoutings({ wo_number: woNumber, limit: 500 }),
      ccGetGateStatus(woNumber),
    ]);
    if (mine !== seq.current) return; // a newer selection superseded this load
    if (r.status === "fulfilled") { setRoutings(r.value.items); setRoutingError(null); }
    else { setRoutings(null); setRoutingError(ccErrorMessage(r.reason)); }
    if (g.status === "fulfilled") { setGate(g.value); setGateError(null); }
    else { setGate(null); setGateError(ccErrorMessage(g.reason)); }
    setLoading(false);
  }, []);

  // Active materials for the routing form; the backend still validates the choice.
  useEffect(() => {
    ccListMaterials({ is_active: true, limit: 500 })
      .then((p) => setMaterials(p.items))
      .catch((err) => setMaterialsError(ccErrorMessage(err)));
  }, []);

  useEffect(() => {
    setRoutings(null); setGate(null); setRoutingError(null); setGateError(null); setAddAllocOpen(false);
    setReservation(null); setReleaseTarget(null); setAllocRows([]);
    if (wo) void load(wo.wo_number);
  }, [wo, load]);

  // Reload everything the screen shows for the selected Work Order (also used after a conflict).
  const reload = (woNumber: string) => { void load(woNumber); setAllocRefresh((k) => k + 1); };

  // The panel always shows the newest backend row for its allocation (falls back to the row it was opened on).
  const reservationAllocation = reservation
    ? allocRows.find((a) => a.allocation_id === reservation.allocation.allocation_id) ?? reservation.allocation
    : null;

  const activeRouting = routings?.find((r) => r.status === "ACTIVE") ?? null;

  const kv = (k: string, v: React.ReactNode) => (
    <div key={k}><dt className="text-zinc-500">{k}</dt><dd className="text-zinc-900 dark:text-zinc-100">{v}</dd></div>
  );

  return (
    <div className="space-y-4">
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-amber-600">
          <CalendarClock className="h-3.5 w-3.5" /> Continuous Casting
        </p>
        <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50">Planning</h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          Select an existing Work Order to see its Continuous Casting routing versions and material gate status.
          All figures come from the backend.
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
              {kv("Order quantity", <span className="font-mono">{wo.order_qty}</span>)}
              {kv("Current stage", <span className="font-mono">{wo.current_stage}</span>)}
              {kv("Status", wo.status)}
              {kv("Delivery date", wo.delivery_date ?? "-")}
            </dl>
          </section>

          <section className="space-y-2">
            <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Material gate</h2>
            <CCErrorBanner message={gateError} />
            <CCGateStatusPanel gate={gate} />
          </section>

          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Routing</h2>
              {routings && (
                <CCRoleGate allowed={CC_ROUTING_ROLES}>
                  {activeRouting ? (
                    <button type="button" onClick={() => setFormMode("supersede")}
                      className="rounded-lg border border-amber-500/50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-500/10 dark:text-amber-300">
                      Supersede Routing
                    </button>
                  ) : (
                    <button type="button" onClick={() => setFormMode("create")}
                      className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700">
                      Create Continuous Casting Routing
                    </button>
                  )}
                </CCRoleGate>
              )}
            </div>
            <CCErrorBanner message={routingError} />
            <CCErrorBanner message={materialsError} />
            {routings && (
              <CCRoutingVersionHistory
                routings={routings}
                renderActions={(r) =>
                  r.status === "SUPERSEDED" ? (
                    <CCRoleGate allowed={CC_RESERVE_ROLES}>
                      <button type="button" onClick={() => setReleaseTarget(r)}
                        className="whitespace-nowrap rounded-md border border-amber-500/50 px-2 py-1 text-[11px] font-semibold text-amber-700 hover:bg-amber-500/10 dark:text-amber-300">
                        Release superseded reservations
                      </button>
                    </CCRoleGate>
                  ) : null
                }
              />
            )}
            {!routings && !routingError && <p className="text-xs text-zinc-400">Loading...</p>}
          </section>
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-sm font-bold text-zinc-900 dark:text-zinc-50">Allocations</h2>
                <p className="text-xs text-zinc-500">Allocation is planning only. It reserves no stock.</p>
              </div>
              {activeRouting && !addAllocOpen && (
                <CCRoleGate allowed={CC_RESERVE_ROLES}>
                  <button type="button" onClick={() => setAddAllocOpen(true)}
                    className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700">
                    Add allocation
                  </button>
                </CCRoleGate>
              )}
            </div>
            {activeRouting && addAllocOpen && (
              <CCRoleGate allowed={CC_RESERVE_ROLES}>
                <CCAllocationPanel
                  key={activeRouting.routing_id}
                  routing={activeRouting}
                  onClose={() => setAddAllocOpen(false)}
                  onChanged={() => reload(wo.wo_number)}
                />
              </CCRoleGate>
            )}
            {reservation && reservationAllocation && (
              <CCRoleGate allowed={CC_RESERVE_ROLES}>
                <CCReservationPanel
                  key={`${reservation.mode}:${reservation.allocation.allocation_id}`}
                  mode={reservation.mode}
                  allocation={reservationAllocation}
                  onClose={() => setReservation(null)}
                  onChanged={() => reload(wo.wo_number)}
                />
              </CCRoleGate>
            )}
            <CCAllocationList
              woNumber={wo.wo_number}
              refreshKey={allocRefresh}
              onLoaded={setAllocRows}
              renderActions={(a) =>
                // Offered only while the backend reports the allocation's routing as ACTIVE.
                a.routing_status === "ACTIVE" ? (
                  <CCRoleGate allowed={CC_RESERVE_ROLES}>
                    <span className="flex gap-1">
                      <button type="button" onClick={() => setReservation({ mode: "reserve", allocation: a })}
                        className="rounded-md border border-purple-500/50 px-2 py-1 text-[11px] font-semibold text-purple-700 hover:bg-purple-500/10 dark:text-purple-300">
                        Reserve
                      </button>
                      <button type="button" onClick={() => setReservation({ mode: "release", allocation: a })}
                        className="whitespace-nowrap rounded-md border border-amber-500/50 px-2 py-1 text-[11px] font-semibold text-amber-700 hover:bg-amber-500/10 dark:text-amber-300">
                        Release reservation
                      </button>
                    </span>
                  </CCRoleGate>
                ) : null
              }
            />
          </section>

          <CCReleaseSupersededModal
            routing={releaseTarget}
            onClose={() => setReleaseTarget(null)}
            onChanged={() => reload(wo.wo_number)}
          />

          <CCRoutingFormModal
            mode={formMode ?? "create"}
            isOpen={formMode !== null}
            woNumber={wo.wo_number}
            materials={materials}
            activeRouting={activeRouting}
            onClose={() => setFormMode(null)}
            onSuccess={() => reload(wo.wo_number)}
            onStale={() => reload(wo.wo_number)}
          />
        </>
      )}
    </div>
  );
}

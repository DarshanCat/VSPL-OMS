// Continuous Casting ("China Material") API client.
// Reuses the one configured axios instance (base URL, Bearer cookie, no-cache headers) from lib/api.ts.
// Thin transport only: no business formulas, no free-stock / usable-blank / gate-verdict / eligibility
// calculation. Every value shown by the UI comes from these backend responses.
import axios from "axios";
import { api, logout } from "@/lib/api";
import type {
  CCAdjustmentCreate, CCAllocationCreate, CCAllocationListParams, CCAllocationOut, CCAllocationResult,
  CCCutAvailableOut, CCCutAvailableParams, CCCutConsumeCreate, CCCutResultCreate, CCCutResultListParams,
  CCCutResultOut, CCCutResultResult, CCGateStatus, CCHoldCreate, CCHoldReleaseCreate, CCInwardCreate,
  CCInwardDetail, CCInwardListParams, CCInwardQADecisionBody, CCInwardQADecisionResult, CCInwardResult,
  CCInwardStockOut, CCIssueCreate, CCLedgerListParams, CCLedgerOut, CCListResponse, CCMaterialCreate,
  CCMaterialListParams, CCMaterialOut, CCMaterialPatch, CCMaterialResult,
  CCMaterialStockSummaryParams, CCMaterialStockSummaryResponse,
  CCReleaseCreate, CCReserveCreate,
  CCReturnCreate, CCRoutingCreate, CCRoutingDetail, CCRoutingListParams, CCRoutingOut, CCRoutingReleaseBody,
  CCRoutingReleaseResult, CCRoutingResult, CCRoutingSupersede, CCScrapCreate, CCSplitCreate, CCSplitResult,
  CCStockMovementResult, CCStockUnitDetail, CCStockUnitListParams, CCStockUnitOut, CCTraceInward,
  CCTraceWorkOrder, CCUnitMovementResult, CCWorkOrderListItem, CCWorkOrderSearchParams,
} from "@/lib/continuousCastingTypes";

export * from "@/lib/continuousCastingTypes";

const BASE = "/api/v1/continuous-casting";

// Drop undefined / empty-string filters so they are not sent as literal query text.
function clean<T extends object>(params?: T): Record<string, unknown> | undefined {
  if (!params) return undefined;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out[k] = v;
  }
  return out;
}

async function get<T>(path: string, params?: object): Promise<T> {
  const { data } = await api.get<T>(`${BASE}${path}`, { params: clean(params) });
  return data;
}
async function post<T>(path: string, body: unknown): Promise<T> {
  const { data } = await api.post<T>(`${BASE}${path}`, body);
  return data;
}
async function patch<T>(path: string, body: unknown): Promise<T> {
  const { data } = await api.patch<T>(`${BASE}${path}`, body);
  return data;
}

// A fresh replay key per submission. Only the three backend-replay-safe operations (scrap, adjustments, cut
// results) accept one. A caller that RETRIES the very same submission after a network failure should pass
// the key it already generated so the backend can recognise the replay; otherwise a new key is made here.
export function ccNewRequestId(): string {
  return crypto.randomUUID();
}

// ------------------------------------------------------------------ error helper (China-scoped)
// Turns any thrown error into text for display, preserving the backend's own wording.
// 401 is handled here only (no global interceptor): the existing logout() clears the access_token cookie and
// sends the browser to /login, exactly as the rest of the app does when the user signs out.
export function ccErrorMessage(err: unknown): string {
  if (!axios.isAxiosError(err)) {
    return err instanceof Error && err.message ? err.message : "Unexpected error. Please try again.";
  }
  const status = err.response?.status;
  const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
  if (status === 401) {
    if (typeof window !== "undefined") logout();
    return "Your session has expired. Redirecting to sign in...";
  }
  const text = ccDetailText(detail);
  if (status === 403) {
    return text ? `Not permitted for your role: ${text}` : "Not permitted for your role.";
  }
  if (status === 400 || status === 404 || status === 409 || status === 422) {
    return text || `Request failed (${status}).`;
  }
  if (status !== undefined && status >= 500) {
    return `The server could not complete the request (HTTP ${status}). Please try again or contact support.`;
  }
  if (status === undefined) {
    return "Cannot reach the server. Check your connection and try again.";
  }
  return text || `Request failed (${status}).`;
}

// String details pass through unchanged; FastAPI validation arrays become one "loc: message" line each.
function ccDetailText(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        if (typeof d === "string") return d;
        const item = d as { loc?: unknown[]; msg?: unknown };
        const loc = Array.isArray(item.loc)
          ? item.loc.filter((p) => p !== "body" && p !== "query" && p !== "path").join(".")
          : "";
        const msg = typeof item.msg === "string" ? item.msg : JSON.stringify(d);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join("\n");
  }
  if (detail && typeof detail === "object") return JSON.stringify(detail);
  return "";
}

// ------------------------------------------------------------------ Materials
export const ccCreateMaterial = (body: CCMaterialCreate) => post<CCMaterialResult>("/materials", body);
export const ccUpdateMaterial = (materialId: string, body: CCMaterialPatch) =>
  patch<CCMaterialResult>(`/materials/${materialId}`, body);
export const ccGetMaterial = (materialId: string) => get<CCMaterialResult>(`/materials/${materialId}`);
export const ccListMaterials = (params?: CCMaterialListParams) =>
  get<CCListResponse<CCMaterialOut>>("/materials", params);

// ------------------------------------------------------------------ Inward / QA
export const ccCreateInward = (body: CCInwardCreate) => post<CCInwardResult>("/inwards", body);
export const ccDecideInwardQA = (inwardId: string, body: CCInwardQADecisionBody) =>
  post<CCInwardQADecisionResult>(`/inwards/${inwardId}/qa`, body);
export const ccListInwards = (params?: CCInwardListParams) =>
  get<CCListResponse<CCInwardStockOut>>("/inwards", params);
export const ccGetInward = (inwardId: string) => get<CCInwardDetail>(`/inwards/${inwardId}`);

// ------------------------------------------------------------------ Routing
export const ccCreateRouting = (body: CCRoutingCreate) => post<CCRoutingResult>("/routings", body);
// wo_number travels in the body (not the path)
export const ccSupersedeRouting = (body: CCRoutingSupersede) => post<CCRoutingResult>("/routings/supersede", body);
export const ccReleaseSupersededRouting = (routingId: string, body: CCRoutingReleaseBody = {}) =>
  post<CCRoutingReleaseResult>(`/routings/${routingId}/release-superseded`, body);
export const ccListRoutings = (params?: CCRoutingListParams) =>
  get<CCListResponse<CCRoutingOut>>("/routings", params);
export const ccGetRouting = (routingId: string) => get<CCRoutingDetail>(`/routings/${routingId}`);

// ------------------------------------------------------------------ Allocation / Reservation
export const ccCreateAllocation = (body: CCAllocationCreate) => post<CCAllocationResult>("/allocations", body);
export const ccReserve = (body: CCReserveCreate) => post<CCStockMovementResult>("/reservations", body);
export const ccReleaseReservation = (body: CCReleaseCreate) =>
  post<CCStockMovementResult>("/reservations/release", body);
export const ccListAllocations = (params?: CCAllocationListParams) =>
  get<CCListResponse<CCAllocationOut>>("/allocations", params);

// ------------------------------------------------------------------ Stores
export const ccIssue = (body: CCIssueCreate) => post<CCStockMovementResult>("/issues", body);
export const ccReturn = (body: CCReturnCreate) => post<CCStockMovementResult>("/returns", body);
export const ccSplit = (body: CCSplitCreate) => post<CCSplitResult>("/splits", body);
export const ccHold = (body: CCHoldCreate) => post<CCUnitMovementResult>("/holds", body);
export const ccReleaseHold = (body: CCHoldReleaseCreate) => post<CCUnitMovementResult>("/holds/release", body);
export const ccScrap = (body: CCScrapCreate) =>
  post<CCUnitMovementResult>("/scrap", { ...body, client_request_id: body.client_request_id ?? ccNewRequestId() });
export const ccAdjustOut = (body: CCAdjustmentCreate) =>
  post<CCUnitMovementResult>("/adjustments/out", {
    ...body, client_request_id: body.client_request_id ?? ccNewRequestId(),
  });
export const ccAdjustIn = (body: CCAdjustmentCreate) =>
  post<CCUnitMovementResult>("/adjustments/in", {
    ...body, client_request_id: body.client_request_id ?? ccNewRequestId(),
  });

// ------------------------------------------------------------------ Production
export const ccCutConsume = (body: CCCutConsumeCreate) => post<CCStockMovementResult>("/cut-consume", body);
export const ccRecordCutResult = (body: CCCutResultCreate) =>
  post<CCCutResultResult>("/cut-results", { ...body, client_request_id: body.client_request_id ?? ccNewRequestId() });
export const ccListCutResults = (params?: CCCutResultListParams) =>
  get<CCListResponse<CCCutResultOut>>("/cut-results", params);
export const ccListAvailableCutConsumes = (params?: CCCutAvailableParams) =>
  get<CCListResponse<CCCutAvailableOut>>("/cut-results/available", params);
export const ccGetCutResult = (cutResultId: string) => get<CCCutResultOut>(`/cut-results/${cutResultId}`);

// ------------------------------------------------------------------ Stock / Ledger
export const ccListMaterialStockSummary = (params?: CCMaterialStockSummaryParams) =>
  get<CCMaterialStockSummaryResponse>("/stock-summary", params);
export const ccListStockUnits = (params?: CCStockUnitListParams) =>
  get<CCListResponse<CCStockUnitOut>>("/stock-units", params);
export const ccGetStockUnit = (unitId: string) => get<CCStockUnitDetail>(`/stock-units/${unitId}`);
export const ccListLedger = (params?: CCLedgerListParams) => get<CCListResponse<CCLedgerOut>>("/ledger", params);

// ------------------------------------------------------------------ Traceability / Gate
export const ccTraceInward = (inwardId: string) => get<CCTraceInward>(`/traceability/inwards/${inwardId}`);
export const ccTraceWorkOrder = (woNumber: string) =>
  get<CCTraceWorkOrder>(`/traceability/work-orders/${encodeURIComponent(woNumber)}`);
export const ccGetGateStatus = (woNumber: string) =>
  get<CCGateStatus>(`/work-orders/${encodeURIComponent(woNumber)}/gate-status`);

// ------------------------------------------------------------------ OMS Work Order lookup (read only)
// Thin typed wrapper over the existing GET /api/v1/work-orders (it returns a plain array, no total).
// Exists because lib/api.ts getWorkOrders is untyped and has no offset; lib/api.ts is not modified.
export async function ccSearchWorkOrders(params?: CCWorkOrderSearchParams): Promise<CCWorkOrderListItem[]> {
  const { data } = await api.get<CCWorkOrderListItem[]>("/api/v1/work-orders", { params: clean(params) });
  return data;
}

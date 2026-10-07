// Engineering Readiness & Release API client
import axios from "axios";
import { api } from "@/lib/api";

export interface EngineeringKPIs {
  pending_review: number;
  ready_for_release: number;
  released: number;
  blocked: number;
  npd_count: number;
}

export interface EngineeringRevision {
  id: string;
  part_id: string;
  drawing_number: string;
  drawing_revision: string;
  drawing_url?: string | null;
  customer_spec_ref?: string | null;
  process_sheet_number?: string | null;
  pattern_number?: string | null;
  tooling_id?: string | null;
  is_active: boolean;
  created_by_id?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface EngineeringRevisionCreate {
  drawing_number: string;
  drawing_revision: string;
  drawing_url?: string | null;
  customer_spec_ref?: string | null;
  process_sheet_number?: string | null;
  pattern_number?: string | null;
  tooling_id?: string | null;
  is_active?: boolean;
}

export interface EngineeringRevisionUpdate {
  drawing_number?: string;
  drawing_revision?: string;
  drawing_url?: string | null;
  customer_spec_ref?: string | null;
  process_sheet_number?: string | null;
  pattern_number?: string | null;
  tooling_id?: string | null;
  is_active?: boolean;
}

export interface WOReadinessItem {
  work_order_id: string;
  work_order_number: string;
  part_id: string;
  part_name: string;
  customer_name: string;
  order_type: string;
  quantity: number;
  target_date?: string | null;
  drawing_available: boolean;
  drawing_revision_verified: boolean;
  customer_spec_verified: boolean;
  process_sheet_verified: boolean;
  pattern_ready: boolean;
  tooling_ready: boolean;
  verified_revision?: string | null;
  readiness_status: "PENDING" | "READY" | "RELEASED" | "BLOCKED" | string;
  is_released: boolean;
  released_at?: string | null;
  checklist_count: number;
  checklist_total: number;
}

export interface WOReadinessDetail {
  work_order_id: string;
  work_order_number: string;
  part_id: string;
  part_name: string;
  customer_name: string;
  order_type: string;
  quantity: number;
  target_date?: string | null;
  readiness_id?: string | null;
  drawing_available: boolean;
  drawing_revision_verified: boolean;
  customer_spec_verified: boolean;
  process_sheet_verified: boolean;
  pattern_ready: boolean;
  tooling_ready: boolean;
  verified_revision?: string | null;
  readiness_status: string;
  remarks?: string | null;
  engineer_id?: string | null;
  engineer_name?: string | null;
  released_at?: string | null;
  is_released: boolean;
  active_part_revision?: EngineeringRevision | null;
  available_revisions: EngineeringRevision[];
  replacement_required: boolean;
  replacement_part_id?: string | null;
  replacement_pattern_number?: string | null;
  replacement_reason?: string | null;
  can_release: boolean;
  blocking_reasons: string[];
}

export interface WOReadinessChecklistUpdate {
  drawing_available?: boolean;
  drawing_revision_verified?: boolean;
  customer_spec_verified?: boolean;
  process_sheet_verified?: boolean;
  pattern_ready?: boolean;
  tooling_ready?: boolean;
  verified_revision?: string | null;
  remarks?: string | null;
  replacement_part_id?: string | null;
  replacement_pattern_number?: string | null;
  replacement_reason?: string | null;
}

export interface EngineeringReleaseRequest {
  work_order_id: string;
  verified_revision: string;
  document_name?: string | null;
  document_url?: string | null;
  remarks?: string | null;
  replacement_part_id?: string | null;
  replacement_pattern_number?: string | null;
  replacement_reason?: string | null;
}

export interface EngineeringRevocationRequest {
  revocation_reason: string;
}

export interface EngineeringReleaseResponse {
  work_order_id: string;
  work_order_number: string;
  status: string;
  is_released: boolean;
  engineering_released_by?: string | null;
  engineering_released_at?: string | null;
  verified_revision?: string | null;
  message: string;
}

const BASE = "/api/v1/engineering";

function clean<T extends object>(params?: T): Record<string, unknown> | undefined {
  if (!params) return undefined;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out[k] = v;
  }
  return out;
}

export async function getEngineeringKPIs(): Promise<EngineeringKPIs> {
  const { data } = await api.get<EngineeringKPIs>(`${BASE}/kpis`);
  return data;
}

export async function getWorkOrdersReadiness(params?: {
  status?: string;
  order_type?: string;
  search?: string;
  skip?: number;
  limit?: number;
}): Promise<WOReadinessItem[]> {
  const { data } = await api.get<WOReadinessItem[]>(`${BASE}/readiness`, {
    params: clean(params),
  });
  return data;
}

export async function getWorkOrderReadiness(woId: string): Promise<WOReadinessDetail> {
  const { data } = await api.get<WOReadinessDetail>(`${BASE}/readiness/${woId}`);
  return data;
}

export async function updateWorkOrderReadiness(
  woId: string,
  payload: WOReadinessChecklistUpdate
): Promise<WOReadinessDetail> {
  const { data } = await api.put<WOReadinessDetail>(`${BASE}/readiness/${woId}`, payload);
  return data;
}

export async function releaseEngineering(
  payload: EngineeringReleaseRequest
): Promise<EngineeringReleaseResponse> {
  const { data } = await api.post<EngineeringReleaseResponse>(`${BASE}/release`, payload);
  return data;
}

export async function revokeEngineeringRelease(
  woId: string,
  payload: EngineeringRevocationRequest
): Promise<EngineeringReleaseResponse> {
  const { data } = await api.post<EngineeringReleaseResponse>(`${BASE}/revoke/${woId}`, payload);
  return data;
}

export async function getPartRevisions(partId: string): Promise<EngineeringRevision[]> {
  const { data } = await api.get<EngineeringRevision[]>(`${BASE}/revisions/${partId}`);
  return data;
}

export async function createPartRevision(
  partId: string,
  payload: EngineeringRevisionCreate
): Promise<EngineeringRevision> {
  const { data } = await api.post<EngineeringRevision>(`${BASE}/revisions/${partId}`, payload);
  return data;
}

export async function updatePartRevision(
  revisionId: string,
  payload: EngineeringRevisionUpdate
): Promise<EngineeringRevision> {
  const { data } = await api.put<EngineeringRevision>(
    `${BASE}/revisions/item/${revisionId}`,
    payload
  );
  return data;
}

export async function setActivePartRevision(revisionId: string): Promise<EngineeringRevision> {
  const { data } = await api.post<EngineeringRevision>(
    `${BASE}/revisions/item/${revisionId}/set-active`
  );
  return data;
}

export function engineeringErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) return detail[0].msg;
    return err.message || "An unexpected error occurred.";
  }
  return err instanceof Error ? err.message : "An unexpected error occurred.";
}

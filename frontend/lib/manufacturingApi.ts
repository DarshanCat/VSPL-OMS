// Manufacturing Readiness & Release API client
import axios from "axios";
import { api } from "@/lib/api";

export type ChecklistItemStatus = "READY" | "NOT_READY" | "N_A" | "EXCEPTION";

export interface ManufacturingKPIs {
  pending_review: number;
  ready_for_release: number;
  released: number;
  blocked: number;
  replacement_count: number;
}

export interface MachineOption {
  id: string;
  machine_code: string;
  machine_name: string;
  department?: string | null;
  is_active: boolean;
}

export interface OperatorOption {
  id: string;
  operator_code: string;
  operator_name: string;
  skill_level?: string | null;
  is_active: boolean;
}

export interface ContinuousCastingSummary {
  is_cc: boolean;
  routing_id: string;
  routing_version: number;
  required_grade?: string | null;
  planned_blanks?: number | null;
  usable_good_blanks: number;
  blank_length_mm?: number | null;
  is_cutting_ready: boolean;
}

export interface WOManufacturingReadinessItem {
  work_order_id: string;
  work_order_number: string;
  part_id: string;
  part_name: string;
  customer_name: string;
  order_type: string;
  quantity: number;
  target_date?: string | null;
  is_replacement: boolean;
  source_wo_number?: string | null;
  replacement_reason?: string | null;

  engineering_released: boolean;
  engineering_released_at?: string | null;
  engineering_document_revision?: string | null;

  material_staging_status: ChecklistItemStatus | string;
  machine_capacity_status: ChecklistItemStatus | string;
  tooling_fixtures_status: ChecklistItemStatus | string;
  cnc_program_setup_status: ChecklistItemStatus | string;
  gauges_quality_status: ChecklistItemStatus | string;
  operator_manning_status: ChecklistItemStatus | string;

  machine_code?: string | null;
  operator_name?: string | null;

  readiness_status: "PENDING" | "READY" | "RELEASED" | "BLOCKED" | string;
  is_released: boolean;
  released_at?: string | null;
  passed_count: number;
  total_count: number;
}

export interface WOManufacturingReadinessDetail {
  work_order_id: string;
  work_order_number: string;
  part_id: string;
  part_name: string;
  customer_name: string;
  order_type: string;
  quantity: number;
  target_date?: string | null;
  is_replacement: boolean;
  source_wo_number?: string | null;
  replacement_reason?: string | null;

  // Engineering Gate
  engineering_released: boolean;
  engineering_released_by?: string | null;
  engineering_released_at?: string | null;
  engineering_document_revision?: string | null;
  engineering_document_url?: string | null;
  engineering_remarks?: string | null;

  // 6-Point Checklist details
  material_staging_status: ChecklistItemStatus | string;
  material_staging_remark?: string | null;

  machine_capacity_status: ChecklistItemStatus | string;
  machine_capacity_remark?: string | null;
  machine_id?: string | null;
  machine_code?: string | null;

  tooling_fixtures_status: ChecklistItemStatus | string;
  tooling_fixtures_remark?: string | null;
  fixture_id?: string | null;

  cnc_program_setup_status: ChecklistItemStatus | string;
  cnc_program_setup_remark?: string | null;
  nc_program_number?: string | null;
  setup_sheet_url?: string | null;

  gauges_quality_status: ChecklistItemStatus | string;
  gauges_quality_remark?: string | null;
  gauge_set_id?: string | null;

  operator_manning_status: ChecklistItemStatus | string;
  operator_manning_remark?: string | null;
  operator_id?: string | null;
  operator_name?: string | null;

  readiness_status: string;
  remarks?: string | null;

  document_name?: string | null;
  document_url?: string | null;
  document_revision?: string | null;

  released_by_id?: string | null;
  released_by_name?: string | null;
  released_at?: string | null;
  is_released: boolean;

  can_release: boolean;
  blocking_reasons: string[];

  continuous_casting_summary?: ContinuousCastingSummary | null;
  available_machines: MachineOption[];
  available_operators: OperatorOption[];
}

export interface WOManufacturingReadinessUpdate {
  material_staging_status?: string;
  material_staging_remark?: string | null;

  machine_capacity_status?: string;
  machine_capacity_remark?: string | null;
  machine_id?: string | null;
  machine_code?: string | null;

  tooling_fixtures_status?: string;
  tooling_fixtures_remark?: string | null;
  fixture_id?: string | null;

  cnc_program_setup_status?: string;
  cnc_program_setup_remark?: string | null;
  nc_program_number?: string | null;
  setup_sheet_url?: string | null;

  gauges_quality_status?: string;
  gauges_quality_remark?: string | null;
  gauge_set_id?: string | null;

  operator_manning_status?: string;
  operator_manning_remark?: string | null;
  operator_id?: string | null;
  operator_name?: string | null;

  document_name?: string | null;
  document_url?: string | null;
  document_revision?: string | null;
  remarks?: string | null;
}

export interface ManufacturingReleaseRequest {
  document_name?: string | null;
  document_url?: string | null;
  document_revision?: string | null;
  remarks?: string | null;
}

export interface ManufacturingRevocationRequest {
  revocation_reason: string;
}

export interface ManufacturingReleaseResponse {
  work_order_id: string;
  work_order_number: string;
  status: string;
  is_released: boolean;
  manufacturing_released_by?: string | null;
  manufacturing_released_at?: string | null;
  message: string;
}

const BASE = "/api/v1/manufacturing";

function clean<T extends object>(params?: T): Record<string, unknown> | undefined {
  if (!params) return undefined;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") out[k] = v;
  }
  return out;
}

export async function getManufacturingKPIs(): Promise<ManufacturingKPIs> {
  const { data } = await api.get<ManufacturingKPIs>(`${BASE}/kpis`);
  return data;
}

export async function getManufacturingReadinessList(params?: {
  status?: string;
  order_type?: string;
  search?: string;
  is_replacement?: boolean;
  skip?: number;
  limit?: number;
}): Promise<WOManufacturingReadinessItem[]> {
  const { data } = await api.get<WOManufacturingReadinessItem[]>(`${BASE}/readiness`, {
    params: clean(params),
  });
  return data;
}

export async function getManufacturingReadinessDetail(woId: string): Promise<WOManufacturingReadinessDetail> {
  const { data } = await api.get<WOManufacturingReadinessDetail>(`${BASE}/readiness/${woId}`);
  return data;
}

export async function updateManufacturingReadiness(
  woId: string,
  payload: WOManufacturingReadinessUpdate
): Promise<WOManufacturingReadinessDetail> {
  const { data } = await api.put<WOManufacturingReadinessDetail>(`${BASE}/readiness/${woId}`, payload);
  return data;
}

export async function releaseManufacturing(
  woId: string,
  payload: ManufacturingReleaseRequest
): Promise<ManufacturingReleaseResponse> {
  const { data } = await api.post<ManufacturingReleaseResponse>(`${BASE}/release/${woId}`, payload);
  return data;
}

export async function revokeManufacturingRelease(
  woId: string,
  payload: ManufacturingRevocationRequest
): Promise<ManufacturingReleaseResponse> {
  const { data } = await api.post<ManufacturingReleaseResponse>(`${BASE}/revoke/${woId}`, payload);
  return data;
}

export function manufacturingErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0 && detail[0].msg) return detail[0].msg;
    return err.message || "An unexpected error occurred.";
  }
  return err instanceof Error ? err.message : "An unexpected error occurred.";
}

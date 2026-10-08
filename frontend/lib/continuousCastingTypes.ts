// Continuous Casting ("China Material") API types.
// Each interface mirrors a backend Pydantic schema (backend/app/schemas/continuous_casting.py and
// continuous_casting_read.py) field for field. Datetimes arrive as ISO strings; UUIDs as strings.
// Nothing here is computed on the client: every balance, flag and verdict comes from the backend.

// ------------------------------------------------------------------ shared
export interface CCListResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface CCPageParams {
  limit?: number;
  offset?: number;
}

export type CCQAStatus = "PENDING_QA" | "ACCEPTED" | "REJECTED" | "ON_HOLD";
export type CCQADecision = "ACCEPTED" | "REJECTED" | "ON_HOLD";
export type CCStockUnitStatus = "IN_STOCK" | "ON_HOLD" | "CONSUMED" | "SCRAPPED";
export type CCRoutingStatus = "DRAFT" | "ACTIVE" | "SUPERSEDED";
export type CCMaterialSource = "CONTINUOUS_CASTING" | "F1_PRODUCTION";
export type CCReconciliationStatus = "PENDING" | "RECONCILED" | "VARIANCE";
export type CCMovementType =
  | "INWARD" | "RESERVE" | "RELEASE" | "ISSUE" | "CUT_CONSUME" | "RETURN" | "HOLD" | "HOLD_RELEASE"
  | "SCRAP" | "ADJUSTMENT_IN" | "ADJUSTMENT_OUT" | "SPLIT_OUT" | "SPLIT_IN";

// ------------------------------------------------------------------ write requests
export interface CCMaterialCreate {
  material_code: string;
  grade: string;
  section: string;
  stock_dimension_a_mm: number;
  stock_dimension_b_mm?: number | null;
  description?: string | null;
}

// PATCH body: only the fields sent are applied; an explicit null clears stock_dimension_b_mm / description.
export interface CCMaterialPatch {
  material_code?: string;
  grade?: string;
  section?: string;
  stock_dimension_a_mm?: number;
  stock_dimension_b_mm?: number | null;
  description?: string | null;
  is_active?: boolean;
}

export interface CCInwardCreate {
  material_id: string;
  unit_lengths_mm: number[];
  received_piece_count?: number | null;
  received_total_length_mm?: number | null;
  stock_dimension_a_mm?: number | null;
  stock_dimension_b_mm?: number | null;
  grn_reference?: string | null;
  location?: string | null;
  remarks?: string | null;
}

export interface CCInwardQADecisionBody {
  decision: CCQADecision;
  reason?: string | null; // required by the backend for REJECTED and ON_HOLD
}

export interface CCRoutingCreate {
  wo_number: string;
  validated_material_id: string;
  required_grade: string;
  required_section: string;
  finished_dimension_a_mm: number;
  finished_dimension_b_mm?: number | null;
  finished_axial_length_mm: number;
  machining_stock_a_mm: number;
  machining_stock_b_mm: number;
  planned_blanks: number;
  planned_cuts: number;
  kerf_mm: number;
  end_trim_mm: number;
}

export interface CCRoutingSupersede extends CCRoutingCreate {
  reason: string;
}

export interface CCRoutingReleaseBody {
  reason?: string | null;
}

export interface CCAllocationCreate {
  routing_id: string;
  stock_unit_id: string;
  planned_length_mm: number;
}

export interface CCReserveCreate {
  routing_id: string;
  allocation_id: string;
  length_mm: number;
  reason?: string | null;
}
export type CCReleaseCreate = CCReserveCreate;

export interface CCIssueCreate {
  routing_id: string;
  allocation_id: string;
  stock_unit_id: string;
  length_mm: number;
  reason?: string | null;
}
export type CCCutConsumeCreate = CCIssueCreate;

export interface CCReturnCreate extends CCIssueCreate {
  inward_id: string;
}

export interface CCSplitCreate {
  stock_unit_id: string;
  inward_id: string;
  length_mm: number;
  reason?: string | null;
}

export interface CCHoldCreate {
  stock_unit_id: string;
  inward_id: string;
  reason: string;
  reference?: string | null;
}
export type CCHoldReleaseCreate = CCHoldCreate;

// client_request_id exists ONLY on scrap, adjustments and cut results (the backend replay-safe operations).
export interface CCScrapCreate {
  stock_unit_id: string;
  inward_id: string;
  length_mm: number;
  reason: string;
  reference: string;
  nc_record_id?: string | null;
  client_request_id?: string | null;
}

export interface CCAdjustmentCreate {
  stock_unit_id: string;
  inward_id: string;
  length_mm: number;
  reason: string;
  reference: string;
  client_request_id?: string | null;
}

export interface CCCutResultCreate {
  routing_id: string;
  allocation_id: string;
  stock_unit_id: string;
  ledger_transaction_number: string;
  consumed_length_mm: number;
  actual_good_blanks: number;
  rejected_blanks: number;
  actual_cuts: number;
  end_trim_mm: number;
  remarks?: string | null;
  client_request_id?: string | null;
}

// ------------------------------------------------------------------ write results
export interface CCMaterialResult {
  success: boolean;
  material_id: string;
  material_code: string;
  grade: string;
  section: string;
  stock_dimension_a_mm: number;
  stock_dimension_b_mm: number | null;
  description: string | null;
  is_active: boolean;
  referenced: boolean;
  inward_count: number;
  routing_count: number;
  created_by: string | null;
  updated_by: string | null;
  message: string;
}

export interface CCInwardUnitOut {
  unit_number: string;
  ledger_transaction_number: string;
  original_length_mm: number;
  remaining_length_mm: number;
}

export interface CCInwardResult {
  success: boolean;
  inward_id: string;
  inward_number: string;
  material_code: string;
  grn_reference: string | null;
  qa_status: string;
  physical_stock_status: string;
  allocation_eligible: boolean;
  allocation_ineligible_reason: string | null;
  received_piece_count: number;
  received_total_length_mm: number;
  ledger_inward_length_mm: number;
  units_original_length_mm: number;
  units_remaining_length_mm: number;
  reconciled: boolean;
  units: CCInwardUnitOut[];
  message: string;
}

export interface CCInwardQADecisionResult {
  success: boolean;
  inward_id: string;
  inward_number: string;
  previous_qa_status: string;
  qa_status: string;
  reason: string | null;
  decided_by: string;
  qa_allows_allocation: boolean;
  qa_block_reason: string | null;
  message: string;
}

export interface CCRoutingResult {
  success: boolean;
  routing_id: string;
  wo_number: string;
  version: number;
  status: string;
  material_source: string;
  validated_material_code: string;
  blank_length_mm: number;
  gross_required_length_mm: number;
  planned_blanks: number;
  planned_cuts: number;
  kerf_mm: number;
  end_trim_mm: number;
  superseded_version: number | null;
  message: string;
}

export interface CCAllocationResult {
  success: boolean;
  allocation_id: string;
  allocation_number: string;
  routing_id: string;
  routing_version: number;
  wo_number: string;
  stock_unit_number: string;
  inward_number: string;
  planned_length_mm: number;
  status: string;
  reserved_length_mm: number;
  unit_free_length_mm: number;
  unit_available_for_planning_mm: number;
  routing_gross_required_length_mm: number;
  routing_planned_total_mm: number;
  message: string;
}

// RESERVE, RELEASE, ISSUE, CUT_CONSUME and RETURN
export interface CCStockMovementResult {
  success: boolean;
  movement_type: string;
  ledger_transaction_number: string;
  allocation_id: string;
  allocation_number: string;
  routing_id: string;
  routing_version: number;
  wo_number: string;
  stock_unit_number: string;
  inward_number: string;
  length_mm: number;
  allocation_status: string;
  allocation_planned_length_mm: number;
  allocation_reserved_length_mm: number;
  allocation_issued_length_mm: number;
  allocation_consumed_length_mm: number;
  unit_remaining_length_mm: number;
  unit_reserved_length_mm: number;
  unit_issued_length_mm: number;
  unit_consumed_length_mm: number;
  unit_free_length_mm: number;
  ledger_reserved_length_mm: number;
  reconciled: boolean;
  message: string;
}

export interface CCRoutingReleaseResult {
  success: boolean;
  routing_id: string;
  routing_version: number;
  wo_number: string;
  allocations_released: number;
  total_released_length_mm: number;
  releases: CCStockMovementResult[];
  message: string;
}

export interface CCSplitResult {
  success: boolean;
  split_out_transaction_number: string;
  split_in_transaction_number: string;
  inward_id: string;
  inward_number: string;
  length_mm: number;
  parent_unit_id: string;
  parent_unit_number: string;
  parent_status: string;
  parent_remaining_length_mm: number;
  parent_reserved_length_mm: number;
  parent_issued_length_mm: number;
  parent_consumed_length_mm: number;
  parent_free_length_mm: number;
  child_unit_id: string;
  child_unit_number: string;
  child_status: string;
  child_original_length_mm: number;
  child_remaining_length_mm: number;
  child_free_length_mm: number;
  child_location: string | null;
  child_allocation_eligible: boolean;
  child_allocation_ineligible_reason: string | null;
  inward_total_length_mm: number;
  inward_units_remaining_plus_consumed_mm: number;
  reconciled: boolean;
  message: string;
}

// HOLD, HOLD_RELEASE, SCRAP, ADJUSTMENT_IN and ADJUSTMENT_OUT
export interface CCUnitMovementResult {
  success: boolean;
  movement_type: string;
  ledger_transaction_number: string;
  replayed: boolean;
  inward_id: string;
  inward_number: string;
  stock_unit_id: string;
  stock_unit_number: string;
  length_mm: number;
  unit_status: string;
  unit_remaining_length_mm: number;
  unit_reserved_length_mm: number;
  unit_issued_length_mm: number;
  unit_consumed_length_mm: number;
  unit_scrapped_length_mm: number;
  unit_free_length_mm: number;
  unit_net_adjustment_mm: number;
  inward_received_total_length_mm: number;
  inward_accounted_length_mm: number;
  reconciled: boolean;
  message: string;
}

export interface CCCutResultResult {
  success: boolean;
  replayed: boolean;
  cut_number: string;
  wo_number: string;
  routing_id: string;
  routing_version: number;
  routing_status: string;
  allocation_number: string;
  stock_unit_number: string;
  ledger_transaction_number: string;
  planned_blanks: number;
  actual_good_blanks: number;
  rejected_blanks: number;
  actual_cuts: number;
  blank_length_mm: number;
  kerf_mm: number;
  end_trim_mm: number;
  consumed_length_mm: number;
  required_length_mm: number;
  variance_mm: number;
  reconciliation_status: string;
  usable_for_oms: boolean;
  routing_blanks_recorded: number;
  routing_planned_blanks: number;
  message: string;
}

// ------------------------------------------------------------------ read models
export interface CCMaterialOut {
  material_id: string;
  material_code: string;
  grade: string;
  section: string;
  stock_dimension_a_mm: number;
  stock_dimension_b_mm: number | null;
  description: string | null;
  is_active: boolean;
  referenced: boolean;
  inward_count: number;
  routing_count: number;
  created_by: string | null;
  updated_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CCMaterialStockSummaryOut {
  material_id: string;
  material_code: string;
  grade: string;
  section: string;
  stock_dimension_a_mm: number;
  stock_dimension_b_mm: number | null;
  standard_length_mm: number | null;
  size_display: string;
  unit_count: number;
  total_length_mm: number;
  remaining_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
  scrapped_length_mm: number;
  free_length_mm: number;
  documented_weight_kg: number | null;
  status: string;
  inward_count: number;
  inward_numbers: string[];
}

export interface CCMaterialStockSummaryTotals {
  total_bars: number;
  total_length_mm: number;
  total_weight_kg: number;
}

export interface CCMaterialStockSummaryResponse {
  items: CCMaterialStockSummaryOut[];
  total: number;
  totals: CCMaterialStockSummaryTotals;
  limit: number;
  offset: number;
}

export interface CCMaterialStockSummaryParams extends CCPageParams {
  search?: string;
  grade?: string;
  section?: string;
  status?: string;
  location?: string;
}

export interface CCInwardStockOut {
  inward_id: string;
  inward_number: string;
  material_id: string;
  material_code: string;
  grade: string;
  section: string;
  stock_dimension_a_mm: number;
  stock_dimension_b_mm: number | null;
  received_piece_count: number;
  received_total_length_mm: number;
  grn_reference: string | null;
  qa_status: string;
  location: string | null;
  received_at: string | null;
  unit_count: number;
  remaining_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
  scrapped_length_mm: number;
  free_length_mm: number;
}

export interface CCQADecisionInfo {
  decision: string;
  previous_qa_status: string | null;
  reason: string | null;
  decided_by: string | null;
  decided_at: string | null;
}

export interface CCConservation {
  accounted_length_mm: number;
  expected_length_mm: number;
  adjustments_in_mm: number;
  adjustments_out_mm: number;
  consistent: boolean;
}

export interface CCInwardDetail extends CCInwardStockOut {
  remarks: string | null;
  created_by: string | null;
  updated_by: string | null;
  original_received_length_mm: number;
  physical_piece_count: number;
  qa_decision: CCQADecisionInfo | null;
  conservation: CCConservation;
}

export interface CCAllocationOut {
  allocation_id: string;
  allocation_number: string;
  routing_id: string;
  routing_version: number;
  routing_status: string;
  work_order_id: string;
  wo_number: string;
  inward_id: string;
  inward_number: string;
  stock_unit_id: string;
  stock_unit_number: string;
  planned_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
  plan_remaining_length_mm: number;
  status: string;
}

export interface CCRoutingOut {
  routing_id: string;
  work_order_id: string;
  wo_number: string;
  version: number;
  status: string;
  is_active: boolean;
  material_source: string;
  validated_material_id: string | null;
  validated_material_code: string | null;
  required_grade: string | null;
  required_section: string | null;
  finished_dimension_a_mm: number | null;
  finished_dimension_b_mm: number | null;
  finished_axial_length_mm: number | null;
  machining_stock_a_mm: number | null;
  machining_stock_b_mm: number | null;
  blank_length_mm: number | null;
  planned_blanks: number | null;
  planned_cuts: number | null;
  kerf_mm: number | null;
  end_trim_mm: number | null;
  gross_required_length_mm: number | null;
  validated_by: string | null;
  validated_at: string | null;
  superseded_at: string | null;
  superseded_by: string | null;
  supersede_reason: string | null;
  created_by: string | null;
  created_at: string | null;
  allocation_count: number;
}

export interface CCRoutingDetail extends CCRoutingOut {
  allocations: CCAllocationOut[];
}

export interface CCStockUnitOut {
  unit_id: string;
  unit_number: string;
  inward_id: string;
  inward_number: string;
  inward_qa_status: string;
  material_id: string;
  material_code: string;
  parent_unit_id: string | null;
  parent_unit_number: string | null;
  original_length_mm: number;
  remaining_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
  scrapped_length_mm: number;
  free_length_mm: number;
  piece_quantity: number;
  status: string;
  location: string | null;
  created_at: string | null;
  allocation_eligible: boolean;
  allocation_ineligible_reason: string | null;
}

export interface CCUnitChild {
  unit_id: string;
  unit_number: string;
  original_length_mm: number;
  remaining_length_mm: number;
  status: string;
}

export interface CCLastHold {
  movement_type: string;
  transaction_number: string;
  reason: string | null;
  performed_by: string | null;
  created_at: string | null;
}

export interface CCUnitIntegrity {
  consistent: boolean;
  ledger_remaining_length_mm: number;
  ledger_reserved_length_mm: number;
  ledger_issued_length_mm: number;
  ledger_consumed_length_mm: number;
  ledger_scrapped_length_mm: number;
}

export interface CCStockUnitDetail extends CCStockUnitOut {
  children: CCUnitChild[];
  net_adjustment_mm: number;
  last_hold_event: CCLastHold | null;
  integrity: CCUnitIntegrity;
  allocations: CCAllocationOut[];
}

export interface CCLedgerOut {
  transaction_number: string;
  movement_type: string;
  inward_id: string;
  inward_number: string;
  stock_unit_id: string;
  stock_unit_number: string;
  allocation_id: string | null;
  allocation_number: string | null;
  routing_id: string | null;
  routing_version: number | null;
  wo_number: string | null;
  length_mm: number;
  piece_qty: number | null;
  unit_remaining_after_mm: number | null;
  related_stock_unit_id: string | null;
  related_stock_unit_number: string | null;
  nc_record_id: string | null;
  nc_number: string | null;
  reason: string | null;
  reference: string | null;
  performed_by: string | null;
  created_at: string | null;
}

export interface CCCutResultOut {
  cut_result_id: string;
  cut_number: string;
  ledger_transaction_number: string | null;
  work_order_id: string;
  wo_number: string;
  routing_id: string;
  routing_version: number;
  routing_status: string;
  allocation_id: string;
  allocation_number: string;
  stock_unit_id: string;
  stock_unit_number: string;
  inward_number: string;
  planned_blanks: number;
  actual_cuts: number;
  actual_good_blanks: number;
  rejected_blanks: number;
  blank_length_mm: number;
  kerf_mm: number;
  end_trim_mm: number;
  consumed_length_mm: number;
  reconciliation_status: string;
  variance_mm: number | null;
  remarks: string | null;
  performed_by: string | null;
  created_at: string | null;
  usable_for_oms: boolean;
}

export interface CCCutAvailableOut {
  ledger_transaction_number: string;
  consumed_length_mm: number;
  allocation_id: string;
  allocation_number: string;
  stock_unit_id: string;
  stock_unit_number: string;
  routing_id: string;
  routing_version: number;
  routing_status: string;
  wo_number: string;
  created_at: string | null;
  planned_blanks: number;
  blank_length_mm: number;
  kerf_mm: number;
  planned_cuts: number | null;
  routing_blanks_recorded: number;
  routing_blanks_remaining_in_plan: number;
}

export interface CCGateStatus {
  wo_number: string;
  gate_applies: boolean;
  material_source: string | null;
  routing_id: string | null;
  routing_version: number | null;
  first_route_stage: string | null;
  first_stage_valid: boolean | null;
  planned_blanks: number | null;
  recorded_blanks: number | null;
  usable_good_blanks: number | null;
  first_stage_good_qty: number | null;
  first_stage_rejected_qty: number | null;
  remaining_capacity: number | null;
  verdict: string;
  reasons: string[];
}

// ------------------------------------------------------------------ traceability
export interface CCTraceUnit {
  unit_id: string;
  unit_number: string;
  parent_unit_number: string | null;
  original_length_mm: number;
  remaining_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
  scrapped_length_mm: number;
  free_length_mm: number;
  status: string;
  allocations: CCAllocationOut[];
}

export interface CCTraceInwardRollup {
  inward_id: string;
  inward_number: string;
  unit_count: number;
  allocation_count: number;
  planned_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
}

export interface CCTraceWorkOrderRollup {
  wo_number: string;
  routing_versions: number[];
  active_routing_version: number | null;
  allocation_count: number;
  planned_length_mm: number;
  reserved_length_mm: number;
  issued_length_mm: number;
  consumed_length_mm: number;
}

export interface CCTraceInward {
  inward: CCInwardDetail;
  units: CCTraceUnit[];
  work_orders: CCTraceWorkOrderRollup[];
  cut_results: CCCutResultOut[];
  ledger_totals_by_movement: Record<string, unknown>;
  recent_ledger: CCLedgerOut[];
  units_total: number;
  allocations_total: number;
  cut_results_total: number;
  ledger_rows_total: number;
  truncated: boolean;
  limitations: string[];
}

export interface CCTraceWorkOrder {
  wo_number: string;
  work_order_id: string;
  routings: CCRoutingOut[];
  active_routing_version: number | null;
  allocations: CCAllocationOut[];
  inwards: CCTraceInwardRollup[];
  units: CCTraceUnit[];
  cut_results: CCCutResultOut[];
  usable_good_blanks: number | null;
  allocations_total: number;
  cut_results_total: number;
  truncated: boolean;
  limitations: string[];
}

// ------------------------------------------------------------------ list query params
export interface CCMaterialListParams extends CCPageParams {
  search?: string; is_active?: boolean; grade?: string; section?: string;
}
export interface CCInwardListParams extends CCPageParams {
  inward_number?: string; material_id?: string; qa_status?: CCQAStatus; location?: string;
  received_from?: string; received_to?: string; has_free_stock?: boolean;
}
export interface CCStockUnitListParams extends CCPageParams {
  inward_id?: string; material_id?: string; status?: CCStockUnitStatus; location?: string;
  on_hold?: boolean; available?: boolean; parent_unit_id?: string;
}
export interface CCRoutingListParams extends CCPageParams {
  wo_number?: string; status?: CCRoutingStatus; material_source?: CCMaterialSource;
}
export interface CCAllocationListParams extends CCPageParams {
  routing_id?: string; wo_number?: string; stock_unit_id?: string; inward_id?: string; status?: string;
}
export interface CCLedgerListParams extends CCPageParams {
  stock_unit_id?: string; inward_id?: string; allocation_id?: string; wo_number?: string; routing_id?: string;
  movement_type?: CCMovementType; created_from?: string; created_to?: string;
}
export interface CCCutResultListParams extends CCPageParams {
  wo_number?: string; routing_id?: string; allocation_id?: string; stock_unit_id?: string;
  ledger_transaction_number?: string; reconciliation_status?: CCReconciliationStatus;
}
export interface CCCutAvailableParams extends CCPageParams {
  routing_id?: string; wo_number?: string;
}

// ------------------------------------------------------------------ OMS work orders (read only)
// Mirrors the existing OMS WorkOrderListItem returned by GET /api/v1/work-orders. Used only to pick an
// existing Work Order; the China module never creates or changes one. Revision is not part of this schema.
export interface CCWorkOrderListItem {
  id: string;
  wo_number: string;
  oar_number: string | null;
  customer_code: string;
  customer_name: string;
  part_number: string;
  part_name: string | null;
  grade: string | null;
  order_qty: number;
  physical_wo_qty: number;
  match_size: number | null;
  current_stage: string;
  next_allowed_stage: string | null;
  available_wip_at_current_stage: number;
  status: string;
  delivery_risk: string;
  shortfall: string;
  delivery_date: string | null;
  created_at: string;
}

export interface CCWorkOrderSearchParams extends CCPageParams {
  search?: string;
  status_filter?: string;
}

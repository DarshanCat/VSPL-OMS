import axios from "axios";
import Cookies from "js-cookie";

export const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_BASE,
});

api.interceptors.request.use((config) => {
  const token = Cookies.get("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Auth
export async function login(email: string, password: string) {
  const { data } = await api.post("/api/v1/auth/login", { email, password });
  Cookies.set("access_token", data.access_token, { expires: 1 });
  return data;
}

export async function changePassword(currentPassword: string, newPassword: string) {
  const { data } = await api.post("/api/v1/auth/change-password", {
    current_password: currentPassword,
    new_password: newPassword,
  });
  // The backend issues a fresh token once must_change_password clears -- the old one
  // may have been obtained with the temporary password, whose hash no longer exists.
  Cookies.set("access_token", data.access_token, { expires: 1 });
  return data;
}

export function logout() {
  Cookies.remove("access_token");
  window.location.href = "/login";
}

// User context helper
export function getCurrentUserToken() {
  return Cookies.get("access_token");
}

// Decodes the role already embedded in the JWT payload by the backend
// (create_access_token includes {"role": user.role.value}) so the frontend can tailor
// navigation without a network round trip. This is a UI convenience only -- every
// endpoint enforces its own authorization server-side regardless of what this returns.
export function getCurrentUserRole(): string | null {
  const token = Cookies.get("access_token");
  if (!token) return null;
  try {
    const payloadB64 = token.split(".")[1];
    const json = JSON.parse(atob(payloadB64.replace(/-/g, "+").replace(/_/g, "/")));
    return json.role || null;
  } catch {
    return null;
  }
}

// Server-resolved identity of the authenticated caller (never client-supplied) --
// used to render the sidebar's real logged-in user instead of a hardcoded placeholder.
export async function getCurrentUser(): Promise<{
  id: string;
  full_name: string;
  email: string;
  role: string;
  department?: string | null;
  is_active: boolean;
  must_change_password: boolean;
}> {
  const { data } = await api.get("/api/v1/auth/me");
  return data;
}

// User administration (ADMIN only -- enforced server-side regardless of who calls these)
export interface AdminUser {
  id: string;
  full_name: string;
  email: string;
  role: string;
  department?: string | null;
  is_active: boolean;
  must_change_password: boolean;
}

export interface TemporaryPasswordResult {
  user: AdminUser;
  temporary_password: string;
}

export async function getUsers(): Promise<AdminUser[]> {
  const { data } = await api.get("/api/v1/users");
  return data;
}

export async function createUser(payload: {
  full_name: string;
  email: string;
  department?: string;
  role: string;
}): Promise<TemporaryPasswordResult> {
  const { data } = await api.post("/api/v1/users", payload);
  return data;
}

export async function resetUserPassword(userId: string): Promise<TemporaryPasswordResult> {
  const { data } = await api.post(`/api/v1/users/${encodeURIComponent(userId)}/reset-password`);
  return data;
}

export async function setUserStatus(userId: string, isActive: boolean): Promise<AdminUser> {
  const { data } = await api.patch(`/api/v1/users/${encodeURIComponent(userId)}/status`, {
    is_active: isActive,
  });
  return data;
}

// Dashboard
export async function getDashboardStats() {
  const { data } = await api.get("/api/v1/dashboard/stats");
  return data;
}

// Work Orders & Tracking
export async function getWorkOrders(params?: {
  search?: string;
  stage?: string;
  customer_code?: string;
  status_filter?: string;
  limit?: number;
}) {
  const { data } = await api.get("/api/v1/work-orders", { params });
  return data;
}

export async function getWorkOrderTracking(woIdentifier: string) {
  const { data } = await api.get(`/api/v1/work-orders/${encodeURIComponent(woIdentifier)}/tracking`);
  return data;
}

export async function getWorkOrderRoute(woIdentifier: string) {
  const { data } = await api.get(`/api/v1/work-orders/${encodeURIComponent(woIdentifier)}/route`);
  return data;
}

export async function getStageState(woIdentifier: string, stageName: string) {
  const { data } = await api.get(`/api/v1/work-orders/${encodeURIComponent(woIdentifier)}/stage/${encodeURIComponent(stageName)}/state`);
  return data;
}

// Production & WIP
export async function recordStageProduction(payload: {
  wo_number: string;
  stage: string;
  good_qty: number;
  rejected_quantity?: number;
  machine_id?: string;
  operator_name?: string;
  shift?: string;
  defect_code?: string;
  remarks?: string;
  client_request_id?: string;
}) {
  const { data } = await api.post("/api/v1/production/entry", payload);
  return data;
}

export async function moveParts(payload: {
  wo_number: string;
  from_stage: string;
  to_stage: string;
  quantity_moved: number;
  rejected_quantity?: number;
  machine_id?: string;
  operator_name?: string;
  shift?: string;
  defect_code?: string;
  remarks?: string;
  client_request_id?: string;
}) {
  const { data } = await api.post("/api/v1/production/move", payload);
  return data;
}

export async function getMovements(params?: { wo_number?: string; stage?: string; limit?: number }) {
  const { data } = await api.get("/api/v1/production/movements", { params });
  return data;
}

export async function getWIPMatrix() {
  const { data } = await api.get("/api/v1/production/wip");
  return data;
}

export async function getPlantReconciliation() {
  const { data } = await api.get("/api/v1/production/reconciliation");
  return data;
}

// Packing / BSR
export async function getPackingQueue() {
  const { data } = await api.get("/api/v1/packing/queue");
  return data;
}

export async function updatePacking(payload: {
  wo_number: string;
  packed_quantity: number;
  box_count?: number;
  package_type?: string;
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/packing/update", payload);
  return data;
}

// Dispatch
export async function getDispatchQueue() {
  const { data } = await api.get("/api/v1/dispatch/queue");
  return data;
}

export async function executeDispatch(payload: {
  wo_number: string;
  invoice_number: string;
  dispatched_quantity: number;
  customer_po?: string;
  vehicle_number?: string;
  transporter?: string;
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/dispatch/ship", payload);
  return data;
}

export async function getDispatchHistory() {
  const { data } = await api.get("/api/v1/dispatch/history");
  return data;
}

// Operations
export async function createOrderIntake(payload: {
  customer_code: string;
  customer_name: string;
  customer_po: string;
  part_number: string;
  grade?: string;
  part_description?: string;
  po_quantity: number;
  max_batch_size: number;
  delivery_date?: string;
  order_type?: string;
  order_classification?: "regular" | "npd";
  wo_quantities?: number[];
  source_type?: string;
  po_line_id?: string;
  schedule_id?: string;
}) {
  const { data } = await api.post("/api/v1/operations/intake", payload);
  return data;
}

// --- Masters: Customer / PO / Schedule ---

export interface MasterCustomer {
  id: string;
  customer_code: string;
  name: string;
  address?: string | null;
  gst?: string | null;
  contact_person?: string | null;
  email?: string | null;
  phone?: string | null;
  is_active: boolean;
}

export async function getMasterCustomers(): Promise<MasterCustomer[]> {
  const { data } = await api.get("/api/v1/masters/customers");
  return data;
}

export async function createMasterCustomer(payload: {
  customer_code: string;
  name: string;
  address?: string;
  gst?: string;
  contact_person?: string;
  email?: string;
  phone?: string;
  is_active?: boolean;
}): Promise<MasterCustomer> {
  const { data } = await api.post("/api/v1/masters/customers", payload);
  return data;
}

export async function updateMasterCustomer(payload: {
  id: string;
  address?: string;
  gst?: string;
  contact_person?: string;
  email?: string;
  phone?: string;
  is_active?: boolean;
}): Promise<MasterCustomer> {
  const { data } = await api.put("/api/v1/masters/customers", payload);
  return data;
}

export interface POLineOut {
  id: string;
  part_number: string;
  customer_part_number?: string | null;
  po_qty: number;
  allocated_qty: number;
  available_qty: number;
  required_date?: string | null;
}

export interface POMasterOut {
  id: string;
  po_number: string;
  customer_code: string;
  customer_name: string;
  po_date?: string | null;
  validity_date?: string | null;
  status: string;
  lines: POLineOut[];
}

export async function getPOMasters(customerCode?: string): Promise<POMasterOut[]> {
  const { data } = await api.get("/api/v1/masters/pos", {
    params: customerCode ? { customer_code: customerCode } : undefined,
  });
  return data;
}

export async function createPOMaster(payload: {
  po_number: string;
  customer_code: string;
  po_date?: string;
  validity_date?: string;
  lines: { customer_part_number?: string; part_number?: string; po_qty: number; required_date?: string }[];
}): Promise<POMasterOut> {
  const { data } = await api.post("/api/v1/masters/pos", payload);
  return data;
}

export interface CustomerPartOut {
  customer_part_number: string;
  part_number: string;
  description?: string | null;
  grade?: string | null;
}

export async function getCustomerParts(customerCode: string): Promise<CustomerPartOut[]> {
  const { data } = await api.get("/api/v1/masters/customer-parts", { params: { customer_code: customerCode } });
  return data;
}

export interface ResolveCustomerPartResponse {
  customer_part_number: string;
  resolved: boolean;
  part_number?: string | null;
  is_new: boolean;
  message: string;
}

export async function resolveCustomerPart(customerCode: string, customerPartNumber: string): Promise<ResolveCustomerPartResponse> {
  const { data } = await api.get("/api/v1/masters/resolve-customer-part", {
    params: { customer_code: customerCode, customer_part_number: customerPartNumber },
  });
  return data;
}

export interface ScheduleOut {
  id: string;
  schedule_number: string;
  customer_code: string;
  customer_name: string;
  part_number: string;
  scheduled_qty: number;
  required_date?: string | null;
  customer_schedule_ref?: string | null;
  po_status: string;
  linked_oar_number?: string | null;
}

export async function getSchedules(customerCode?: string): Promise<ScheduleOut[]> {
  const { data } = await api.get("/api/v1/masters/schedules", {
    params: customerCode ? { customer_code: customerCode } : undefined,
  });
  return data;
}

export async function createSchedule(payload: {
  customer_code: string;
  part_number: string;
  scheduled_qty: number;
  required_date?: string;
  customer_schedule_ref?: string;
}): Promise<ScheduleOut> {
  const { data } = await api.post("/api/v1/masters/schedules", payload);
  return data;
}

// --- PO <-> Schedule Matching ---

export interface MatchCandidate {
  schedule_id: string;
  schedule_number: string;
  part_number: string;
  scheduled_qty: number;
  required_date?: string | null;
  oar_number?: string | null;
  quantity_match: "EXACT" | "PO_BELOW_SCHEDULE" | "PO_ABOVE_SCHEDULE";
  mismatch_message?: string | null;
}

export interface DuplicateCheckResult {
  has_candidate: boolean;
  candidates: MatchCandidate[];
  message?: string | null;
}

export async function checkScheduleDuplicate(customerCode: string, partNumber: string): Promise<DuplicateCheckResult> {
  const { data } = await api.get("/api/v1/po-matching/check-duplicate", {
    params: { customer_code: customerCode, part_number: partNumber },
  });
  return data;
}

export async function getMatchCandidates(poLineId: string): Promise<MatchCandidate[]> {
  const { data } = await api.get("/api/v1/po-matching/candidates", { params: { po_line_id: poLineId } });
  return data;
}

export interface MatchConfirmResponse {
  success: boolean;
  oar_number: string;
  schedule_number: string;
  po_number: string;
  quantity_match: string;
  message: string;
}

export async function confirmMatch(payload: {
  po_line_id: string;
  schedule_id: string;
  acknowledge_mismatch?: boolean;
}): Promise<MatchConfirmResponse> {
  const { data } = await api.post("/api/v1/po-matching/match", payload);
  return data;
}

export async function getOarList(params?: {
  search?: string;
  status_filter?: string;
  customer_code?: string;
  limit?: number;
  offset?: number;
}) {
  const { data } = await api.get("/api/v1/operations/oars", { params });
  return data;
}

export async function releaseWorkOrder(payload: {
  wo_number: string;
  physical_wo_qty: number;
  route_stages: string[];
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/operations/wo-release", payload);
  return data;
}

export async function createConversion(payload: {
  conversion_wo_number: string;
  source_wo_number: string;
  destination_oar_number: string;
  dest_part_number?: string;
  quantity: number;
  entry_stage: string;
  reason: string;
}) {
  const { data } = await api.post("/api/v1/operations/conversion", payload);
  return data;
}

export async function getNCRecords() {
  const { data } = await api.get("/api/v1/operations/nc");
  return data;
}

export async function createNCRecord(payload: {
  wo_number: string;
  stage: string;
  defect_code: string;
  qty: number;
  root_cause?: string;
  disposition?: string;
  responsibility?: string;
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/operations/nc", payload);
  return data;
}

export async function updateNCRecord(payload: {
  nc_number: string;
  status: string;
  root_cause?: string;
  disposition?: string;
  remarks?: string;
}) {
  const { data } = await api.put("/api/v1/operations/nc", payload);
  return data;
}

// Rejection Tracking
export async function getRejections(params?: {
  search?: string;
  wo_number?: string;
  oar_number?: string;
  part_number?: string;
  customer_code?: string;
  stage?: string;
  source_type?: string;
  status?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}) {
  const { data } = await api.get("/api/v1/rejection", { params });
  return data;
}

export async function getRejectionSummary() {
  const { data } = await api.get("/api/v1/rejection/summary");
  return data;
}

export async function getRejectionDetail(ncNumber: string) {
  const { data } = await api.get(`/api/v1/rejection/${encodeURIComponent(ncNumber)}`);
  return data;
}

export async function createExcessOrNonMoving(payload: {
  wo_number: string;
  stage?: string;
  source_type: "EXCESS_PRODUCTION" | "NON_MOVING";
  qty: number;
  reason: string;
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/rejection/excess-non-moving", payload);
  return data;
}

export async function createDisposition(payload: {
  nc_number: string;
  action: "CONVERT_PART" | "SAME_PART" | "CWO" | "SCRAP" | "DEVIATION_ACCEPT";
  quantity: number;
  destination_oar_number?: string;
  entry_stage?: string;
  conversion_wo_number?: string;
  destination_customer_code?: string;
  reason: string;
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/rejection/disposition", payload);
  return data;
}

export async function createMeltingEntry(payload: {
  disposition_id: string;
  melting_destination?: string;
  remarks?: string;
}) {
  const { data } = await api.post("/api/v1/rejection/melting-entry", payload);
  return data;
}

export async function getCWODetail(woNumber: string) {
  const { data } = await api.get(`/api/v1/rejection/cwo/${encodeURIComponent(woNumber)}`);
  return data;
}

// Conversion Part Mapping (authoritative Source Part -> Destination Part master)
export async function getConversionMappings(params?: { source_part_number?: string; active_only?: boolean }) {
  const { data } = await api.get("/api/v1/conversion-mapping", { params });
  return data;
}

export async function createConversionMapping(payload: {
  source_part_number: string;
  destination_part_number: string;
  conversion_type: "PART_TO_PART" | "SAME_PART";
  conversion_factor?: number;
  is_active?: boolean;
}) {
  const { data } = await api.post("/api/v1/conversion-mapping", payload);
  return data;
}

export async function updateConversionMapping(payload: {
  id: string;
  is_active?: boolean;
  conversion_factor?: number;
}) {
  const { data } = await api.put("/api/v1/conversion-mapping", payload);
  return data;
}

// Analytics & Mathematical KPIs & Machine Learning
export async function getPlantKPIs() {
  const { data } = await api.get("/api/v1/analytics/kpis/plant");
  return data;
}

export async function getWorkOrderKPIs(woIdentifier: string) {
  const { data } = await api.get(`/api/v1/analytics/kpis/work-order/${encodeURIComponent(woIdentifier)}`);
  return data;
}

export async function predictDelay(woNumber: string) {
  const { data } = await api.post("/api/v1/analytics/predictions/delay", { wo_number: woNumber });
  return data;
}

export async function predictRejection(payload: {
  wo_number: string;
  target_stage?: string;
  machine_id?: string;
  quantity?: number;
}) {
  const { data } = await api.post("/api/v1/analytics/predictions/rejection", payload);
  return data;
}

export async function getBottlenecks() {
  const { data } = await api.get("/api/v1/analytics/predictions/bottlenecks");
  return data;
}

export async function getProductionForecast(days: number = 7) {
  const { data } = await api.get("/api/v1/analytics/forecasts/production", { params: { days } });
  return data;
}

export async function getAnomalies() {
  const { data } = await api.get("/api/v1/analytics/anomalies");
  return data;
}

export async function getModelGovernance() {
  const { data } = await api.get("/api/v1/analytics/models/governance");
  return data;
}

export async function submitPredictionFeedback(payload: {
  wo_number: string;
  model_name: string;
  predicted_outcome: any;
  actual_outcome: any;
  notes?: string;
}) {
  const { data } = await api.post("/api/v1/analytics/feedback", payload);
  return data;
}

// AI Assistant
export async function queryAIAssistant(query: string) {
  const { data } = await api.post("/api/v1/ai/query", { query });
  return data;
}

export async function getAIInsights() {
  const { data } = await api.get("/api/v1/ai/insights");
  return data;
}

// Admin / Entities
export async function getCustomers() {
  const { data } = await api.get("/api/v1/admin/customers");
  return data;
}

export interface AdminPart {
  id: string;
  part_number: string;
  grade?: string | null;
  description?: string | null;
}

export async function getParts(): Promise<AdminPart[]> {
  const { data } = await api.get("/api/v1/admin/parts");
  return data;
}

export async function getMachines() {
  const { data } = await api.get("/api/v1/admin/machines");
  return data;
}

export async function getAuditLogs() {
  const { data } = await api.get("/api/v1/admin/audit-logs");
  return data;
}

// OMS Engine Cycles
export async function runOMSCycle(formData: FormData) {
  const { data } = await api.post("/api/v1/oms/run-cycle", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function getLatestMaster() {
  const { data } = await api.get("/api/v1/oms/latest-master");
  return data;
}

// --- Tracking & Search (read-only) ---

export interface SearchHit {
  type: "po" | "wo" | "part" | "oar" | "customer";
  id: string;
  label: string;
  sublabel?: string | null;
}

export interface UnifiedSearchResponse {
  query: string;
  pos: SearchHit[];
  wos: SearchHit[];
  parts: SearchHit[];
  oars: SearchHit[];
  customers: SearchHit[];
}

export async function unifiedSearch(q: string): Promise<UnifiedSearchResponse> {
  const { data } = await api.get("/api/v1/tracking/search", { params: { q } });
  return data;
}

export interface PageMeta {
  total: number;
  limit: number;
  offset: number;
}

export interface POTrackingListItem {
  po_id: string;
  po_number: string;
  customer_code: string;
  customer_name: string;
  status: string;
  po_date?: string | null;
  validity_date?: string | null;
  total_po_qty: number;
  total_allocated_qty: number;
  line_count: number;
}

export interface POTrackingLineWO {
  wo_number: string;
  oar_number?: string | null;
  current_stage: string;
  wo_status: string;
  ok_completed: number;
  rejected: number;
  available_wip: number;
  packing_status?: string | null;
  dispatched_qty: number;
}

export interface POTrackingLine {
  line_id: string;
  part_number: string;
  po_qty: number;
  allocated_qty: number;
  available_qty: number;
  required_date?: string | null;
  linked_oars: string[];
  work_orders: POTrackingLineWO[];
}

export interface POTrackingDetail {
  po_id: string;
  po_number: string;
  customer_code: string;
  customer_name: string;
  status: string;
  po_date?: string | null;
  validity_date?: string | null;
  lines: POTrackingLine[];
  total_po_qty: number;
  total_allocated_qty: number;
  total_remaining_qty: number;
}

export async function searchPOTracking(params: {
  po_number?: string; customer?: string; part_number?: string; oar_number?: string;
  status?: string; required_date?: string; limit?: number; offset?: number;
}): Promise<POTrackingListItem[]> {
  const { data } = await api.get("/api/v1/tracking/po", { params });
  return data;
}

export async function getPOTrackingMeta(params: Record<string, any>): Promise<PageMeta> {
  const { data } = await api.get("/api/v1/tracking/po/meta", { params });
  return data;
}

export async function getPOTrackingDetail(poNumber: string): Promise<POTrackingDetail> {
  const { data } = await api.get(`/api/v1/tracking/po/${encodeURIComponent(poNumber)}`);
  return data;
}

export interface WOTrackingListItem {
  wo_number: string;
  oar_number?: string | null;
  customer_po?: string | null;
  customer_code: string;
  customer_name: string;
  part_number: string;
  current_stage: string;
  status: string;
  physical_wo_qty: number;
}

export interface WORejectionHistoryItem {
  nc_number: string;
  stage?: string | null;
  defect_code?: string | null;
  qty: number;
  status: string;
  date_raised?: string | null;
  date_closed?: string | null;
}

export async function searchWOTracking(params: {
  wo_number?: string; oar_number?: string; po_number?: string; part_number?: string;
  customer?: string; current_stage?: string; status?: string; limit?: number; offset?: number;
}): Promise<WOTrackingListItem[]> {
  const { data } = await api.get("/api/v1/tracking/wo", { params });
  return data;
}

export async function getWOTrackingMeta(params: Record<string, any>): Promise<PageMeta> {
  const { data } = await api.get("/api/v1/tracking/wo/meta", { params });
  return data;
}

export async function getWORejectionHistory(woIdentifier: string): Promise<WORejectionHistoryItem[]> {
  const { data } = await api.get(`/api/v1/tracking/wo/${encodeURIComponent(woIdentifier)}/rejections`);
  return data;
}

export interface PartTrackingListItem {
  part_number: string;
  description?: string | null;
  grade?: string | null;
  wo_count: number;
  customer_count: number;
}

export interface PartWOBreakdown {
  wo_number: string;
  oar_number?: string | null;
  customer_code: string;
  customer_name: string;
  physical_wo_qty: number;
  current_stage: string;
  wo_status: string;
  ok_completed: number;
  rejected: number;
  available_wip: number;
  packing_status?: string | null;
  dispatched_qty: number;
}

export interface PartTrackingDetail {
  part_number: string;
  description?: string | null;
  grade?: string | null;
  customers: string[];
  active_po_lines: POTrackingLine[];
  schedules: string[];
  oars: string[];
  work_orders: PartWOBreakdown[];
}

export async function searchPartTracking(params: {
  part_number?: string; description?: string; limit?: number; offset?: number;
}): Promise<PartTrackingListItem[]> {
  const { data } = await api.get("/api/v1/tracking/part", { params });
  return data;
}

export async function getPartTrackingMeta(params: Record<string, any>): Promise<PageMeta> {
  const { data } = await api.get("/api/v1/tracking/part/meta", { params });
  return data;
}

export async function getPartTrackingDetail(partNumber: string): Promise<PartTrackingDetail> {
  const { data } = await api.get(`/api/v1/tracking/part/${encodeURIComponent(partNumber)}`);
  return data;
}

export interface OARTrackingDetail {
  oar_number: string;
  customer_code: string;
  customer_name: string;
  source_type: string;
  customer_po: string;
  matched_po_number?: string | null;
  schedule_number?: string | null;
  oar_po_status?: string | null;
  part_number: string;
  oar_qty: number;
  allocated_qty: number;
  remaining_qty: number;
  status: string;
  work_orders: POTrackingLineWO[];
}

export async function getOARTrackingDetail(oarNumber: string): Promise<OARTrackingDetail> {
  const { data } = await api.get(`/api/v1/tracking/oar/${encodeURIComponent(oarNumber)}`);
  return data;
}

export interface CustomerTrackingDetail {
  customer_code: string;
  customer_name: string;
  is_active: boolean;
  active_pos: POTrackingListItem[];
  schedules: string[];
  oars: string[];
  work_orders: WOTrackingListItem[];
  parts: string[];
}

export async function getCustomerTrackingDetail(customerCode: string): Promise<CustomerTrackingDetail> {
  const { data } = await api.get(`/api/v1/tracking/customer/${encodeURIComponent(customerCode)}`);
  return data;
}

// Report / file downloads. A plain `<a href download>` never sends the
// Authorization header this API requires (there is no cookie-based auth), so every
// protected download must go through this authenticated blob fetch instead.
export async function downloadFile(url: string, filename: string): Promise<void> {
  const { data } = await api.get(url, { responseType: "blob" });
  const blobUrl = window.URL.createObjectURL(data as Blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(blobUrl);
}

// Heat Number & Traceability
export interface Heat {
  id: string;
  heat_number: string;
  grade: string;
  melt_date?: string | null;
  status: string;
  tc_number?: string | null;
  supplier_or_foundry?: string | null;
  remarks?: string | null;
  created_at: string;
  total_allocated_qty: number;
}

export interface HeatCreatePayload {
  heat_number: string;
  grade: string;
  melt_date?: string | null;
  status?: string;
  tc_number?: string | null;
  supplier_or_foundry?: string | null;
  remarks?: string | null;
}

export interface HeatAllocationItem {
  id: string;
  heat_number: string;
  grade: string;
  tc_number?: string | null;
  allocated_qty: number;
  stage: string;
  allocated_at: string;
  allocated_by?: string | null;
  remarks?: string | null;
}

export interface StageTraceabilityItem {
  stage: string;
  sequence: number;
  target_qty: number;
  ok_qty: number;
  rejected_qty: number;
  inproc_qty: number;
  onhand_qty: number;
  status: string;
}

export interface DispatchTraceabilityItem {
  invoice_number: string;
  dispatched_qty: number;
  dispatch_date?: string | null;
  customer_po?: string | null;
}

export interface WOTraceability {
  wo_number: string;
  oar_number?: string | null;
  customer_code?: string | null;
  customer_name?: string | null;
  customer_po?: string | null;
  part_number?: string | null;
  part_description?: string | null;
  grade?: string | null;
  physical_wo_qty: number;
  current_stage: string;
  status: string;
  heats: HeatAllocationItem[];
  total_heat_allocated_qty: number;
  stage_progression: StageTraceabilityItem[];
  dispatches: DispatchTraceabilityItem[];
}

export async function getHeats(params?: { grade?: string; status?: string; search?: string }): Promise<Heat[]> {
  const { data } = await api.get("/api/v1/heats", { params });
  return data;
}

export async function createHeat(payload: HeatCreatePayload): Promise<Heat> {
  const { data } = await api.post("/api/v1/heats", payload);
  return data;
}

export async function getWOTraceability(woNumber: string): Promise<WOTraceability> {
  const { data } = await api.get(`/api/v1/work-orders/${encodeURIComponent(woNumber)}/traceability`);
  return data;
}

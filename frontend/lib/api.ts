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
}> {
  const { data } = await api.get("/api/v1/auth/me");
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
  wo_quantities?: number[];
}) {
  const { data } = await api.post("/api/v1/operations/intake", payload);
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

export async function getParts() {
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

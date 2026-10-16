"use client";
import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  Truck,
  Search,
  CheckCircle2,
  AlertTriangle,
  Download,
  FileText,
  RefreshCw,
  ArrowRight,
  ShieldCheck,
  Building,
  Calendar,
  CreditCard,
  RotateCcw,
  Receipt,
  Plus,
  ExternalLink,
  DollarSign,
  AlertCircle
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge, getRAGVariant } from "@/app/components/ui/Badge";
import { Modal } from "@/app/components/ui/Modal";
import {
  getDispatchQueue,
  executeDispatch,
  getDispatchHistory,
  updateInvoicePayment,
  lookupProductPricing,
  createCustomerReturn,
  getCustomerReturns,
  DispatchItem,
  CustomerReturnItem,
  API_BASE,
} from "@/lib/api";

export default function DispatchPage() {
  const [activeTab, setActiveTab] = useState<"queue" | "history" | "returns">("queue");
  const [queue, setQueue] = useState<any[]>([]);
  const [history, setHistory] = useState<DispatchItem[]>([]);
  const [returns, setReturns] = useState<CustomerReturnItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");

  // Dispatch Action Modal
  const [selectedItem, setSelectedItem] = useState<any>(null);
  const [invoiceNo, setInvoiceNo] = useState("");
  const [dispatchQty, setDispatchQty] = useState<number | "">("");
  const [unitPrice, setUnitPrice] = useState<number | "">("");
  const [vehicleNo, setVehicleNo] = useState("");
  const [transporter, setTransporter] = useState("");
  const [remarks, setRemarks] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [modalError, setModalError] = useState("");
  const [dispatchSuccess, setDispatchSuccess] = useState<any>(null);

  // Payment Tracking Modal
  const [paymentItem, setPaymentItem] = useState<DispatchItem | null>(null);
  const [paymentStatus, setPaymentStatus] = useState<string>("UNPAID");
  const [paidAmount, setPaidAmount] = useState<number | "">("");
  const [paymentRef, setPaymentRef] = useState<string>("");
  const [paymentDate, setPaymentDate] = useState<string>("");
  const [paymentRemarks, setPaymentRemarks] = useState<string>("");
  const [submittingPayment, setSubmittingPayment] = useState(false);
  const [paymentError, setPaymentError] = useState("");
  const [paymentSuccess, setPaymentSuccess] = useState("");

  // Customer Return / Complaint Modal
  const [showReturnModal, setShowReturnModal] = useState(false);
  const [retCustomerCode, setRetCustomerCode] = useState("");
  const [retCustomerName, setRetCustomerName] = useState("");
  const [retCustomerPo, setRetCustomerPo] = useState("");
  const [retInvoiceNo, setRetInvoiceNo] = useState("");
  const [retOriginalWo, setRetOriginalWo] = useState("");
  const [retPartNumber, setRetPartNumber] = useState("");
  const [retQty, setRetQty] = useState<number | "">("");
  const [retUnitPrice, setRetUnitPrice] = useState<number | "">("");
  const [retPriceSource, setRetPriceSource] = useState<string>("");
  const [retComplaintReason, setRetComplaintReason] = useState("");
  const [retEntryStage, setRetEntryStage] = useState("F1");
  const [retConversionWo, setRetConversionWo] = useState("");
  const [retDestinationOar, setRetDestinationOar] = useState("");
  const [submittingReturn, setSubmittingReturn] = useState(false);
  const [returnModalError, setReturnModalError] = useState("");
  const [returnSuccessMsg, setReturnSuccessMsg] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError("");
    try {
      const [qData, hData, rData] = await Promise.all([
        getDispatchQueue(),
        getDispatchHistory(),
        getCustomerReturns().catch(() => []),
      ]);
      setQueue(qData);
      setHistory(hData);
      setReturns(rData);
    } catch (err: any) {
      setError("Failed to fetch dispatch records from server.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openShipModal = async (item: any) => {
    setSelectedItem(item);
    setDispatchQty("");
    const invCount = history.length + 1;
    setInvoiceNo(`INV-2026-${String(invCount).padStart(4, "0")}`);
    setVehicleNo("KA-04-E-8821");
    setTransporter("VRL Logistics Express");
    setRemarks("");
    setModalError("");

    // Auto-fetch price from PO
    try {
      const pricing = await lookupProductPricing({
        customer_code: item.customer_code,
        part_number: item.part_number,
        wo_number: item.wo_number,
      });
      if (pricing && pricing.unit_price > 0) {
        setUnitPrice(pricing.unit_price);
      } else {
        setUnitPrice("");
      }
    } catch {
      setUnitPrice("");
    }
  };

  const handleShipSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedItem) return;

    const qty = Number(dispatchQty);
    if (qty <= 0) {
      setModalError("Please enter a valid dispatch quantity (> 0).");
      return;
    }

    if (qty > selectedItem.ready_for_dispatch_qty) {
      setModalError(
        `Cannot dispatch ${qty} pieces. Only ${selectedItem.ready_for_dispatch_qty} pieces are ready for dispatch after Packing / BSR for WO ${selectedItem.wo_number}.`
      );
      return;
    }

    if (!invoiceNo.trim()) {
      setModalError("Invoice Number is mandatory for dispatch.");
      return;
    }

    setSubmitting(true);
    setModalError("");

    try {
      const res = await executeDispatch({
        wo_number: selectedItem.wo_number,
        invoice_number: invoiceNo.trim(),
        dispatched_quantity: qty,
        unit_price: unitPrice !== "" ? Number(unitPrice) : undefined,
        customer_po: selectedItem.customer_po,
        vehicle_number: vehicleNo,
        transporter: transporter,
        remarks: remarks,
      });

      setDispatchSuccess(res);
      setSelectedItem(null);
      loadData();
    } catch (err: any) {
      setModalError(err?.response?.data?.detail || "Dispatch validation failed.");
    } finally {
      setSubmitting(false);
    }
  };

  const openPaymentModal = (item: DispatchItem) => {
    setPaymentItem(item);
    setPaymentStatus(item.payment_status || "UNPAID");
    const fallbackAmount = item.payment_status === "PAID" ? (item.total_invoice_value ?? 0) : 0;
    setPaidAmount(item.paid_amount ?? fallbackAmount);
    setPaymentRef(item.payment_reference || "");
    setPaymentRemarks(item.payment_remarks || "");
    setPaymentDate(item.payment_date ? item.payment_date.substring(0, 10) : new Date().toISOString().substring(0, 10));
    setPaymentError("");
  };

  const handlePaymentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!paymentItem) return;

    setSubmittingPayment(true);
    setPaymentError("");

    try {
      await updateInvoicePayment(paymentItem.id, {
        payment_status: paymentStatus,
        paid_amount: paidAmount !== "" ? Number(paidAmount) : 0,
        payment_reference: paymentRef.trim() || undefined,
        payment_remarks: paymentRemarks.trim() || undefined,
        payment_date: paymentDate ? new Date(paymentDate).toISOString() : undefined,
      });

      setPaymentSuccess(`Payment details for invoice ${paymentItem.invoice_number} successfully updated.`);
      setPaymentItem(null);
      loadData();
    } catch (err: any) {
      setPaymentError(err?.response?.data?.detail || "Failed to update payment status.");
    } finally {
      setSubmittingPayment(false);
    }
  };

  const openNewReturnModal = async (fromInvoice?: DispatchItem) => {
    setReturnModalError("");
    if (fromInvoice) {
      setRetCustomerCode(fromInvoice.customer_code || "");
      setRetCustomerName(fromInvoice.customer_name || "");
      setRetCustomerPo(fromInvoice.customer_po || "");
      setRetInvoiceNo(fromInvoice.invoice_number || "");
      setRetOriginalWo(fromInvoice.wo_number || "");
      setRetPartNumber(fromInvoice.part_number || "");
      setRetQty("");
      setRetUnitPrice(fromInvoice.unit_price || "");
      setRetPriceSource(fromInvoice.unit_price ? "Dispatch Invoice" : "");
    } else {
      setRetCustomerCode("");
      setRetCustomerName("");
      setRetCustomerPo("");
      setRetInvoiceNo("");
      setRetOriginalWo("");
      setRetPartNumber("");
      setRetQty("");
      setRetUnitPrice("");
      setRetPriceSource("");
    }
    setRetComplaintReason("");
    setRetEntryStage("F1");
    setRetConversionWo("");
    setRetDestinationOar("");
    setShowReturnModal(true);
  };

  const fetchPricingForReturn = async (custCode?: string, partNo?: string, woNo?: string) => {
    const c = custCode ?? retCustomerCode;
    const p = partNo ?? retPartNumber;
    const w = woNo ?? retOriginalWo;
    if (!c && !p && !w) return;

    try {
      const res = await lookupProductPricing({
        customer_code: c || undefined,
        part_number: p || undefined,
        wo_number: w || undefined,
      });
      if (res && res.unit_price > 0) {
        setRetUnitPrice(res.unit_price);
        setRetPriceSource(res.source || "PO Master");
      }
    } catch {
      // Keep existing
    }
  };

  const handleReturnSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const qty = Number(retQty);
    if (!qty || qty <= 0) {
      setReturnModalError("Please enter a valid returned quantity (> 0).");
      return;
    }
    if (!retComplaintReason.trim()) {
      setReturnModalError("Customer complaint reason is mandatory.");
      return;
    }
    if (!retCustomerCode.trim() || !retPartNumber.trim()) {
      setReturnModalError("Customer Code and Part Number are mandatory.");
      return;
    }

    setSubmittingReturn(true);
    setReturnModalError("");

    try {
      const res = await createCustomerReturn({
        customer_code: retCustomerCode.trim(),
        customer_name: retCustomerName.trim() || undefined,
        customer_po: retCustomerPo.trim() || undefined,
        invoice_number: retInvoiceNo.trim() || undefined,
        original_wo_number: retOriginalWo.trim() || undefined,
        part_number: retPartNumber.trim(),
        returned_qty: qty,
        unit_price: retUnitPrice !== "" ? Number(retUnitPrice) : undefined,
        complaint_reason: retComplaintReason.trim(),
        entry_stage: retEntryStage || "F1",
        conversion_wo_number: retConversionWo.trim() || undefined,
        destination_oar_number: retDestinationOar.trim() || undefined,
      });

      setReturnSuccessMsg(
        `Customer Return logged! Generated Return #${res.return_number} and created Conversion Work Order ${res.conversion_wo_number} replacing quantity (${qty} pcs credited to ${res.entry_stage}).`
      );
      setShowReturnModal(false);
      setActiveTab("returns");
      loadData();
    } catch (err: any) {
      setReturnModalError(err?.response?.data?.detail || "Failed to process customer return.");
    } finally {
      setSubmittingReturn(false);
    }
  };

  const filteredHistory = history.filter((h) => {
    if (!search.trim()) return true;
    const s = search.toLowerCase();
    return (
      h.invoice_number?.toLowerCase().includes(s) ||
      h.wo_number?.toLowerCase().includes(s) ||
      h.customer_name?.toLowerCase().includes(s) ||
      h.customer_code?.toLowerCase().includes(s) ||
      h.part_number?.toLowerCase().includes(s) ||
      h.payment_status?.toLowerCase().includes(s)
    );
  });

  const filteredReturns = returns.filter((r) => {
    if (!search.trim()) return true;
    const s = search.toLowerCase();
    return (
      r.return_number?.toLowerCase().includes(s) ||
      r.customer_name?.toLowerCase().includes(s) ||
      r.customer_code?.toLowerCase().includes(s) ||
      r.part_number?.toLowerCase().includes(s) ||
      r.conversion_wo_number?.toLowerCase().includes(s) ||
      r.complaint_reason?.toLowerCase().includes(s)
    );
  });

  const getPaymentBadge = (status?: string) => {
    switch (status) {
      case "PAID":
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-400">● PAID</span>;
      case "PARTIALLY_PAID":
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-400">◐ PARTIAL</span>;
      case "OVERDUE":
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-800 dark:bg-purple-950/60 dark:text-purple-400">▲ OVERDUE</span>;
      default:
        return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800 dark:bg-rose-950/60 dark:text-rose-400">○ UNPAID</span>;
    }
  };

  // Quick aggregates
  const totalReturnQty = returns.reduce((acc, r) => acc + (r.returned_qty || 0), 0);
  const totalReturnValue = returns.reduce((acc, r) => acc + (r.total_return_value || 0), 0);

  return (
    <AppShell>
      <div className="space-y-6">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
                Final Gate / Outward Bay
              </span>
              <span className="text-xs text-zinc-400">Invoice Tracking & Returns Conversion</span>
            </div>
            <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
              Dispatch, Invoicing & Customer Returns
            </h1>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              Execute shipments against verified packing inventory, manage invoice payment realization, and convert customer returns into rework Work Orders.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => openNewReturnModal()}
              className="flex items-center gap-1.5 rounded-xl border border-rose-200 dark:border-rose-900/40 bg-rose-50 dark:bg-rose-950/30 px-3.5 py-2 text-xs font-bold text-rose-700 dark:text-rose-300 hover:bg-rose-100 dark:hover:bg-rose-900/50 transition-colors shadow-sm"
            >
              <RotateCcw className="h-3.5 w-3.5 text-rose-600" />
              <span>Log Customer Return</span>
            </button>
            <a
              href={`${API_BASE}/api/v1/reports/export/dispatch-csv`}
              download
              className="flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 px-3.5 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors shadow-sm"
            >
              <Download className="h-3.5 w-3.5 text-blue-600" />
              <span>Export CSV</span>
            </a>
            <button
              onClick={loadData}
              disabled={loading}
              className="flex items-center gap-1.5 rounded-xl bg-blue-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-blue-500 transition-colors"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              <span>Refresh</span>
            </button>
          </div>
        </div>

        {/* Tab Toggle */}
        <div className="flex items-center gap-2 border-b border-zinc-200 dark:border-zinc-800 pb-2">
          <button
            type="button"
            onClick={() => setActiveTab("queue")}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-lg transition-colors ${
              activeTab === "queue"
                ? "bg-blue-600 text-white shadow-xs"
                : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <Truck className="h-4 w-4" />
            <span>Ready for Dispatch Queue ({queue.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("history")}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-lg transition-colors ${
              activeTab === "history"
                ? "bg-blue-600 text-white shadow-xs"
                : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <Receipt className="h-4 w-4" />
            <span>Invoices & Payment Realization ({history.length})</span>
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("returns")}
            className={`flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-lg transition-colors ${
              activeTab === "returns"
                ? "bg-rose-600 text-white shadow-xs"
                : "text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            }`}
          >
            <RotateCcw className="h-4 w-4" />
            <span>Customer Complaints & Returns ({returns.length})</span>
          </button>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Success Alerts */}
        {dispatchSuccess && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-center justify-between text-xs text-emerald-700 dark:text-emerald-300">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              <span className="font-bold">{dispatchSuccess.message}</span>
            </div>
            <button
              onClick={() => setDispatchSuccess(null)}
              className="text-zinc-400 hover:text-zinc-600 text-xs font-semibold"
            >
              Dismiss
            </button>
          </div>
        )}

        {paymentSuccess && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-center justify-between text-xs text-emerald-700 dark:text-emerald-300">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              <span className="font-bold">{paymentSuccess}</span>
            </div>
            <button
              onClick={() => setPaymentSuccess("")}
              className="text-zinc-400 hover:text-zinc-600 text-xs font-semibold"
            >
              Dismiss
            </button>
          </div>
        )}

        {returnSuccessMsg && (
          <div className="rounded-2xl border border-emerald-500/30 bg-emerald-500/10 p-4 flex items-center justify-between text-xs text-emerald-700 dark:text-emerald-300">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-emerald-500" />
              <span className="font-bold">{returnSuccessMsg}</span>
            </div>
            <button
              onClick={() => setReturnSuccessMsg("")}
              className="text-zinc-400 hover:text-zinc-600 text-xs font-semibold"
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Tab 1: Ready Queue */}
        {activeTab === "queue" && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                  <tr>
                    <th className="py-3 px-3">Work Order</th>
                    <th className="py-3 px-3">Customer Code</th>
                    <th className="py-3 px-3">Customer Name</th>
                    <th className="py-3 px-3">Customer PO</th>
                    <th className="py-3 px-3">Part Number</th>
                    <th className="py-3 px-3 text-right">Order Qty</th>
                    <th className="py-3 px-3 text-right font-extrabold text-emerald-600">Ready for Dispatch</th>
                    <th className="py-3 px-3 text-right text-zinc-400">Already Shipped</th>
                    <th className="py-3 px-3 text-center">Action</th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                  {queue.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-zinc-400 text-xs">
                        No goods currently in the Ready for Dispatch queue. Complete Packing / BSR first.
                      </td>
                    </tr>
                  ) : (
                    queue.map((item) => (
                      <tr key={item.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                        <td className="py-3 px-3 font-mono font-bold">
                          <Link
                            href={`/production/tracking?wo=${item.wo_number}`}
                            className="text-blue-600 dark:text-blue-400 hover:underline"
                          >
                            {item.wo_number}
                          </Link>
                        </td>
                        <td className="py-3 px-3 font-mono text-zinc-500">{item.customer_code}</td>
                        <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300 truncate max-w-[150px]">
                          {item.customer_name}
                        </td>
                        <td className="py-3 px-3 font-mono text-zinc-700 dark:text-zinc-300">{item.customer_po}</td>
                        <td className="py-3 px-3 font-semibold text-zinc-900 dark:text-zinc-100">{item.part_number}</td>
                        <td className="py-3 px-3 text-right text-zinc-500 font-mono">{item.order_qty} pcs</td>
                        <td className="py-3 px-3 text-right font-mono font-extrabold text-emerald-600 dark:text-emerald-400 text-sm">
                          {item.ready_for_dispatch_qty} pcs
                        </td>
                        <td className="py-3 px-3 text-right text-zinc-400 font-mono">{item.already_dispatched_qty} pcs</td>
                        <td className="py-3 px-3 text-center">
                          <button
                            type="button"
                            onClick={() => openShipModal(item)}
                            disabled={item.ready_for_dispatch_qty <= 0}
                            className="rounded-lg bg-emerald-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-xs hover:bg-emerald-500 disabled:opacity-30 transition-colors"
                          >
                            Ship Goods
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Tab 2: Dispatch Invoices & Payment Realization */}
        {activeTab === "history" && (
          <div className="space-y-4">
            <div className="flex items-center justify-between gap-4">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-zinc-400" />
                <input
                  type="text"
                  placeholder="Filter invoices, WO, customer, part, payment..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-9 pr-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-blue-500"
                />
              </div>
              <div className="text-xs text-zinc-500">
                Showing <span className="font-bold text-zinc-900 dark:text-zinc-100">{filteredHistory.length}</span> invoices
              </div>
            </div>

            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                    <tr>
                      <th className="py-3 px-3">Invoice Number</th>
                      <th className="py-3 px-3">Dispatch Date</th>
                      <th className="py-3 px-3">Work Order</th>
                      <th className="py-3 px-3">Customer</th>
                      <th className="py-3 px-3">Part Number</th>
                      <th className="py-3 px-3 text-right">Dispatched Qty</th>
                      <th className="py-3 px-3 text-right">Price / Pc</th>
                      <th className="py-3 px-3 text-right font-extrabold text-zinc-900 dark:text-zinc-100">Total Value</th>
                      <th className="py-3 px-3 text-center">Payment Status</th>
                      <th className="py-3 px-3 text-right">Paid Amount</th>
                      <th className="py-3 px-3 text-center">Actions</th>
                    </tr>
                  </thead>

                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                    {filteredHistory.length === 0 ? (
                      <tr>
                        <td colSpan={11} className="py-8 text-center text-zinc-400 text-xs">
                          No matching dispatch invoices found.
                        </td>
                      </tr>
                    ) : (
                      filteredHistory.map((h) => {
                        const invValue = h.total_invoice_value || (h.dispatched_qty * (h.unit_price || 0));
                        return (
                          <tr key={h.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                            <td className="py-3 px-3 font-mono font-bold text-emerald-600 dark:text-emerald-400">
                              {h.invoice_number}
                            </td>
                            <td className="py-3 px-3 text-zinc-500">{h.dispatch_date?.substring(0, 10)}</td>
                            <td className="py-3 px-3 font-mono font-bold text-zinc-900 dark:text-zinc-100">
                              <Link href={`/production/tracking?wo=${h.wo_number}`} className="hover:underline">
                                {h.wo_number}
                              </Link>
                            </td>
                            <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300">
                              <div>{h.customer_name}</div>
                              <div className="text-[10px] text-zinc-400 font-mono">{h.customer_po}</div>
                            </td>
                            <td className="py-3 px-3 font-semibold text-zinc-900 dark:text-zinc-100">{h.part_number}</td>
                            <td className="py-3 px-3 text-right font-mono font-bold text-emerald-600">
                              {h.dispatched_qty} pcs
                            </td>
                            <td className="py-3 px-3 text-right font-mono text-zinc-600 dark:text-zinc-400">
                              ₹{(h.unit_price || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                            </td>
                            <td className="py-3 px-3 text-right font-mono font-bold text-zinc-900 dark:text-zinc-100">
                              ₹{invValue.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                            </td>
                            <td className="py-3 px-3 text-center">
                              {getPaymentBadge(h.payment_status)}
                              {h.payment_reference && (
                                <div className="text-[9px] text-zinc-400 truncate max-w-[100px] mx-auto mt-0.5" title={h.payment_reference}>
                                  Ref: {h.payment_reference}
                                </div>
                              )}
                            </td>
                            <td className="py-3 px-3 text-right font-mono text-zinc-600 dark:text-zinc-300">
                              ₹{(h.paid_amount || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                            </td>
                            <td className="py-3 px-3 text-center">
                              <div className="flex items-center justify-center gap-1.5">
                                <button
                                  type="button"
                                  onClick={() => openPaymentModal(h)}
                                  className="rounded-lg bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900/40 px-2.5 py-1 text-[11px] font-bold text-blue-700 dark:text-blue-300 hover:bg-blue-100 transition-colors"
                                  title="Update invoice payment status"
                                >
                                  Update Payment
                                </button>
                                <button
                                  type="button"
                                  onClick={() => openNewReturnModal(h)}
                                  className="rounded-lg bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/40 px-2 py-1 text-[11px] font-bold text-rose-700 dark:text-rose-300 hover:bg-rose-100 transition-colors"
                                  title="Customer Complaint / Return"
                                >
                                  Return
                                </button>
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Tab 3: Customer Complaints & Returns */}
        {activeTab === "returns" && (
          <div className="space-y-4">
            {/* Summary Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
                <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Total Complaints Logged</div>
                <div className="mt-1 text-2xl font-extrabold text-zinc-900 dark:text-zinc-50 font-mono">
                  {returns.length}
                </div>
              </div>
              <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
                <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Total Quantity Returned</div>
                <div className="mt-1 text-2xl font-extrabold text-rose-600 dark:text-rose-400 font-mono">
                  {totalReturnQty.toLocaleString()} <span className="text-sm font-normal text-zinc-500">pcs</span>
                </div>
              </div>
              <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-4">
                <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Total Return Value</div>
                <div className="mt-1 text-2xl font-extrabold text-amber-600 dark:text-amber-400 font-mono">
                  ₹{totalReturnValue.toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>

            <div className="flex items-center justify-between gap-4">
              <div className="relative flex-1 max-w-sm">
                <Search className="absolute left-3 top-2.5 h-3.5 w-3.5 text-zinc-400" />
                <input
                  type="text"
                  placeholder="Filter returns by return #, customer, WO, part, reason..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 pl-9 pr-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-rose-500"
                />
              </div>
              <button
                type="button"
                onClick={() => openNewReturnModal()}
                className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-3.5 py-2 text-xs font-bold text-white shadow-sm hover:bg-rose-500 transition-colors"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Log New Customer Return</span>
              </button>
            </div>

            <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-400 uppercase text-[10px] font-bold">
                    <tr>
                      <th className="py-3 px-3">Return #</th>
                      <th className="py-3 px-3">Date</th>
                      <th className="py-3 px-3">Customer</th>
                      <th className="py-3 px-3">Part Number</th>
                      <th className="py-3 px-3">Orig. WO / Inv</th>
                      <th className="py-3 px-3 text-right text-rose-600 font-extrabold">Returned Qty</th>
                      <th className="py-3 px-3 text-right">Selling Price</th>
                      <th className="py-3 px-3 text-right font-extrabold">Total Return Value</th>
                      <th className="py-3 px-3">Complaint Reason</th>
                      <th className="py-3 px-3">Conversion WO</th>
                      <th className="py-3 px-3">Entry Stage</th>
                      <th className="py-3 px-3">Status</th>
                    </tr>
                  </thead>

                  <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/60 font-medium">
                    {filteredReturns.length === 0 ? (
                      <tr>
                        <td colSpan={12} className="py-8 text-center text-zinc-400 text-xs">
                          No customer returns logged yet. Use "Log Customer Return" to record complaints and route to Conversion.
                        </td>
                      </tr>
                    ) : (
                      filteredReturns.map((r) => (
                        <tr key={r.id} className="hover:bg-zinc-50/50 dark:hover:bg-zinc-800/40">
                          <td className="py-3 px-3 font-mono font-bold text-rose-600 dark:text-rose-400">
                            {r.return_number}
                          </td>
                          <td className="py-3 px-3 text-zinc-500">{r.complaint_date?.substring(0, 10)}</td>
                          <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300">
                            <div>{r.customer_name}</div>
                            <div className="text-[10px] text-zinc-400 font-mono">{r.customer_code}</div>
                          </td>
                          <td className="py-3 px-3 font-semibold text-zinc-900 dark:text-zinc-100">{r.part_number}</td>
                          <td className="py-3 px-3 font-mono text-[11px] text-zinc-500">
                            <div>WO: {r.original_wo_number || "—"}</div>
                            <div>Inv: {r.invoice_number || "—"}</div>
                          </td>
                          <td className="py-3 px-3 text-right font-mono font-bold text-rose-600">
                            {r.returned_qty} pcs
                          </td>
                          <td className="py-3 px-3 text-right font-mono text-zinc-600 dark:text-zinc-400">
                            ₹{(r.unit_price || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="py-3 px-3 text-right font-mono font-bold text-zinc-900 dark:text-zinc-100">
                            ₹{(r.total_return_value || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                          </td>
                          <td className="py-3 px-3 text-zinc-700 dark:text-zinc-300 max-w-[200px] truncate" title={r.complaint_reason}>
                            {r.complaint_reason}
                          </td>
                          <td className="py-3 px-3 font-mono font-bold">
                            <Link
                              href={`/production/tracking?wo=${r.conversion_wo_number}`}
                              className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:underline"
                            >
                              <span>{r.conversion_wo_number}</span>
                              <ExternalLink className="h-3 w-3" />
                            </Link>
                          </td>
                          <td className="py-3 px-3 font-mono font-bold text-emerald-600">
                            {r.entry_stage}
                          </td>
                          <td className="py-3 px-3">
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-100 text-blue-800 dark:bg-blue-950/60 dark:text-blue-300">
                              {r.status}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}

        {/* Ship Goods Modal */}
        <Modal
          isOpen={!!selectedItem}
          onClose={() => setSelectedItem(null)}
          title={`Generate Invoice & Dispatch Goods — ${selectedItem?.wo_number}`}
          subtitle={`Customer: ${selectedItem?.customer_name} | Ready for Dispatch: ${selectedItem?.ready_for_dispatch_qty} pcs`}
        >
          <form onSubmit={handleShipSubmit} className="space-y-4">
            {modalError && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                {modalError}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Invoice Number *
                </label>
                <input
                  type="text"
                  required
                  value={invoiceNo}
                  onChange={(e) => setInvoiceNo(e.target.value)}
                  placeholder="e.g. INV-2026-0082"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:border-emerald-500 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                  <span>Dispatch Qty (pcs) *</span>
                  <span className="text-[10px] text-zinc-400">Max: {selectedItem?.ready_for_dispatch_qty}</span>
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  max={selectedItem?.ready_for_dispatch_qty}
                  value={dispatchQty}
                  onChange={(e) => setDispatchQty(e.target.value === "" ? "" : Number(e.target.value))}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-extrabold text-emerald-600 focus:border-emerald-500 focus:outline-none"
                />
              </div>
            </div>

            {/* Pricing Section */}
            <div className="grid grid-cols-2 gap-3 p-3 bg-zinc-50 dark:bg-zinc-900/60 rounded-xl border border-zinc-200/60 dark:border-zinc-800/60">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                  <span>Selling Price / Pc (₹)</span>
                  <span className="text-[10px] text-blue-600">From PO</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={unitPrice}
                  onChange={(e) => setUnitPrice(e.target.value === "" ? "" : Number(e.target.value))}
                  placeholder="0.00"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Total Calculated Invoice Value
                </label>
                <div className="mt-1.5 px-3 py-2 text-sm font-mono font-extrabold text-emerald-600 bg-white dark:bg-zinc-950 rounded-xl border border-zinc-200 dark:border-zinc-800">
                  ₹{((Number(dispatchQty) || 0) * (Number(unitPrice) || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Vehicle Number
                </label>
                <input
                  type="text"
                  value={vehicleNo}
                  onChange={(e) => setVehicleNo(e.target.value)}
                  placeholder="e.g. KA-01-AB-1234"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Transporter / Logistics
                </label>
                <input
                  type="text"
                  value={transporter}
                  onChange={(e) => setTransporter(e.target.value)}
                  placeholder="e.g. VRL Logistics / Direct Truck"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                Dispatch Remarks / E-Way Bill No
              </label>
              <input
                type="text"
                value={remarks}
                onChange={(e) => setRemarks(e.target.value)}
                placeholder="e.g. E-Way Bill generated, dispatched to customer central warehouse"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setSelectedItem(null)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !dispatchQty || !invoiceNo}
                className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-500 disabled:opacity-50 transition-colors"
              >
                <Truck className="h-4 w-4" />
                <span>{submitting ? "Processing..." : "Confirm & Finalize Dispatch"}</span>
              </button>
            </div>
          </form>
        </Modal>

        {/* Payment Tracking Modal */}
        <Modal
          isOpen={!!paymentItem}
          onClose={() => setPaymentItem(null)}
          title={`Update Payment Realization — ${paymentItem?.invoice_number}`}
          subtitle={`Customer: ${paymentItem?.customer_name} | Total Invoice Value: ₹${(paymentItem?.total_invoice_value || 0).toLocaleString("en-IN", { minimumFractionDigits: 2 })}`}
        >
          <form onSubmit={handlePaymentSubmit} className="space-y-4">
            {paymentError && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                {paymentError}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Payment Status *
                </label>
                <select
                  value={paymentStatus}
                  onChange={(e) => {
                    const st = e.target.value;
                    setPaymentStatus(st);
                    if (st === "PAID" && paymentItem) {
                      setPaidAmount(paymentItem.total_invoice_value || 0);
                    }
                  }}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-bold text-zinc-900 dark:text-zinc-50 focus:outline-none"
                >
                  <option value="UNPAID">🔴 UNPAID</option>
                  <option value="PARTIALLY_PAID">🟡 PARTIALLY_PAID</option>
                  <option value="PAID">🟢 PAID</option>
                  <option value="OVERDUE">🟣 OVERDUE</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                  <span>Amount Realized (₹)</span>
                  <span className="text-[10px] text-zinc-400">Total: ₹{(paymentItem?.total_invoice_value || 0).toLocaleString()}</span>
                </label>
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={paidAmount}
                  onChange={(e) => setPaidAmount(e.target.value === "" ? "" : Number(e.target.value))}
                  placeholder="0.00"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:outline-none"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Payment Reference / UTR / Cheque No
                </label>
                <input
                  type="text"
                  value={paymentRef}
                  onChange={(e) => setPaymentRef(e.target.value)}
                  placeholder="e.g. UTR-HDFC-991208123"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Payment Date
                </label>
                <input
                  type="date"
                  value={paymentDate}
                  onChange={(e) => setPaymentDate(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                Payment Remarks / Banking Notes
              </label>
              <input
                type="text"
                value={paymentRemarks}
                onChange={(e) => setPaymentRemarks(e.target.value)}
                placeholder="e.g. Direct bank transfer verified by finance"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setPaymentItem(null)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submittingPayment}
                className="flex items-center gap-1.5 rounded-xl bg-blue-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50 transition-colors"
              >
                <CreditCard className="h-4 w-4" />
                <span>{submittingPayment ? "Updating..." : "Save Payment Status"}</span>
              </button>
            </div>
          </form>
        </Modal>

        {/* Customer Return & Complaints Modal */}
        <Modal
          isOpen={showReturnModal}
          onClose={() => setShowReturnModal(false)}
          title="Log Customer Return & Generate Conversion Work Order"
          subtitle="Record customer complaint, capture product selling value, and create replacement WO for Conversion"
        >
          <form onSubmit={handleReturnSubmit} className="space-y-4">
            {returnModalError && (
              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-xs font-semibold text-rose-500">
                {returnModalError}
              </div>
            )}

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Customer Code *
                </label>
                <input
                  type="text"
                  required
                  value={retCustomerCode}
                  onChange={(e) => setRetCustomerCode(e.target.value)}
                  onBlur={() => fetchPricingForReturn()}
                  placeholder="e.g. CUST-001 or BOSCH"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Customer Name
                </label>
                <input
                  type="text"
                  value={retCustomerName}
                  onChange={(e) => setRetCustomerName(e.target.value)}
                  placeholder="e.g. Bosch Chassis Systems"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Part Number *
                </label>
                <input
                  type="text"
                  required
                  value={retPartNumber}
                  onChange={(e) => setRetPartNumber(e.target.value)}
                  onBlur={() => fetchPricingForReturn()}
                  placeholder="e.g. PART-8821"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Original WO #
                </label>
                <input
                  type="text"
                  value={retOriginalWo}
                  onChange={(e) => setRetOriginalWo(e.target.value)}
                  onBlur={() => fetchPricingForReturn()}
                  placeholder="e.g. WO-00042"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Invoice Number
                </label>
                <input
                  type="text"
                  value={retInvoiceNo}
                  onChange={(e) => setRetInvoiceNo(e.target.value)}
                  placeholder="e.g. INV-2026-0012"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>
            </div>

            {/* Quantity and Pricing Section */}
            <div className="grid grid-cols-3 gap-3 p-3 bg-zinc-50 dark:bg-zinc-900/60 rounded-xl border border-zinc-200/60 dark:border-zinc-800/60">
              <div>
                <label className="text-xs font-bold text-rose-600 dark:text-rose-400">
                  Returned Qty (pcs) *
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  value={retQty}
                  onChange={(e) => setRetQty(e.target.value === "" ? "" : Number(e.target.value))}
                  placeholder="e.g. 50"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-extrabold text-rose-600 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100 flex items-center justify-between">
                  <span>Product Selling Value (₹/pc)</span>
                  {retPriceSource && (
                    <span className="text-[9px] text-blue-600 font-normal">({retPriceSource})</span>
                  )}
                </label>
                <input
                  type="number"
                  step="0.01"
                  min={0}
                  value={retUnitPrice}
                  onChange={(e) => setRetUnitPrice(e.target.value === "" ? "" : Number(e.target.value))}
                  placeholder="e.g. 450.00"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 py-2 text-xs font-mono font-bold text-zinc-900 dark:text-zinc-50 focus:outline-none"
                />
              </div>

              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Total Return Value (₹)
                </label>
                <div className="mt-1.5 px-3 py-2 text-xs font-mono font-extrabold text-zinc-900 dark:text-zinc-100 bg-white dark:bg-zinc-950 rounded-xl border border-zinc-200 dark:border-zinc-800">
                  ₹{((Number(retQty) || 0) * (Number(retUnitPrice) || 0)).toLocaleString("en-IN", { minimumFractionDigits: 2 })}
                </div>
              </div>
            </div>

            <div>
              <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                Customer Complaint Reason *
              </label>
              <textarea
                required
                rows={2}
                value={retComplaintReason}
                onChange={(e) => setRetComplaintReason(e.target.value)}
                placeholder="Explain the customer's defect/complaint (e.g. Dimensional variation on OD, surface roughness rejection, rework required at F1)"
                className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950 px-3 py-2 text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none focus:border-rose-500"
              />
            </div>

            {/* Conversion Routing Options */}
            <div className="grid grid-cols-2 gap-3 p-3 bg-blue-50/50 dark:bg-blue-950/20 rounded-xl border border-blue-200/50 dark:border-blue-900/40">
              <div>
                <label className="text-xs font-bold text-zinc-900 dark:text-zinc-100">
                  Conversion Entry Stage *
                </label>
                <select
                  value={retEntryStage}
                  onChange={(e) => setRetEntryStage(e.target.value)}
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 py-2 text-xs font-bold text-zinc-900 dark:text-zinc-100 focus:outline-none"
                >
                  <option value="F1">Forging Stage 1 (F1)</option>
                  <option value="SP">Shot Peening (SP)</option>
                  <option value="P1">Phosphating (P1)</option>
                  <option value="MC">Machining (MC)</option>
                  <option value="INSP">Final Inspection (INSP)</option>
                  <option value="BSR">Packing / BSR</option>
                </select>
                <p className="mt-1 text-[10px] text-zinc-500">WIP inventory of {Number(retQty) || 0} pcs will be immediately credited to this stage.</p>
              </div>

              <div>
                <label className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  Custom Conversion WO ID (Optional)
                </label>
                <input
                  type="text"
                  value={retConversionWo}
                  onChange={(e) => setRetConversionWo(e.target.value)}
                  placeholder="Auto-generated if left blank"
                  className="mt-1.5 w-full rounded-xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 px-3 py-2 text-xs font-mono text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
                <p className="mt-1 text-[10px] text-zinc-500">Leaves as blank to auto-create standard collision-free WO ID.</p>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              <button
                type="button"
                onClick={() => setShowReturnModal(false)}
                className="rounded-xl border border-zinc-200 dark:border-zinc-800 px-4 py-2.5 text-xs font-semibold text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submittingReturn}
                className="flex items-center gap-1.5 rounded-xl bg-rose-600 px-5 py-2.5 text-xs font-bold text-white shadow-sm hover:bg-rose-500 disabled:opacity-50 transition-colors"
              >
                <RotateCcw className="h-4 w-4" />
                <span>{submittingReturn ? "Routing to Conversion..." : "Confirm Return & Send to Conversion"}</span>
              </button>
            </div>
          </form>
        </Modal>
      </div>
    </AppShell>
  );
}

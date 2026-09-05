"use client";
import React, { useState } from "react";
import {
  FileSpreadsheet,
  UploadCloud,
  CheckCircle2,
  AlertTriangle,
  Download,
  Play,
  Layers,
  FileCheck,
  RefreshCw
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { runOMSCycle, API_BASE } from "@/lib/api";

export default function OMSEnginePage() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
    }
  };

  const handleRunCycle = async () => {
    if (!file) {
      setError("Please select an input Excel workbook first.");
      return;
    }

    setLoading(true);
    setError("");
    setResult(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const data = await runOMSCycle(formData);
      setResult(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "OMS Engine cycle execution failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <AppShell>
      <div className="max-w-4xl mx-auto space-y-6">
        {/* Header */}
        <div>
          <div className="flex items-center gap-2">
            <span className="rounded-md bg-emerald-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
              Core Engine Integration
            </span>
            <span className="text-xs text-zinc-400">OMS Engine v3.3</span>
          </div>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            OMS Daily Cycle Processor
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Run the deterministic Order Management System cycle to reconcile batch files, back-calculate stage targets, and generate Master spreadsheets.
          </p>
        </div>

        {error && (
          <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-4 text-xs text-rose-500 font-semibold">
            {error}
          </div>
        )}

        {/* Upload & Run Card */}
        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-5">
          <div className="flex items-center justify-between pb-3 border-b border-zinc-100 dark:border-zinc-800">
            <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-50">
              Run Daily Execution Cycle
            </h3>
            <span className="text-xs font-semibold text-emerald-600 bg-emerald-50 dark:bg-emerald-950/50 px-2.5 py-1 rounded-full">
              Deterministic Math Model
            </span>
          </div>

          <div className="rounded-2xl border-2 border-dashed border-zinc-300 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-950/50 p-8 text-center">
            <UploadCloud className="h-10 w-10 text-zinc-400 mx-auto" />
            <p className="text-sm font-bold text-zinc-900 dark:text-zinc-100 mt-2">
              Select Daily Input Excel File
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
              Supports .xlsx, .xlsm with Production Update, Order Intake, WO Release & NC tabs
            </p>

            <label className="mt-4 inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 cursor-pointer transition-colors shadow-sm">
              <span>Choose File</span>
              <input
                type="file"
                accept=".xlsx,.xls,.xlsm"
                onChange={handleFileChange}
                className="hidden"
              />
            </label>

            {file && (
              <p className="mt-3 text-xs font-mono font-bold text-blue-600 dark:text-blue-400">
                Selected: {file.name} ({(file.size / 1024).toFixed(1)} KB)
              </p>
            )}
          </div>

          <button
            type="button"
            onClick={handleRunCycle}
            disabled={loading || !file}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 py-3.5 text-xs font-bold text-white shadow-sm hover:bg-emerald-500 disabled:opacity-50 transition-colors cursor-pointer"
          >
            {loading ? (
              <>
                <RefreshCw className="h-4 w-4 animate-spin" />
                <span>Running OMS Cycle Calculations...</span>
              </>
            ) : (
              <>
                <Play className="h-4 w-4" />
                <span>Execute OMS Daily Run Cycle</span>
              </>
            )}
          </button>
        </div>

        {/* Results Card */}
        {result && (
          <div className="rounded-2xl border border-emerald-500/30 bg-white dark:bg-zinc-900 p-6 shadow-sm space-y-4">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-500" />
              <div>
                <h4 className="text-base font-bold text-zinc-900 dark:text-zinc-50">
                  {result.message}
                </h4>
                <p className="text-xs text-zinc-500">
                  Cycle Date: {result.cycle_date} | Timestamp: {result.timestamp}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 border-t border-zinc-100 dark:border-zinc-800 pt-4">
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 p-3 border border-zinc-200 dark:border-zinc-800 text-xs">
                <span className="text-zinc-400 block text-[10px] uppercase font-bold">Processed WOs</span>
                <span className="font-extrabold text-zinc-900 dark:text-zinc-100 text-base">{result.processed_orders ?? 0}</span>
              </div>
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 p-3 border border-zinc-200 dark:border-zinc-800 text-xs">
                <span className="text-zinc-400 block text-[10px] uppercase font-bold">Calculated WIP</span>
                <span className="font-extrabold text-blue-600 text-base">{result.calculated_wip ?? 0} pcs</span>
              </div>
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 p-3 border border-zinc-200 dark:border-zinc-800 text-xs">
                <span className="text-zinc-400 block text-[10px] uppercase font-bold">Shortfalls Detected</span>
                <span className="font-extrabold text-rose-600 text-base">{result.shortfalls_detected ?? 0}</span>
              </div>
              <div className="rounded-xl bg-zinc-50 dark:bg-zinc-950 p-3 border border-zinc-200 dark:border-zinc-800 text-xs">
                <span className="text-zinc-400 block text-[10px] uppercase font-bold">MRB Updates</span>
                <span className="font-extrabold text-emerald-600 text-base">{result.mrb_updates ?? 0}</span>
              </div>
            </div>

            {/* Downloads */}
            <div className="flex flex-wrap gap-3 pt-3 border-t border-zinc-100 dark:border-zinc-800">
              {result.master_file_url && (
                <a
                  href={`${API_BASE}${result.master_file_url}`}
                  download
                  className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white shadow-xs hover:bg-blue-500"
                >
                  <Download className="h-3.5 w-3.5" />
                  <span>Download Master Spreadsheet (.xlsx)</span>
                </a>
              )}

              {result.report_file_url && (
                <a
                  href={`${API_BASE}${result.report_file_url}`}
                  download
                  className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-300 dark:border-zinc-700 bg-zinc-100 dark:bg-zinc-800 px-4 py-2 text-xs font-bold text-zinc-900 dark:text-zinc-100 hover:bg-zinc-200"
                >
                  <FileSpreadsheet className="h-3.5 w-3.5 text-emerald-600" />
                  <span>Download Daily Report (.xlsx)</span>
                </a>
              )}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

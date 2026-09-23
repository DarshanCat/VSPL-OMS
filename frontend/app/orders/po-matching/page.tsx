"use client";
import React, { useEffect, useState } from "react";
import { AppShell } from "@/app/components/layout/AppShell";
import {
  getMasterCustomers, getPOMasters, getMatchCandidates, confirmMatch,
  MasterCustomer, POMasterOut, MatchCandidate,
} from "@/lib/api";
import { GitMerge, AlertTriangle, CheckCircle2, Scale } from "lucide-react";

const MATCH_STYLES: Record<string, string> = {
  EXACT: "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400",
  PO_BELOW_SCHEDULE: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400",
  PO_ABOVE_SCHEDULE: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-400",
};

export default function POMatchingPage() {
  const [customers, setCustomers] = useState<MasterCustomer[]>([]);
  const [pos, setPOs] = useState<POMasterOut[]>([]);
  const [customerCode, setCustomerCode] = useState("");
  const [poLineId, setPoLineId] = useState("");
  const [candidates, setCandidates] = useState<MatchCandidate[]>([]);

  const [loading, setLoading] = useState(true);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [error, setError] = useState("");
  const [matchBusy, setMatchBusy] = useState<string | null>(null);
  const [pendingAck, setPendingAck] = useState<MatchCandidate | null>(null);
  const [result, setResult] = useState<{ oar_number: string; message: string } | null>(null);

  async function loadMasters() {
    setLoading(true);
    setError("");
    try {
      const [c, p] = await Promise.all([getMasterCustomers(), getPOMasters()]);
      setCustomers(c);
      setPOs(p);
      if (!customerCode && c.length) setCustomerCode(c[0].customer_code);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not load PO data.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadMasters();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filteredPOs = pos.filter((po) => po.customer_code === customerCode);
  const lineOptions = filteredPOs.flatMap((po) =>
    po.lines.map((l) => ({ ...l, po_number: po.po_number, po_id: po.id }))
  );
  const selectedLine = lineOptions.find((l) => l.id === poLineId);

  async function loadCandidates(lineId: string, opts?: { keepResult?: boolean }) {
    setPoLineId(lineId);
    setCandidates([]);
    if (!opts?.keepResult) setResult(null);
    if (!lineId) return;
    setCandidatesLoading(true);
    setError("");
    try {
      const data = await getMatchCandidates(lineId);
      setCandidates(data);
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Could not load match candidates.");
    } finally {
      setCandidatesLoading(false);
    }
  }

  async function doMatch(candidate: MatchCandidate, acknowledge: boolean) {
    setMatchBusy(candidate.schedule_id);
    setError("");
    try {
      const res = await confirmMatch({
        po_line_id: poLineId,
        schedule_id: candidate.schedule_id,
        acknowledge_mismatch: acknowledge,
      });
      setResult({ oar_number: res.oar_number, message: res.message });
      setPendingAck(null);
      await loadCandidates(poLineId, { keepResult: true });
      await loadMasters();
    } catch (err: any) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 409) {
        setPendingAck(candidate);
      } else {
        setError(detail || "Could not confirm match.");
      }
    } finally {
      setMatchBusy(null);
    }
  }

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-6">
        <div>
          <span className="rounded-md bg-blue-600 px-2 py-0.5 text-[10px] font-bold text-white uppercase tracking-wider">
            Order Management
          </span>
          <h1 className="text-2xl font-extrabold tracking-tight text-zinc-900 dark:text-zinc-50 mt-1">
            PO Matching
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            Match a received PO line to an existing schedule-based OAR — links the PO instead of
            creating a duplicate order, and preserves the original schedule information.
          </p>
        </div>

        {error && (
          <div className="flex items-start gap-1.5 rounded-lg bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-xs font-medium text-rose-600 dark:text-rose-400">
            <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        {result && (
          <div className="flex items-start gap-1.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
            <span>{result.message} (OAR {result.oar_number})</span>
          </div>
        )}

        <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-5 shadow-sm">
          <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            <GitMerge className="h-4 w-4 text-blue-500" /> Select Customer / PO Line
          </h3>
          <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
            <select
              value={customerCode}
              onChange={(e) => { setCustomerCode(e.target.value); loadCandidates(""); }}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs"
            >
              <option value="" disabled>Select customer</option>
              {customers.map((c) => (
                <option key={c.id} value={c.customer_code}>{c.customer_code} — {c.name}</option>
              ))}
            </select>
            <select
              value={poLineId}
              onChange={(e) => loadCandidates(e.target.value)}
              disabled={loading || lineOptions.length === 0}
              className="rounded-lg border border-zinc-200 dark:border-zinc-700 bg-transparent px-3 py-2 text-xs disabled:opacity-50"
            >
              <option value="">Select PO line</option>
              {lineOptions.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.po_number} — {l.part_number} (qty {l.po_qty}, available {l.available_qty})
                </option>
              ))}
            </select>
          </div>
        </div>

        {selectedLine && (
          <div className="rounded-2xl border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 shadow-sm overflow-hidden">
            <div className="p-4 border-b border-zinc-100 dark:border-zinc-800 flex items-center gap-2">
              <Scale className="h-4 w-4 text-zinc-500" />
              <h3 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                Schedule vs. PO — {selectedLine.po_number} / {selectedLine.part_number}
              </h3>
            </div>
            {candidatesLoading ? (
              <div className="p-4 text-xs text-zinc-500">Loading candidates...</div>
            ) : candidates.length === 0 ? (
              <div className="p-4 text-xs text-zinc-500">
                No matching schedule-based demand found for this customer/part.
              </div>
            ) : (
              <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {candidates.map((c) => (
                  <div key={c.schedule_id} className="p-4 grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
                    <div>
                      <p className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">Schedule</p>
                      <p className="text-xs font-mono font-semibold text-zinc-900 dark:text-zinc-100">{c.schedule_number}</p>
                      <p className="text-xs text-zinc-500">Qty {c.scheduled_qty} · Req {c.required_date || "-"}</p>
                      {c.oar_number && <p className="text-[11px] text-zinc-400">OAR {c.oar_number}</p>}
                    </div>
                    <div>
                      <p className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">PO</p>
                      <p className="text-xs font-mono font-semibold text-zinc-900 dark:text-zinc-100">{selectedLine.po_number}</p>
                      <p className="text-xs text-zinc-500">Qty {selectedLine.po_qty}</p>
                      <span className={`inline-block mt-1 rounded-md px-2 py-0.5 text-[10px] font-bold uppercase ${MATCH_STYLES[c.quantity_match]}`}>
                        {c.quantity_match.replace(/_/g, " ")}
                      </span>
                      {c.mismatch_message && (
                        <p className="text-[11px] text-amber-600 dark:text-amber-400 mt-1">{c.mismatch_message}</p>
                      )}
                    </div>
                    <div className="justify-self-end space-y-2">
                      {pendingAck?.schedule_id === c.schedule_id ? (
                        <div className="rounded-lg border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/30 p-2.5 text-[11px] text-amber-800 dark:text-amber-300 space-y-2">
                          <p>{c.mismatch_message} — confirm to proceed anyway?</p>
                          <div className="flex gap-2">
                            <button
                              type="button"
                              disabled={matchBusy === c.schedule_id}
                              onClick={() => doMatch(c, true)}
                              className="rounded-lg bg-amber-600 px-3 py-1.5 text-[11px] font-bold text-white hover:bg-amber-500 disabled:opacity-50"
                            >
                              Acknowledge & Match
                            </button>
                            <button type="button" onClick={() => setPendingAck(null)}
                              className="rounded-lg bg-zinc-100 dark:bg-zinc-800 px-3 py-1.5 text-[11px] font-semibold text-zinc-700 dark:text-zinc-300">
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <button
                          type="button"
                          disabled={matchBusy === c.schedule_id}
                          onClick={() => doMatch(c, false)}
                          className="rounded-xl bg-blue-600 px-4 py-2 text-xs font-bold text-white hover:bg-blue-500 disabled:opacity-60 transition-colors"
                        >
                          {matchBusy === c.schedule_id ? "Matching..." : "Match & Confirm"}
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}

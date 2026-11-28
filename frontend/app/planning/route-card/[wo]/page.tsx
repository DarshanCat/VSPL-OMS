"use client";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { AlertTriangle, ArrowLeft, Loader2, Printer, RefreshCw } from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { getRouteCard, planningErrorText, RouteCard, RouteCardGate } from "@/lib/api";

// Code 128 (set B) bar patterns, so the WO number prints as a scannable barcode with no extra library.
const C128 = ["212222","222122","222221","121223","121322","131222","122213","122312","132212","221213","221312","231212","112232","122132","122231","113222","123122","123221","223211","221132","221231","213212","223112","312131","311222","321122","321221","312212","322112","322211","212123","212321","232121","111323","131123","131321","112313","132113","132311","211313","231113","231311","112133","112331","132131","113123","113321","133121","313121","211331","231131","213113","213311","213131","311123","311321","331121","312113","312311","332111","314111","221411","431111","111224","111422","121124","121421","141122","141221","112214","112412","122114","122411","142112","142211","241211","221114","413111","241112","134111","111242","121142","121241","114212","124112","124211","411212","421112","421211","212141","214121","412121","111143","111341","131141","114113","114311","411113","411311","113141","114131","311141","411131","211412","211214","211232","2331112"];

function Barcode({ value }: { value: string }) {
  const bars = useMemo(() => {
    const text = (value || "").replace(/[^\x20-\x7e]/g, "?");
    const codes = [104, ...Array.from(text).map((c) => c.charCodeAt(0) - 32)];
    const sum = codes.reduce((acc, c, i) => acc + c * (i === 0 ? 1 : i), 0);
    codes.push(sum % 103, 106);
    let x = 10; // quiet zone
    const out: { x: number; w: number }[] = [];
    for (const code of codes) {
      let bar = true;
      for (const ch of C128[code]) {
        const w = Number(ch);
        if (bar) out.push({ x, w });
        x += w;
        bar = !bar;
      }
    }
    return { out, width: x + 10 };
  }, [value]);
  return (
    <svg viewBox={`0 0 ${bars.width} 40`} preserveAspectRatio="none" style={{ width: "100%", height: 34 }} role="img" aria-label={`Barcode ${value}`}>
      {bars.out.map((b, i) => <rect key={i} x={b.x} y={0} width={b.w} height={40} fill="#000" />)}
    </svg>
  );
}

const dmy = (iso?: string | null) => {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return y && m && d ? `${d}/${m}/${y}` : iso;
};
const n = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(v));

function qtyCell(g: RouteCardGate, v: number): string {
  return g.quantity_source === "NONE" ? "" : String(v);
}

export default function RouteCardPage() {
  const params = useParams<{ wo: string }>();
  const wo = decodeURIComponent(String(params?.wo || ""));
  const [card, setCard] = useState<RouteCard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setCard(await getRouteCard(wo));
    } catch (err: any) {
      setError(planningErrorText(err, "Could not load the route card."));
    } finally {
      setLoading(false);
    }
  }, [wo]);

  useEffect(() => { if (wo) load(); }, [wo, load]);

  const labelCls = "rc-lab";
  const cell = (label: string, value: React.ReactNode, mono = false) => (
    <>
      <div className={labelCls}>{label}</div>
      <div className={`rc-val${mono ? " rc-mono" : ""}`}>{value}</div>
    </>
  );

  return (
    <AppShell>
      <style>{`
        .rc-paper{background:#fff;color:#111;border:1px solid #333;max-width:1100px;margin:0 auto;font-family:Arial,Helvetica,sans-serif;font-size:11.5px;position:relative}
        .rc-top{display:grid;grid-template-columns:1fr 170px 150px;background:#1a56b8;color:#fff;border-bottom:1px solid #333}
        .rc-top .t{padding:12px;text-align:center;font-weight:700;letter-spacing:.08em;font-size:17px;align-self:center}
        .rc-top .m{padding:6px 9px;border-left:1px solid rgba(255,255,255,.5);font-size:10.5px}
        .rc-top .m b{display:block;font-size:11.5px}
        .rc-grid{display:grid;grid-template-columns:repeat(4,1fr 1.25fr)}
        .rc-lab,.rc-val{padding:6px 7px;border-bottom:1px solid #333;border-right:1px solid #333;min-height:30px;display:flex;align-items:center}
        .rc-lab{background:#e9ecf0;font-weight:700}
        .rc-val{font-weight:600;word-break:break-word}
        .rc-mono{font-family:ui-monospace,Menlo,monospace}
        .rc-scroll{overflow-x:auto}
        .rc-inner{min-width:940px}
        .rc-table{width:100%;border-collapse:collapse}
        .rc-table th,.rc-table td{border:1px solid #333;padding:6px 6px;text-align:left;vertical-align:middle}
        .rc-table th{background:#e9ecf0;font-size:10.5px}
        .rc-table td.c,.rc-table th.c{text-align:center}
        .rc-table td.sig{min-width:70px;height:42px}
        .rc-sub{display:block;font-weight:500;font-size:10px;color:#444}
        .rc-draft{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none;font-size:110px;font-weight:800;letter-spacing:.1em;color:rgba(200,30,30,.12);transform:rotate(-24deg);z-index:2}
        .rc-foot{display:flex;justify-content:space-between;padding:6px 8px;font-size:10px;color:#333;border-top:1px solid #333}
        @page{size:A4 landscape;margin:8mm}
        @media print{
          body *{visibility:hidden}
          .rc-print,.rc-print *{visibility:visible}
          .rc-print{position:absolute;left:0;top:0;width:100%}
          .rc-paper{border:1px solid #000;max-width:none}
          .rc-scroll{overflow:visible}
          .rc-inner{min-width:0}
          .rc-noprint{display:none !important}
          .rc-top{-webkit-print-color-adjust:exact;print-color-adjust:exact}
          .rc-lab,.rc-table th{-webkit-print-color-adjust:exact;print-color-adjust:exact}
        }
      `}</style>

      <div className="mx-auto max-w-[1100px] space-y-4">
        <div className="rc-noprint flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <Link href="/planning/wo-release-search" className="inline-flex items-center gap-1 text-xs font-bold text-zinc-600 dark:text-zinc-300 hover:underline">
              <ArrowLeft className="h-3.5 w-3.5" /> Work orders
            </Link>
            <h1 className="text-lg font-extrabold text-zinc-900 dark:text-zinc-100">Route card · {wo}</h1>
          </div>
          <div className="flex items-center gap-2">
            <button type="button" onClick={load} disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 px-3 py-2 text-xs font-bold text-zinc-700 dark:text-zinc-200 disabled:opacity-50">
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
            </button>
            <button type="button" onClick={() => window.print()} disabled={!card}
              className="inline-flex items-center gap-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 px-3.5 py-2 text-xs font-bold text-white disabled:opacity-50">
              <Printer className="h-3.5 w-3.5" /> Print
            </button>
          </div>
        </div>

        {error && (
          <div className="rc-noprint flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 dark:border-rose-900 dark:bg-rose-950/40 p-3 text-xs font-semibold text-rose-700 dark:text-rose-300" role="alert">
            <AlertTriangle className="h-4 w-4 shrink-0" /> <span>{error}</span>
          </div>
        )}
        {loading && !card && (
          <div className="rc-noprint flex items-center gap-2 text-sm text-zinc-500"><Loader2 className="h-4 w-4 animate-spin" /> Building the route card…</div>
        )}

        {card && (
          <div className="rc-print">
            <div className="rc-scroll"><div className="rc-paper"><div className="rc-inner">
              {card.is_draft && <div className="rc-draft">DRAFT</div>}
              <div className="rc-top">
                <div className="t">ROUTE CARD</div>
                <div className="m">Doc #<b>{card.doc_number}</b>Rev date <b>{dmy(card.doc_rev_date)}</b></div>
                <div className="m">Issue date<b>{dmy(card.issue_date)}</b>Rev {card.revision}</div>
              </div>
              <div className="rc-grid">
                {cell("Customer Name", card.customer_name)}
                {cell("Unique Production Code", card.unique_production_code)}
                {cell("PO Number (Customer)", card.po_numbers.join(", "))}
                {cell("PO ID", card.oar_numbers.join(", "))}

                {cell("Internal Part No", card.internal_part_number)}
                {cell("Customer Part No", card.customer_part_number)}
                {cell("WO ID", card.wo_number, true)}
                {cell("WO Type", <span>{card.wo_type}{card.source_wo_number ? <span className="rc-sub">replaces {card.source_wo_number}</span> : null}</span>)}

                {cell("FG Qty", n(card.fg_qty))}
                {cell("Tool Assembly Description", card.tool_assembly_description)}
                {cell("RC Qty", n(card.rc_qty))}
                {cell("Internal Grade", card.internal_grade)}

                {cell("Die ID", card.die_id)}
                {cell("M/C Cost", card.machine_cost)}
                {cell("Unique Bin ID", card.bin_id)}
                {cell("Bath No", card.bath_no)}

                {cell("Heat Number", card.heat_numbers.join(", "))}
                {cell("WO Barcode", <div style={{ width: "100%" }}><Barcode value={card.wo_number} /></div>)}
                {cell("Setup No", card.setup_number)}
                {cell("Status", card.is_draft ? "DRAFT · " + card.release_status.replace(/_/g, " ") : "RELEASED")}
              </div>

              <table className="rc-table">
                <thead>
                  <tr>
                    <th>Process Description</th>
                    <th className="c">Process Start Date</th>
                    <th>Process Responsibility</th>
                    <th style={{ minWidth: 190 }}>Part Route</th>
                    <th className="c">Production Qty</th>
                    <th className="c">Accepted Qty</th>
                    <th className="c">Rejected Qty</th>
                    <th className="c">Prepared by</th>
                    <th className="c">Checked by</th>
                    <th className="c">Approved by</th>
                  </tr>
                </thead>
                <tbody>
                  {card.gates.length === 0 && (
                    <tr><td colSpan={10} style={{ textAlign: "center", padding: 18 }}>No route yet. The gates appear here once the work order has its routing.</td></tr>
                  )}
                  {card.gates.map((g) => (
                    <tr key={g.gate}>
                      <td><b>{g.process}</b></td>
                      <td className="c">{dmy(g.start_date)}</td>
                      <td>{g.responsibility || ""}</td>
                      <td>
                        {g.part_route === "VENDOR" ? (
                          <>
                            <b>In-Vendor</b>
                            {g.vendor_trips.map((t, i) => (
                              <span className="rc-sub" key={i}>
                                {t.vendor_name} · DC {t.dc_number}{t.process_name ? ` · ${t.process_name}` : ""}
                                {t.out_qty > 0 ? ` · ${t.out_qty} out` : ""}
                              </span>
                            ))}
                          </>
                        ) : "In-House"}
                      </td>
                      <td className="c">{qtyCell(g, g.production_qty)}</td>
                      <td className="c">{qtyCell(g, g.accepted_qty)}</td>
                      <td className="c">
                        {qtyCell(g, g.rejected_qty)}
                        {g.pending_qty > 0 && <span className="rc-sub">{g.pending_qty} pending MRB</span>}
                      </td>
                      <td className="sig" /><td className="sig" /><td className="sig" />
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="rc-foot">
                <span>Production, accepted and rejected quantities fill in from the floor entries and MRB approval.</span>
                <span>Printed {new Date(card.generated_at).toLocaleString("en-GB")}</span>
              </div>
            </div></div></div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

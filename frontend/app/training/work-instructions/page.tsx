"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import {
  Play,
  Pause,
  RotateCcw,
  ChevronLeft,
  ChevronRight,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Printer,
  BookOpen,
  Layers,
  Boxes,
  CalendarClock,
  Cog,
  GitMerge,
  ArrowRightLeft,
  Shuffle,
  HelpCircle,
  CheckSquare,
  Search,
  Sparkles,
  ShieldAlert,
  Languages,
  ArrowRight,
  FileText,
  Factory,
  PackageCheck,
  Check
} from "lucide-react";
import { AppShell } from "@/app/components/layout/AppShell";
import { Badge } from "@/app/components/ui/Badge";

// ==========================================
// TRANSLATION DICTIONARIES (EN & KN)
// ==========================================
type Lang = "en" | "kn";

interface TransText {
  en: string;
  kn: string;
}

const T: Record<string, TransText> = {
  headerTitle: {
    en: "VSPL SMES Operator Training & Interactive Work Instructions",
    kn: "ವಿಎಸ್‌ಪಿಎಲ್ ಎಸ್‌ಎಂಇಎಸ್ ಆಪರೇಟರ್ ತರಬೇತಿ ಮತ್ತು ಸಂವಾದಾತ್ಮಕ ಕೆಲಸದ ಮಾರ್ಗದರ್ಶಿ"
  },
  headerSubtitle: {
    en: "Mastering Continuous Casting (F1 Bypass) & Work Order Conversion (Zero Re-Melt Reallocation)",
    kn: "ನಿರಂತರ ಎರಕಹೊಯ್ಯುವಿಕೆ (F1 ಬೈಪಾಸ್) ಮತ್ತು ವರ್ಕ್ ಆರ್ಡರ್ ಪರಿವರ್ತನೆ (ಶೂನ್ಯ ಮರುಕರಗಿಸುವಿಕೆ) ವಿಧಾನಗಳು"
  },
  moduleCC: {
    en: "Continuous Casting Module (WI-CC-01)",
    kn: "ನಿರಂತರ ಎರಕಹೊಯ್ಯುವಿಕೆ ಮಾಡ್ಯೂಲ್ (WI-CC-01)"
  },
  moduleConv: {
    en: "Work Order Conversion Module (WI-CONV-01)",
    kn: "ವರ್ಕ್ ಆರ್ಡರ್ ಪರಿವರ್ತನೆ ಮಾಡ್ಯೂಲ್ (WI-CONV-01)"
  },
  f1BypassRule: {
    en: "MANDATORY BUSINESS RULE: Continuous Casting completely bypasses Stage F1 (Centrifugal Melt & Fettling). Accepted blanks are credited directly to Stage F2 (Machining WIP) only after Material Gate reconciliation.",
    kn: "ಕಡ್ಡಾಯ ನಿಯಮ: ನಿರಂತರ ಎರಕಹೊಯ್ಯುವಿಕೆಯು ಹಂತ F1 (ಕರಗಿಸುವಿಕೆ ಮತ್ತು ಗ್ರೈಂಡಿಂಗ್) ಅನ್ನು ಸಂಪೂರ್ಣವಾಗಿ ಬೈಪಾಸ್ ಮಾಡುತ್ತದೆ. ಸ್ವೀಕೃತ ಬ್ಲಾಂಕ್ಸ್‌ಗಳು ಮೆಟೀರಿಯಲ್ ಗೇಟ್ ಪರಿಶೀಲನೆಯ ನಂತರ ನೇರವಾಗಿ F2 (ಮ್ಯಾಶಿನಿಂಗ್ WIP) ಗೆ ಜಮೆಯಾಗುತ್ತವೆ."
  },
  zeroRemeltRule: {
    en: "MANDATORY BUSINESS RULE: Work Order Conversion reallocates eligible in-process material from a Source WO to a Child Conversion WO without remelting. Material is debited from source-stage WIP and initialized at the authorized entry stage on the Child WO with full lineage preserved.",
    kn: "ಕಡ್ಡಾಯ ನಿಯಮ: ವರ್ಕ್ ಆರ್ಡರ್ ಪರಿವರ್ತನೆಯು ಮೂಲ WO ನಿಂದ ಹೊಸ ಮಗು (Child) WO ಗೆ ಮರುಕರಗಿಸದೆ ವಸ್ತುಗಳನ್ನು ಮರುಹಂಚಿಕೆ ಮಾಡುತ್ತದೆ. ಮೂಲ ಹಂತದ WIP ನಿಂದ ಕಡಿತಗೊಳಿಸಿ, ಅನುಮೋದಿತ ಪ್ರವೇಶ ಹಂತದಲ್ಲಿ ಜಮೆ ಮಾಡಲಾಗುತ್ತದೆ."
  },
  viewGuided: { en: "Step-by-Step Training", kn: "ಹಂತ-ಹಂತದ ತರಬೇತಿ" },
  viewChecklist: { en: "Completion Checklist", kn: "ಪೂರ್ಣತೆಯ ಪರಿಶೀಲನಾಪಟ್ಟಿ" },
  viewQuiz: { en: "Knowledge Check (Quiz)", kn: "ಜ್ಞಾನ ಪರೀಕ್ಷೆ (ರಸಪ್ರಶ್ನೆ)" },
  viewTroubleshoot: { en: "Error Troubleshooting", kn: "ದೋಷ ಪರಿಹಾರ ಮಾರ್ಗದರ್ಶಿ" },
  viewGlossary: { en: "Industrial Glossary", kn: "ತಾಂತ್ರಿಕ ಶಬ್ದಕೋಶ" },
  viewPrint: { en: "Print 1-Page Cheat Sheet", kn: "೧-ಪುಟದ ಚೀಟ್-ಶೀಟ್ ಮುದ್ರಿಸಿ" }
};

export default function WorkInstructionsTrainingPage() {
  const [lang, setLang] = useState<Lang>("en");
  const [activeModule, setActiveModule] = useState<"cc" | "conv">("cc");
  const [viewMode, setViewMode] = useState<"guided" | "checklist" | "quiz" | "troubleshoot" | "glossary" | "print">("guided");
  const [step, setStep] = useState<number>(1);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [reducedMotion, setReducedMotion] = useState<boolean>(false);

  // CC Calculator State
  const [barLen, setBarLen] = useState<number>(3000);
  const [barDia, setBarDia] = useState<number>(85);
  const [cutLen, setCutLen] = useState<number>(145);
  const [kerf, setKerf] = useState<number>(3);

  // Conversion Simulator State
  const [srcOD, setSrcOD] = useState<number>(90);
  const [dstOD, setDstOD] = useState<number>(82);
  const [srcLen, setSrcLen] = useState<number>(210);
  const [dstLen, setDstLen] = useState<number>(195);

  // Checklists
  const [ccChecklist, setCcChecklist] = useState<Record<string, boolean>>({
    inwardChecked: false,
    routingActive: false,
    allocationReserved: false,
    cutsRecorded: false,
    gateReconciled: false,
    f2Credited: false,
    traceabilityLogged: false
  });

  const [convChecklist, setConvChecklist] = useState<Record<string, boolean>>({
    mappingVerified: false,
    sourceWIPEligible: false,
    destOARConfirmed: false,
    envelopeCleared: false,
    reasonLogged: false,
    conversionExecuted: false,
    sourceDebited: false,
    childCreated: false,
    lineageTracked: false
  });

  // Quiz State
  const [quizAnswers, setQuizAnswers] = useState<Record<string, number>>({});
  const [quizSubmitted, setQuizSubmitted] = useState<boolean>(false);

  // Auto-play timer
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isPlaying && viewMode === "guided") {
      timer = setInterval(() => {
        setStep((prev) => (prev >= 6 ? 1 : prev + 1));
      }, 6000);
    }
    return () => clearInterval(timer);
  }, [isPlaying, viewMode]);

  // Handle module switch
  const handleModuleChange = (mod: "cc" | "conv") => {
    setActiveModule(mod);
    setStep(1);
    setIsPlaying(false);
    setQuizSubmitted(false);
  };

  // CC Yield Calculations
  const endTrim = 25;
  const effectiveCut = cutLen + kerf;
  const usableBarLen = Math.max(0, barLen - endTrim);
  const calcGoodBlanks = effectiveCut > 0 ? Math.floor(usableBarLen / effectiveCut) : 0;
  const calcScrapMm = barLen - (calcGoodBlanks * cutLen + calcGoodBlanks * kerf);
  const calcYieldPct = barLen > 0 ? ((calcGoodBlanks * cutLen / barLen) * 100).toFixed(1) : "0";
  const barRadius = barDia / 2.0;
  const barArea = Math.PI * barRadius * barRadius;
  const calcWeightKg = (barArea * barLen * 7.2e-6).toFixed(1);

  // Conversion Envelope Calculations
  const odDiff = srcOD - dstOD;
  const lenDiff = srcLen - dstLen;
  const isConvQualified = odDiff >= 3.0 && lenDiff >= 2.0;

  // Checklist counts
  const ccCheckedCount = Object.values(ccChecklist).filter(Boolean).length;
  const convCheckedCount = Object.values(convChecklist).filter(Boolean).length;

  return (
    <AppShell>
      <div className="max-w-6xl mx-auto space-y-6 pb-20 print:p-0 print:max-w-none">
        
        {/* ==================================================== */}
        {/* TOP HERO HEADER WITH BRANDING & BILINGUAL TOGGLE */}
        {/* ==================================================== */}
        <div className="bg-gradient-to-r from-zinc-900 via-slate-900 to-indigo-950 border border-zinc-800 rounded-3xl p-6 sm:p-8 text-white shadow-2xl relative overflow-hidden print:hidden">
          <div className="absolute top-0 right-0 -mr-16 -mt-16 w-64 h-64 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider flex items-center gap-1">
                  <Factory className="h-3 w-3" /> VSPL Smart MES
                </span>
                <span className="bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider flex items-center gap-1">
                  <Sparkles className="h-3 w-3" /> Industrial Training Standard
                </span>
                <span className="bg-amber-500/20 text-amber-300 border border-amber-500/30 text-[10px] font-bold px-2.5 py-0.5 rounded-full uppercase tracking-wider">
                  SOP-2026-CC-CONV
                </span>
              </div>
              <h1 className="text-2xl sm:text-3xl font-black tracking-tight text-white">
                {T.headerTitle[lang]}
              </h1>
              <p className="text-xs sm:text-sm text-zinc-300 max-w-3xl leading-relaxed">
                {T.headerSubtitle[lang]}
              </p>
            </div>

            {/* Language & Accessibility Controls */}
            <div className="flex items-center gap-2 self-start md:self-auto bg-zinc-800/80 p-1.5 rounded-2xl border border-zinc-700/60 backdrop-blur-md">
              <button
                type="button"
                onClick={() => setLang("en")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                  lang === "en"
                    ? "bg-cyan-500 text-zinc-950 shadow-md font-extrabold"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                English
              </button>
              <button
                type="button"
                onClick={() => setLang("kn")}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                  lang === "kn"
                    ? "bg-cyan-500 text-zinc-950 shadow-md font-extrabold"
                    : "text-zinc-400 hover:text-white"
                }`}
              >
                <Languages className="h-3.5 w-3.5" /> ಕನ್ನಡ
              </button>
            </div>
          </div>

          {/* Module Selector Big Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-8">
            <button
              type="button"
              onClick={() => handleModuleChange("cc")}
              className={`p-5 rounded-2xl border text-left transition-all relative overflow-hidden flex flex-col justify-between ${
                activeModule === "cc"
                  ? "bg-amber-500/15 border-amber-500/60 ring-2 ring-amber-500/40 shadow-xl"
                  : "bg-zinc-800/40 border-zinc-700/50 hover:bg-zinc-800/80 hover:border-zinc-600"
              }`}
            >
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold text-amber-400 uppercase tracking-widest flex items-center gap-1.5">
                    <Layers className="h-3.5 w-3.5" /> Module 01
                  </span>
                  <Badge variant={activeModule === "cc" ? "amber" : "gray"} size="sm">
                    {activeModule === "cc" ? "Active Training" : "Click to Learn"}
                  </Badge>
                </div>
                <h3 className="text-lg font-bold text-white mb-1">
                  {T.moduleCC[lang]}
                </h3>
                <p className="text-xs text-zinc-300 leading-relaxed">
                  {lang === "en"
                    ? "Inward -> Bar Registration -> Planning -> Bar Reservation -> Bandsaw Cutting -> F1 Bypass -> F2 Credit"
                    : "ಇನ್‌ವರ್ಡ್ -> ಬಾರ್ ನೋಂದಣಿ -> ಯೋಜನೆ -> ಕಟಿಂಗ್ -> F1 ಬೈಪಾಸ್ -> F2 ಮ್ಯಾಶಿನಿಂಗ್ ಜಮೆ"}
                </p>
              </div>
              <div className="mt-4 pt-3 border-t border-zinc-700/50 flex items-center justify-between text-[11px] text-zinc-400">
                <span>Checklist Progress: {ccCheckedCount}/7 completed</span>
                <span className="text-amber-400 font-semibold flex items-center gap-1">
                  Explore Module <ChevronRight className="h-3.5 w-3.5" />
                </span>
              </div>
            </button>

            <button
              type="button"
              onClick={() => handleModuleChange("conv")}
              className={`p-5 rounded-2xl border text-left transition-all relative overflow-hidden flex flex-col justify-between ${
                activeModule === "conv"
                  ? "bg-indigo-500/15 border-indigo-500/60 ring-2 ring-indigo-500/40 shadow-xl"
                  : "bg-zinc-800/40 border-zinc-700/50 hover:bg-zinc-800/80 hover:border-zinc-600"
              }`}
            >
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[11px] font-bold text-indigo-400 uppercase tracking-widest flex items-center gap-1.5">
                    <ArrowRightLeft className="h-3.5 w-3.5" /> Module 02
                  </span>
                  <Badge variant={activeModule === "conv" ? "purple" : "gray"} size="sm">
                    {activeModule === "conv" ? "Active Training" : "Click to Learn"}
                  </Badge>
                </div>
                <h3 className="text-lg font-bold text-white mb-1">
                  {T.moduleConv[lang]}
                </h3>
                <p className="text-xs text-zinc-300 leading-relaxed">
                  {lang === "en"
                    ? "Part Mapping (SAME/PART) -> WO Selection -> Eligibility -> Material Reallocation -> StageWIP Debit -> Lineage"
                    : "ಭಾಗ ಮ್ಯಾಪಿಂಗ್ -> WO ಆಯ್ಕೆ -> ಅರ್ಹತೆ ಪರಿಶೀಲನೆ -> ಮರುಹಂಚಿಕೆ -> ಸ್ಟೇಜ್ WIP ಕಡಿತ -> ಟ್ರೇಸೇಬಿಲಿಟಿ"}
                </p>
              </div>
              <div className="mt-4 pt-3 border-t border-zinc-700/50 flex items-center justify-between text-[11px] text-zinc-400">
                <span>Checklist Progress: {convCheckedCount}/9 completed</span>
                <span className="text-indigo-400 font-semibold flex items-center gap-1">
                  Explore Module <ChevronRight className="h-3.5 w-3.5" />
                </span>
              </div>
            </button>
          </div>
        </div>

        {/* ==================================================== */}
        {/* MANDATORY BUSINESS RULE ALERT BANNER */}
        {/* ==================================================== */}
        <div className={`p-4 rounded-2xl border text-xs sm:text-sm font-medium flex items-start gap-3 shadow-md print:hidden ${
          activeModule === "cc"
            ? "bg-amber-500/10 border-amber-500/30 text-amber-900 dark:text-amber-200"
            : "bg-indigo-500/10 border-indigo-500/30 text-indigo-900 dark:text-indigo-200"
        }`}>
          <AlertTriangle className={`h-5 w-5 shrink-0 mt-0.5 ${
            activeModule === "cc" ? "text-amber-500" : "text-indigo-500"
          }`} />
          <div className="space-y-1">
            <span className="font-extrabold uppercase tracking-wide">
              {lang === "en" ? "CRITICAL PRODUCTION DOCTRINE" : "ಅತ್ಯಂತ ಮುಖ್ಯ ನಿಯಮ"}:
            </span>
            <p className="leading-relaxed">
              {activeModule === "cc" ? T.f1BypassRule[lang] : T.zeroRemeltRule[lang]}
            </p>
          </div>
        </div>

        {/* ==================================================== */}
        {/* MODE TABS (GUIDED / CHECKLIST / QUIZ / TROUBLESHOOT) */}
        {/* ==================================================== */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200 dark:border-zinc-800 pb-3 print:hidden">
          <div className="flex flex-wrap gap-1.5">
            {[
              { id: "guided", label: T.viewGuided[lang], icon: BookOpen },
              { id: "checklist", label: T.viewChecklist[lang], icon: CheckSquare },
              { id: "quiz", label: T.viewQuiz[lang], icon: Sparkles },
              { id: "troubleshoot", label: T.viewTroubleshoot[lang], icon: AlertTriangle },
              { id: "glossary", label: T.viewGlossary[lang], icon: HelpCircle },
              { id: "print", label: T.viewPrint[lang], icon: Printer }
            ].map((tabItem) => {
              const Icon = tabItem.icon;
              return (
                <button
                  key={tabItem.id}
                  type="button"
                  onClick={() => setViewMode(tabItem.id as any)}
                  className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                    viewMode === tabItem.id
                      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-sm"
                      : "text-zinc-600 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {tabItem.label}
                </button>
              );
            })}
          </div>

          {/* Animation Controls when in Guided mode */}
          {viewMode === "guided" && (
            <div className="flex items-center gap-1 bg-zinc-100 dark:bg-zinc-800 p-1 rounded-xl border border-zinc-200 dark:border-zinc-700 text-xs">
              <button
                type="button"
                onClick={() => setIsPlaying(!isPlaying)}
                className={`px-2.5 py-1 rounded-lg font-bold flex items-center gap-1 ${
                  isPlaying
                    ? "bg-rose-500 text-white"
                    : "bg-emerald-500 text-white"
                }`}
                title={isPlaying ? "Pause Animation" : "Auto-Play Steps"}
              >
                {isPlaying ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
                <span>{isPlaying ? (lang === "en" ? "Pause" : "ವಿರಾಮ") : (lang === "en" ? "Play Flow" : "ಪ್ಲೇ")}</span>
              </button>
              <button
                type="button"
                onClick={() => { setStep(1); setIsPlaying(false); }}
                className="p-1 rounded-lg hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-600 dark:text-zinc-300"
                title="Restart Flow"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>

        {/* ==================================================== */}
        {/* VIEW 1: GUIDED STEP-BY-STEP LEARNING MODE */}
        {/* ==================================================== */}
        {viewMode === "guided" && (
          <div className="space-y-6">

            {/* ANIMATED PIPELINE STEP BAR */}
            <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-2xl p-4 shadow-sm overflow-x-auto">
              <div className="min-w-[700px] flex items-center justify-between relative">
                {/* Connecting background line */}
                <div className="absolute top-1/2 left-6 right-6 h-1 bg-zinc-200 dark:bg-zinc-800 -translate-y-1/2 z-0" />
                <div
                  className="absolute top-1/2 left-6 h-1 bg-cyan-500 -translate-y-1/2 z-0 transition-all duration-500"
                  style={{ width: `${((step - 1) / 5) * 94}%` }}
                />

                {(activeModule === "cc" ? [
                  { num: 1, title: "Inward & Mill MTC", label: "ಬಾರ್ ಇನ್‌ವರ್ಡ್" },
                  { num: 2, title: "WO & Routing", label: "ಪ್ಲಾನಿಂಗ್" },
                  { num: 3, title: "Bar Allocation", label: "ರಿಸರ್ವೇಶನ್" },
                  { num: 4, title: "Bandsaw Cutting", label: "ಕಟಿಂಗ್" },
                  { num: 5, title: "Gate & F1 Bypass", label: "ಗೇಟ್ & F2 ಜಮೆ" },
                  { num: 6, title: "Traceability", label: "ಟ್ರೇಸೇಬಿಲಿಟಿ" }
                ] : [
                  { num: 1, title: "Part Mapping", label: "ಭಾಗ ಮ್ಯಾಪಿಂಗ್" },
                  { num: 2, title: "Conversion WO", label: "WO ರಚನೆ" },
                  { num: 3, title: "Check Eligibility", label: "ಅರ್ಹತೆ" },
                  { num: 4, title: "Execute Debit", label: "ಮರುಹಂಚಿಕೆ" },
                  { num: 5, title: "Verify Lineage", label: "ಪರಿಶೀಲನೆ" },
                  { num: 6, title: "Move to Shop", label: "ಉತ್ಪಾದನೆ" }
                ]).map((s) => (
                  <button
                    key={s.num}
                    type="button"
                    onClick={() => { setStep(s.num); setIsPlaying(false); }}
                    className={`relative z-10 flex flex-col items-center gap-1.5 focus:outline-none transition-transform ${
                      step === s.num ? "scale-110" : "hover:scale-105"
                    }`}
                  >
                    <div
                      className={`w-9 h-9 rounded-full flex items-center justify-center font-bold text-xs transition-all shadow-md ${
                        step === s.num
                          ? "bg-cyan-500 text-zinc-950 ring-4 ring-cyan-500/30"
                          : step > s.num
                          ? "bg-emerald-500 text-white"
                          : "bg-zinc-100 dark:bg-zinc-800 text-zinc-500 border border-zinc-300 dark:border-zinc-700"
                      }`}
                    >
                      {step > s.num ? <Check className="h-4 w-4" /> : s.num}
                    </div>
                    <span className={`text-[11px] font-bold ${
                      step === s.num ? "text-cyan-600 dark:text-cyan-400" : "text-zinc-500"
                    }`}>
                      {lang === "en" ? s.title : s.label}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* STEP DETAIL CARD */}
            {activeModule === "cc" ? (
              // ==========================================
              // CONTINUOUS CASTING STEPS (1 TO 6)
              // ==========================================
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
                
                {/* STEP 1: MATERIAL INWARD */}
                {step === 1 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-amber-500 uppercase tracking-wider">Step 1 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Material Inward & Bar Registration" : "ವಸ್ತು ಇನ್‌ವರ್ಡ್ ಮತ್ತು ಬಾರ್ ನೋಂದಣಿ"}
                        </h2>
                      </div>
                      <Link
                        href="/continuous-casting/inward"
                        className="px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <PackageCheck className="h-3.5 w-3.5" />
                        <span>Open Screen: /continuous-casting/inward</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "What You Must Do on Screen:" : "ಆಪರೇಟರ್ ಮಾಡಬೇಕಾದ ಕೆಲಸ:"}
                          </strong>
                          <ol className="list-decimal list-inside space-y-1.5 text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            <li>Open Continuous Casting Inward modal (click <strong>"+ New Inward"</strong>).</li>
                            <li>Select the certified Material Code (e.g. <code>CC-CI-85-ROUND</code>) with grade <strong>SG 450-M</strong> or <strong>SG 500-7</strong>.</li>
                            <li>Enter the supplier delivery note / invoice reference and inward date.</li>
                            <li>Enter the <strong>Heat Number / Mill Test Certificate (MTC)</strong> stamped on the physical bars.</li>
                            <li>Record physical dimensions: <strong>OD (Outer Diameter)</strong>, optional <strong>ID</strong> (for hollow bars), length (mm), and declared pieces.</li>
                            <li>Click <strong>Save Inward</strong> to register physical bars into inventory.</li>
                          </ol>
                        </div>

                        {/* Example Box */}
                        <div className="bg-cyan-50 dark:bg-cyan-950/20 border border-cyan-200 dark:border-cyan-800/50 p-4 rounded-2xl text-xs space-y-1.5">
                          <span className="font-bold text-cyan-800 dark:text-cyan-300 uppercase tracking-wider text-[10px] block">
                            [TRAINING EXAMPLE - NOT LIVE PRODUCTION]
                          </span>
                          <div className="font-mono text-zinc-700 dark:text-zinc-300 space-y-1">
                            <div>• Material: <span className="font-bold text-cyan-700 dark:text-cyan-300">CC-CI-85-ROUND (SG 500-7)</span></div>
                            <div>• Heat / MTC: <span className="font-bold text-cyan-700 dark:text-cyan-300">HT-2026-X892</span></div>
                            <div>• Dimensions: <span className="font-bold">OD: 85 mm | Length: 3000 mm | Weight: 122.5 kg</span></div>
                            <div>• Invoice Ref: <span className="font-bold">INV-9921</span> | Location: <span className="font-bold">BAY-CC-01</span></div>
                          </div>
                        </div>
                      </div>

                      {/* Visual Bar Illustration */}
                      <div className="bg-zinc-950 rounded-2xl p-6 border border-zinc-800 flex flex-col justify-center items-center text-center space-y-4">
                        <span className="text-[11px] font-bold text-zinc-400 uppercase tracking-widest">
                          Physical Continuous Cast Bar Anatomy
                        </span>
                        
                        {/* SVG Drawing of Bar */}
                        <div className="w-full max-w-sm py-4">
                          <svg viewBox="0 0 400 120" className="w-full h-auto drop-shadow-lg">
                            <defs>
                              <linearGradient id="barGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                                <stop offset="0%" stopColor="#64748b" />
                                <stop offset="50%" stopColor="#94a3b8" />
                                <stop offset="100%" stopColor="#334155" />
                              </linearGradient>
                            </defs>
                            {/* Cylinder Body */}
                            <rect x="50" y="25" width="280" height="70" rx="0" fill="url(#barGrad)" stroke="#cbd5e1" strokeWidth="2" />
                            {/* Cylinder Back / End */}
                            <ellipse cx="330" cy="60" rx="20" ry="35" fill="#475569" stroke="#cbd5e1" strokeWidth="2" />
                            {/* Cylinder Front End Face */}
                            <ellipse cx="50" cy="60" rx="20" ry="35" fill="#64748b" stroke="#cbd5e1" strokeWidth="2" />
                            {/* Stamped Heat Tag */}
                            <rect x="90" y="45" width="110" height="30" rx="4" fill="#0f172a" stroke="#38bdf8" strokeWidth="1.5" />
                            <text x="145" y="64" fill="#38bdf8" fontSize="10" fontFamily="monospace" fontWeight="bold" textAnchor="middle">
                              HT-2026-X892
                            </text>
                            {/* Dimension Arrows */}
                            <line x1="50" y1="108" x2="330" y2="108" stroke="#f59e0b" strokeWidth="1.5" markerEnd="url(#arrow)" />
                            <text x="190" y="118" fill="#f59e0b" fontSize="10" fontWeight="bold" textAnchor="middle">
                              Length: 3000 mm
                            </text>
                            <line x1="20" y1="25" x2="20" y2="95" stroke="#10b981" strokeWidth="1.5" />
                            <text x="15" y="65" fill="#10b981" fontSize="10" fontWeight="bold" textAnchor="end">
                              OD: 85 mm
                            </text>
                          </svg>
                        </div>

                        <div className="grid grid-cols-2 gap-2 text-left w-full text-[11px] bg-zinc-900/90 p-3 rounded-xl border border-zinc-800">
                          <div>
                            <span className="text-zinc-500 block">Expected Result:</span>
                            <span className="text-emerald-400 font-bold">✓ Unit in Stock: AVAILABLE</span>
                          </div>
                          <div>
                            <span className="text-zinc-500 block">Common Operator Mistake:</span>
                            <span className="text-rose-400 font-bold">⚠ Mismatched MTC heat number</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 2: PLANNING & ROUTING */}
                {step === 2 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-amber-500 uppercase tracking-wider">Step 2 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Work Order Selection & Routing Creation" : "ವರ್ಕ್ ಆರ್ಡರ್ ಆಯ್ಕೆ ಮತ್ತು ರೂಟಿಂಗ್ ರಚನೆ"}
                        </h2>
                      </div>
                      <Link
                        href="/continuous-casting/planning"
                        className="px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <CalendarClock className="h-3.5 w-3.5" />
                        <span>Open Screen: /continuous-casting/planning</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "Standard Operating Procedure:" : "ಕಾರ್ಯವಿಧಾನ:"}
                          </strong>
                          <ul className="list-disc list-inside space-y-1.5 text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            <li>Select Work Order (e.g. <code>WO-16998</code>) using the Work Order selector.</li>
                            <li>System displays current routing versions and material requirement.</li>
                            <li>If no active routing exists, click <strong>"Create Routing"</strong>.</li>
                            <li>Enter target blank length: <code>Finished Axial Length + Machining Stock A + Stock B</code>.</li>
                            <li>Set saw kerf allowance (standard: <strong>3 mm</strong>) and facing end trim (standard: <strong>25 mm</strong>).</li>
                            <li>Save routing and verify its status is <strong>ACTIVE (v1)</strong>.</li>
                          </ul>
                        </div>

                        {/* Formula Callout */}
                        <div className="bg-slate-900 border border-slate-700 p-4 rounded-2xl text-xs space-y-2 text-white font-mono">
                          <span className="text-[10px] font-bold text-amber-400 uppercase tracking-widest block">
                            Integer-mm Calculation Formula (Backend Enforced)
                          </span>
                          <div className="text-cyan-300">
                            Blank Length = Finished_Len + Stock_A + Stock_B
                          </div>
                          <div className="text-emerald-300">
                            Gross Length = (Planned_Blanks × Blank_Len) + (Cuts × Kerf) + End_Trim
                          </div>
                        </div>
                      </div>

                      {/* Sample Work Order Card */}
                      <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800 space-y-4">
                        <div className="flex items-center justify-between border-b border-zinc-800 pb-3">
                          <div className="flex items-center gap-2">
                            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse" />
                            <span className="font-mono text-sm font-bold text-white">WO-16998 [EXAMPLE]</span>
                          </div>
                          <Badge variant="green" size="sm">ROUTING ACTIVE</Badge>
                        </div>

                        <div className="grid grid-cols-2 gap-3 text-xs">
                          <div className="bg-zinc-800/60 p-2.5 rounded-xl">
                            <span className="text-zinc-400 block text-[10px]">Customer Part No</span>
                            <span className="font-mono font-bold text-white">MIL-8820-BRG</span>
                          </div>
                          <div className="bg-zinc-800/60 p-2.5 rounded-xl">
                            <span className="text-zinc-400 block text-[10px]">Casting Process</span>
                            <span className="font-bold text-amber-400">CONTINUOUS (F1 Bypassed)</span>
                          </div>
                          <div className="bg-zinc-800/60 p-2.5 rounded-xl">
                            <span className="text-zinc-400 block text-[10px]">Target Blank Length</span>
                            <span className="font-mono font-bold text-white">145 mm (140 + 2.5 + 2.5)</span>
                          </div>
                          <div className="bg-zinc-800/60 p-2.5 rounded-xl">
                            <span className="text-zinc-400 block text-[10px]">Planned Quantity</span>
                            <span className="font-mono font-bold text-white">19 Blanks</span>
                          </div>
                        </div>

                        <div className="p-3 bg-amber-500/10 border border-amber-500/20 rounded-xl text-[11px] text-amber-300">
                          <strong>Expected Result:</strong> Active routing certified. Proceed to Stock Allocation.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 3: ALLOCATION & RESERVATION */}
                {step === 3 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-amber-500 uppercase tracking-wider">Step 3 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Stock Allocation & Bar Reservation" : "ಸ್ಟಾಕ್ ಹಂಚಿಕೆ ಮತ್ತು ಬಾರ್ ರಿಸರ್ವೇಶನ್"}
                        </h2>
                      </div>
                      <Link
                        href="/continuous-casting/planning"
                        className="px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <CalendarClock className="h-3.5 w-3.5" />
                        <span>Open Screen: /continuous-casting/planning</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "How Allocation & Reservation Works:" : "ಹಂಚಿಕೆ ಮತ್ತು ರಿಸರ್ವೇಶನ್ ಕಾರ್ಯವಿಧಾನ:"}
                          </strong>
                          <p className="text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            Under the active routing, click <strong>"+ Add Allocation"</strong>. Enter the planned blank count (e.g. 19 pcs). Then open the <strong>Reservation Panel</strong> to bind specific physical stock bar units to this Work Order.
                          </p>
                          <div className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800/50 rounded-xl text-amber-800 dark:text-amber-300">
                            <strong>Locking Rule:</strong> Once a bar unit is reserved for WO-16998, its status becomes <code>RESERVED</code>. It is locked against duplicate claims and cannot be consumed by competing orders.
                          </div>
                        </div>

                        <div className="p-4 bg-zinc-900 rounded-2xl border border-zinc-800 text-xs space-y-2">
                          <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest block">
                            Stock Unit Status Lifecycle
                          </span>
                          <div className="flex items-center gap-2 text-zinc-300 font-mono text-[11px]">
                            <span className="px-2 py-0.5 rounded bg-zinc-800 text-zinc-300">AVAILABLE</span>
                            <span>→</span>
                            <span className="px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30">RESERVED</span>
                            <span>→</span>
                            <span className="px-2 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30">CUT_CONSUMED</span>
                          </div>
                        </div>
                      </div>

                      {/* Visual Bar Lock Animation Card */}
                      <div className="bg-gradient-to-br from-zinc-900 to-slate-900 p-6 rounded-2xl border border-zinc-800 flex flex-col justify-between space-y-4">
                        <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
                          <span className="text-xs font-bold text-zinc-300">Allocated Bar Unit</span>
                          <Badge variant="amber" size="sm">LOCKED TO WO-16998</Badge>
                        </div>

                        <div className="bg-zinc-950 p-4 rounded-xl border border-amber-500/30 space-y-2">
                          <div className="flex items-center justify-between text-xs font-mono">
                            <span className="text-amber-400 font-bold">BAR-UNIT-00892</span>
                            <span className="text-zinc-400">Heat: HT-2026-X892</span>
                          </div>
                          <div className="w-full bg-zinc-800 h-3 rounded-full overflow-hidden flex">
                            <div className="bg-amber-500 h-full w-[85%]" title="Reserved Length: 2812 mm" />
                            <div className="bg-zinc-700 h-full w-[15%]" title="Unallocated End Trim: 188 mm" />
                          </div>
                          <div className="flex justify-between text-[10px] text-zinc-400 font-mono">
                            <span>Reserved: 2812 mm (19 blanks)</span>
                            <span>Trim / Drop: 188 mm</span>
                          </div>
                        </div>

                        <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-[11px] text-emerald-300">
                          <strong>Verification:</strong> Bar unit successfully reserved. Cutting machine operator can now safely initiate CUT_CONSUME.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 4: SAW CUTTING & CONSUMPTION */}
                {step === 4 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-amber-500 uppercase tracking-wider">Step 4 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Bandsaw Cutting & Consumption (CUT_CONSUME)" : "ಬ್ಯಾಂಡ್‌ಸಾ ಕಟಿಂಗ್ ಮತ್ತು ಬಳಕೆ (CUT_CONSUME)"}
                        </h2>
                      </div>
                      <Link
                        href="/continuous-casting/cutting"
                        className="px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <Cog className="h-3.5 w-3.5" />
                        <span>Open Screen: /continuous-casting/cutting</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "Physical Cutting & Entry Procedure:" : "ಕಟಿಂಗ್ ಮತ್ತು ಎಂಟ್ರಿ ವಿಧಾನ:"}
                          </strong>
                          <ol className="list-decimal list-inside space-y-1.5 text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            <li>Open Cutting screen and select the Work Order.</li>
                            <li>Click <strong>"Start Cut Consumption (CUT_CONSUME)"</strong> to record total bar length consumed.</li>
                            <li>Perform precision bandsaw cutting according to safety SOPs (coolant on, blade tension calibrated).</li>
                            <li>In the Cut Result panel, record:
                              <ul className="list-disc list-inside ml-4 mt-1 space-y-1 text-zinc-500">
                                <li><code>Actual Good Blanks</code> (usable pieces)</li>
                                <li><code>Rejected Blanks</code> (if any defect occurred)</li>
                                <li><code>Actual Cuts</code> (saw strokes)</li>
                                <li><code>End Trim (mm)</code> (stub facing)</li>
                              </ul>
                            </li>
                            <li>Review inputs before final submit.</li>
                          </ol>
                        </div>

                        <div className="bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-900/50 p-3.5 rounded-2xl text-xs text-rose-800 dark:text-rose-300">
                          <strong>Common Operator Mistake:</strong> Entering more blanks than physical bar length can yield, or entering 0 cuts. System will reject mathematically impossible entries.
                        </div>
                      </div>

                      {/* Live Bandsaw Yield Simulator */}
                      <div className="bg-zinc-900 border border-zinc-800 p-5 rounded-2xl space-y-4 text-xs">
                        <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
                          <span className="font-bold text-white flex items-center gap-1.5">
                            <Cog className="h-4 w-4 text-amber-500" /> Interactive Saw Yield Calculator
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">Live Simulator</span>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Bar Length (mm)</label>
                            <input
                              type="number"
                              value={barLen}
                              onChange={(e) => setBarLen(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Bar OD (mm)</label>
                            <input
                              type="number"
                              value={barDia}
                              onChange={(e) => setBarDia(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Blank Cut Length (mm)</label>
                            <input
                              type="number"
                              value={cutLen}
                              onChange={(e) => setCutLen(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Saw Kerf Blade (mm)</label>
                            <input
                              type="number"
                              value={kerf}
                              onChange={(e) => setKerf(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                        </div>

                        <div className="grid grid-cols-3 gap-2 text-center pt-2 border-t border-zinc-800">
                          <div className="bg-zinc-800/80 p-2 rounded-xl">
                            <span className="text-[10px] text-zinc-400 block">Good Blanks</span>
                            <span className="text-base font-black text-cyan-400">{calcGoodBlanks} pcs</span>
                          </div>
                          <div className="bg-zinc-800/80 p-2 rounded-xl">
                            <span className="text-[10px] text-zinc-400 block">Material Yield</span>
                            <span className="text-base font-black text-emerald-400">{calcYieldPct}%</span>
                          </div>
                          <div className="bg-zinc-800/80 p-2 rounded-xl">
                            <span className="text-[10px] text-zinc-400 block">Remaining Stub</span>
                            <span className="text-base font-black text-amber-400">{calcScrapMm} mm</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 5: SUBMIT & RECONCILE (DUAL BRANCH) */}
                {step === 5 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-amber-500 uppercase tracking-wider">Step 5 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Material Gate Validation & F1 Bypass Release" : "ಮೆಟೀರಿಯಲ್ ಗೇಟ್ ಪರಿಶೀಲನೆ ಮತ್ತು F1 ಬೈಪಾಸ್ ಬಿಡುಗಡೆ"}
                        </h2>
                      </div>
                      <Link
                        href="/continuous-casting/cutting"
                        className="px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <ShieldAlert className="h-3.5 w-3.5" />
                        <span>Open Screen: /continuous-casting/cutting</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="space-y-4">
                      <p className="text-xs text-zinc-600 dark:text-zinc-300">
                        When you submit the cut record, the backend executes an instantaneous mathematical reconciliation.
                        The workflow branches into two possible outcomes:
                      </p>

                      {/* DUAL BRANCH DECISION TREE */}
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {/* SUCCESS BRANCH */}
                        <div className="p-5 rounded-2xl bg-emerald-500/10 border-2 border-emerald-500/40 space-y-3">
                          <div className="flex items-center gap-2">
                            <CheckCircle2 className="h-5 w-5 text-emerald-500" />
                            <h3 className="font-extrabold text-sm text-emerald-800 dark:text-emerald-300">
                              SUCCESS BRANCH (Reconciled)
                            </h3>
                          </div>
                          <ul className="text-xs space-y-2 text-zinc-700 dark:text-zinc-300 leading-relaxed">
                            <li>• <strong>Condition:</strong> <code>consumed_length_mm == required_length_mm</code> (Variance = 0 mm).</li>
                            <li>• Status marked as <strong>RECONCILED</strong>.</li>
                            <li>• <strong>F1 is Automatically Bypassed:</strong> No fettling, no grinding entry needed.</li>
                            <li>• <strong>F2 WIP Credited:</strong> Accepted good blanks (e.g. 19 pcs) are credited directly to Stage F2 (Machining).</li>
                            <li>• Machining operators can immediately start CNC turning/milling.</li>
                          </ul>
                          <div className="bg-emerald-500/20 p-2.5 rounded-xl font-mono text-[11px] text-emerald-400 font-bold text-center">
                            ✓ READY FOR F2 MACHINING SHOP FLOOR
                          </div>
                        </div>

                        {/* FAILURE BRANCH */}
                        <div className="p-5 rounded-2xl bg-rose-500/10 border-2 border-rose-500/40 space-y-3">
                          <div className="flex items-center gap-2">
                            <XCircle className="h-5 w-5 text-rose-500" />
                            <h3 className="font-extrabold text-sm text-rose-800 dark:text-rose-300">
                              FAILURE / VARIANCE BRANCH
                            </h3>
                          </div>
                          <ul className="text-xs space-y-2 text-zinc-700 dark:text-zinc-300 leading-relaxed">
                            <li>• <strong>Condition:</strong> <code>consumed &gt; required</code> or blanks exceed planned limit.</li>
                            <li>• Status marked as <strong>VARIANCE</strong> or <strong>BLOCKED</strong>.</li>
                            <li>• <strong>CRITICAL RULE:</strong> STOP workflow immediately. Read error message.</li>
                            <li>• Escalate to Planning / Production Supervisor to audit saw log.</li>
                            <li>• <strong>NEVER</strong> attempt to manually alter StageWIP or bypass the Material Gate.</li>
                          </ul>
                          <div className="bg-rose-500/20 p-2.5 rounded-xl font-mono text-[11px] text-rose-400 font-bold text-center">
                            ✗ MATERIAL GATE BLOCKED - ESCALATE TO PLANNER
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 6: TRACEABILITY */}
                {step === 6 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-amber-500 uppercase tracking-wider">Step 6 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Full Genealogy & Heat Traceability" : "ಸಂಪೂರ್ಣ ವಂಶಾವಳಿ ಮತ್ತು ಹೀಟ್ ಟ್ರೇಸೇಬಿಲಿಟಿ"}
                        </h2>
                      </div>
                      <Link
                        href="/continuous-casting/traceability"
                        className="px-3 py-1.5 rounded-xl bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/30 hover:bg-amber-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <GitMerge className="h-3.5 w-3.5" />
                        <span>Open Screen: /continuous-casting/traceability</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="space-y-4">
                      <p className="text-xs text-zinc-600 dark:text-zinc-300 leading-relaxed">
                        Continuous casting guarantees complete end-to-end traceability from the molten iron chemistry to the finished customer component. Any inspector can query the system across 3 distinct search dimensions:
                      </p>

                      {/* Worked Example Diagram */}
                      <div className="bg-zinc-950 p-6 rounded-2xl border border-zinc-800 text-white space-y-4">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest block">
                          Worked Traceability Genealogy (Interactive Deep Link)
                        </span>

                        <div className="grid grid-cols-1 sm:grid-cols-5 gap-2 text-center text-xs">
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-amber-400 block font-bold">1. Mill Heat</span>
                            <span className="font-mono font-bold text-white">HT-2026-X892</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Spectro MTC</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-cyan-400 block font-bold">2. Bar Unit</span>
                            <span className="font-mono font-bold text-white">BAR-00892</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">3000 mm × 85 OD</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-indigo-400 block font-bold">3. Cut Record</span>
                            <span className="font-mono font-bold text-white">CUT-1029</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">19 Good Blanks</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-purple-400 block font-bold">4. Machining WO</span>
                            <span className="font-mono font-bold text-white">WO-16998</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Stage F2 CNC</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-emerald-400 block font-bold">5. Dispatch</span>
                            <span className="font-mono font-bold text-white">DISP-4401</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Customer OAR</span>
                          </div>
                        </div>

                        <div className="p-3 bg-zinc-900/80 rounded-xl text-xs text-zinc-300 flex items-center justify-between">
                          <span>Search By: <strong>?heat=HT-2026-X892</strong> or <strong>?wo=WO-16998</strong></span>
                          <span className="text-cyan-400 font-mono text-[11px]">100% Audit Compliance Certified</span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

              </div>
            ) : (
              // ==========================================
              // WORK ORDER CONVERSION STEPS (1 TO 6)
              // ==========================================
              <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
                
                {/* STEP 1: PART MAPPING */}
                {step === 1 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">Step 1 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Conversion Part Mapping (Planning Master)" : "ಪರಿವರ್ತನೆ ಭಾಗ ಮ್ಯಾಪಿಂಗ್"}
                        </h2>
                      </div>
                      <Link
                        href="/planning/conversion-mapping"
                        className="px-3 py-1.5 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <Shuffle className="h-3.5 w-3.5" />
                        <span>Open Screen: /planning/conversion-mapping</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "Authoritative Rule for Conversion Mapping:" : "ಮ್ಯಾಪಿಂಗ್ ಕಡ್ಡಾಯ ನಿಯಮ:"}
                          </strong>
                          <p className="text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            No part can ever be converted to another part unless an <strong>ACTIVE mapping row exists in the database</strong>. Even a part converting to itself (SAME_PART) mandates an explicit, active row.
                          </p>
                          <ul className="list-disc list-inside space-y-1 text-zinc-500 dark:text-zinc-400">
                            <li><strong>SAME_PART:</strong> Source part and destination part are identical (e.g. <code>MIL107 → MIL107</code>). Factor is strictly 1.0.</li>
                            <li><strong>PART_TO_PART:</strong> Source and destination parts differ (e.g. <code>PMC82 → PMC82-A</code>). Requires geometric suitability.</li>
                          </ul>
                        </div>

                        <div className="p-3 bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800/50 rounded-xl text-xs text-amber-800 dark:text-amber-300">
                          <strong>Role Permission:</strong> Only Authorized Planners or Quality Managers can create or activate mapping rules. Operators cannot invent mappings on the fly.
                        </div>
                      </div>

                      {/* Mapping Example Card */}
                      <div className="bg-zinc-900 p-5 rounded-2xl border border-zinc-800 space-y-4 text-xs">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest block">
                          Verified Mapping Master Example [TRAINING VIEW]
                        </span>

                        <div className="bg-zinc-950 p-4 rounded-xl border border-zinc-800 space-y-3">
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-cyan-400 font-bold">PMC82 → PMC82-A</span>
                            <Badge variant="green" size="sm">ACTIVE</Badge>
                          </div>
                          <div className="grid grid-cols-2 gap-2 text-[11px] text-zinc-400 font-mono">
                            <div>Type: <span className="text-white font-bold">PART_TO_PART</span></div>
                            <div>Factor: <span className="text-white font-bold">1.0</span></div>
                            <div>Created By: <span className="text-white font-bold">Planner</span></div>
                            <div>Status: <span className="text-emerald-400 font-bold">Approved</span></div>
                          </div>
                        </div>

                        <div className="p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl text-[11px] text-emerald-300">
                          <strong>Expected Result:</strong> Mapping row found and active. System permits conversion initiation.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 2: CONVERSION REQUEST */}
                {step === 2 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">Step 2 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Conversion Form Fields & Request Initiation" : "ಪರಿವರ್ತನೆ ಫಾರ್ಮ್ ಮತ್ತು ವಿನಂತಿ ಆರಂಭ"}
                        </h2>
                      </div>
                      <Link
                        href="/planning/conversion"
                        className="px-3 py-1.5 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <ArrowRightLeft className="h-3.5 w-3.5" />
                        <span>Open Screen: /planning/conversion</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "Every Field Explained:" : "ಫಾರ್ಮ್ ವಿವರಣೆ:"}
                          </strong>
                          <ul className="space-y-2 text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            <li>• <strong>Conversion WO Name:</strong> Unique identifier for child order (e.g. <code>C-0021</code>).</li>
                            <li>• <strong>Source Work Order:</strong> Originating order containing surplus/cancelled stock (e.g. <code>WO-15878</code>).</li>
                            <li>• <strong>Destination OAR:</strong> Customer Order Acknowledgement requiring parts (e.g. <code>OAR-8228</code>).</li>
                            <li>• <strong>Quantity to Convert:</strong> Number of physical pieces to transfer (must be &gt; 0 and &le; source WIP).</li>
                            <li>• <strong>Entry Stage:</strong> Stage where material enters on Child WO (<code>F1, F2, F3, SP, FI</code>).</li>
                            <li>• <strong>Reason:</strong> Legitimate business justification for audit trail.</li>
                          </ul>
                        </div>
                      </div>

                      {/* Simulated Form Card */}
                      <div className="bg-zinc-900 p-5 rounded-2xl border border-zinc-800 space-y-3 text-xs">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest block">
                          Form Entry Example [TRAINING SIMULATION]
                        </span>

                        <div className="space-y-2">
                          <div className="bg-zinc-950 p-2.5 rounded-xl border border-zinc-800 flex justify-between">
                            <span className="text-zinc-400">Child WO Name:</span>
                            <span className="font-mono font-bold text-cyan-400">C-0021</span>
                          </div>
                          <div className="bg-zinc-950 p-2.5 rounded-xl border border-zinc-800 flex justify-between">
                            <span className="text-zinc-400">Source WO:</span>
                            <span className="font-mono font-bold text-white">WO-15878</span>
                          </div>
                          <div className="bg-zinc-950 p-2.5 rounded-xl border border-zinc-800 flex justify-between">
                            <span className="text-zinc-400">Destination OAR:</span>
                            <span className="font-mono font-bold text-white">OAR-8228</span>
                          </div>
                          <div className="bg-zinc-950 p-2.5 rounded-xl border border-zinc-800 flex justify-between">
                            <span className="text-zinc-400">Quantity:</span>
                            <span className="font-mono font-bold text-emerald-400">100 Pieces</span>
                          </div>
                          <div className="bg-zinc-950 p-2.5 rounded-xl border border-zinc-800 flex justify-between">
                            <span className="text-zinc-400">Entry Stage:</span>
                            <span className="font-mono font-bold text-amber-400">F2 (Machining)</span>
                          </div>
                        </div>

                        <div className="p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-xl text-[11px] text-cyan-300">
                          <strong>Note:</strong> Double check that source WO actually has 100 pieces ready at the debit stage.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 3: VERIFY ELIGIBILITY */}
                {step === 3 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">Step 3 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Pre-Execution Eligibility & Envelope Verification" : "ಕಾರ್ಯಗತಗೊಳಿಸುವ ಮುನ್ನ ಅರ್ಹತೆ ಪರಿಶೀಲನೆ"}
                        </h2>
                      </div>
                      <Badge variant="amber" size="sm">CRITICAL SAFETY CHECK</Badge>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div className="space-y-4">
                        <div className="bg-zinc-50 dark:bg-zinc-800/50 p-4 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 text-xs space-y-2">
                          <strong className="text-zinc-900 dark:text-white font-bold block">
                            {lang === "en" ? "Must Verify Before Submitting:" : "ಸಲ್ಲಿಸುವ ಮುನ್ನ ಪರಿಶೀಲಿಸಬೇಕಾದ ಅಂಶಗಳು:"}
                          </strong>
                          <ul className="space-y-1.5 text-zinc-600 dark:text-zinc-300 leading-relaxed">
                            <li>☑ Source part is compatible with destination part.</li>
                            <li>☑ Active ConversionPartMapping row is verified in DB.</li>
                            <li>☑ Source WO StageWIP has &ge; 100 eligible pieces (no pending quality hold).</li>
                            <li>☑ Machining envelope satisfies:
                              <div className="font-mono text-[11px] text-cyan-600 dark:text-cyan-400 ml-4 mt-1">
                                OD_source &ge; OD_dest + 3.0 mm<br />
                                Length_source &ge; Length_dest + 2.0 mm
                              </div>
                            </li>
                            <li>☑ Business reason recorded for financial and quality traceability.</li>
                          </ul>
                        </div>
                      </div>

                      {/* Interactive Envelope Simulator */}
                      <div className="bg-zinc-900 border border-zinc-800 p-5 rounded-2xl space-y-4 text-xs">
                        <div className="flex items-center justify-between border-b border-zinc-800 pb-2">
                          <span className="font-bold text-white flex items-center gap-1.5">
                            <Sparkles className="h-4 w-4 text-indigo-400" /> Interactive Envelope Simulator
                          </span>
                          <span className="text-[10px] text-zinc-400 font-mono">Live Validation</span>
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Source Bar OD (mm)</label>
                            <input
                              type="number"
                              value={srcOD}
                              onChange={(e) => setSrcOD(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Target Part OD (mm)</label>
                            <input
                              type="number"
                              value={dstOD}
                              onChange={(e) => setDstOD(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Source Length (mm)</label>
                            <input
                              type="number"
                              value={srcLen}
                              onChange={(e) => setSrcLen(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                          <div>
                            <label className="text-zinc-400 block text-[10px] mb-1">Target Length (mm)</label>
                            <input
                              type="number"
                              value={dstLen}
                              onChange={(e) => setDstLen(Number(e.target.value))}
                              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-white font-mono text-xs"
                            />
                          </div>
                        </div>

                        <div className={`p-3 rounded-xl border text-center font-bold text-xs ${
                          isConvQualified
                            ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
                            : "bg-rose-500/20 border-rose-500/40 text-rose-300"
                        }`}>
                          {isConvQualified ? (
                            <span>✓ ENVELOPE CLEARED: OD Margin: +{odDiff.toFixed(1)} mm | Length: +{lenDiff.toFixed(1)} mm</span>
                          ) : (
                            <span>✗ REJECTED: Insufficient machining allowance</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 4: EXECUTE CONVERSION */}
                {step === 4 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">Step 4 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Execute Conversion & Atomic Reallocation" : "ಪರಿವರ್ತನೆ ಜಾರಿ ಮತ್ತು ಮರುಹಂಚಿಕೆ"}
                        </h2>
                      </div>
                      <Badge variant="purple" size="sm">ATOMIC DATABASE TRANSACTION</Badge>
                    </div>

                    <div className="space-y-4">
                      <p className="text-xs text-zinc-600 dark:text-zinc-300 leading-relaxed">
                        When you click <strong>"Execute Conversion"</strong>, the backend executes an atomic database transaction.
                        This is a controlled material reallocation, <strong>NOT the creation of new physical inventory</strong>:
                      </p>

                      {/* Visual Reallocation Flow */}
                      <div className="bg-zinc-950 p-6 rounded-2xl border border-zinc-800 space-y-4 text-white">
                        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 items-center">
                          {/* Source Card */}
                          <div className="bg-zinc-900 p-4 rounded-xl border border-rose-500/30 text-center space-y-1.5">
                            <span className="text-[10px] font-bold text-rose-400 uppercase">1. Source WO: WO-15878</span>
                            <div className="text-xl font-black font-mono text-white">F1 WIP: 250 pcs</div>
                            <div className="text-xs font-bold text-rose-400">-100 pcs Debited</div>
                            <div className="text-[11px] text-zinc-400 font-mono">New Balance: 150 pcs</div>
                          </div>

                          {/* Arrow Center */}
                          <div className="flex flex-col items-center justify-center text-center space-y-1">
                            <span className="text-[10px] font-bold text-amber-400 uppercase">Atomic Transfer</span>
                            <ArrowRight className="h-6 w-6 text-cyan-400 animate-pulse hidden sm:block" />
                            <span className="text-[10px] text-zinc-400 font-mono">Lineage Preserved</span>
                          </div>

                          {/* Child Destination Card */}
                          <div className="bg-zinc-900 p-4 rounded-xl border border-emerald-500/30 text-center space-y-1.5">
                            <span className="text-[10px] font-bold text-emerald-400 uppercase">2. Child WO: C-0021</span>
                            <div className="text-xl font-black font-mono text-white">F2 WIP: 0 pcs</div>
                            <div className="text-xs font-bold text-emerald-400">+100 pcs Initialized</div>
                            <div className="text-[11px] text-zinc-400 font-mono">Linked to OAR-8228</div>
                          </div>
                        </div>

                        <div className="p-3 bg-zinc-900 rounded-xl text-center text-xs text-zinc-300 font-mono">
                          Zero Re-Melt Enforced: ~55 kWh electricity conserved • 0% slag oxidation loss
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 5: VERIFY RESULTS (BEFORE VS AFTER) */}
                {step === 5 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">Step 5 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Verify Results: Before vs. After Reconciliation" : "ಫಲಿತಾಂಶ ಪರಿಶೀಲನೆ: ಮೊದಲು ಮತ್ತು ನಂತರ"}
                        </h2>
                      </div>
                      <Badge variant="green" size="sm">AUDIT RECONCILIATION</Badge>
                    </div>

                    <div className="space-y-4">
                      <p className="text-xs text-zinc-600 dark:text-zinc-300">
                        Always perform a reconciliation audit immediately following execution to confirm balances match expectations:
                      </p>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
                        {/* BEFORE CARD */}
                        <div className="bg-zinc-50 dark:bg-zinc-800/40 p-5 rounded-2xl border border-zinc-200 dark:border-zinc-700/60 space-y-3">
                          <span className="font-extrabold text-zinc-500 uppercase tracking-wider text-[11px] block">
                            STATE BEFORE CONVERSION
                          </span>
                          <div className="space-y-2 font-mono text-zinc-700 dark:text-zinc-300">
                            <div className="flex justify-between border-b border-zinc-200 dark:border-zinc-700 pb-1">
                              <span>Source WO-15878 (Stage F1):</span>
                              <strong className="text-zinc-900 dark:text-white">250 pcs</strong>
                            </div>
                            <div className="flex justify-between border-b border-zinc-200 dark:border-zinc-700 pb-1">
                              <span>Child WO C-0021:</span>
                              <strong className="text-zinc-400">DOES NOT EXIST</strong>
                            </div>
                            <div className="flex justify-between">
                              <span>Dest OAR-8228 Pending:</span>
                              <strong className="text-amber-500">100 pcs pending</strong>
                            </div>
                          </div>
                        </div>

                        {/* AFTER CARD */}
                        <div className="bg-emerald-50 dark:bg-emerald-950/20 p-5 rounded-2xl border border-emerald-200 dark:border-emerald-800/50 space-y-3">
                          <span className="font-extrabold text-emerald-700 dark:text-emerald-400 uppercase tracking-wider text-[11px] block">
                            STATE AFTER CONVERSION (VERIFIED)
                          </span>
                          <div className="space-y-2 font-mono text-zinc-700 dark:text-zinc-300">
                            <div className="flex justify-between border-b border-emerald-200 dark:border-emerald-800 pb-1">
                              <span>Source WO-15878 (Stage F1):</span>
                              <strong className="text-zinc-900 dark:text-white">150 pcs (Debited 100)</strong>
                            </div>
                            <div className="flex justify-between border-b border-emerald-200 dark:border-emerald-800 pb-1">
                              <span>Child WO C-0021 (Stage F2):</span>
                              <strong className="text-emerald-500">100 pcs Active</strong>
                            </div>
                            <div className="flex justify-between">
                              <span>Dest OAR-8228 Pending:</span>
                              <strong className="text-emerald-500">0 pcs (Fulfilled by C-0021)</strong>
                            </div>
                          </div>
                        </div>
                      </div>

                      <div className="p-3 bg-zinc-900 rounded-xl text-xs text-zinc-300 text-center font-mono">
                        Lineage Registered: <code>Child C-0021.converted_from_wo_id == WO-15878.id</code>
                      </div>
                    </div>
                  </div>
                )}

                {/* STEP 6: CONTINUE PRODUCTION */}
                {step === 6 && (
                  <div className="space-y-6">
                    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
                      <div>
                        <span className="text-xs font-bold text-indigo-500 uppercase tracking-wider">Step 6 of 6</span>
                        <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50 mt-0.5">
                          {lang === "en" ? "Production Move & Shop Floor Flow" : "ಉತ್ಪಾದನೆ ಚಲನೆ ಮತ್ತು ಮುಂದಿನ ಹಂತ"}
                        </h2>
                      </div>
                      <Link
                        href="/production/move"
                        className="px-3 py-1.5 rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-indigo-400 border border-indigo-500/30 hover:bg-indigo-500/20 text-xs font-bold flex items-center gap-1.5 transition-all"
                      >
                        <ArrowRightLeft className="h-3.5 w-3.5" />
                        <span>Open Screen: /production/move</span>
                        <ArrowRight className="h-3 w-3" />
                      </Link>
                    </div>

                    <div className="space-y-4">
                      <p className="text-xs text-zinc-600 dark:text-zinc-300 leading-relaxed">
                        Now open <strong>Move Parts (/production/move)</strong> on the shop floor terminal. Search for <code>C-0021</code>.
                        The converted pieces are waiting at the designated entry stage (Stage F2):
                      </p>

                      <div className="bg-zinc-950 p-6 rounded-2xl border border-zinc-800 text-white space-y-4">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest block">
                          Normal Shop-Floor Production Progression for Child Order C-0021
                        </span>

                        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 text-center text-xs">
                          <div className="bg-zinc-900 p-3 rounded-xl border border-emerald-500/30">
                            <span className="text-[10px] text-emerald-400 block font-bold">1. Entry Stage</span>
                            <span className="font-mono font-bold text-white">Stage F2 (100 pcs)</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Ready for CNC</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-zinc-400 block font-bold">2. Quality Stage</span>
                            <span className="font-mono font-bold text-white">Stage FI (Final Insp)</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Dimensional & CMM</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-zinc-400 block font-bold">3. Packing Stage</span>
                            <span className="font-mono font-bold text-white">Stage PACKING / BSR</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Preservative Oil & Box</span>
                          </div>
                          <div className="bg-zinc-900 p-3 rounded-xl border border-zinc-800">
                            <span className="text-[10px] text-zinc-400 block font-bold">4. Dispatch</span>
                            <span className="font-mono font-bold text-white">DISPATCH CENTER</span>
                            <span className="text-[10px] text-zinc-400 block mt-1">Fulfills OAR-8228</span>
                          </div>
                        </div>

                        <div className="p-3 bg-indigo-500/10 border border-indigo-500/20 rounded-xl text-xs text-indigo-300 text-center">
                          <strong>Conclusion:</strong> Work Order conversion cycle complete! 100% material integrity and traceability maintained.
                        </div>
                      </div>
                    </div>
                  </div>
                )}

              </div>
            )}

            {/* PREVIOUS / NEXT STEP NAVIGATION BUTTONS */}
            <div className="flex items-center justify-between pt-4 border-t border-zinc-200 dark:border-zinc-800">
              <button
                type="button"
                disabled={step <= 1}
                onClick={() => { setStep((prev) => Math.max(1, prev - 1)); setIsPlaying(false); }}
                className={`px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all ${
                  step <= 1
                    ? "opacity-40 cursor-not-allowed bg-zinc-100 dark:bg-zinc-800 text-zinc-400"
                    : "bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-800 dark:text-zinc-200"
                }`}
              >
                <ChevronLeft className="h-4 w-4" />
                <span>{lang === "en" ? "Previous Step" : "ಹಿಂದಿನ ಹಂತ"}</span>
              </button>

              <div className="text-xs font-bold text-zinc-500 font-mono">
                Step {step} of 6
              </div>

              <button
                type="button"
                disabled={step >= 6}
                onClick={() => { setStep((prev) => Math.min(6, prev + 1)); setIsPlaying(false); }}
                className={`px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5 transition-all ${
                  step >= 6
                    ? "opacity-40 cursor-not-allowed bg-zinc-100 dark:bg-zinc-800 text-zinc-400"
                    : "bg-cyan-500 hover:bg-cyan-400 text-zinc-950 font-extrabold shadow-md"
                }`}
              >
                <span>{lang === "en" ? "Next Step" : "ಮುಂದಿನ ಹಂತ"}</span>
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>

          </div>
        )}

        {/* ==================================================== */}
        {/* VIEW 2: COMPLETION CHECKLIST */}
        {/* ==================================================== */}
        {viewMode === "checklist" && (
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
              <div>
                <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50">
                  {activeModule === "cc"
                    ? (lang === "en" ? "Continuous Casting Operator Checklist" : "ನಿರಂತರ ಎರಕಹೊಯ್ಯುವಿಕೆ ಪರಿಶೀಲನಾಪಟ್ಟಿ")
                    : (lang === "en" ? "Work Order Conversion Operator Checklist" : "ವರ್ಕ್ ಆರ್ಡರ್ ಪರಿವರ್ತನೆ ಪರಿಶೀಲನಾಪಟ್ಟಿ")}
                </h2>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                  Check off each item during shift handover or operational review.
                </p>
              </div>
              <Badge variant={
                (activeModule === "cc" ? ccCheckedCount === 7 : convCheckedCount === 9) ? "green" : "amber"
              } size="md">
                {activeModule === "cc" ? `${ccCheckedCount} of 7 Completed` : `${convCheckedCount} of 9 Completed`}
              </Badge>
            </div>

            {/* Checklist Items */}
            <div className="space-y-3">
              {activeModule === "cc" ? [
                { id: "inwardChecked", title: "Correct bar and heat identity verified against Mill Test Certificate (MTC)", kn: "ಮಿಲ್ ಪರೀಕ್ಷಾ ಪ್ರಮಾಣಪತ್ರದೊಂದಿಗೆ ಬಾರ್ ಮತ್ತು ಹೀಟ್ ಸಂಖ್ಯೆ ತಾಳೆ ನೋಡಲಾಗಿದೆ" },
                { id: "routingActive", title: "Continuous casting routing created and verified in ACTIVE status", kn: "ನಿರಂತರ ಎರಕಹೊಯ್ಯುವಿಕೆ ರೂಟಿಂಗ್ ACTIVE ಸ್ಥಿತಿಯಲ್ಲಿದೆ" },
                { id: "allocationReserved", title: "Stock allocation added and physical bar unit successfully RESERVED", kn: "ಸ್ಟಾಕ್ ಹಂಚಿಕೆ ಮಾಡಿ ಭೌತಿಕ ಬಾರ್ ರಿಸರ್ವ್ ಮಾಡಲಾಗಿದೆ" },
                { id: "cutsRecorded", title: "Physical saw cutting completed according to safety SOPs and recorded via CUT_CONSUME", kn: "ಸುರಕ್ಷತಾ ಕ್ರಮಗಳೊಂದಿಗೆ ಕಟಿಂಗ್ ಮಾಡಿ CUT_CONSUME ದಾಖಲಿಸಲಾಗಿದೆ" },
                { id: "gateReconciled", title: "Material Gate validation successful (RECONCILED with variance = 0 mm)", kn: "ಮೆಟೀರಿಯಲ್ ಗೇಟ್ ಪರಿಶೀಲನೆ ಯಶಸ್ವಿ (Variance = 0 mm)" },
                { id: "f2Credited", title: "Accepted good blanks verified directly credited to Stage F2 (Machining WIP) with F1 bypassed", kn: "F1 ಬೈಪಾಸ್ ಆಗಿ ನೇರವಾಗಿ F2 ಮ್ಯಾಶಿನಿಂಗ್ WIP ಗೆ ಜಮೆ ಆಗಿದೆ" },
                { id: "traceabilityLogged", title: "Complete genealogy logged and searchable by Heat Number and Work Order", kn: "ಹೀಟ್ ಮತ್ತು WO ಮೂಲಕ ಸಂಪೂರ್ಣ ವಂಶಾವಳಿ ಟ್ರೇಸ್ ಮಾಡಲು ಲಭ್ಯವಿದೆ" }
              ].map((item) => (
                <label
                  key={item.id}
                  className="flex items-start gap-3 p-3.5 rounded-2xl border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 cursor-pointer transition-all"
                >
                  <input
                    type="checkbox"
                    checked={!!ccChecklist[item.id]}
                    onChange={(e) => setCcChecklist({ ...ccChecklist, [item.id]: e.target.checked })}
                    className="w-4 h-4 mt-0.5 rounded text-cyan-600 focus:ring-cyan-500"
                  />
                  <div className="text-xs">
                    <span className={`font-semibold block ${ccChecklist[item.id] ? "line-through text-zinc-400" : "text-zinc-800 dark:text-zinc-200"}`}>
                      {item.title}
                    </span>
                    {lang === "kn" && (
                      <span className="text-zinc-500 block text-[11px] mt-0.5">{item.kn}</span>
                    )}
                  </div>
                </label>
              )) : [
                { id: "mappingVerified", title: "Active, applicable part mapping confirmed in ConversionPartMapping master", kn: "ಪಾರ್ಟ್ ಮ್ಯಾಪಿಂಗ್ ಮಾಸ್ಟರ್‌ನಲ್ಲಿ ACTIVE ಸ್ಥಿತಿ ಖಚಿತಪಡಿಸಿಕೊಳ್ಳಲಾಗಿದೆ" },
                { id: "sourceWIPEligible", title: "Source Work Order on-hand eligible WIP confirmed at debit stage", kn: "ಮೂಲ WO ನ ಕಡಿತ ಹಂತದಲ್ಲಿ ಅಗತ್ಯ WIP ಲಭ್ಯವಿದೆ" },
                { id: "destOARConfirmed", title: "Destination customer OAR verified and open for fulfillment", kn: "ಗ್ರಾಹಕರ ಗಮ್ಯಸ್ಥಾನ OAR ತೆರೆದಿದೆ ಮತ್ತು ಪರಿಶೀಲಿಸಲಾಗಿದೆ" },
                { id: "envelopeCleared", title: "Machining envelope cleared (OD_src >= OD_dst + 3mm & Length_src >= Length_dst + 2mm)", kn: "ಮ್ಯಾಶಿನಿಂಗ್ ಅಳತೆ ಮಾನದಂಡ ಪೂರ್ಣಗೊಂಡಿದೆ (OD +3mm, Length +2mm)" },
                { id: "reasonLogged", title: "Valid business reason documented for audit trail", kn: "ಆಡಿಟ್ ಟ್ರಯಲ್‌ಗಾಗಿ ಸೂಕ್ತ ವ್ಯಾಪಾರ ಕಾರಣ ನಮೂದಿಸಲಾಗಿದೆ" },
                { id: "conversionExecuted", title: "Atomic conversion executed with zero remelting loss", kn: "ಮರುಕರಗಿಸದೆ ಪರಿವರ್ತನೆ ಯಶಸ್ವಿಯಾಗಿ ಜಾರಿಯಾಗಿದೆ" },
                { id: "sourceDebited", title: "Source WO StageWIP correctly debited by converted quantity", kn: "ಮೂಲ WO ನಿಂದ ನಿಗದಿತ ಪ್ರಮಾಣ ಕಡಿತವಾಗಿದೆ" },
                { id: "childCreated", title: "Child Conversion WO created at authorized Entry Stage", kn: "ಅನುಮೋದಿತ ಪ್ರವೇಶ ಹಂತದಲ್ಲಿ ಮಗು (Child) WO ರಚನೆಯಾಗಿದೆ" },
                { id: "lineageTracked", title: "Source-to-child lineage and destination OAR balance updated", kn: "ಮೂಲದಿಂದ ಮಗುವಿಗೆ ವಂಶಾವಳಿ ಮತ್ತು OAR ಬ್ಯಾಲೆನ್ಸ್ ಅಪ್‌ಡೇಟ್ ಆಗಿದೆ" }
              ].map((item) => (
                <label
                  key={item.id}
                  className="flex items-start gap-3 p-3.5 rounded-2xl border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/40 cursor-pointer transition-all"
                >
                  <input
                    type="checkbox"
                    checked={!!convChecklist[item.id]}
                    onChange={(e) => setConvChecklist({ ...convChecklist, [item.id]: e.target.checked })}
                    className="w-4 h-4 mt-0.5 rounded text-indigo-600 focus:ring-indigo-500"
                  />
                  <div className="text-xs">
                    <span className={`font-semibold block ${convChecklist[item.id] ? "line-through text-zinc-400" : "text-zinc-800 dark:text-zinc-200"}`}>
                      {item.title}
                    </span>
                    {lang === "kn" && (
                      <span className="text-zinc-500 block text-[11px] mt-0.5">{item.kn}</span>
                    )}
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* ==================================================== */}
        {/* VIEW 3: KNOWLEDGE CHECK (QUIZ WITH INSTANT FEEDBACK) */}
        {/* ==================================================== */}
        {viewMode === "quiz" && (
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 dark:border-zinc-800 pb-4">
              <div>
                <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50">
                  {lang === "en" ? "Knowledge Check: Operator Competency Quiz" : "ಆಪರೇಟರ್ ಜ್ಞಾನ ಪರೀಕ್ಷೆ"}
                </h2>
                <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                  Select your answers and click Submit to check your operational readiness.
                </p>
              </div>
              <Badge variant="cyan" size="md">Instant Feedback</Badge>
            </div>

            <div className="space-y-6">
              {(activeModule === "cc" ? [
                {
                  id: "q1",
                  q: "Which production stage does Continuous Casting automatically bypass?",
                  kn: "ನಿರಂತರ ಎರಕಹೊಯ್ಯುವಿಕೆಯು ಯಾವ ಹಂತವನ್ನು ಸ್ವಯಂಚಾಲಿತವಾಗಿ ಬೈಪಾಸ್ ಮಾಡುತ್ತದೆ?",
                  options: [
                    "Stage F2 (Machining)",
                    "Stage F1 (Centrifugal Melt & Fettling)",
                    "Stage FI (Final Inspection)",
                    "Stage PACKING / BSR"
                  ],
                  correct: 1,
                  explanation: "Continuous casting produces smooth, inclusion-free bars that bypass F1 completely and enter Stage F2 directly."
                },
                {
                  id: "q2",
                  q: "What should you do if the Material Gate returns a VARIANCE error after saw cutting?",
                  kn: "ಕಟಿಂಗ್ ನಂತರ ಮೆಟೀರಿಯಲ್ ಗೇಟ್ VARIANCE ದೋಷ ಬಂದರೆ ಏನು ಮಾಡಬೇಕು?",
                  options: [
                    "Manually edit StageWIP in the database to force approval",
                    "Bypass the gate and start machining anyway",
                    "STOP workflow immediately, read the error, and report to the responsible planner/supervisor",
                    "Remelt the remaining bar immediately"
                  ],
                  correct: 2,
                  explanation: "Never manually alter WIP or bypass gates. A VARIANCE indicates unaccounted stock loss and mandates supervisor audit."
                },
                {
                  id: "q3",
                  q: "When does accepted blank quantity get credited to Stage F2 WIP?",
                  kn: "ಸ್ವೀಕೃತ ಬ್ಲಾಂಕ್ಸ್ ಪ್ರಮಾಣವು ಯಾವಾಗ F2 WIP ಗೆ ಜಮೆಯಾಗುತ್ತದೆ?",
                  options: [
                    "Immediately when the raw bar arrives at inward",
                    "Only after successful Material Gate validation and zero-variance reconciliation",
                    "When the customer pays the invoice",
                    "When the bandsaw blade is replaced"
                  ],
                  correct: 1,
                  explanation: "Accepted blanks are strictly credited only after authoritative cutting reconciliation (variance = 0 mm)."
                }
              ] : [
                {
                  id: "q1",
                  q: "Can a part number convert to itself without an active mapping in ConversionPartMapping?",
                  kn: "ಸಕ್ರಿಯ ಮ್ಯಾಪಿಂಗ್ ಇಲ್ಲದೆ ಒಂದು ಭಾಗವು ತನಗೆ ತಾನೇ (SAME_PART) ಪರಿವರ್ತನೆಗೊಳ್ಳಬಹುದೇ?",
                  options: [
                    "Yes, same-part conversion is always implicitly allowed",
                    "No, every conversion (including SAME_PART) mandates an explicit ACTIVE mapping row",
                    "Only if the customer gives verbal permission",
                    "Only on night shifts"
                  ],
                  correct: 1,
                  explanation: "SAME_PART is never implicitly allowed. It must have an explicit active mapping row with factor 1.0."
                },
                {
                  id: "q2",
                  q: "Does Work Order Conversion create new physical inventory?",
                  kn: "ವರ್ಕ್ ಆರ್ಡರ್ ಪರಿವರ್ತನೆಯು ಹೊಸ ಭೌತಿಕ ದಾಸ್ತಾನನ್ನು ಸೃಷ್ಟಿಸುತ್ತದೆಯೇ?",
                  options: [
                    "Yes, it doubles the stock count",
                    "No, it is an atomic reallocation that debits source-stage WIP and initializes Child WO StageWIP",
                    "Yes, if approved by quality",
                    "It creates virtual scrap only"
                  ],
                  correct: 1,
                  explanation: "Conversion reallocates existing in-process pieces between orders without creating or melting inventory."
                },
                {
                  id: "q3",
                  q: "What is the minimum radial outer-diameter (OD) clearance required for PART_TO_PART conversion?",
                  kn: "PART_TO_PART ಪರಿವರ್ತನೆಗೆ ಕನಿಷ್ಠ ಎಷ್ಟು OD ಮಾರ್ಜಿನ್ ಬೇಕು?",
                  options: [
                    "0 mm (Exact match)",
                    "At least 3.0 mm (OD_source >= OD_dest + 3mm)",
                    "50 mm",
                    "0.1 mm"
                  ],
                  correct: 1,
                  explanation: "To allow proper CNC clean-up and machining skin removal, OD_source must exceed OD_dest by at least 3.0 mm."
                }
              ]).map((item, qIdx) => (
                <div key={item.id} className="p-5 rounded-2xl border border-zinc-200 dark:border-zinc-800 space-y-3">
                  <h4 className="text-sm font-bold text-zinc-900 dark:text-zinc-100">
                    Question {qIdx + 1}: {item.q}
                  </h4>
                  {lang === "kn" && (
                    <p className="text-xs text-zinc-500">{item.kn}</p>
                  )}

                  <div className="space-y-2 pt-1">
                    {item.options.map((opt, optIdx) => {
                      const isSelected = quizAnswers[item.id] === optIdx;
                      const isCorrect = item.correct === optIdx;
                      return (
                        <button
                          key={optIdx}
                          type="button"
                          onClick={() => {
                            if (!quizSubmitted) {
                              setQuizAnswers({ ...quizAnswers, [item.id]: optIdx });
                            }
                          }}
                          className={`w-full text-left p-3 rounded-xl text-xs font-medium border transition-all flex items-center justify-between ${
                            quizSubmitted
                              ? isCorrect
                                ? "bg-emerald-500/15 border-emerald-500/50 text-emerald-800 dark:text-emerald-200 font-bold"
                                : isSelected
                                ? "bg-rose-500/15 border-rose-500/50 text-rose-800 dark:text-rose-200"
                                : "bg-zinc-50 dark:bg-zinc-800/40 border-zinc-200 dark:border-zinc-800 opacity-60 text-zinc-500"
                              : isSelected
                              ? "bg-cyan-500/15 border-cyan-500/50 text-cyan-900 dark:text-cyan-200 font-bold ring-2 ring-cyan-500/30"
                              : "bg-zinc-50 dark:bg-zinc-800/40 border-zinc-200 dark:border-zinc-800 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300"
                          }`}
                        >
                          <span>{opt}</span>
                          {quizSubmitted && isCorrect && <CheckCircle2 className="h-4 w-4 text-emerald-500" />}
                          {quizSubmitted && isSelected && !isCorrect && <XCircle className="h-4 w-4 text-rose-500" />}
                        </button>
                      );
                    })}
                  </div>

                  {quizSubmitted && (
                    <div className="p-3 bg-zinc-100 dark:bg-zinc-800/60 rounded-xl text-xs text-zinc-600 dark:text-zinc-300">
                      <strong>Explanation:</strong> {item.explanation}
                    </div>
                  )}
                </div>
              ))}

              <div className="pt-2 flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setQuizSubmitted(true)}
                  className="px-6 py-2.5 rounded-xl bg-cyan-500 hover:bg-cyan-400 text-zinc-950 font-black text-xs shadow-md"
                >
                  Submit & Score Answers
                </button>
                {quizSubmitted && (
                  <button
                    type="button"
                    onClick={() => { setQuizSubmitted(false); setQuizAnswers({}); }}
                    className="px-4 py-2 rounded-xl bg-zinc-200 dark:bg-zinc-800 text-xs font-bold text-zinc-700 dark:text-zinc-300"
                  >
                    Reset Quiz
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ==================================================== */}
        {/* VIEW 4: ERROR TROUBLESHOOTING GUIDE */}
        {/* ==================================================== */}
        {viewMode === "troubleshoot" && (
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
            <div className="border-b border-zinc-100 dark:border-zinc-800 pb-4">
              <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50">
                {lang === "en" ? "Common Error Codes & Operational Troubleshooting" : "ದೋಷ ನಿವಾರಣೆ ಮಾರ್ಗದರ್ಶಿ"}
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                Exact system error messages from SMES backend, their root causes, and standard corrective actions.
              </p>
            </div>

            <div className="space-y-4">
              {[
                {
                  code: "HTTP 400: Work Order uses Continuous Casting, which bypasses F1",
                  module: "Continuous Casting",
                  cause: "An operator attempted to enter Stage F1 production or move material into F1 for a Continuous Casting order.",
                  remedy: "Continuous casting material skips F1 entirely. Ensure the bar is cut via CUT_CONSUME; accepted blanks will appear directly at Stage F2 (Machining)."
                },
                {
                  code: "HTTP 400: Work Order is marked for Continuous Casting but has no active Continuous Casting routing",
                  module: "Continuous Casting",
                  cause: "Attempted to cut or produce blanks before creating and activating a routing in Continuous Casting Planning.",
                  remedy: "Open Planning (/continuous-casting/planning), select the Work Order, and create an ACTIVE routing with valid blank length and kerf."
                },
                {
                  code: "HTTP 400: consumed_length_mm must equal ledger row length exactly",
                  module: "Continuous Casting",
                  cause: "The cut result recorded differs from the physical stock deducted in the CUT_CONSUME transaction.",
                  remedy: "Ensure the cut result matches the recorded saw cut consumption. Reconcile with saw machine digital read-out."
                },
                {
                  code: "HTTP 400: conversion_type SAME_PART requires source and destination part to be identical",
                  module: "Work Order Conversion",
                  cause: "SAME_PART was chosen in mapping or conversion, but source and destination parts have different part numbers.",
                  remedy: "Change conversion type to PART_TO_PART, or select identical part numbers for SAME_PART."
                },
                {
                  code: "HTTP 400: Quantity to convert exceeds eligible source-stage WIP",
                  module: "Work Order Conversion",
                  cause: "The quantity entered on the conversion form is greater than the available on-hand pieces at the source stage.",
                  remedy: "Check Live WIP matrix (/production/wip) for the source Work Order. Adjust conversion quantity to be <= available good WIP."
                },
                {
                  code: "HTTP 404: Conversion mapping not found / inactive",
                  module: "Work Order Conversion",
                  cause: "No approved row exists in ConversionPartMapping master for this source and destination part combination.",
                  remedy: "Request the Planner to review engineering suitability and create an ACTIVE row in /planning/conversion-mapping."
                }
              ].map((errItem, idx) => (
                <div key={idx} className="p-4 rounded-2xl border border-zinc-200 dark:border-zinc-800 space-y-2 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-rose-600 dark:text-rose-400">
                      {errItem.code}
                    </span>
                    <Badge variant="gray" size="sm">{errItem.module}</Badge>
                  </div>
                  <div className="text-zinc-600 dark:text-zinc-300">
                    <strong className="text-zinc-800 dark:text-zinc-200">Root Cause:</strong> {errItem.cause}
                  </div>
                  <div className="text-emerald-700 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/20 p-2.5 rounded-xl border border-emerald-200 dark:border-emerald-800/40">
                    <strong>Standard Corrective Action:</strong> {errItem.remedy}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ==================================================== */}
        {/* VIEW 5: INDUSTRIAL GLOSSARY */}
        {/* ==================================================== */}
        {viewMode === "glossary" && (
          <div className="bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-3xl p-6 sm:p-8 shadow-sm space-y-6">
            <div className="border-b border-zinc-100 dark:border-zinc-800 pb-4">
              <h2 className="text-xl font-black text-zinc-900 dark:text-zinc-50">
                {lang === "en" ? "VSPL Industrial Manufacturing Glossary" : "ತಾಂತ್ರಿಕ ಶಬ್ದಕೋಶ"}
              </h2>
              <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
                Standard terminology used across shop-floor terminals, drawings, and MES screens.
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {[
                { term: "WO (Work Order)", def: "Authoritative production order driving batch manufacturing through shop-floor routing stages.", kn: "ಉತ್ಪಾದನಾ ಕಾರ್ಯಾದೇಶ." },
                { term: "OAR (Order Acknowledgement Receipt)", def: "Customer sales order document against which finished parts are dispatched.", kn: "ಗ್ರಾಹಕರ ಮಾರಾಟ ಆದೇಶ." },
                { term: "WIP (Work in Process)", def: "Material that has entered the production stream but is not yet a completed finished good.", kn: "ಪ್ರಗತಿಯಲ್ಲಿರುವ ಉತ್ಪಾದನಾ ವಸ್ತು." },
                { term: "OD / ID", def: "Outer Diameter (external bar diameter) and Inner Diameter (bore diameter for hollow bars).", kn: "ಹೊರಗಿನ ಮತ್ತು ಒಳಗಿನ ವ್ಯಾಸ." },
                { term: "Saw Kerf Allowance", def: "The thickness of metal removed by the bandsaw blade teeth during each cut (typically 2-4 mm).", kn: "ಕಟಿಂಗ್ ಬ್ಲೇಡ್ ದಪ್ಪದ ನಷ್ಟ." },
                { term: "Heat Number / MTC", def: "Unique metallurgical traceability batch number stamped by the casting mill with chemical test cert.", kn: "ಹೀಟ್ / ಮೆಲ್ಟ್ ಬ್ಯಾಚ್ ಸಂಖ್ಯೆ." },
                { term: "Material Gate", def: "Server-side quality gate enforcing that Stage F2 intake never exceeds reconciled cut good blanks.", kn: "ಗುಣಮಟ್ಟದ ರಕ್ಷಣಾ ಗೇಟ್." },
                { term: "Conversion Mapping", def: "Database rule table specifying allowed part conversions and their conversion factors.", kn: "ಭಾಗ ಪರಿವರ್ತನೆ ನಿಯಮ ಕೋಷ್ಟಕ." }
              ].map((g, idx) => (
                <div key={idx} className="p-4 rounded-2xl border border-zinc-200 dark:border-zinc-800 text-xs space-y-1">
                  <span className="font-bold text-cyan-600 dark:text-cyan-400 text-sm block">{g.term}</span>
                  <p className="text-zinc-600 dark:text-zinc-300 leading-relaxed">{g.def}</p>
                  {lang === "kn" && <p className="text-zinc-400 text-[11px] font-medium">{g.kn}</p>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ==================================================== */}
        {/* VIEW 6: PRINTABLE 1-PAGE CHEAT SHEET */}
        {/* ==================================================== */}
        {viewMode === "print" && (
          <div className="bg-white text-zinc-950 p-8 rounded-3xl border border-zinc-300 shadow-xl space-y-6 print:border-none print:shadow-none print:p-0">
            <div className="flex items-center justify-between border-b-2 border-zinc-950 pb-4">
              <div>
                <span className="text-xs font-black tracking-widest uppercase text-cyan-700">VSPL SMART MANUFACTURING EXECUTION SYSTEM</span>
                <h2 className="text-2xl font-black">QUICK REFERENCE WORK INSTRUCTION CHEAT SHEET</h2>
                <span className="text-xs text-zinc-600">Post this laminated guide next to horizontal bandsaws and terminal workstations</span>
              </div>
              <button
                type="button"
                onClick={() => window.print()}
                className="px-4 py-2 rounded-xl bg-zinc-950 text-white font-bold text-xs flex items-center gap-2 print:hidden"
              >
                <Printer className="h-4 w-4" /> Print Document
              </button>
            </div>

            {/* Continuous Casting Cheat Sheet */}
            <div className="border border-zinc-900 rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between border-b border-zinc-300 pb-2">
                <h3 className="font-extrabold text-sm uppercase">MODULE 1: CONTINUOUS CASTING (WI-CC-01)</h3>
                <span className="text-xs font-bold text-rose-700">DOCTRINE: BYPASSES STAGE F1 DIRECTLY TO F2</span>
              </div>
              <div className="grid grid-cols-4 gap-2 text-xs">
                <div className="border p-2 rounded">
                  <strong>1. INWARD</strong><br />
                  Match Heat No. with MTC.<br />
                  Record OD, ID, length.<br />
                  Status: AVAILABLE
                </div>
                <div className="border p-2 rounded">
                  <strong>2. PLANNING</strong><br />
                  Select WO.<br />
                  Create ACTIVE routing.<br />
                  Set kerf (3mm) & trim.
                </div>
                <div className="border p-2 rounded">
                  <strong>3. CUTTING</strong><br />
                  CUT_CONSUME ledger.<br />
                  Record good & scrap.<br />
                  Variance MUST be 0.
                </div>
                <div className="border p-2 rounded bg-emerald-50">
                  <strong>4. F2 CREDIT</strong><br />
                  Gate validated.<br />
                  Blanks enter F2 WIP.<br />
                  Start CNC machining.
                </div>
              </div>
            </div>

            {/* Work Order Conversion Cheat Sheet */}
            <div className="border border-zinc-900 rounded-xl p-4 space-y-3">
              <div className="flex items-center justify-between border-b border-zinc-300 pb-2">
                <h3 className="font-extrabold text-sm uppercase">MODULE 2: WORK ORDER CONVERSION (WI-CONV-01)</h3>
                <span className="text-xs font-bold text-indigo-700">DOCTRINE: ZERO RE-MELT ATOMIC REALLOCATION</span>
              </div>
              <div className="grid grid-cols-4 gap-2 text-xs">
                <div className="border p-2 rounded">
                  <strong>1. MAPPING</strong><br />
                  Active row mandatory.<br />
                  SAME_PART factor 1.0.<br />
                  PART_TO_PART envelope.
                </div>
                <div className="border p-2 rounded">
                  <strong>2. REQUEST</strong><br />
                  Unique WO name (C-0021).<br />
                  Select Source WO.<br />
                  Target OAR & Entry Stage.
                </div>
                <div className="border p-2 rounded">
                  <strong>3. ENVELOPE</strong><br />
                  OD_src &ge; OD_dst + 3mm.<br />
                  L_src &ge; L_dst + 2mm.<br />
                  Qty &le; Source WIP.
                </div>
                <div className="border p-2 rounded bg-indigo-50">
                  <strong>4. REALLOCATION</strong><br />
                  Source WIP debited.<br />
                  Child WO created.<br />
                  Lineage preserved.
                </div>
              </div>
            </div>

            <div className="border-t border-zinc-400 pt-2 flex justify-between text-[10px] text-zinc-500 font-mono">
              <span>VSPL Manufacturing Engineering Division • Document Ref: SOP-2026-CC-CONV-01</span>
              <span>Approved by Operations & Quality Assurance</span>
            </div>
          </div>
        )}

      </div>
    </AppShell>
  );
}
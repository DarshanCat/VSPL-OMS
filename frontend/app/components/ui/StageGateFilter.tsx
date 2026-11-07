"use client";

import React from "react";
import { STAGE_CONFIGS } from "@/lib/userStage";
import { Filter, Lock, Layers } from "lucide-react";

interface StageGateFilterProps {
  currentGate: string; // "ALL" | "F1" | "F2" | ...
  onSelectGate: (gate: string) => void;
  isLocked?: boolean;
  userStageName?: string | null;
  counts?: Record<string, number>;
}

export const StageGateFilter: React.FC<StageGateFilterProps> = ({
  currentGate,
  onSelectGate,
  isLocked = false,
  userStageName,
  counts = {},
}) => {
  if (isLocked && currentGate !== "ALL") {
    const activeCfg = STAGE_CONFIGS.find((c) => c.id === currentGate);
    return (
      <div className="flex items-center justify-between p-3 rounded-2xl bg-gradient-to-r from-blue-50/80 to-indigo-50/80 dark:from-blue-950/30 dark:to-indigo-950/30 border border-blue-200 dark:border-blue-900/60 shadow-xs">
        <div className="flex items-center gap-2.5">
          <div className="p-1.5 rounded-xl bg-blue-600 text-white shadow-xs">
            <Lock className="h-4 w-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-extrabold text-blue-950 dark:text-blue-100">
                Gate Locked: {activeCfg?.name || currentGate}
              </span>
              <span className="px-2 py-0.2 rounded-full text-[10px] font-bold bg-blue-100 dark:bg-blue-900 text-blue-700 dark:text-blue-200">
                Operator Scope
              </span>
            </div>
            <p className="text-[11px] text-zinc-500 dark:text-zinc-400">
              You are assigned to <strong>{currentGate}</strong>. You only see material physically at this gate.
            </p>
          </div>
        </div>
        {counts[currentGate] !== undefined && (
          <div className="text-right">
            <span className="text-xs font-extrabold text-blue-700 dark:text-blue-300 font-mono block">
              {counts[currentGate]} active
            </span>
            <span className="text-[10px] text-zinc-400">at this gate</span>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-xs font-bold text-zinc-600 dark:text-zinc-400">
        <div className="flex items-center gap-1.5">
          <Layers className="h-3.5 w-3.5 text-blue-600" />
          <span>SHOP FLOOR GATE FILTER</span>
        </div>
        <span className="text-[11px] text-zinc-400 font-normal">
          Showing: <strong>{currentGate === "ALL" ? "All Shop Floor Gates" : `Gate ${currentGate}`}</strong>
        </span>
      </div>

      <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
        <button
          type="button"
          onClick={() => onSelectGate("ALL")}
          className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 ${
            currentGate === "ALL"
              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900 shadow-sm"
              : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700"
          }`}
        >
          <span>All Gates</span>
          {counts["ALL"] !== undefined && (
            <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
              currentGate === "ALL" ? "bg-white/20 text-white dark:bg-black/20 dark:text-black" : "bg-zinc-200 dark:bg-zinc-700 text-zinc-600 dark:text-zinc-300"
            }`}>
              {counts["ALL"]}
            </span>
          )}
        </button>

        {STAGE_CONFIGS.map((stg) => {
          const isSelected = currentGate === stg.id;
          const count = counts[stg.id];
          return (
            <button
              key={stg.id}
              type="button"
              onClick={() => onSelectGate(stg.id)}
              className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all cursor-pointer whitespace-nowrap flex items-center gap-1.5 border ${
                isSelected
                  ? "bg-blue-600 text-white border-blue-600 shadow-sm ring-2 ring-blue-500/20"
                  : "bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-800 text-zinc-700 dark:text-zinc-300 hover:bg-zinc-50 dark:hover:bg-zinc-800/60"
              }`}
            >
              <span>{stg.id}</span>
              <span className={`text-[10px] hidden sm:inline font-normal ${isSelected ? "text-blue-100" : "text-zinc-400"}`}>
                ({stg.name.split(" ")[0]})
              </span>
              {count !== undefined && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-mono ${
                  isSelected ? "bg-white/20 text-white" : "bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300"
                }`}>
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
};

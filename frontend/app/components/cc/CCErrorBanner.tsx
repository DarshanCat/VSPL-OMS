import React from "react";
import { AlertTriangle } from "lucide-react";

// Shows a backend message verbatim (multi-line validation errors keep their line breaks).
export function CCErrorBanner({ message, className = "" }: { message?: string | null; className?: string }) {
  if (!message) return null;
  return (
    <div
      role="alert"
      className={`flex items-start gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-700 dark:text-rose-300 ${className}`}
    >
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span className="whitespace-pre-line">{message}</span>
    </div>
  );
}

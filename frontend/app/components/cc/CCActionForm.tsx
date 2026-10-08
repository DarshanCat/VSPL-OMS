"use client";
import React from "react";
import { CCErrorBanner } from "./CCErrorBanner";

// Form shell: Enter submits, submit is locked while busy, backend error shown verbatim.
// Field validation beyond "required / positive integer" stays on the backend.
export function CCActionForm({
  onSubmit,
  busy = false,
  error,
  submitLabel,
  children,
}: {
  onSubmit: () => void;
  busy?: boolean;
  error?: string | null;
  submitLabel: string;
  children: React.ReactNode;
}) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!busy) onSubmit();
      }}
      className="space-y-3"
    >
      {children}
      <CCErrorBanner message={error} />
      <button
        type="submit"
        disabled={busy}
        className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {busy ? "Working..." : submitLabel}
      </button>
    </form>
  );
}

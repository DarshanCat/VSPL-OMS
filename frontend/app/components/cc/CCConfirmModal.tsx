"use client";
import React from "react";
import { Modal } from "@/app/components/ui/Modal";
import { CCErrorBanner } from "./CCErrorBanner";

// Confirmation step for irreversible stock movements. The caller owns `busy` and `error`.
export function CCConfirmModal({
  isOpen,
  onClose,
  onConfirm,
  title,
  children,
  confirmLabel = "Confirm",
  busy = false,
  error,
}: {
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  children: React.ReactNode;
  confirmLabel?: string;
  busy?: boolean;
  error?: string | null;
}) {
  return (
    <Modal isOpen={isOpen} onClose={busy ? () => {} : onClose} title={title} maxWidth="md">
      <div className="space-y-4 px-6 py-4 text-sm text-zinc-700 dark:text-zinc-300">
        {children}
        <CCErrorBanner message={error} />
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs font-medium hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </Modal>
  );
}

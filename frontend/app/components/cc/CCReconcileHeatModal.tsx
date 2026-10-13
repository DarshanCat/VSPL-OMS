"use client";
import React, { useEffect, useState } from "react";
import { Modal } from "@/app/components/ui/Modal";
import { CCActionForm } from "./CCActionForm";
import {
  ccErrorMessage,
  ccReconcileInwardHeat,
  ccReconcileStockUnitHeat,
  CCHeatReconcileResult,
} from "@/lib/continuousCastingApi";
import { ccInputCls, ccLabelCls } from "@/lib/continuousCastingForm";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: (result: CCHeatReconcileResult) => void;
  targetType: "INWARD" | "STOCK_UNIT";
  targetId: string;
  targetNumber: string;
  currentHeatNumber?: string | null;
}

export function CCReconcileHeatModal({
  isOpen,
  onClose,
  onSuccess,
  targetType,
  targetId,
  targetNumber,
  currentHeatNumber,
}: Props) {
  const [heatNumber, setHeatNumber] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isOpen) {
      setHeatNumber(currentHeatNumber ?? "");
      setReason("");
      setError(null);
      setBusy(false);
    }
  }, [isOpen, currentHeatNumber]);

  const handleSubmit = async () => {
    const trimmedHeat = heatNumber.trim();
    const trimmedReason = reason.trim();
    if (!trimmedHeat) {
      setError("Heat number cannot be empty.");
      return;
    }
    if (!trimmedReason) {
      setError("A reason is mandatory for heat number reconciliation audit trail.");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      let res: CCHeatReconcileResult;
      if (targetType === "INWARD") {
        res = await ccReconcileInwardHeat(targetId, {
          heat_number: trimmedHeat,
          reason: trimmedReason,
        });
      } else {
        res = await ccReconcileStockUnitHeat(targetId, {
          heat_number: trimmedHeat,
          reason: trimmedReason,
        });
      }
      onSuccess(res);
      onClose();
    } catch (err) {
      setError(ccErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const isLegacyUnreconciled = !currentHeatNumber;

  return (
    <Modal
      isOpen={isOpen}
      onClose={busy ? () => {} : onClose}
      title={`Reconcile Heat Number — ${targetType === "INWARD" ? "Inward" : "Stock Unit"} ${targetNumber}`}
      maxWidth="md"
    >
      <div className="p-6">
        {isLegacyUnreconciled ? (
          <div className="mb-4 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
            <strong>Legacy Inventory:</strong> This record currently has no heat number assigned. Reconciling will associate the verified mill/foundry heat certificate with this {targetType === "INWARD" ? "inward and all its stock units / cuts" : "stock unit and its cut records"}.
          </div>
        ) : (
          <div className="mb-4 rounded-lg border border-blue-500/30 bg-blue-500/10 p-3 text-xs text-blue-700 dark:text-blue-300">
            <strong>Current Heat Number:</strong> <span className="font-mono font-semibold">{currentHeatNumber}</span>. Any update will be recorded in the immutable audit log with full attribution.
          </div>
        )}

        <CCActionForm
          onSubmit={handleSubmit}
          busy={busy}
          error={error}
          submitLabel="Save Reconciliation"
        >
          <div>
            <label className={ccLabelCls}>Verified Heat Number *</label>
            <input
              className={ccInputCls}
              value={heatNumber}
              onChange={(e) => setHeatNumber(e.target.value)}
              placeholder="e.g. HT-2026-089A"
              required
            />
            <p className="mt-1 text-[11px] text-zinc-500">
              Foundry heat / melt number from manufacturer test certificate (MTC).
            </p>
          </div>

          <div>
            <label className={ccLabelCls}>Reconciliation Reason *</label>
            <textarea
              className={ccInputCls}
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="e.g. MTC verified against supplier invoice / physical bar marking."
              required
            />
            <p className="mt-1 text-[11px] text-zinc-500">
              Mandatory justification recorded in the immutable system audit log.
            </p>
          </div>
        </CCActionForm>
      </div>
    </Modal>
  );
}

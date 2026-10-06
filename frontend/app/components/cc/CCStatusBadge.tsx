import React from "react";
import { Badge, BadgeVariant } from "@/app/components/ui/Badge";

// Colour mapping for backend status strings only; it never decides or derives a status.
const VARIANTS: Record<string, BadgeVariant> = {
  ACCEPTED: "green", RECONCILED: "green", ACTIVE: "green", IN_STOCK: "green", PASS: "green",
  PENDING_QA: "amber", PENDING: "amber", ON_HOLD: "amber", DRAFT: "amber", VARIANCE: "amber",
  REJECTED: "red", SCRAPPED: "red", BLOCK: "red", BLOCKED: "red",
  CONSUMED: "gray", SUPERSEDED: "gray", RELEASED: "gray",
  PLANNED: "blue", RESERVED: "purple", ISSUED: "cyan", PARTIALLY_CONSUMED: "amber",
};

export function CCStatusBadge({ status, size = "sm" }: { status: string | null | undefined; size?: "sm" | "md" }) {
  if (!status) return <span className="text-zinc-400">-</span>;
  return (
    <Badge variant={VARIANTS[status.toUpperCase()] ?? "blue"} size={size}>
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

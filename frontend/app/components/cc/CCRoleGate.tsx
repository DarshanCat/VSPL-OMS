"use client";
import React, { useEffect, useState } from "react";
import { getCurrentUserRole } from "@/lib/api";
import { ccRoleAllowed, CCRoleTuple } from "@/lib/continuousCastingRoles";

// UI VISIBILITY ONLY. Hides write controls from roles the backend would refuse anyway. It is not security:
// the backend enforces every role with require_roles(...) and answers 403 whatever this renders.
export function CCRoleGate({
  allowed,
  children,
  fallback = null,
}: {
  allowed: CCRoleTuple;
  children: React.ReactNode;
  fallback?: React.ReactNode;
}) {
  const [role, setRole] = useState<string | null>(null);
  useEffect(() => setRole(getCurrentUserRole()), []);
  return <>{ccRoleAllowed(role, allowed) ? children : fallback}</>;
}

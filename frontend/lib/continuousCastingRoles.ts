// UX-ONLY mirror of backend/app/core/roles.py (the CC_* tuples).
// The role strings are the lowercase UserRole values the backend puts in the JWT ("role" claim) and that
// getCurrentUserRole() returns. This module only decides which buttons are SHOWN; the backend enforces every
// one of these with require_roles(...) and answers 403 regardless of what the UI displays.
// Keep in step with roles.py by hand. Reads need only an authenticated user, so there is no read tuple.

export const CC_MATERIAL_MASTER_ROLES = ["admin", "engineering"] as const;
export const CC_INWARD_ROLES = ["admin", "store"] as const;
export const CC_QA_ROLES = ["admin", "qa"] as const;
export const CC_ROUTING_ROLES = ["admin", "engineering"] as const;
export const CC_RESERVE_ROLES = ["admin", "planner"] as const; // also allocation and release
export const CC_ISSUE_ROLES = ["admin", "store"] as const; // also return and split
export const CC_CUT_ROLES = ["admin", "production_manager"] as const; // also cut results
export const CC_HOLD_ROLES = ["admin", "store", "qa"] as const;
export const CC_HOLD_RELEASE_ROLES = ["admin", "qa"] as const;
export const CC_SCRAP_ROLES = ["admin", "store"] as const;
export const CC_ADJUSTMENT_ROLES = ["admin"] as const;

export type CCRoleTuple = readonly string[];

// True when the (lowercase) role string is in the tuple. A missing role shows nothing.
export function ccRoleAllowed(role: string | null | undefined, allowed: CCRoleTuple): boolean {
  return !!role && allowed.includes(role);
}

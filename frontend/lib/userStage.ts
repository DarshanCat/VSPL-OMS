export const STAGE_CONFIGS: {
  id: string;
  name: string;
  shortDesc: string;
  badgeBg: string;
}[] = [
  { id: "F1", name: "Foundry (F1)", shortDesc: "Continuous casting & moulding", badgeBg: "bg-blue-600" },
  { id: "F2", name: "Fettling (F2)", shortDesc: "Fettling, grinding & rough CNC", badgeBg: "bg-indigo-600" },
  { id: "F3", name: "Precision CNC (F3)", shortDesc: "Precision machining & boring", badgeBg: "bg-purple-600" },
  { id: "SP", name: "Surface Prep (SP)", shortDesc: "Shot blasting & heat treat", badgeBg: "bg-amber-600" },
  { id: "FI", name: "Final QA (FI)", shortDesc: "CMM, visual inspection & QA sign-off", badgeBg: "bg-emerald-600" },
  { id: "PACKING", name: "Packing & BSR", shortDesc: "Finished goods buffering & packing", badgeBg: "bg-teal-600" },
  { id: "DISPATCH", name: "Dispatch", shortDesc: "DC generation & customer shipping", badgeBg: "bg-cyan-600" },
];

export function resolveAssignedStage(user: { role?: string; department?: string | null; email?: string } | null): {
  stage: string | null;
  isLocked: boolean;
  label: string;
} {
  if (!user) return { stage: null, isLocked: false, label: "All Gates" };
  const dept = (user.department || "").trim().toUpperCase();
  const email = (user.email || "").trim().toLowerCase();
  const role = (user.role || "").trim().toUpperCase();

  // If Admin, Production Manager, Planner, CEO, Data Analyst -> not locked, can inspect any gate
  const isManagerOrAdmin = ["ADMIN", "PRODUCTION_MANAGER", "PLANNER", "CEO", "SALES", "DATA_ANALYST"].includes(role);

  // 1. Department match
  for (const s of ["F1", "F2", "F3", "SP", "FI", "PACKING", "DISPATCH"]) {
    if (dept === s || dept.startsWith(s + " ") || dept.endsWith(" " + s)) {
      return { stage: s, isLocked: !isManagerOrAdmin, label: s };
    }
  }
  if (dept.includes("FOUNDRY")) return { stage: "F1", isLocked: !isManagerOrAdmin, label: "F1" };
  if (dept.includes("CNC") || dept.includes("FETTLING") || dept.includes("TURNING")) return { stage: "F2", isLocked: !isManagerOrAdmin, label: "F2" };
  if (dept.includes("QUALITY") || dept.includes("INSPECTION") || dept.includes("QA")) return { stage: "FI", isLocked: !isManagerOrAdmin, label: "FI" };
  if (dept.includes("DISPATCH")) return { stage: "DISPATCH", isLocked: !isManagerOrAdmin, label: "DISPATCH" };
  if (dept.includes("PACKING") || dept.includes("STORES") || dept.includes("STORE")) return { stage: "PACKING", isLocked: !isManagerOrAdmin, label: "PACKING" };

  // 2. Email pattern match
  if (email.includes(".f1@") || email.startsWith("f1@") || email.includes("-f1@")) return { stage: "F1", isLocked: !isManagerOrAdmin, label: "F1" };
  if (email.includes(".f2@") || email.startsWith("f2@") || email.includes("-f2@")) return { stage: "F2", isLocked: !isManagerOrAdmin, label: "F2" };
  if (email.includes(".f3@") || email.startsWith("f3@") || email.includes("-f3@")) return { stage: "F3", isLocked: !isManagerOrAdmin, label: "F3" };
  if (email.includes(".sp@") || email.startsWith("sp@") || email.includes("-sp@")) return { stage: "SP", isLocked: !isManagerOrAdmin, label: "SP" };
  if (email.includes(".fi@") || email.includes(".qa@") || email.startsWith("qa@") || email.includes("quality")) return { stage: "FI", isLocked: !isManagerOrAdmin, label: "FI" };
  if (email.includes("dispatch")) return { stage: "DISPATCH", isLocked: !isManagerOrAdmin, label: "DISPATCH" };
  if (email.includes("packing")) return { stage: "PACKING", isLocked: !isManagerOrAdmin, label: "PACKING" };

  // 3. Role match
  if (role === "DISPATCH") return { stage: "DISPATCH", isLocked: true, label: "DISPATCH" };
  if (role === "PACKING") return { stage: "PACKING", isLocked: true, label: "PACKING" };
  if (role === "QA") return { stage: "FI", isLocked: true, label: "FI" };

  return { stage: null, isLocked: false, label: "All Gates" };
}

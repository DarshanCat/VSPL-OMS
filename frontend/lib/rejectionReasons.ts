// Single source of truth for the rejection-reason / defect-code vocabulary used across
// the app. No backend master table exists for this yet (see Rejection Tracking
// restructuring notes) -- this list was previously duplicated only inside
// app/quality/nc/page.tsx; it now backs both the legacy NC page and Rejection Tracking
// so the two never drift apart.
export const DEFECT_CODES = [
  { code: "DEF-POROSITY", label: "DEF-POROSITY — Casting Gas Porosity" },
  { code: "DEF-SURF-BLOW", label: "DEF-SURF-BLOW — Surface Blowholes / Pits" },
  { code: "DEF-DIM-OUT", label: "DEF-DIM-OUT — Dimensional Tolerance Out" },
  { code: "DEF-INCLUSION", label: "DEF-INCLUSION — Slag / Oxide Inclusion" },
  { code: "DEF-CRACK", label: "DEF-CRACK — Thermal Stress Crack" },
  { code: "DEF-FINISH", label: "DEF-FINISH — Surface Roughness (Ra) High" },
];

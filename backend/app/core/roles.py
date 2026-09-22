"""Single source of truth for the role groupings already used across the OMS planning
and quality-oversight endpoints, so a new endpoint (e.g. Rejection Tracking) reuses the
exact same authorization boundaries instead of redefining them."""
from app.models.user import UserRole

# Planning/release decisions: WO release, conversion, and any disposition action that
# creates a new Work Order (CONVERT_PART / SAME_PART / CWO).
PLANNING_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER)

# Quality/oversight decisions: NC disposition, and any disposition action that does not
# create a new Work Order (SCRAP / DEVIATION_ACCEPT).
QUALITY_OVERSIGHT_ROLES = (UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.QA, UserRole.CEO)

# Physical material handling: moving parts on the shop floor, and executing an
# already-decided disposition's physical fulfillment (e.g. sending SCRAP material for
# melting). STORE never gets QUALITY_OVERSIGHT_ROLES' authority to make or change a
# disposition decision -- it can only carry out one that already exists.
STORE_ROLES = (UserRole.STORE,)
MELTING_ENTRY_ROLES = QUALITY_OVERSIGHT_ROLES + STORE_ROLES

# Recording actual production completion (good/rejected quantity) at a stage is a
# shop-floor / planning activity -- STORE, QA, DISPATCH, PACKING, SALES, and CEO have
# no reason to log production output, so they are excluded here rather than left on
# the previous fully-open (any authenticated user) rule.
PRODUCTION_ENTRY_ROLES = (
    UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.PLANNER,
    UserRole.MACHINE_OPERATOR, UserRole.OPERATOR,
)

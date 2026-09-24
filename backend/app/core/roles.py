"""Single source of truth for the role groupings enforced across every OMS endpoint.

These tuples implement the explicit OMS Roles & Responsibilities matrix (Super Admin,
Planner/PPC, Production Manager, Store, QA, Dispatch, CEO, Data Analyst). Frontend
navigation hiding is a UX convenience only -- every one of these tuples is enforced on
the backend via `require_roles(...)` (or, where noted, a service-layer `_require_role`
call), and an unauthorized request always gets a real 403, never just a hidden button.

Keep these granular. Do not fold unrelated department functions into one tuple just
because two roles happen to share it today -- each tuple below exists because the
spec grants (or withholds) that *specific* capability, not because of a broader
"department" grouping.
"""
from app.models.user import UserRole

# Master-data administration and planning-only mutations: Customer Master, PO Master,
# Schedule Master, Order Intake (OAR creation), PO<->Schedule matching, Conversion Part
# Mapping (master data), and the OMS Engine batch upload/download tools. Per the spec,
# Production Manager explicitly does NOT get PO/Schedule/OAR creation or master-data
# administration -- only Admin (Super Admin) and Planner do.
PLANNING_ROLES = (UserRole.ADMIN, UserRole.PLANNER)

# WO release specifically: Production Manager already held this permission before the
# Roles & Responsibilities spec was written, and the spec's own carve-out ("Cannot: WO
# release unless existing explicit permission already grants it") preserves it rather
# than stripping it -- this is intentionally a superset of PLANNING_ROLES, not a copy
# of it, so a future change to PLANNING_ROLES doesn't silently also change this.
WO_RELEASE_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER)

# The planner-driven Conversion Module (operations.py POST /conversion) -- distinct
# from Conversion Part Mapping (master data, gated by PLANNING_ROLES above) and from
# the QA-triggered CONVERT_PART/SAME_PART/CWO disposition action (gated by
# PLANNING_ROLES via rejection_service.py's own action-conditional branch). The spec
# doesn't restrict this planner+production floor collaboration, so it's left as the
# pre-existing three-role set rather than tightened to match PLANNING_ROLES.
CONVERSION_MODULE_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER)

# Physical shop-floor production entry (recording good/rejected quantity at a stage).
# Planner is explicitly excluded per spec ("Cannot: production entry").
PRODUCTION_ENTRY_ROLES = (
    UserRole.ADMIN, UserRole.PRODUCTION_MANAGER,
    UserRole.MACHINE_OPERATOR, UserRole.OPERATOR,
)

# Physical material movement between stages: Store's core responsibility ("Physical
# material movement"), Production Manager's "authorized material movement", and the
# shop-floor operator roles that already perform it as part of production entry.
# Planner is explicitly excluded ("Cannot: arbitrary material movement").
MATERIAL_MOVEMENT_ROLES = (
    UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.STORE,
    UserRole.MACHINE_OPERATOR, UserRole.OPERATOR,
)

# QA disposition APPROVAL: authorizing SCRAP / DEVIATION_ACCEPT, and closing/updating
# an NC record's QA status. Per spec, Production Manager and CEO do NOT approve
# quality dispositions ("Cannot: QA disposition approval" / CEO's blanket "no
# operational transaction mutation unless explicitly authorized") -- this replaces
# their former inclusion here.
#
# Raising an NC/rejection report in the first place (POST /operations/nc, POST
# /rejection/excess-non-moving) is intentionally NOT gated by this or any other role
# tuple -- flagging a defect from the shop floor is meant to stay open to any
# authenticated user (see test_rbac_remediation.py::test_nc_creation_remains_open_to_
# any_authenticated_user for the explicit, pre-existing contract this preserves).
# Only the approval/disposition decision that follows is access-controlled.
QUALITY_APPROVAL_ROLES = (UserRole.ADMIN, UserRole.QA)

# Read/oversight visibility only (e.g. audit log listing) -- broader than approval
# since nothing here is a mutation. Kept as its own tuple (not reused for approval)
# so widening who may *view* oversight data never accidentally widens who may
# *approve* a disposition.
QUALITY_OVERSIGHT_ROLES = (UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.QA, UserRole.CEO)

# Physical material handling: moving parts on the shop floor, and executing an
# already-decided disposition's physical fulfillment (e.g. sending SCRAP material for
# melting). STORE never gets QUALITY_APPROVAL_ROLES' authority to make or change a
# disposition decision -- it can only carry out one that already exists.
STORE_ROLES = (UserRole.STORE,)

# Physical melting execution: Store's responsibility, with Production Manager/QA/Admin
# oversight able to perform it too. CEO is excluded -- CEO must never execute an
# operational mutation per spec ("No operational transaction mutation unless
# explicitly authorized").
MELTING_ENTRY_ROLES = (UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.QA, UserRole.STORE)

# Packing/BSR processing. Per spec this is Dispatch's remit ("Packing/BSR" is listed
# under the Dispatch role); the dedicated PACKING role (an existing UserRole value
# with no prior backend semantics) is also granted, since it exists for exactly this.
PACKING_ROLES = (UserRole.ADMIN, UserRole.DISPATCH, UserRole.PACKING)

# Final dispatch execution. Per spec, Production Manager explicitly cannot execute
# final dispatch ("Cannot: final dispatch") -- this is intentionally narrower than the
# former DISPATCH_ROLES, which included Production Manager.
DISPATCH_EXECUTION_ROLES = (UserRole.ADMIN, UserRole.DISPATCH)

# User account administration: creating accounts, generating/resetting temporary
# passwords, activating/deactivating, role assignment. Matches the existing
# /auth/register gate (require_roles(UserRole.ADMIN)) -- Super Admin only.
USER_MANAGEMENT_ROLES = (UserRole.ADMIN,)

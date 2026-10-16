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

# Master-data administration and planning mutations: Customer Master, PO Master,
# Schedule Master, Order Intake (OAR creation), WO generation, PO<->Schedule matching,
# Conversion Part Mapping (master data), and the OMS Engine batch upload/download tools.
# Sales and Planner functions are unified, and CEO holds full administrative & operational authority.
PLANNING_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.SALES, UserRole.CEO)

# PO Master visibility and editing
PO_MASTER_VIEW_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.SALES, UserRole.CEO)
PO_MASTER_EDIT_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.SALES, UserRole.CEO)

# WO release specifically: Admin, Planner, Production Manager, Sales, CEO
WO_RELEASE_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER, UserRole.SALES, UserRole.CEO)

# The planner-driven Conversion Module (operations.py POST /conversion)
CONVERSION_MODULE_ROLES = (UserRole.ADMIN, UserRole.PLANNER, UserRole.PRODUCTION_MANAGER, UserRole.SALES, UserRole.CEO)

# Physical shop-floor production entry (recording good/rejected quantity at a stage).
# CEO granted rights alongside Admin, PM, and Operators.
PRODUCTION_ENTRY_ROLES = (
    UserRole.ADMIN, UserRole.PRODUCTION_MANAGER,
    UserRole.MACHINE_OPERATOR, UserRole.OPERATOR,
    UserRole.CEO,
)

# Physical material movement between stages:
# CEO granted rights alongside Admin, PM, Store, and Operators.
MATERIAL_MOVEMENT_ROLES = (
    UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.STORE,
    UserRole.MACHINE_OPERATOR, UserRole.OPERATOR,
    UserRole.CEO,
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

# Material Review Board (MRB): Quality, Planner, Admin, and CEO
# Authorizes verification, approval, adjustment, and disposition of shop floor OK and rejection entries.
MRB_ROLES = (UserRole.ADMIN, UserRole.QA, UserRole.PLANNER, UserRole.CEO)

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

# Heat batch creation & master management: Metallurgy / Foundry / QA / Store / Admin
HEAT_MANAGEMENT_ROLES = (UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.STORE, UserRole.QA, UserRole.PLANNER)

# Heat allocation to Work Order at casting: Floor operators, Store, Production Manager, Admin
HEAT_ALLOCATION_ROLES = (
    UserRole.ADMIN, UserRole.PRODUCTION_MANAGER, UserRole.STORE,
    UserRole.MACHINE_OPERATOR, UserRole.OPERATOR,
)

# Engineering Release: first step of the release chain (Engineering Release ->
# Manufacturing Release -> WO Release -> Production). Super Admin may administer
# every release step per existing admin policy.
ENGINEERING_RELEASE_ROLES = (UserRole.ADMIN, UserRole.ENGINEERING)

# Manufacturing Release: second step of the release chain -- the service layer also
# enforces that Engineering Release must already be recorded before this can happen.
MANUFACTURING_RELEASE_ROLES = (UserRole.ADMIN, UserRole.MANUFACTURING, UserRole.PRODUCTION_MANAGER)

# Continuous Casting (China) raw-material module. One tuple per operation so widening
# one never widens another; no China-specific role is introduced.
CC_INWARD_ROLES = (UserRole.ADMIN, UserRole.STORE)
CC_RESERVE_ROLES = (UserRole.ADMIN, UserRole.PLANNER)
CC_ISSUE_ROLES = (UserRole.ADMIN, UserRole.STORE)
CC_CUT_ROLES = (UserRole.ADMIN, UserRole.PRODUCTION_MANAGER)
# Physical quarantine, disposal and count correction (Phase 9). Quality places a hold, Stores
# executes a scrap; a quarantine is released by Quality/Admin only; adjustments are Admin only.
CC_HOLD_ROLES = (UserRole.ADMIN, UserRole.STORE, UserRole.QA)
CC_HOLD_RELEASE_ROLES = (UserRole.ADMIN, UserRole.QA)
CC_SCRAP_ROLES = (UserRole.ADMIN, UserRole.STORE)
CC_ADJUSTMENT_ROLES = (UserRole.ADMIN,)
# Routing creation/supersession (compatibility and allowances are Engineering's call).
CC_ROUTING_ROLES = (UserRole.ADMIN, UserRole.ENGINEERING)
# Material master (Phase 11A): Engineering owns the technical material / grade / dimensions that it
# later validates against a WO routing. Inward QA decision: Quality owns acceptance (UserRole.QA is the
# repository's existing quality role -- the same one QUALITY_APPROVAL_ROLES uses).
CC_MATERIAL_MASTER_ROLES = (UserRole.ADMIN, UserRole.ENGINEERING)
CC_QA_ROLES = (UserRole.ADMIN, UserRole.QA)
CC_HEAT_RECONCILE_ROLES = (UserRole.ADMIN, UserRole.QA, UserRole.PLANNER, UserRole.STORE)



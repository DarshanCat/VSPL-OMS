"""One-time provisioning for the seven named VSPL OMS onboarding accounts -- NOT wired
into application startup. Run manually, once, against the target database:

    python -m app.scripts.bootstrap_named_accounts

For each account: if it already exists, it is reported and left completely
unchanged (no password, role, or department overwrite). If it does not exist, it is
created with a fresh, cryptographically random temporary password
(app.core.security.generate_temp_password) and must_change_password=True -- the
account is forced to set its own permanent password on first login. The plaintext
temporary password is printed to THIS terminal exactly once, for the operator to hand
to that person through a secure channel; it is never logged, never stored anywhere
except as its bcrypt hash, and never printed again by any other command or endpoint.

data.analyst@vijayspheroidals.com is mapped to UserRole.DATA_ANALYST -- a dedicated,
read-only role added by the OMS Roles & Responsibilities RBAC pass (see
app/core/roles.py). It is granted no entry in any require_roles(...) tuple, so it can
authenticate and read every tracking/reports/analytics endpoint (all gated only by
"any authenticated user") but cannot mutate any manufacturing transaction or master
data, matching the spec's "Cannot modify manufacturing transactions or master data
unless separately assigned an authorized operational role."
"""
import sys

from app.core.database import SessionLocal
from app.core.security import generate_temp_password, get_password_hash
from app.models.user import User, UserRole

# (full_name placeholder, email, department, role) -- full_name is intentionally
# generic (derived from the email's local part) since none was specified for these
# accounts; an admin can rename them later via the Users screen.
ACCOUNTS = [
    ("Data Analyst", "data.analyst@vijayspheroidals.com", "Management / Analytics", UserRole.DATA_ANALYST),
    ("PPC", "ppc@vijayspheroidals.com", "Planning", UserRole.PLANNER),
    ("Stores", "stores@vijayspheroidals.com", "Stores", UserRole.STORE),
    ("Quality", "quality@vijayspheroidals.com", "Quality", UserRole.QA),
    ("Demo Production Manager", "demo.production@vspl.com", "Production", UserRole.PRODUCTION_MANAGER),
    ("Demo Dispatch", "demo.dispatch@vspl.com", "Dispatch", UserRole.DISPATCH),
    ("Demo CEO", "demo.ceo@vspl.com", "Management", UserRole.CEO),
]


def main() -> int:
    db = SessionLocal()
    created = []
    skipped = []
    try:
        for full_name, email, department, role in ACCOUNTS:
            existing = db.query(User).filter(User.email == email).first()
            if existing:
                skipped.append((email, existing.role.value, existing.department))
                continue

            temp_password = generate_temp_password()
            user = User(
                full_name=full_name,
                email=email,
                hashed_password=get_password_hash(temp_password),
                role=role,
                department=department,
                is_active=True,
                must_change_password=True,
            )
            db.add(user)
            db.commit()
            created.append((email, department, role.value, temp_password))

        print("\n=== Bootstrap result (temporary passwords shown ONLY here, ONLY now) ===")
        if created:
            print("\nCreated:")
            for email, department, role, temp_password in created:
                print(f"  email: {email}")
                print(f"  department: {department}")
                print(f"  role: {role}")
                print(f"  temporary_password: {temp_password}")
                print("  (must change password on first login)")
                print()
        if skipped:
            print("Already existed -- left unchanged:")
            for email, role, department in skipped:
                print(f"  {email}  (role={role}, department={department})")
        if not created and not skipped:
            print("No accounts processed.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

"""One-time production admin provisioning -- NOT wired into application startup.

Run manually, once, against the target database (the process must have the same
DATABASE_URL environment variable set as the deployed backend):

    python -m app.scripts.create_admin --email admin@example.com --name "Full Name"

The password is entered interactively (never as a CLI argument, so it never lands
in shell history or a process listing), hashed with the existing
app.core.security.get_password_hash, and used to insert exactly one ADMIN user via
the existing SQLAlchemy User model. Refuses to run if a user with that email
already exists -- it never overwrites an existing account, and it never seeds a
known/default password.

This does not depend on the users table being empty (unlike the
BOOTSTRAP_ADMIN_EMAIL/BOOTSTRAP_ADMIN_PASSWORD startup path in
app/services/seed_service.py, which only fires once, on the very first cold start
against a completely empty table) -- so it is the reliable way to (re)provision an
admin at any point, including after that startup window has already passed.
"""
import argparse
import getpass
import sys

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import User, UserRole


def main() -> int:
    parser = argparse.ArgumentParser(description="Create exactly one ADMIN account. Never overwrites an existing user.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="Full name for the account")
    parser.add_argument("--employee-id", default="ADM-000")
    parser.add_argument("--department", default="Administration")
    args = parser.parse_args()

    password = getpass.getpass("Password: ")
    confirm = getpass.getpass("Confirm password: ")
    if not password:
        print("Password cannot be empty. Aborted.", file=sys.stderr)
        return 1
    if password != confirm:
        print("Passwords did not match. Aborted.", file=sys.stderr)
        return 1

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == args.email).first()
        if existing:
            print(
                f"A user with email '{args.email}' already exists (role={existing.role.value}, "
                f"active={existing.is_active}). Aborted -- this script never overwrites an "
                f"existing account.",
                file=sys.stderr,
            )
            return 1

        user = User(
            email=args.email,
            hashed_password=get_password_hash(password),
            full_name=args.name,
            role=UserRole.ADMIN,
            employee_id=args.employee_id,
            department=args.department,
            is_active=True,
        )
        db.add(user)
        db.commit()
        print(f"Created ADMIN account for '{args.email}'.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

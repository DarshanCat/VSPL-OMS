import secrets
import string
from datetime import datetime, timedelta
import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt
from app.core.config import settings

ALLOWED_EMAIL_DOMAINS = {
    "vijayspheroidals.com",
    "vijayspheroidals.onmicrosoft.com",
}

def validate_company_email(email: str) -> str:
    """Validates that an email belongs strictly to an allowed company domain.
    Normalizes the email by stripping surrounding whitespace and lowercasing the domain.
    Rejects lookalike domains, subdomain attachments, and unapproved domains with HTTP 400.
    Returns the normalized email."""
    if not email or not isinstance(email, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed.",
        )

    cleaned = email.strip()
    if "@" not in cleaned:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed.",
        )

    parts = cleaned.rsplit("@", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed.",
        )

    local_part, domain = parts[0], parts[1].lower()

    if domain not in ALLOWED_EMAIL_DOMAINS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only company email addresses ending with @vijayspheroidals.com or @vijayspheroidals.onmicrosoft.com are allowed.",
        )

    return f"{local_part}@{domain}"

_TEMP_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_="


def generate_temp_password(length: int = 16) -> str:
    """A cryptographically random one-time password for admin-provisioned accounts --
    never a predictable value (no company name, email, or fixed default). Guarantees at
    least one lowercase, uppercase, digit, and symbol so it passes typical complexity
    checks, then fills the rest from secrets.choice (not random/randint)."""
    required = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*-_="),
    ]
    rest = [secrets.choice(_TEMP_PASSWORD_ALPHABET) for _ in range(length - len(required))]
    chars = required + rest
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)

def hash_password(password: str) -> str:
    pwd_bytes = password.encode("utf-8")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")

get_password_hash = hash_password

def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False

def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None

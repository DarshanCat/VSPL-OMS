#!/bin/bash
set -e

echo "Creating VSPL SMES backend structure..."

mkdir -p backend/app/core
mkdir -p backend/app/models
mkdir -p backend/app/schemas
mkdir -p backend/app/api/v1
cd backend

# ---------- requirements.txt ----------
cat > requirements.txt << 'EOF'
fastapi==0.111.0
uvicorn[standard]==0.30.1
sqlalchemy==2.0.30
alembic==1.13.1
psycopg2-binary==2.9.9
pydantic==2.7.1
pydantic-settings==2.2.1
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-multipart==0.0.9
redis==5.0.4
celery==5.4.0
python-dotenv==1.0.1
EOF

# ---------- .env.example ----------
cat > .env.example << 'EOF'
DATABASE_URL=postgresql://vspl_user:vspl_pass@localhost:5432/vspl_smes
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=change-this-to-a-long-random-string
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480
ENVIRONMENT=development
EOF
cp .env.example .env

# ---------- docker-compose.yml ----------
cat > docker-compose.yml << 'EOF'
version: "3.9"
services:
  db:
    image: postgres:16
    restart: always
    environment:
      POSTGRES_USER: vspl_user
      POSTGRES_PASSWORD: vspl_pass
      POSTGRES_DB: vspl_smes
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7
    restart: always
    ports:
      - "6379:6379"

volumes:
  pgdata:
EOF

# ---------- app/__init__.py files ----------
touch app/__init__.py
touch app/core/__init__.py
touch app/schemas/__init__.py
touch app/api/__init__.py
touch app/api/v1/__init__.py

# ---------- app/core/config.py ----------
cat > app/core/config.py << 'EOF'
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str
    REDIS_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"

settings = Settings()
EOF

# ---------- app/core/database.py ----------
cat > app/core/database.py << 'EOF'
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
EOF

# ---------- app/core/security.py ----------
cat > app/core/security.py << 'EOF'
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

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
EOF

# ---------- app/models/user.py ----------
cat > app/models/user.py << 'EOF'
import enum
import uuid
from sqlalchemy import Column, String, Boolean, Enum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    CEO = "ceo"
    PRODUCTION_MANAGER = "production_manager"
    PLANNER = "planner"
    QA = "qa"
    DISPATCH = "dispatch"
    MACHINE_OPERATOR = "machine_operator"
    STORE = "store"
    SALES = "sales"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/order.py ----------
cat > app/models/order.py << 'EOF'
import enum
import uuid
from sqlalchemy import Column, String, Integer, Date, Enum, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class OrderStatus(str, enum.Enum):
    ACCEPT = "accept"
    HOLD = "hold"
    REJECT = "reject"

class Customer(Base):
    __tablename__ = "customers"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_code = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)

class Part(Base):
    __tablename__ = "parts"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    part_number = Column(String, unique=True, nullable=False)
    grade = Column(String)
    description = Column(String)

class Order(Base):
    """Represents an accepted OAR (Order Acknowledgement Record)."""
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False)
    part_id = Column(UUID(as_uuid=True), ForeignKey("parts.id"), nullable=False)
    customer_po = Column(String, nullable=False)
    po_qty = Column(Integer, nullable=False)
    max_batch_size = Column(Integer, nullable=False)
    delivery_date = Column(Date)
    order_type = Column(String)
    status = Column(Enum(OrderStatus), nullable=False, default=OrderStatus.ACCEPT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/work_order.py ----------
cat > app/models/work_order.py << 'EOF'
import enum
import uuid
from sqlalchemy import Column, String, Integer, Enum, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class StageCode(str, enum.Enum):
    F1 = "F1"
    F2 = "F2"
    F3 = "F3"
    SP = "SP"
    FI = "FI"
    BSR = "BSR"
    DISPATCH = "DISPATCH"

class WOStatus(str, enum.Enum):
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OVERDUE = "overdue"
    CLOSED = "closed"

class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    wo_number = Column(String, unique=True, nullable=False)
    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    physical_wo_qty = Column(Integer, nullable=False)
    status = Column(Enum(WOStatus), nullable=False, default=WOStatus.ON_TRACK)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class WORoute(Base):
    """Ordered stage sequence + per-stage target for a WO (back-calculated from yield)."""
    __tablename__ = "wo_routes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    stage = Column(Enum(StageCode), nullable=False)
    sequence = Column(Integer, nullable=False)
    stage_target_qty = Column(Integer, nullable=False)
    cumulative_ok_qty = Column(Integer, default=0)
EOF

# ---------- app/models/production.py ----------
cat > app/models/production.py << 'EOF'
import enum
import uuid
from sqlalchemy import Column, String, Integer, Enum, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base
from app.models.work_order import StageCode

class ProductionStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"

class ProductionUpdate(Base):
    __tablename__ = "production_updates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    stage = Column(Enum(StageCode), nullable=False)
    machine = Column(String)
    operator_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    shift = Column(String)
    good_qty = Column(Integer, default=0)
    reject_qty = Column(Integer, default=0)
    status = Column(Enum(ProductionStatus), nullable=False)
    remarks = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/conversion.py ----------
cat > app/models/conversion.py << 'EOF'
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class Conversion(Base):
    __tablename__ = "conversions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_wo_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    destination_order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False)
    conversion_wo_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    entry_stage = Column(String, nullable=False)
    quantity = Column(Integer, nullable=False)
    reason = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/nc.py ----------
cat > app/models/nc.py << 'EOF'
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class NCRecord(Base):
    __tablename__ = "nc_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nc_number = Column(String, unique=True, nullable=False)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    stage = Column(String)
    defect_code = Column(String)
    qty = Column(Integer, nullable=False)
    root_cause = Column(String)
    disposition = Column(String)
    status = Column(String, default="open")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/dispatch.py ----------
cat > app/models/dispatch.py << 'EOF'
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class Dispatch(Base):
    __tablename__ = "dispatches"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    work_order_id = Column(UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False)
    invoice_number = Column(String, unique=True)
    dispatched_qty = Column(Integer, nullable=False)
    dispatch_date = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/audit.py ----------
cat > app/models/audit.py << 'EOF'
import uuid
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"))
    action = Column(String, nullable=False)
    entity = Column(String, nullable=False)
    entity_id = Column(String)
    details = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
EOF

# ---------- app/models/__init__.py ----------
cat > app/models/__init__.py << 'EOF'
from app.models.user import User, UserRole
from app.models.order import Customer, Part, Order, OrderStatus
from app.models.work_order import WorkOrder, WORoute, StageCode, WOStatus
from app.models.production import ProductionUpdate, ProductionStatus
from app.models.conversion import Conversion
from app.models.nc import NCRecord
from app.models.dispatch import Dispatch
from app.models.audit import AuditLog
EOF

# ---------- app/schemas/auth.py ----------
cat > app/schemas/auth.py << 'EOF'
from pydantic import BaseModel, EmailStr
from app.models.user import UserRole

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    role: UserRole

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class UserOut(BaseModel):
    id: str
    full_name: str
    email: EmailStr
    role: UserRole

    class Config:
        from_attributes = True
EOF

# ---------- app/api/deps.py ----------
cat > app/api/deps.py << 'EOF'
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import decode_access_token
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user = db.query(User).filter(User.email == payload.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user

def require_roles(*roles: UserRole):
    def wrapper(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user
    return wrapper
EOF

# ---------- app/api/v1/auth.py ----------
cat > app/api/v1/auth.py << 'EOF'
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.schemas.auth import UserLogin, UserCreate, Token, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

@router.post("/register", response_model=UserOut)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        full_name=payload.full_name,
        email=payload.email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    token = create_access_token({"sub": user.email, "role": user.role.value})
    return Token(access_token=token)
EOF

# ---------- app/main.py ----------
cat > app/main.py << 'EOF'
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.v1 import auth

app = FastAPI(title="VSPL SMES API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)

@app.get("/health")
def health():
    return {"status": "ok"}
EOF

echo "Backend files created."
echo "Next steps:"
echo "  cd backend"
echo "  python -m venv venv && source venv/bin/activate"
echo "  pip install -r requirements.txt"
echo "  docker compose up -d"
echo "  alembic init alembic   # then point env.py at app.core.database.Base"
echo "  alembic revision --autogenerate -m 'init'"
echo "  alembic upgrade head"
echo "  uvicorn app.main:app --reload"
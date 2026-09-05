import os
import uuid
from sqlalchemy import create_engine, String, TypeDecorator, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type when on PostgreSQL, otherwise uses CHAR(36) string format.
    """
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        else:
            return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value) if isinstance(value, uuid.UUID) else value
        else:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(str(value)))

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError):
            return value


db_url = settings.DATABASE_URL
connect_args = {}

if db_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
    engine = create_engine(db_url, connect_args=connect_args)
else:
    try:
        engine = create_engine(db_url, pool_pre_ping=True)
        with engine.connect() as conn:
            pass
    except Exception:
        fallback_url = "sqlite:///./vspl_smes.db"
        engine = create_engine(fallback_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def auto_migrate_schema():
    """Auto-migrate schema to ensure newly added columns and enum types exist in PostgreSQL/SQLite."""
    statements = [
        # Convert enum columns to VARCHAR in PostgreSQL for flexible compatibility
        "ALTER TABLE users ALTER COLUMN role TYPE VARCHAR;",
        "ALTER TABLE work_orders ALTER COLUMN status TYPE VARCHAR;",
        "ALTER TABLE work_orders ALTER COLUMN current_stage TYPE VARCHAR;",
        "ALTER TABLE orders ALTER COLUMN status TYPE VARCHAR;",
        "ALTER TABLE wo_routes ALTER COLUMN stage TYPE VARCHAR;",
        "ALTER TABLE stage_wip ALTER COLUMN stage TYPE VARCHAR;",

        # Users
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS employee_id VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Work Orders
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS physical_wo_qty INTEGER DEFAULT 0;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS current_stage VARCHAR DEFAULT 'F1';",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS projected_final_good INTEGER DEFAULT 0;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS shortfall VARCHAR DEFAULT 'No';",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS released_by VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS release_date TIMESTAMP;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Orders
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS oar_number VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_po VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS po_qty INTEGER DEFAULT 0;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS max_batch_size INTEGER DEFAULT 500;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_date DATE;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type VARCHAR DEFAULT 'Standard';",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Production movements
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS client_request_id VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS source_type VARCHAR DEFAULT 'SMES_UI';",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS machine_id VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS operator_id UUID;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS operator_name VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS shift VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS movement_date VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS movement_time VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS remarks VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS created_by UUID;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Stage WIP
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS ent_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS ok_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS inproc_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS onhand_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS rejected_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS received_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS available_wip INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS moved_out_qty INTEGER DEFAULT 0;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE stage_wip ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # WO Routes
        "ALTER TABLE wo_routes ADD COLUMN IF NOT EXISTS cumulative_ent_qty INTEGER DEFAULT 0;",
        "ALTER TABLE wo_routes ADD COLUMN IF NOT EXISTS cumulative_ok_qty INTEGER DEFAULT 0;",
        "ALTER TABLE wo_routes ADD COLUMN IF NOT EXISTS cumulative_rej_qty INTEGER DEFAULT 0;",
        "ALTER TABLE wo_routes ADD COLUMN IF NOT EXISTS cumulative_inproc_qty INTEGER DEFAULT 0;",
        "ALTER TABLE wo_routes ADD COLUMN IF NOT EXISTS cumulative_onhand_qty INTEGER DEFAULT 0;",
        "ALTER TABLE wo_routes ADD COLUMN IF NOT EXISTS stage_status VARCHAR DEFAULT 'Pending';",

        # Packing records
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS fi_approved_qty INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS available_for_packing INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS received_qty INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS packed_qty INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS pending_qty INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS ready_for_dispatch_qty INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS dispatched_qty INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS box_count INTEGER DEFAULT 0;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS package_type VARCHAR;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS remarks VARCHAR;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'Pending';",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE packing_records ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Dispatches
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS customer_po VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS invoice_number VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS dispatched_qty INTEGER DEFAULT 0;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS dispatch_date TIMESTAMP;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS transporter VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS vehicle_number VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS remarks VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS created_by UUID;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # NC Records
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS nc_number VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS stage VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS defect_code VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS qty INTEGER DEFAULT 0;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS root_cause VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS disposition VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS responsibility VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'Open';",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS date_raised TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS date_closed TIMESTAMP;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS remarks VARCHAR;",
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Audit Logs
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS user_id UUID;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS user_name VARCHAR;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS action VARCHAR;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entity VARCHAR;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS entity_id VARCHAR;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS old_value TEXT;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS new_value TEXT;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS details TEXT;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS ip_address VARCHAR;",
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;"
    ]

    for stmt in statements:
        try:
            with engine.begin() as conn:
                conn.execute(text(stmt))
        except Exception:
            pass

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

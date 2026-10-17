import os
import re
import uuid
from datetime import datetime, timezone
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
    if settings.ENVIRONMENT.lower() == "production":
        # Production must never silently downgrade to a local SQLite file if the
        # configured PostgreSQL/Neon connection fails -- that would put real users on a
        # throwaway local database without anyone noticing. Fail loudly instead so the
        # process refuses to start (or /health reports it truthfully) rather than serve
        # traffic against the wrong database.
        engine = create_engine(db_url, pool_pre_ping=True)
    else:
        # Development convenience only: if Postgres isn't running locally, fall back to
        # SQLite so `uvicorn app.main:app` still works without docker-compose up.
        try:
            engine = create_engine(db_url, pool_pre_ping=True)
            with engine.connect() as conn:
                pass
        except Exception:
            fallback_url = "sqlite:///./vspl_smes.db"
            engine = create_engine(fallback_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Diagnostics only -- never business data, never credentials. Populated by the
# actual lifespan handler (app.main:lifespan) and by auto_migrate_schema() itself,
# and surfaced read-only via app/api/v1/migration.py's status endpoint so a
# deployment's startup behavior can be verified without guessing.
LIFESPAN_STATUS = {"started_at": None, "create_all_ran": False}
SCHEMA_SYNC_LAST_RESULT = None


def auto_migrate_schema():
    """Auto-migrate schema to ensure newly added columns and enum types exist in PostgreSQL/SQLite.

    Returns a summary dict (attempted/succeeded/failed counts, dialect, timestamp --
    never the statements' data or any credential) and also stores it on the module as
    SCHEMA_SYNC_LAST_RESULT so a diagnostic endpoint can report the last run without
    needing this function to be called again."""
    global SCHEMA_SYNC_LAST_RESULT
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
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Work Orders
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS physical_wo_qty INTEGER DEFAULT 0;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS current_stage VARCHAR DEFAULT 'F1';",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS projected_final_good INTEGER DEFAULT 0;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS shortfall VARCHAR DEFAULT 'No';",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS released_by VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS release_date TIMESTAMP;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS casting_process VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineering_released_by VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineering_released_at TIMESTAMP;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineering_document_name VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineering_document_url VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineering_document_revision VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS engineering_remarks VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS manufacturing_released_by VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS manufacturing_released_at TIMESTAMP;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS manufacturing_document_name VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS manufacturing_document_url VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS manufacturing_document_revision VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS manufacturing_remarks VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS source_wo_id UUID;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS is_replacement BOOLEAN DEFAULT FALSE;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS replacement_reason VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS heat_number VARCHAR;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS classification VARCHAR DEFAULT 'Production';",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE work_orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Orders
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS oar_number VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_po VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS po_qty INTEGER DEFAULT 0;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS max_batch_size INTEGER DEFAULT 500;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS delivery_date DATE;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_type VARCHAR DEFAULT 'Production';",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "UPDATE orders SET order_type = 'Production' WHERE order_type IS NULL OR order_type = 'Standard';",
        "UPDATE work_orders SET classification = 'Production' WHERE classification IS NULL OR classification = 'Standard';",

        # Production movements
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS client_request_id VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS source_type VARCHAR DEFAULT 'SMES_UI';",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS machine_id VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS operator_id UUID;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS operator_name VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS shift VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS movement_date VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS movement_time VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS heat_number VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS remarks VARCHAR;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS created_by UUID;",
        "ALTER TABLE production_movements ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Production updates
        "ALTER TABLE production_updates ADD COLUMN IF NOT EXISTS client_request_id VARCHAR;",
        "ALTER TABLE production_updates ADD COLUMN IF NOT EXISTS operator_name VARCHAR;",
        "ALTER TABLE production_updates ADD COLUMN IF NOT EXISTS heat_number VARCHAR;",

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
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS client_request_id VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS customer_po VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS invoice_number VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS dispatched_qty INTEGER DEFAULT 0;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS dispatch_date TIMESTAMP;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS transporter VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS vehicle_number VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS remarks VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS created_by UUID;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS unit_price FLOAT DEFAULT 0.0;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS total_invoice_value FLOAT DEFAULT 0.0;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS payment_status VARCHAR DEFAULT 'UNPAID';",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS paid_amount FLOAT DEFAULT 0.0;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS payment_date TIMESTAMP;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS payment_reference VARCHAR;",
        "ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS payment_remarks VARCHAR;",

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
        # Rejection Tracking: source discriminator. Every pre-existing NC row was created by
        # a production-rejection event (the only path that existed before this column), so
        # backfilling the default 'REJECTION' onto old rows is correct, not just convenient.
        "ALTER TABLE nc_records ADD COLUMN IF NOT EXISTS source_type VARCHAR DEFAULT 'REJECTION';",
        "UPDATE nc_records SET source_type = 'REJECTION' WHERE source_type IS NULL;",

        # Conversions: optional link back to the Rejection Tracking record a conversion
        # was dispositioned from. Null for every pre-existing direct mid-route conversion.
        "ALTER TABLE conversions ADD COLUMN IF NOT EXISTS nc_record_id UUID;",

        # Rejection dispositions: physical material-handling fulfillment fields for a
        # SCRAP disposition being sent for melting (a later, separate event from the
        # disposition decision itself).
        "ALTER TABLE rejection_dispositions ADD COLUMN IF NOT EXISTS melting_status VARCHAR;",
        "ALTER TABLE rejection_dispositions ADD COLUMN IF NOT EXISTS melting_destination VARCHAR;",
        "ALTER TABLE rejection_dispositions ADD COLUMN IF NOT EXISTS melting_sent_by_id UUID;",
        "ALTER TABLE rejection_dispositions ADD COLUMN IF NOT EXISTS melting_sent_by_name VARCHAR;",
        "ALTER TABLE rejection_dispositions ADD COLUMN IF NOT EXISTS melting_sent_at TIMESTAMP;",
        "ALTER TABLE rejection_dispositions ADD COLUMN IF NOT EXISTS melting_remarks VARCHAR;",

        # Customer master data completion
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS address VARCHAR;",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS gst VARCHAR;",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS contact_person VARCHAR;",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS email VARCHAR;",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS phone VARCHAR;",
        "ALTER TABLE customers ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;",

        # OAR demand-source linkage (PO vs Schedule) -- default 'po' makes every
        # existing OAR row correctly PO-sourced with no backfill needed.
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS source_type VARCHAR DEFAULT 'po';",
        "UPDATE orders SET source_type = 'po' WHERE source_type IS NULL;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS po_line_id UUID;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS schedule_id UUID;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS oar_po_status VARCHAR;",
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS commitment_date DATE;",
        "ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_oar_number_key;",

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
        "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",

        # Idempotency: enforce uniqueness of client-supplied request tokens so a duplicate
        # submission (double-click / network retry) cannot post the same transaction twice,
        # even under concurrent requests. Nulls remain unrestricted (multiple untagged rows allowed).
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_production_movements_client_request_id ON production_movements (client_request_id) WHERE client_request_id IS NOT NULL;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_production_updates_client_request_id ON production_updates (client_request_id) WHERE client_request_id IS NOT NULL;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_dispatches_client_request_id ON dispatches (client_request_id) WHERE client_request_id IS NOT NULL;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_packing_transactions_client_request_id ON packing_transactions (client_request_id) WHERE client_request_id IS NOT NULL;",

        # Packing Unit Code: assigned once per packing transaction, at creation --
        # unique and immutable. ADD COLUMN alone does not carry the model's unique=True
        # onto an EXISTING table (only a fresh create_all() would), so a partial unique
        # index enforces it at the DB level while still allowing multiple NULLs for
        # rows that predate this column.
        "ALTER TABLE packing_transactions ADD COLUMN IF NOT EXISTS packing_unit_code VARCHAR;",
        "ALTER TABLE packing_transactions ADD COLUMN IF NOT EXISTS packed_quantity INTEGER DEFAULT 0;",
        "ALTER TABLE packing_transactions ADD COLUMN IF NOT EXISTS created_by UUID;",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_packing_transactions_packing_unit_code ON packing_transactions (packing_unit_code) WHERE packing_unit_code IS NOT NULL;",


        # Customer Part Cross-References
        "CREATE TABLE IF NOT EXISTS customer_part_cross_references ("
        "    id UUID PRIMARY KEY,"
        "    customer_id UUID NOT NULL REFERENCES customers(id),"
        "    customer_part_no VARCHAR NOT NULL,"
        "    part_id UUID NOT NULL REFERENCES parts(id),"
        "    source VARCHAR,"
        "    is_active BOOLEAN NOT NULL DEFAULT TRUE,"
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "    created_by_id UUID REFERENCES users(id),"
        "    created_by_name VARCHAR"
        ");",
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_part_cross_ref ON customer_part_cross_references (customer_id, customer_part_no);",

        # Machines
        "ALTER TABLE machines ADD COLUMN IF NOT EXISTS created_by_id UUID;",
        "ALTER TABLE machines ADD COLUMN IF NOT EXISTS created_by_name VARCHAR;",

        # Shifts
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS created_by_id UUID;",
        "ALTER TABLE shifts ADD COLUMN IF NOT EXISTS created_by_name VARCHAR;",

        # Operators
        "ALTER TABLE operators ADD COLUMN IF NOT EXISTS user_id UUID;",
        "ALTER TABLE operators ADD COLUMN IF NOT EXISTS created_by_id UUID;",
        "ALTER TABLE operators ADD COLUMN IF NOT EXISTS created_by_name VARCHAR;",

        # Conversion part mappings
        "ALTER TABLE conversion_part_mappings ADD COLUMN IF NOT EXISTS created_by_id UUID;",
        "ALTER TABLE conversion_part_mappings ADD COLUMN IF NOT EXISTS updated_by_id UUID;",

        # Continuous Casting Heat Number Tracking
        "ALTER TABLE cc_inwards ADD COLUMN IF NOT EXISTS heat_number VARCHAR;",
        "ALTER TABLE cc_stock_units ADD COLUMN IF NOT EXISTS heat_number VARCHAR;",
        "ALTER TABLE cc_cut_records ADD COLUMN IF NOT EXISTS heat_number VARCHAR;",

        # PO Master uniqueness: some pre-existing installations only ever got the old,
        # single-column unique index on po_number (from before the model's composite
        # (customer_id, po_number) uniqueness existed), which wrongly rejects the same
        # po_number for two different customers. Replace it with the composite unique
        # index the current model intends, restoring po_number's own index as a plain,
        # non-unique lookup index.
        "DROP INDEX IF EXISTS ix_po_master_po_number;",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_po_master_customer_po ON po_master (customer_id, po_number);",
        "CREATE INDEX IF NOT EXISTS ix_po_master_po_number ON po_master (po_number);",

        # PO Lines customer_part_number
        "ALTER TABLE po_lines ADD COLUMN IF NOT EXISTS customer_part_number VARCHAR;",
        "UPDATE po_lines SET customer_part_number = (SELECT customer_part_number FROM customer_part_mappings WHERE customer_part_mappings.part_id = po_lines.part_id LIMIT 1) WHERE customer_part_number IS NULL;",

        # Orders customer_part_number
        "ALTER TABLE orders ADD COLUMN IF NOT EXISTS customer_part_number VARCHAR;",
        "UPDATE orders SET customer_part_number = (SELECT customer_part_number FROM customer_part_mappings WHERE customer_part_mappings.customer_id = orders.customer_id AND customer_part_mappings.part_id = orders.part_id LIMIT 1) WHERE customer_part_number IS NULL;",
        "UPDATE orders SET customer_part_number = (SELECT customer_part_number FROM po_lines WHERE po_lines.id = orders.po_line_id LIMIT 1) WHERE customer_part_number IS NULL AND po_line_id IS NOT NULL;",
        "UPDATE orders SET customer_part_number = (SELECT customer_part_no FROM customer_part_cross_references WHERE customer_part_cross_references.customer_id = orders.customer_id AND customer_part_cross_references.part_id = orders.part_id AND customer_part_cross_references.is_active = 1 LIMIT 1) WHERE customer_part_number IS NULL;",

        # PO Master & PO Line Pricing / Value
        "ALTER TABLE po_lines ADD COLUMN IF NOT EXISTS unit_price FLOAT DEFAULT 0.0;",
        "ALTER TABLE po_lines ADD COLUMN IF NOT EXISTS line_total FLOAT DEFAULT 0.0;",
        "ALTER TABLE po_master ADD COLUMN IF NOT EXISTS total_value FLOAT DEFAULT 0.0;",

        # Schedule Master Pricing / Value
        "ALTER TABLE schedule_master ADD COLUMN IF NOT EXISTS unit_price FLOAT DEFAULT 0.0;",
        "ALTER TABLE schedule_master ADD COLUMN IF NOT EXISTS total_value FLOAT DEFAULT 0.0;",

        # MRB Reviews Table
        "CREATE TABLE IF NOT EXISTS mrb_reviews ("
        "    id UUID PRIMARY KEY,"
        "    mrb_number VARCHAR UNIQUE NOT NULL,"
        "    production_update_id UUID,"
        "    movement_id UUID,"
        "    work_order_id UUID NOT NULL,"
        "    stage VARCHAR NOT NULL,"
        "    machine_id VARCHAR,"
        "    operator_name VARCHAR,"
        "    shift VARCHAR,"
        "    heat_number VARCHAR,"
        "    reported_ok_qty INTEGER NOT NULL DEFAULT 0,"
        "    reported_reject_qty INTEGER NOT NULL DEFAULT 0,"
        "    reported_defect_code VARCHAR,"
        "    floor_remarks VARCHAR,"
        "    verified_ok_qty INTEGER,"
        "    verified_reject_qty INTEGER,"
        "    verified_defect_code VARCHAR,"
        "    status VARCHAR NOT NULL DEFAULT 'PENDING',"
        "    disposition VARCHAR DEFAULT 'PENDING',"
        "    reviewed_by_id UUID,"
        "    reviewed_by_name VARCHAR,"
        "    reviewed_at TIMESTAMPTZ,"
        "    review_notes VARCHAR,"
        "    created_at TIMESTAMPTZ DEFAULT NOW(),"
        "    updated_at TIMESTAMPTZ DEFAULT NOW()"
        ");",
        "CREATE INDEX IF NOT EXISTS ix_mrb_reviews_status ON mrb_reviews (status);",
        "CREATE INDEX IF NOT EXISTS ix_mrb_reviews_created_at ON mrb_reviews (created_at);",

        # Customer Returns & Complaints
        "CREATE TABLE IF NOT EXISTS customer_returns ("
        "    id UUID PRIMARY KEY,"
        "    return_number VARCHAR UNIQUE NOT NULL,"
        "    customer_id UUID REFERENCES customers(id),"
        "    customer_code VARCHAR NOT NULL,"
        "    customer_name VARCHAR NOT NULL,"
        "    customer_po VARCHAR,"
        "    invoice_number VARCHAR,"
        "    original_wo_id UUID REFERENCES work_orders(id),"
        "    original_wo_number VARCHAR,"
        "    part_id UUID REFERENCES parts(id),"
        "    part_number VARCHAR NOT NULL,"
        "    returned_qty INTEGER NOT NULL,"
        "    unit_price FLOAT NOT NULL DEFAULT 0.0,"
        "    total_return_value FLOAT NOT NULL DEFAULT 0.0,"
        "    complaint_reason VARCHAR NOT NULL,"
        "    complaint_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "    status VARCHAR NOT NULL DEFAULT 'SENT_TO_CONVERSION',"
        "    conversion_wo_id UUID REFERENCES work_orders(id),"
        "    conversion_wo_number VARCHAR NOT NULL,"
        "    entry_stage VARCHAR NOT NULL DEFAULT 'F1',"
        "    destination_oar_id UUID REFERENCES orders(id),"
        "    destination_oar_number VARCHAR,"
        "    created_by_id UUID REFERENCES users(id),"
        "    created_by_name VARCHAR,"
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ");",
        "CREATE INDEX IF NOT EXISTS ix_customer_returns_customer_code ON customer_returns (customer_code);",
        "CREATE INDEX IF NOT EXISTS ix_customer_returns_return_number ON customer_returns (return_number);",
        "CREATE INDEX IF NOT EXISTS ix_customer_returns_conversion_wo ON customer_returns (conversion_wo_number);",
    ]


    # SQLite's ALTER TABLE ADD COLUMN does not support the "IF NOT EXISTS" clause used
    # above (it's a Postgres-ism) -- on SQLite every one of those statements has always
    # raised a syntax error and been silently swallowed by the broad except below, so
    # none of them ever actually applied to a local SQLite dev database. Detect that
    # column-add case for SQLite and apply it the SQLite-native way (check via
    # PRAGMA table_info, then ALTER without the unsupported clause) instead of letting
    # it silently no-op.
    is_sqlite = engine.dialect.name == "sqlite"
    if is_sqlite:
        try:
            with engine.begin() as conn:
                sql_row = conn.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'")).fetchone()
                if sql_row and "UNIQUE (oar_number)" in sql_row[0]:
                    cols_info = conn.execute(text("PRAGMA table_info(orders)")).fetchall()
                    col_names = [r[1] for r in cols_info]
                    col_list = ", ".join(col_names)
                    old_sql = sql_row[0]
                    new_sql = old_sql.replace("UNIQUE (oar_number),", "").replace(", UNIQUE (oar_number)", "").replace("UNIQUE (oar_number)", "")
                    conn.execute(text("ALTER TABLE orders RENAME TO orders_old_oar_uniq;"))
                    conn.execute(text(new_sql))
                    conn.execute(text(f"INSERT INTO orders ({col_list}) SELECT {col_list} FROM orders_old_oar_uniq;"))
                    conn.execute(text("DROP TABLE orders_old_oar_uniq;"))
        except Exception:
            pass

    add_col_re = re.compile(
        r"ALTER TABLE (\w+) ADD COLUMN IF NOT EXISTS (\w+) (.+?);\s*$", re.IGNORECASE
    )

    succeeded = 0
    failed = 0
    for stmt in statements:
        try:
            if is_sqlite:
                m = add_col_re.match(stmt.strip())
                if m:
                    table, column, col_def = m.group(1), m.group(2), m.group(3)
                    with engine.begin() as conn:
                        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
                        if column not in existing:
                            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))
                    succeeded += 1
                    continue
            with engine.begin() as conn:
                conn.execute(text(stmt))
            succeeded += 1
        except Exception:
            failed += 1

    result = {
        "attempted": len(statements),
        "succeeded": succeeded,
        "failed": failed,
        "dialect": engine.dialect.name,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    SCHEMA_SYNC_LAST_RESULT = result
    return result

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

import enum
from sqlalchemy import create_engine, Column, Integer, String, Enum
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class OrderStatusUpper(str, enum.Enum):
    ACCEPT = "accept"
    HOLD = "hold"
    REJECT = "reject"
    CONFIRMED = "CONFIRMED"

class OrderStatusLower(str, enum.Enum):
    ACCEPT = "accept"
    HOLD = "hold"
    REJECT = "reject"
    CONFIRMED = "confirmed"

class WOStatusUpper(str, enum.Enum):
    PLANNED = "planned"
    RELEASED = "released"
    IN_PRODUCTION = "in_production"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OVERDUE = "overdue"
    READY = "ready"
    DISPATCHED = "dispatched"
    CLOSED = "closed"
    OPEN = "OPEN"

class WOStatusLower(str, enum.Enum):
    PLANNED = "planned"
    RELEASED = "released"
    IN_PRODUCTION = "in_production"
    ON_TRACK = "on_track"
    AT_RISK = "at_risk"
    OVERDUE = "overdue"
    READY = "ready"
    DISPATCHED = "dispatched"
    CLOSED = "closed"
    OPEN = "open"

class TestOrderUpper(Base):
    __tablename__ = "test_order_upper"
    id = Column(Integer, primary_key=True)
    status = Column(Enum(OrderStatusUpper), nullable=False)

class TestOrderLower(Base):
    __tablename__ = "test_order_lower"
    id = Column(Integer, primary_key=True)
    status = Column(Enum(OrderStatusLower), nullable=False)

class TestWOUpper(Base):
    __tablename__ = "test_wo_upper"
    id = Column(Integer, primary_key=True)
    status = Column(Enum(WOStatusUpper), nullable=False)

class TestWOLower(Base):
    __tablename__ = "test_wo_lower"
    id = Column(Integer, primary_key=True)
    status = Column(Enum(WOStatusLower), nullable=False)

engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
s = Session()

# Insert raw strings
s.connection().exec_driver_sql("INSERT INTO test_order_upper (id, status) VALUES (1, 'CONFIRMED')")
s.connection().exec_driver_sql("INSERT INTO test_order_lower (id, status) VALUES (1, 'CONFIRMED')")
s.connection().exec_driver_sql("INSERT INTO test_wo_upper (id, status) VALUES (1, 'OPEN')")
s.connection().exec_driver_sql("INSERT INTO test_wo_lower (id, status) VALUES (1, 'OPEN')")

print("--- TESTING ORDER STATUS ---")
o_upper = s.query(TestOrderUpper).first()
print("Upper Enum read:", o_upper.status, type(o_upper.status), o_upper.status.value)

try:
    o_lower = s.query(TestOrderLower).first()
    print("Lower Enum read:", o_lower.status, type(o_lower.status), o_lower.status.value)
except Exception as e:
    print("Lower Enum read failed:", type(e).__name__, e)

print("\n--- TESTING WO STATUS ---")
w_upper = s.query(TestWOUpper).first()
print("Upper Enum read:", w_upper.status, type(w_upper.status), w_upper.status.value)

try:
    w_lower = s.query(TestWOLower).first()
    print("Lower Enum read:", w_lower.status, type(w_lower.status), w_lower.status.value)
except Exception as e:
    print("Lower Enum read failed:", type(e).__name__, e)

"""
database.py
-----------
Handles all database concerns for the Automated B2B Client Reporting & Query Engine.

Responsibilities:
  - Define the SQLAlchemy ORM models for the B2B SaaS schema.
  - Provide a database engine and session factory.
  - Expose a seed function that populates the database with realistic mock data
    spanning the last 3 months, suitable for complex JOIN queries.
  - Expose a structured SCHEMA_CONTEXT string that the Gemini model uses to
    understand the exact table/column layout before generating SQL.
"""

import random
from datetime import date, timedelta

from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

# ---------------------------------------------------------------------------
# Engine & Session Factory
# ---------------------------------------------------------------------------

# SQLite file-based DB for portability. Change the URL to any SQLAlchemy-
# compatible connection string (e.g. PostgreSQL) without touching anything else.
DATABASE_URL = "sqlite:///./b2b_reporting.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # Required for SQLite + FastAPI
    echo=False,  # Set True to log all SQL statements during development
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# ORM Base & Models
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    pass


class Client(Base):
    """
    Represents a B2B customer organisation.

    Columns
    -------
    id           : Primary key.
    company_name : Human-readable company identifier.
    tier         : Market segment — Enterprise | Mid-Market | SMB.
    industry     : Vertical the client operates in.
    country      : ISO country name for the client's HQ.
    """

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(120), nullable=False, unique=True)
    tier = Column(String(20), nullable=False)          # Enterprise | Mid-Market | SMB
    industry = Column(String(80), nullable=False)
    country = Column(String(60), nullable=False)

    # Relationships (back-populates for ORM convenience; not used in raw SQL path)
    subscriptions = relationship("Subscription", back_populates="client")
    usage_logs = relationship("UsageLog", back_populates="client")
    invoices = relationship("Invoice", back_populates="client")


class Subscription(Base):
    """
    Tracks the active or historical subscription plan for a client.

    Columns
    -------
    id            : Primary key.
    client_id     : FK → clients.id.
    plan_name     : Commercial plan label (e.g. 'Starter', 'Growth', 'Enterprise').
    monthly_price : Recurring monthly charge in USD.
    status        : Lifecycle state — Active | Paused | Churned.
    """

    __tablename__ = "subscriptions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    plan_name = Column(String(60), nullable=False)
    monthly_price = Column(Float, nullable=False)
    status = Column(String(20), nullable=False)        # Active | Paused | Churned

    client = relationship("Client", back_populates="subscriptions")


class UsageLog(Base):
    """
    Daily snapshot of a client's platform consumption.

    Columns
    -------
    id               : Primary key.
    client_id        : FK → clients.id.
    api_calls_made   : Number of API calls recorded on log_date.
    storage_used_gb  : Cumulative storage consumed (GB) on log_date.
    log_date         : Calendar date of the snapshot.
    """

    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    api_calls_made = Column(Integer, nullable=False)
    storage_used_gb = Column(Float, nullable=False)
    log_date = Column(Date, nullable=False)

    client = relationship("Client", back_populates="usage_logs")


class Invoice(Base):
    """
    Billing record issued to a client.

    Columns
    -------
    id             : Primary key.
    client_id      : FK → clients.id.
    amount_due     : Invoice total in USD.
    payment_status : Settlement state — Paid | Unpaid.
    due_date       : Calendar date by which payment is expected.
    """

    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)
    amount_due = Column(Float, nullable=False)
    payment_status = Column(String(10), nullable=False)  # Paid | Unpaid
    due_date = Column(Date, nullable=False)

    client = relationship("Client", back_populates="invoices")


# ---------------------------------------------------------------------------
# Schema Context String  (fed to Gemini as grounding context)
# ---------------------------------------------------------------------------

SCHEMA_CONTEXT = """
You are querying a SQLite database for a B2B SaaS platform.
Below is the complete schema. Use ONLY these tables and columns.

TABLE: clients
  - id            INTEGER  PRIMARY KEY
  - company_name  TEXT     NOT NULL UNIQUE
  - tier          TEXT     NOT NULL  -- values: 'Enterprise', 'Mid-Market', 'SMB'
  - industry      TEXT     NOT NULL
  - country       TEXT     NOT NULL

TABLE: subscriptions
  - id             INTEGER  PRIMARY KEY
  - client_id      INTEGER  NOT NULL  REFERENCES clients(id)
  - plan_name      TEXT     NOT NULL  -- e.g. 'Starter', 'Growth', 'Professional', 'Enterprise'
  - monthly_price  REAL     NOT NULL
  - status         TEXT     NOT NULL  -- values: 'Active', 'Paused', 'Churned'

TABLE: usage_logs
  - id               INTEGER  PRIMARY KEY
  - client_id        INTEGER  NOT NULL  REFERENCES clients(id)
  - api_calls_made   INTEGER  NOT NULL
  - storage_used_gb  REAL     NOT NULL
  - log_date         DATE     NOT NULL  -- format: YYYY-MM-DD

TABLE: invoices
  - id              INTEGER  PRIMARY KEY
  - client_id       INTEGER  NOT NULL  REFERENCES clients(id)
  - amount_due      REAL     NOT NULL
  - payment_status  TEXT     NOT NULL  -- values: 'Paid', 'Unpaid'
  - due_date        DATE     NOT NULL  -- format: YYYY-MM-DD

RELATIONSHIPS:
  subscriptions.client_id  → clients.id
  usage_logs.client_id     → clients.id
  invoices.client_id       → clients.id

NOTES:
  - All monetary values are in USD.
  - log_date entries span the last 3 months from today.
  - A client may have multiple invoices and multiple usage_log entries.
  - Use standard SQLite date functions (e.g. DATE('now'), strftime) for date arithmetic.
"""


# ---------------------------------------------------------------------------
# Database Initialisation & Seeding
# ---------------------------------------------------------------------------

# --- Static seed data pools ---

_CLIENTS_SEED = [
    ("Apex Dynamics",       "Enterprise",  "FinTech",          "United States"),
    ("BlueSky Analytics",   "Mid-Market",  "Healthcare",       "United Kingdom"),
    ("Cascade Retail",      "SMB",         "E-Commerce",       "Canada"),
    ("Delphi Systems",      "Enterprise",  "Manufacturing",    "Germany"),
    ("Ember Cloud",         "Mid-Market",  "SaaS",             "Australia"),
    ("Frontier Logistics",  "SMB",         "Supply Chain",     "India"),
    ("Granite Partners",    "Enterprise",  "Private Equity",   "United States"),
    ("Horizon Media",       "Mid-Market",  "AdTech",           "France"),
    ("IronBridge Corp",     "SMB",         "Construction",     "Brazil"),
    ("Jade Biotech",        "Enterprise",  "Life Sciences",    "Switzerland"),
    ("Keystone Ventures",   "Mid-Market",  "Venture Capital",  "Singapore"),
    ("Luminary EdTech",     "SMB",         "Education",        "South Africa"),
]

_PLAN_MAP = {
    "Enterprise":  ("Enterprise",   4999.00),
    "Mid-Market":  ("Professional", 1499.00),
    "SMB":         ("Growth",        499.00),
}

_STATUSES = ["Active", "Active", "Active", "Paused", "Churned"]  # weighted toward Active


def _random_date_in_last_90_days() -> date:
    """Return a random calendar date within the last 90 days."""
    offset = random.randint(0, 89)
    return date.today() - timedelta(days=offset)


def seed_database() -> None:
    """
    Create all tables (idempotent) and populate them with realistic mock data.

    The function is safe to call multiple times — it checks for existing rows
    before inserting, so re-running the application will not duplicate data.
    """
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as session:
        # Guard: skip seeding if data already exists
        if session.query(Client).count() > 0:
            return

        random.seed(42)  # Reproducible mock data

        for company, tier, industry, country in _CLIENTS_SEED:
            # --- Client ---
            client = Client(
                company_name=company,
                tier=tier,
                industry=industry,
                country=country,
            )
            session.add(client)
            session.flush()  # Populate client.id before FK references

            # --- Subscription ---
            plan_name, base_price = _PLAN_MAP[tier]
            # Add slight price variation per client (±10 %)
            price = round(base_price * random.uniform(0.90, 1.10), 2)
            subscription = Subscription(
                client_id=client.id,
                plan_name=plan_name,
                monthly_price=price,
                status=random.choice(_STATUSES),
            )
            session.add(subscription)

            # --- Usage Logs (one entry per week for the last 12 weeks) ---
            for week in range(12):
                log_date = date.today() - timedelta(weeks=week)
                usage = UsageLog(
                    client_id=client.id,
                    api_calls_made=random.randint(500, 50_000),
                    storage_used_gb=round(random.uniform(0.5, 500.0), 2),
                    log_date=log_date,
                )
                session.add(usage)

            # --- Invoices (2–4 invoices per client, spread over last 3 months) ---
            num_invoices = random.randint(2, 4)
            for inv_num in range(num_invoices):
                due_date = date.today() - timedelta(days=random.randint(0, 90))
                invoice = Invoice(
                    client_id=client.id,
                    amount_due=round(price * random.uniform(0.8, 1.2), 2),
                    payment_status=random.choice(["Paid", "Paid", "Unpaid"]),  # 2:1 paid ratio
                    due_date=due_date,
                )
                session.add(invoice)

        session.commit()
        print("[database] Seed complete — mock data inserted successfully.")


# ---------------------------------------------------------------------------
# FastAPI Dependency: per-request DB session
# ---------------------------------------------------------------------------


def get_db():
    """
    Yield a SQLAlchemy Session for use as a FastAPI dependency.
    Ensures the session is always closed after the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

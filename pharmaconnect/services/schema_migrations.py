"""Dialect-aware additive schema migrations."""
from __future__ import annotations

from sqlalchemy import inspect, text

from .. import db


def _dialect() -> str:
    return db.engine.dialect.name


def _add_column(table: str, column: str, sqlite_ddl: str, postgres_ddl: str | None = None) -> None:
    insp = inspect(db.engine)
    if table not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns(table)}
    if column in cols:
        return
    ddl = postgres_ddl if _dialect() == "postgresql" and postgres_ddl else sqlite_ddl
    try:
        db.session.execute(text(ddl))
        db.session.commit()
    except Exception:
        db.session.rollback()


def ensure_schema() -> None:
    """Apply lightweight additive migrations for SQLite and PostgreSQL."""
    _add_column("purchase_bills", "warehouse_id", "ALTER TABLE purchase_bills ADD COLUMN warehouse_id INTEGER")

    bill_cols = {
        "order_ref": (
            "ALTER TABLE bills ADD COLUMN order_ref VARCHAR(60)",
            "ALTER TABLE bills ADD COLUMN order_ref VARCHAR(60)",
        ),
        "eway_no": (
            "ALTER TABLE bills ADD COLUMN eway_no VARCHAR(20)",
            "ALTER TABLE bills ADD COLUMN eway_no VARCHAR(20)",
        ),
        "payment_ref": (
            "ALTER TABLE bills ADD COLUMN payment_ref VARCHAR(60)",
            "ALTER TABLE bills ADD COLUMN payment_ref VARCHAR(60)",
        ),
        "irn": (
            "ALTER TABLE bills ADD COLUMN irn VARCHAR(64)",
            "ALTER TABLE bills ADD COLUMN irn VARCHAR(64)",
        ),
        "irn_generated_on": (
            "ALTER TABLE bills ADD COLUMN irn_generated_on DATETIME",
            "ALTER TABLE bills ADD COLUMN irn_generated_on TIMESTAMP",
        ),
    }
    for col, (sqlite_ddl, pg_ddl) in bill_cols.items():
        _add_column("bills", col, sqlite_ddl, pg_ddl)

    _add_column(
        "consignment_batches", "rack",
        "ALTER TABLE consignment_batches ADD COLUMN rack VARCHAR(20)",
    )
    _add_column(
        "retail_customers", "loyalty_points",
        "ALTER TABLE retail_customers ADD COLUMN loyalty_points INTEGER DEFAULT 0",
        "ALTER TABLE retail_customers ADD COLUMN loyalty_points INTEGER DEFAULT 0",
    )
    _add_column(
        "integration_settings", "alert_schedule_enabled",
        "ALTER TABLE integration_settings ADD COLUMN alert_schedule_enabled BOOLEAN DEFAULT 0",
        "ALTER TABLE integration_settings ADD COLUMN alert_schedule_enabled BOOLEAN DEFAULT FALSE",
    )
    _add_column(
        "integration_settings", "alert_schedule_hour",
        "ALTER TABLE integration_settings ADD COLUMN alert_schedule_hour INTEGER DEFAULT 9",
    )
    _add_column(
        "retail_customers", "credit_days",
        "ALTER TABLE retail_customers ADD COLUMN credit_days INTEGER DEFAULT 30",
    )
    _add_column(
        "party_ledgers", "credit_limit",
        "ALTER TABLE party_ledgers ADD COLUMN credit_limit NUMERIC(12, 2) DEFAULT 0",
    )
    _add_column(
        "party_ledgers", "credit_days",
        "ALTER TABLE party_ledgers ADD COLUMN credit_days INTEGER DEFAULT 30",
    )
    _add_column(
        "bills", "due_date",
        "ALTER TABLE bills ADD COLUMN due_date DATETIME",
        "ALTER TABLE bills ADD COLUMN due_date TIMESTAMP",
    )
    _add_column(
        "bills", "balance_due",
        "ALTER TABLE bills ADD COLUMN balance_due NUMERIC(12, 2) DEFAULT 0",
    )

    try:
        db.session.execute(
            text(
                "UPDATE bills SET balance_due = grand_total "
                "WHERE payment_mode = 'CREDIT' AND (balance_due IS NULL OR balance_due = 0)"
            )
        )
        db.session.execute(
            text(
                "UPDATE bills SET due_date = datetime(billed_on, '+30 days') "
                "WHERE payment_mode = 'CREDIT' AND due_date IS NULL"
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
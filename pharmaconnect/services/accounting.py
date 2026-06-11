from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func

from .. import db
from ..models import AccountEntry, Bill, Organization, PartyLedger
from .credit import record_party_payment


def record_payment(org_id: int, party_name: str, amount: Decimal, note: str = "") -> AccountEntry:
    entry = AccountEntry(
        org_id=org_id,
        entry_type="RECEIPT",
        reference=f"RCPT-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        party_name=party_name,
        debit=Decimal("0"),
        credit=amount,
        note=note,
    )
    db.session.add(entry)
    record_party_payment(org_id, party_name, amount)
    return entry


def pnl_summary(org_id: int, days: int = 30) -> dict:
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    sales = (
        db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
        .filter(Bill.facility_id == org_id, Bill.billed_on >= since)
        .scalar()
    )
    receipts = (
        db.session.query(func.coalesce(func.sum(AccountEntry.credit), 0))
        .filter(AccountEntry.org_id == org_id, AccountEntry.entry_type == "RECEIPT", AccountEntry.ts >= since)
        .scalar()
    )
    return {
        "sales": float(sales or 0),
        "receipts": float(receipts or 0),
        "period_days": days,
    }


def receivables(org_id: int) -> list[PartyLedger]:
    return (
        PartyLedger.query.filter_by(org_id=org_id)
        .filter(PartyLedger.outstanding > 0)
        .order_by(PartyLedger.outstanding.desc())
        .all()
    )


def distributor_receivables(distributor_id: int) -> list[dict]:
    from .settlement import distributor_settlement_receivables

    return distributor_settlement_receivables(distributor_id)


def list_parties(org_id: int) -> list[PartyLedger]:
    return (
        PartyLedger.query.filter_by(org_id=org_id)
        .order_by(PartyLedger.party_name)
        .all()
    )


def create_party(
    org_id: int,
    party_name: str,
    party_gstin: str | None = None,
    credit_days: int = 30,
    credit_limit: Decimal = Decimal("0"),
) -> PartyLedger:
    name = party_name.strip()
    if not name:
        raise ValueError("Party name is required")
    existing = PartyLedger.query.filter_by(org_id=org_id, party_name=name).first()
    if existing:
        raise ValueError("Party already exists")
    ledger = PartyLedger(
        org_id=org_id,
        party_name=name,
        party_gstin=party_gstin or None,
        credit_days=max(int(credit_days or 0), 0),
        credit_limit=credit_limit,
    )
    db.session.add(ledger)
    db.session.flush()
    return ledger
"""Credit terms, due dates, overdue checks, and aging."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from .. import db
from ..models import Bill, PartyLedger, RetailCustomer

TWO = Decimal("0.01")


def compute_due_date(billed_on: datetime, credit_days: int) -> datetime:
    days = max(int(credit_days or 0), 0)
    base = billed_on or datetime.utcnow()
    return base + timedelta(days=days)


def _open_retail_bills(customer_id: int) -> list[Bill]:
    return (
        Bill.query.filter_by(retail_customer_id=customer_id, payment_mode="CREDIT")
        .filter(Bill.balance_due > 0)
        .order_by(Bill.due_date.asc(), Bill.billed_on.asc())
        .all()
    )


def _open_party_bills(org_id: int, party_name: str) -> list[Bill]:
    return (
        Bill.query.filter_by(
            facility_id=org_id,
            customer_name=party_name,
            payment_mode="CREDIT",
            bill_type="INSTITUTIONAL",
        )
        .filter(Bill.balance_due > 0)
        .order_by(Bill.due_date.asc(), Bill.billed_on.asc())
        .all()
    )


def overdue_summary(bills: list[Bill]) -> tuple[Decimal, datetime | None]:
    today = datetime.utcnow().date()
    total = Decimal("0")
    oldest: datetime | None = None
    for bill in bills:
        due = bill.due_date.date() if bill.due_date else None
        if not due or due >= today:
            continue
        bal = Decimal(str(bill.balance_due or 0))
        if bal <= 0:
            continue
        total += bal
        if oldest is None or (bill.due_date and bill.due_date < oldest):
            oldest = bill.due_date
    return total, oldest


def assert_retail_credit_allowed(customer: RetailCustomer, amount: Decimal) -> None:
    limit = Decimal(str(customer.credit_limit or 0))
    if limit > 0:
        projected = Decimal(str(customer.outstanding or 0)) + amount
        if projected > limit:
            raise ValueError(
                f"Credit limit exceeded (limit ₹{limit}, current due ₹{customer.outstanding or 0})"
            )
    overdue, oldest = overdue_summary(_open_retail_bills(customer.id))
    if overdue > 0:
        due_txt = oldest.strftime("%d-%b-%Y") if oldest else "—"
        raise ValueError(
            f"Overdue balance ₹{overdue.quantize(TWO)} (oldest due {due_txt}). "
            "Collect overdue amount before new credit."
        )


def assert_party_credit_allowed(ledger: PartyLedger, amount: Decimal) -> None:
    limit = Decimal(str(ledger.credit_limit or 0))
    if limit > 0:
        projected = Decimal(str(ledger.outstanding or 0)) + amount
        if projected > limit:
            raise ValueError(
                f"Credit limit exceeded for {ledger.party_name} "
                f"(limit ₹{limit}, current due ₹{ledger.outstanding or 0})"
            )
    overdue, oldest = overdue_summary(_open_party_bills(ledger.org_id, ledger.party_name))
    if overdue > 0:
        due_txt = oldest.strftime("%d-%b-%Y") if oldest else "—"
        raise ValueError(
            f"{ledger.party_name} has overdue balance ₹{overdue.quantize(TWO)} "
            f"(oldest due {due_txt}). Clear overdue before new credit."
        )


def mark_credit_bill(bill: Bill, credit_days: int) -> None:
    bill.due_date = compute_due_date(bill.billed_on or datetime.utcnow(), credit_days)
    bill.balance_due = Decimal(str(bill.grand_total or 0))


def allocate_payment(bills: list[Bill], amount: Decimal) -> Decimal:
    remaining = amount
    for bill in bills:
        if remaining <= 0:
            break
        due = Decimal(str(bill.balance_due or 0))
        if due <= 0:
            continue
        pay = min(due, remaining).quantize(TWO)
        bill.balance_due = (due - pay).quantize(TWO)
        remaining -= pay
    return (amount - remaining).quantize(TWO)


def record_retail_payment(customer: RetailCustomer, amount: Decimal) -> Decimal:
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    applied = allocate_payment(_open_retail_bills(customer.id), amount)
    if applied <= 0:
        raise ValueError("No open credit invoices to settle")
    customer.outstanding = max(Decimal(str(customer.outstanding or 0)) - applied, Decimal("0"))
    return applied


def record_party_payment(org_id: int, party_name: str, amount: Decimal) -> Decimal:
    if amount <= 0:
        raise ValueError("Payment amount must be positive")
    applied = allocate_payment(_open_party_bills(org_id, party_name), amount)
    if applied <= 0:
        raise ValueError("No open credit invoices to settle")
    ledger = PartyLedger.query.filter_by(org_id=org_id, party_name=party_name).first()
    if ledger:
        ledger.outstanding = max(Decimal(str(ledger.outstanding or 0)) - applied, Decimal("0"))
        ledger.last_txn_on = datetime.utcnow()
    return applied


def reduce_bill_balance(bill: Bill, amount: Decimal) -> None:
    if amount <= 0:
        return
    current = Decimal(str(bill.balance_due or 0))
    if current <= 0:
        return
    bill.balance_due = max(current - amount, Decimal("0")).quantize(TWO)


def _age_bucket(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "days_1_30"
    if days_past_due <= 60:
        return "days_31_60"
    if days_past_due <= 90:
        return "days_61_90"
    return "days_90_plus"


def credit_aging_report(org_id: int) -> dict:
    today = datetime.utcnow().date()
    buckets = {
        "current": Decimal("0"),
        "days_1_30": Decimal("0"),
        "days_31_60": Decimal("0"),
        "days_61_90": Decimal("0"),
        "days_90_plus": Decimal("0"),
    }
    rows: list[dict] = []

    bills = (
        Bill.query.filter_by(facility_id=org_id, payment_mode="CREDIT")
        .filter(Bill.balance_due > 0)
        .order_by(Bill.due_date.asc(), Bill.billed_on.asc())
        .all()
    )
    for bill in bills:
        bal = Decimal(str(bill.balance_due or 0))
        if bal <= 0:
            continue
        due = bill.due_date.date() if bill.due_date else bill.billed_on.date()
        days_past = (today - due).days
        bucket = _age_bucket(days_past)
        buckets[bucket] += bal
        party_type = "Retail" if bill.retail_customer_id else "Institutional"
        rows.append({
            "invoice": bill.number,
            "party": bill.customer_name or "—",
            "party_type": party_type,
            "billed_on": bill.billed_on.strftime("%d-%b-%Y"),
            "due_date": bill.due_date.strftime("%d-%b-%Y") if bill.due_date else "—",
            "balance": float(bal),
            "days_past_due": days_past,
            "bucket": bucket,
            "overdue": days_past > 0,
        })

    total = sum(buckets.values())
    return {
        "buckets": {k: float(v) for k, v in buckets.items()},
        "total_open": float(total),
        "rows": rows,
    }


def retail_credit_status(customer_id: int) -> dict:
    customer = db.session.get(RetailCustomer, customer_id)
    if not customer:
        return {}
    bills = _open_retail_bills(customer_id)
    overdue, oldest = overdue_summary(bills)
    return {
        "credit_days": int(customer.credit_days or 0),
        "credit_limit": float(customer.credit_limit or 0),
        "outstanding": float(customer.outstanding or 0),
        "overdue": float(overdue),
        "oldest_due": oldest.strftime("%d-%b-%Y") if oldest else None,
        "open_invoices": [
            {
                "number": b.number,
                "due_date": b.due_date.strftime("%d-%b-%Y") if b.due_date else "—",
                "balance": float(b.balance_due or 0),
                "overdue": bool(b.due_date and b.due_date.date() < datetime.utcnow().date()),
            }
            for b in bills
        ],
    }
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func

from .. import db
from ..models import (
    AccountEntry,
    Bill,
    BillLine,
    ConsignmentBatch,
    ConsignmentSettlement,
    Organization,
    PartyLedger,
)

TWO = Decimal("0.01")


def _get_or_create_ledger(org_id: int, party_name: str, party_gstin: str | None = None) -> PartyLedger:
    ledger = PartyLedger.query.filter_by(org_id=org_id, party_name=party_name).first()
    if not ledger:
        ledger = PartyLedger(org_id=org_id, party_name=party_name, party_gstin=party_gstin)
        db.session.add(ledger)
        db.session.flush()
    return ledger


def record_for_bill_line(
    bill: Bill,
    bill_line: BillLine,
    batch: ConsignmentBatch,
    facility: Organization,
) -> ConsignmentSettlement:
    distributor = db.session.get(Organization, batch.distributor_id)
    if not distributor:
        raise ValueError("Distributor not found for consignment batch")

    qty = Decimal(str(bill_line.qty))
    rate = Decimal(str(batch.ptr))
    amount = (qty * rate).quantize(TWO, ROUND_HALF_UP)

    settlement = ConsignmentSettlement(
        bill_id=bill.id,
        bill_line_id=bill_line.id,
        distributor_id=distributor.id,
        facility_id=facility.id,
        item_id=bill_line.item_id,
        batch_id=batch.id,
        qty=qty,
        settlement_rate=rate,
        amount=amount,
        status="OPEN",
    )
    db.session.add(settlement)

    fac_ledger = _get_or_create_ledger(facility.id, distributor.name, distributor.gstin)
    fac_ledger.outstanding = Decimal(str(fac_ledger.outstanding or 0)) + amount
    fac_ledger.last_txn_on = datetime.utcnow()

    dist_ledger = _get_or_create_ledger(distributor.id, facility.name, facility.gstin)
    dist_ledger.outstanding = Decimal(str(dist_ledger.outstanding or 0)) + amount
    dist_ledger.last_txn_on = datetime.utcnow()

    db.session.add(
        AccountEntry(
            org_id=facility.id,
            entry_type="CONSIGNMENT_SETTLEMENT",
            reference=bill.number,
            party_name=distributor.name,
            debit=amount,
            credit=Decimal("0"),
            note=f"PTR settlement for {qty} units",
        )
    )
    db.session.add(
        AccountEntry(
            org_id=distributor.id,
            entry_type="CONSIGNMENT_SETTLEMENT",
            reference=bill.number,
            party_name=facility.name,
            debit=Decimal("0"),
            credit=amount,
            note=f"Auto-charge from {bill.number}",
        )
    )
    return settlement


def reverse_for_return_line(
    bill_line: BillLine,
    return_qty: Decimal,
    reference: str,
    facility: Organization,
) -> Decimal:
    """Reverse PTR consignment settlement when a sale is returned."""
    settlement = ConsignmentSettlement.query.filter_by(bill_line_id=bill_line.id).first()
    if not settlement or settlement.status == "REVERSED":
        return Decimal("0")
    if Decimal(str(settlement.amount or 0)) <= 0:
        return Decimal("0")

    line_qty = Decimal(str(bill_line.qty))
    if return_qty <= 0 or return_qty > line_qty:
        raise ValueError("Invalid return qty for settlement reversal")

    portion = return_qty / line_qty
    reverse_amt = (Decimal(str(settlement.amount)) * portion).quantize(TWO, ROUND_HALF_UP)
    if reverse_amt <= 0:
        return Decimal("0")

    distributor = db.session.get(Organization, settlement.distributor_id)
    if not distributor:
        raise ValueError("Distributor not found for settlement reversal")

    was_paid = settlement.status == "PAID"
    new_qty = Decimal(str(settlement.qty)) - return_qty
    new_amt = Decimal(str(settlement.amount)) - reverse_amt
    if new_qty <= 0 or new_amt <= 0:
        settlement.qty = Decimal("0")
        settlement.amount = Decimal("0")
        settlement.status = "REVERSED"
    else:
        settlement.qty = new_qty
        settlement.amount = new_amt
        if was_paid:
            settlement.status = "PAID"

    fac_ledger = PartyLedger.query.filter_by(org_id=facility.id, party_name=distributor.name).first()
    if fac_ledger:
        fac_ledger.outstanding = Decimal(str(fac_ledger.outstanding or 0)) - reverse_amt
        fac_ledger.last_txn_on = datetime.utcnow()

    dist_ledger = PartyLedger.query.filter_by(org_id=distributor.id, party_name=facility.name).first()
    if dist_ledger:
        dist_ledger.outstanding = Decimal(str(dist_ledger.outstanding or 0)) - reverse_amt
        dist_ledger.last_txn_on = datetime.utcnow()

    db.session.add(
        AccountEntry(
            org_id=facility.id,
            entry_type="CONSIGNMENT_SETTLEMENT",
            reference=reference,
            party_name=distributor.name,
            debit=Decimal("0"),
            credit=reverse_amt,
            note=f"PTR reversal for {return_qty} units returned",
        )
    )
    db.session.add(
        AccountEntry(
            org_id=distributor.id,
            entry_type="CONSIGNMENT_SETTLEMENT",
            reference=reference,
            party_name=facility.name,
            debit=reverse_amt,
            credit=Decimal("0"),
            note=f"Settlement reversed on return {reference}",
        )
    )
    return reverse_amt


def facility_payable_to_distributor(facility_id: int, distributor_name: str) -> Decimal:
    ledger = PartyLedger.query.filter_by(org_id=facility_id, party_name=distributor_name).first()
    return Decimal(str(ledger.outstanding or 0)) if ledger else Decimal("0")


def distributor_settlement_receivables(distributor_id: int) -> list[dict]:
    facilities = Organization.query.filter_by(parent_id=distributor_id).all()
    rows = []
    for f in facilities:
        ledger = PartyLedger.query.filter_by(org_id=distributor_id, party_name=f.name).first()
        open_amt = (
            db.session.query(func.coalesce(func.sum(ConsignmentSettlement.amount), 0))
            .filter_by(distributor_id=distributor_id, facility_id=f.id, status="OPEN")
            .scalar()
        )
        rows.append({
            "facility_id": f.id,
            "facility_name": f.name,
            "outstanding": float(ledger.outstanding if ledger else 0),
            "open_settlements": float(open_amt or 0),
        })
    return rows


def recent_settlements(distributor_id: int | None = None, facility_id: int | None = None, limit: int = 30) -> list[ConsignmentSettlement]:
    q = ConsignmentSettlement.query.order_by(ConsignmentSettlement.created_at.desc())
    if distributor_id:
        q = q.filter_by(distributor_id=distributor_id)
    if facility_id:
        q = q.filter_by(facility_id=facility_id)
    return q.limit(limit).all()


def record_settlement_payment(facility_id: int, distributor_id: int, amount: Decimal, note: str = "") -> None:
    if amount <= 0:
        raise ValueError("Amount must be positive")

    facility = db.session.get(Organization, facility_id)
    distributor = db.session.get(Organization, distributor_id)
    if not facility or not distributor:
        raise ValueError("Invalid facility or distributor")

    fac_ledger = PartyLedger.query.filter_by(org_id=facility_id, party_name=distributor.name).first()
    dist_ledger = PartyLedger.query.filter_by(org_id=distributor_id, party_name=facility.name).first()
    if not fac_ledger or Decimal(str(fac_ledger.outstanding or 0)) < amount:
        raise ValueError("Payment exceeds consignment payable")

    fac_ledger.outstanding = Decimal(str(fac_ledger.outstanding)) - amount
    fac_ledger.last_txn_on = datetime.utcnow()
    if dist_ledger:
        dist_ledger.outstanding = max(Decimal(str(dist_ledger.outstanding or 0)) - amount, Decimal("0"))
        dist_ledger.last_txn_on = datetime.utcnow()

    ref = f"SETTLE-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    db.session.add(
        AccountEntry(
            org_id=facility_id,
            entry_type="PAYMENT",
            reference=ref,
            party_name=distributor.name,
            debit=Decimal("0"),
            credit=amount,
            note=note or "Consignment settlement payment",
        )
    )
    db.session.add(
        AccountEntry(
            org_id=distributor_id,
            entry_type="RECEIPT",
            reference=ref,
            party_name=facility.name,
            debit=amount,
            credit=Decimal("0"),
            note=note or "Consignment settlement received",
        )
    )

    remaining = amount
    open_rows = (
        ConsignmentSettlement.query.filter_by(
            distributor_id=distributor_id, facility_id=facility_id, status="OPEN"
        )
        .order_by(ConsignmentSettlement.created_at.asc())
        .all()
    )
    for row in open_rows:
        if remaining <= 0:
            break
        row_amt = Decimal(str(row.amount))
        if remaining >= row_amt:
            row.status = "PAID"
            remaining -= row_amt
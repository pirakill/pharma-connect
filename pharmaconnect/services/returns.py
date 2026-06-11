from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .. import db
from ..models import AccountEntry, Bill, BillLine, Organization, PartyLedger, SaleReturn, SaleReturnLine
from .inventory import receive_return
from .settlement import reverse_for_return_line

TWO = Decimal("0.01")


def next_return_number(facility_id: int) -> str:
    count = SaleReturn.query.filter_by(facility_id=facility_id).count()
    return f"SR{facility_id:03d}-{count + 1:06d}"


def create_sale_return(bill: Bill, lines: list[dict], reason: str = "") -> SaleReturn:
    sr = SaleReturn(
        number=next_return_number(bill.facility_id),
        facility_id=bill.facility_id,
        bill_id=bill.id,
        reason=reason,
    )
    db.session.add(sr)
    db.session.flush()

    taxable = cgst = sgst = igst = Decimal("0")
    for row in lines:
        bl = db.session.get(BillLine, row["bill_line_id"])
        if not bl or bl.bill_id != bill.id:
            raise ValueError("Invalid bill line")
        qty = Decimal(str(row["qty"]))
        if qty > Decimal(str(bl.qty)):
            raise ValueError("Return qty exceeds sold qty")
        portion = qty / Decimal(str(bl.qty))
        line_taxable = (Decimal(str(bl.taxable)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_cgst = (Decimal(str(bl.cgst)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_sgst = (Decimal(str(bl.sgst)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_igst = (Decimal(str(bl.igst)) * portion).quantize(TWO, ROUND_HALF_UP)
        line_total = line_taxable + line_cgst + line_sgst + line_igst

        batch = bl.batch
        receive_return(batch, qty, sr.number, reason)
        facility = db.session.get(Organization, bill.facility_id)
        if facility:
            reverse_for_return_line(bl, qty, sr.number, facility)

        db.session.add(
            SaleReturnLine(
                return_id=sr.id,
                bill_line_id=bl.id,
                item_id=bl.item_id,
                batch_id=bl.batch_id,
                qty=qty,
                rate=bl.rate,
                taxable=line_taxable,
                cgst=line_cgst,
                sgst=line_sgst,
                igst=line_igst,
                line_total=line_total,
            )
        )
        taxable += line_taxable
        cgst += line_cgst
        sgst += line_sgst
        igst += line_igst

    sr.taxable = taxable
    sr.cgst = cgst
    sr.sgst = sgst
    sr.igst = igst
    sr.grand_total = taxable + cgst + sgst + igst

    db.session.add(
        AccountEntry(
            org_id=bill.facility_id,
            entry_type="SALE_RETURN",
            reference=sr.number,
            party_name=bill.customer_name,
            debit=Decimal("0"),
            credit=sr.grand_total,
            note=reason,
        )
    )

    if bill.payment_mode == "CREDIT":
        from .credit import reduce_bill_balance
        from ..models import RetailCustomer

        reduce_bill_balance(bill, sr.grand_total)
        if bill.retail_customer_id:
            rc = db.session.get(RetailCustomer, bill.retail_customer_id)
            if rc:
                rc.outstanding = max(Decimal(str(rc.outstanding or 0)) - sr.grand_total, Decimal("0"))
        elif bill.bill_type == "INSTITUTIONAL" and bill.customer_name:
            ledger = PartyLedger.query.filter_by(org_id=bill.facility_id, party_name=bill.customer_name).first()
            if ledger:
                ledger.outstanding = max(Decimal(str(ledger.outstanding or 0)) - sr.grand_total, Decimal("0"))
                from datetime import datetime
                ledger.last_txn_on = datetime.utcnow()

    return sr
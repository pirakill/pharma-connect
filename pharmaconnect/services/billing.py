from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .. import db
from ..models import AccountEntry, Bill, BillLine, Item, Organization, PartyLedger, RetailCustomer
from .credit import assert_party_credit_allowed, assert_retail_credit_allowed, mark_credit_bill
from .customers import earn_loyalty, record_credit_sale, redeem_loyalty
from .gst import line_tax
from .inventory import fefo_batches, issue_stock
from .numbering import next_bill_number
from .promotions import apply_scheme_discount
from .settlement import record_for_bill_line

TWO = Decimal("0.01")


def _allocate_qty(item_id: int, facility_id: int, qty: Decimal) -> list[tuple]:
    batches = fefo_batches(item_id, facility_id, qty)
    allocations: list[tuple] = []
    remaining = qty
    for batch in batches:
        if remaining <= 0:
            break
        take = min(Decimal(str(batch.available_qty)), remaining)
        allocations.append((batch, take))
        remaining -= take
    return allocations


def create_bill(
    facility: Organization,
    bill_type: str,
    lines: list[dict],
    customer_name: str = "Walk-in",
    customer_gstin: str | None = None,
    payment_mode: str = "CASH",
    doctor_name: str | None = None,
    patient_id: int | None = None,
    retail_customer_id: int | None = None,
    discount: Decimal = Decimal("0"),
    order_ref: str | None = None,
    loyalty_redeem: int = 0,
    payment_ref: str | None = None,
) -> Bill:
    if retail_customer_id:
        rc = db.session.get(RetailCustomer, retail_customer_id)
        if rc:
            customer_name = rc.name
            customer_gstin = customer_gstin or rc.gstin
    bill = Bill(
        number=next_bill_number(facility.id),
        facility_id=facility.id,
        bill_type=bill_type,
        customer_name=customer_name,
        customer_gstin=customer_gstin,
        retail_customer_id=retail_customer_id,
        payment_mode=payment_mode,
        doctor_name=doctor_name,
        patient_id=patient_id,
        discount=discount,
        order_ref=order_ref,
        payment_ref=payment_ref,
    )
    db.session.add(bill)
    db.session.flush()

    subtotal = Decimal("0")
    total_taxable = Decimal("0")
    cgst_total = sgst_total = igst_total = Decimal("0")

    for row in lines:
        item = db.session.get(Item, row["item_id"])
        if not item:
            raise ValueError("Item not found")
        qty = Decimal(str(row["qty"]))
        rate = Decimal(str(row.get("rate", item.mrp)))
        scheme_disc = apply_scheme_discount(facility.id, item.id, qty, rate)
        line_discount = Decimal(str(row.get("discount", 0))) + scheme_disc
        gross = (qty * rate).quantize(TWO, ROUND_HALF_UP)
        taxable = (gross - line_discount).quantize(TWO, ROUND_HALF_UP)
        gst_rate = Decimal(str(item.tax_slab.rate if item.tax_slab else 0))
        buyer_state = customer_gstin[:2] if customer_gstin and len(customer_gstin) >= 2 else facility.state_code
        tax_parts = line_tax(taxable, gst_rate, facility.state_code, buyer_state)
        line_total = (taxable + tax_parts["total_tax"]).quantize(TWO, ROUND_HALF_UP)

        allocations = _allocate_qty(item.id, facility.id, qty)
        alloc_qty = qty
        for batch, take in allocations:
            if take <= 0:
                continue
            portion = (take / qty) if qty else Decimal("1")
            portion_taxable = (taxable * portion).quantize(TWO, ROUND_HALF_UP)
            portion_tax = line_tax(portion_taxable, gst_rate, facility.state_code, buyer_state)
            bill_line = BillLine(
                bill_id=bill.id,
                item_id=item.id,
                batch_id=batch.id,
                qty=take,
                rate=rate,
                discount=(line_discount * portion).quantize(TWO, ROUND_HALF_UP),
                taxable=portion_taxable,
                cgst=portion_tax["cgst"],
                sgst=portion_tax["sgst"],
                igst=portion_tax["igst"],
                line_total=(portion_taxable + portion_tax["total_tax"]).quantize(TWO, ROUND_HALF_UP),
            )
            db.session.add(bill_line)
            db.session.flush()
            issue_stock(batch, take, bill.number)
            record_for_bill_line(bill, bill_line, batch, facility)
            alloc_qty -= take

        subtotal += gross
        total_taxable += taxable
        cgst_total += tax_parts["cgst"]
        sgst_total += tax_parts["sgst"]
        igst_total += tax_parts["igst"]

    loyalty_discount = Decimal("0")
    if retail_customer_id and loyalty_redeem:
        rc = db.session.get(RetailCustomer, retail_customer_id)
        if rc:
            loyalty_discount = redeem_loyalty(rc, loyalty_redeem)

    bill_discount = Decimal(str(discount or 0)) + loyalty_discount
    bill.subtotal = subtotal
    bill.discount = bill_discount
    bill.taxable = max(total_taxable - bill_discount, Decimal("0"))
    bill.cgst = cgst_total
    bill.sgst = sgst_total
    bill.igst = igst_total
    raw_total = bill.taxable + bill.cgst + bill.sgst + bill.igst
    bill.grand_total = raw_total.quantize(TWO, ROUND_HALF_UP)
    bill.round_off = (bill.grand_total - raw_total).quantize(TWO, ROUND_HALF_UP)

    db.session.add(
        AccountEntry(
            org_id=facility.id,
            entry_type="SALE",
            reference=bill.number,
            party_name=customer_name,
            debit=bill.grand_total,
            credit=Decimal("0"),
            note=f"{bill_type} bill",
        )
    )

    if payment_mode == "CREDIT" and retail_customer_id:
        rc = db.session.get(RetailCustomer, retail_customer_id)
        if rc:
            assert_retail_credit_allowed(rc, bill.grand_total)
            record_credit_sale(rc, bill.grand_total)
            mark_credit_bill(bill, int(rc.credit_days or 30))
    elif payment_mode == "CREDIT" and bill_type == "INSTITUTIONAL":
        ledger = PartyLedger.query.filter_by(org_id=facility.id, party_name=customer_name).first()
        if not ledger:
            ledger = PartyLedger(org_id=facility.id, party_name=customer_name, party_gstin=customer_gstin)
            db.session.add(ledger)
            db.session.flush()
        assert_party_credit_allowed(ledger, bill.grand_total)
        ledger.outstanding = Decimal(str(ledger.outstanding or 0)) + bill.grand_total
        from datetime import datetime
        ledger.last_txn_on = datetime.utcnow()
        mark_credit_bill(bill, int(ledger.credit_days or 30))

    if retail_customer_id:
        rc = db.session.get(RetailCustomer, retail_customer_id)
        if rc:
            earn_loyalty(rc, bill.grand_total)

    return bill
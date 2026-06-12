from __future__ import annotations

from datetime import datetime

from sqlalchemy import func

from .. import db
from ..models import Bill, BillLine, ConsignmentBatch, Item, Organization, PurchaseReturn, SaleReturn, SaleReturnLine, AccountEntry
from .inventory import customer_facilities


def gstr1_summary(org_id: int, year: int, month: int) -> dict:
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    bills = (
        Bill.query.filter(Bill.facility_id == org_id, Bill.billed_on >= start, Bill.billed_on < end)
        .order_by(Bill.billed_on)
        .all()
    )
    credit_returns = (
        SaleReturn.query.filter(
            SaleReturn.facility_id == org_id,
            SaleReturn.returned_on >= start,
            SaleReturn.returned_on < end,
        )
        .order_by(SaleReturn.returned_on)
        .all()
    )
    b2c = [b for b in bills if not b.customer_gstin]
    b2b = [b for b in bills if b.customer_gstin]

    def _sum(rows, field):
        return float(sum(getattr(r, field) or 0 for r in rows))

    inv_taxable = _sum(bills, "taxable")
    inv_cgst = _sum(bills, "cgst")
    inv_sgst = _sum(bills, "sgst")
    inv_igst = _sum(bills, "igst")
    cn_taxable = _sum(credit_returns, "taxable")
    cn_cgst = _sum(credit_returns, "cgst")
    cn_sgst = _sum(credit_returns, "sgst")
    cn_igst = _sum(credit_returns, "igst")

    return {
        "period": f"{year}-{month:02d}",
        "b2c_count": len(b2c),
        "b2b_count": len(b2b),
        "credit_note_count": len(credit_returns),
        "taxable": inv_taxable,
        "cgst": inv_cgst,
        "sgst": inv_sgst,
        "igst": inv_igst,
        "total": _sum(bills, "grand_total"),
        "credit_taxable": cn_taxable,
        "credit_cgst": cn_cgst,
        "credit_sgst": cn_sgst,
        "credit_igst": cn_igst,
        "credit_total": _sum(credit_returns, "grand_total"),
        "net_taxable": inv_taxable - cn_taxable,
        "net_cgst": inv_cgst - cn_cgst,
        "net_sgst": inv_sgst - cn_sgst,
        "net_igst": inv_igst - cn_igst,
        "net_total": _sum(bills, "grand_total") - _sum(credit_returns, "grand_total"),
        "invoices": [
            {
                "doc_type": "INV",
                "number": b.number,
                "date": b.billed_on.date().isoformat(),
                "customer": b.customer_name,
                "gstin": b.customer_gstin,
                "taxable": float(b.taxable or 0),
                "cgst": float(b.cgst or 0),
                "sgst": float(b.sgst or 0),
                "igst": float(b.igst or 0),
                "total": float(b.grand_total or 0),
            }
            for b in bills
        ],
        "credit_notes": [
            {
                "doc_type": "CRN",
                "number": cr.number,
                "date": cr.returned_on.date().isoformat(),
                "customer": cr.bill.customer_name if cr.bill else "—",
                "gstin": cr.bill.customer_gstin if cr.bill else None,
                "original_invoice": cr.bill.number if cr.bill else "—",
                "taxable": float(cr.taxable or 0),
                "cgst": float(cr.cgst or 0),
                "sgst": float(cr.sgst or 0),
                "igst": float(cr.igst or 0),
                "total": float(cr.grand_total or 0),
            }
            for cr in credit_returns
        ],
    }


def distributor_kpis(distributor_id: int) -> dict:
    facilities = Organization.query.filter_by(parent_id=distributor_id).count()
    stock_value = (
        db.session.query(func.coalesce(func.sum(ConsignmentBatch.qty_on_hand * ConsignmentBatch.cost_rate), 0))
        .filter_by(distributor_id=distributor_id)
        .scalar()
    )
    facility_ids = [f.id for f in Organization.query.filter_by(parent_id=distributor_id).all()]
    sales_30d = 0.0
    if facility_ids:
        from datetime import timedelta

        since = datetime.utcnow() - timedelta(days=30)
        sales_30d = float(
            db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
            .filter(Bill.facility_id.in_(facility_ids), Bill.billed_on >= since)
            .scalar()
            or 0
        )
    return {
        "facility_count": facilities,
        "consignment_stock_value": float(stock_value or 0),
        "sales_30d": sales_30d,
    }


def network_summary(distributor_id: int, days: int = 30) -> dict:
    """Multi-branch consolidated view for distributor."""
    from datetime import timedelta

    from ..models import RetailCustomer
    from .accounting import distributor_receivables

    since = datetime.utcnow() - timedelta(days=days)
    facilities = (
        Organization.query.filter_by(parent_id=distributor_id)
        .filter(Organization.kind.notin_(["WAREHOUSE"]))
        .order_by(Organization.name)
        .all()
    )
    settlement_map = {r["facility_id"]: r for r in distributor_receivables(distributor_id)}
    branches = []
    totals = {"sales": 0.0, "stock_value": 0.0, "receivable": 0.0, "sku_count": 0}

    for fac in facilities:
        sales = float(
            db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
            .filter(Bill.facility_id == fac.id, Bill.billed_on >= since)
            .scalar()
            or 0
        )
        stock_row = (
            db.session.query(
                func.coalesce(func.sum(ConsignmentBatch.qty_on_hand * ConsignmentBatch.cost_rate), 0),
                func.count(func.distinct(ConsignmentBatch.item_id)),
            )
            .filter_by(distributor_id=distributor_id, facility_id=fac.id)
            .filter(ConsignmentBatch.qty_on_hand > 0)
            .first()
        )
        stock_value = float(stock_row[0] or 0)
        sku_count = int(stock_row[1] or 0)
        revenue, cogs = _margin_totals(fac.id, since)
        cust_due = float(
            db.session.query(func.coalesce(func.sum(RetailCustomer.outstanding), 0))
            .filter_by(facility_id=fac.id)
            .scalar()
            or 0
        )
        settle = settlement_map.get(fac.id, {})
        settlement_due = float(settle.get("outstanding", 0) or 0)
        branches.append({
            "facility_id": fac.id,
            "code": fac.code,
            "name": fac.name,
            "kind": fac.kind,
            "sales": sales,
            "stock_value": stock_value,
            "sku_count": sku_count,
            "gross_profit": revenue - cogs,
            "margin_pct": ((revenue - cogs) / revenue * 100) if revenue else 0.0,
            "customer_due": cust_due,
            "settlement_due": settlement_due,
        })
        totals["sales"] += sales
        totals["stock_value"] += stock_value
        totals["receivable"] += settlement_due
        totals["sku_count"] += sku_count

    return {"branches": branches, "totals": totals, "period_days": days}


def payment_register(org_id: int, days: int = 30) -> list[dict]:
    """Digital payment reconciliation — UPI/Card bills with references."""
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    bills = (
        Bill.query.filter(
            Bill.facility_id == org_id,
            Bill.billed_on >= since,
            Bill.payment_mode.in_(["UPI", "CARD"]),
        )
        .order_by(Bill.billed_on.desc())
        .all()
    )
    return [
        {
            "number": b.number,
            "date": b.billed_on.strftime("%d-%b-%Y %H:%M"),
            "customer": b.customer_name,
            "mode": b.payment_mode,
            "ref": b.payment_ref or "—",
            "amount": float(b.grand_total or 0),
        }
        for b in bills
    ]


def gstr3b_summary(org_id: int, year: int, month: int) -> dict:
    g1 = gstr1_summary(org_id, year, month)
    return {
        "period": g1["period"],
        "outward_taxable": g1["taxable"],
        "outward_cgst": g1["cgst"],
        "outward_sgst": g1["sgst"],
        "outward_igst": g1["igst"],
        "credit_note_count": g1["credit_note_count"],
        "credit_taxable": g1["credit_taxable"],
        "credit_cgst": g1["credit_cgst"],
        "credit_sgst": g1["credit_sgst"],
        "credit_igst": g1["credit_igst"],
        "net_outward_taxable": g1["net_taxable"],
        "net_outward_cgst": g1["net_cgst"],
        "net_outward_sgst": g1["net_sgst"],
        "net_outward_igst": g1["net_igst"],
        "total_tax": g1["cgst"] + g1["sgst"] + g1["igst"],
        "net_total_tax": g1["net_cgst"] + g1["net_sgst"] + g1["net_igst"],
    }


def cashier_summary(org_id: int) -> dict:
    """Today's sales KPIs and recent bills for cashier POS dashboard."""
    from datetime import date, timedelta

    today = date.today()
    day_start = datetime.combine(today, datetime.min.time())
    day_end = day_start + timedelta(days=1)

    sales_today = float(
        db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
        .filter(Bill.facility_id == org_id, Bill.billed_on >= day_start, Bill.billed_on < day_end)
        .scalar() or 0
    )
    bill_count = (
        Bill.query.filter(Bill.facility_id == org_id, Bill.billed_on >= day_start, Bill.billed_on < day_end)
        .count()
    )
    returns_today = float(
        db.session.query(func.coalesce(func.sum(SaleReturn.grand_total), 0))
        .filter(SaleReturn.facility_id == org_id, SaleReturn.returned_on >= day_start, SaleReturn.returned_on < day_end)
        .scalar() or 0
    )
    recent_bills = (
        Bill.query.filter(Bill.facility_id == org_id, Bill.billed_on >= day_start, Bill.billed_on < day_end)
        .order_by(Bill.billed_on.desc())
        .limit(8)
        .all()
    )
    return {
        "date": today,
        "sales_today": sales_today,
        "returns_today": returns_today,
        "net_today": sales_today - returns_today,
        "bill_count": bill_count,
        "recent_bills": recent_bills,
    }


def daily_sales(org_id: int, days: int = 7) -> list[dict]:
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        db.session.query(func.date(Bill.billed_on).label("d"), func.sum(Bill.grand_total).label("total"))
        .filter(Bill.facility_id == org_id, Bill.billed_on >= since)
        .group_by(func.date(Bill.billed_on))
        .order_by(func.date(Bill.billed_on))
        .all()
    )
    return [{"date": str(r.d), "sales": float(r.total or 0)} for r in rows]


def _margin_totals(org_id: int, since) -> tuple[float, float]:
    """Return (revenue_taxable, cogs) for sales minus returns since date."""
    sale_lines = (
        BillLine.query.join(Bill).join(ConsignmentBatch, BillLine.batch_id == ConsignmentBatch.id)
        .filter(Bill.facility_id == org_id, Bill.billed_on >= since)
        .all()
    )
    revenue = sum(float(ln.taxable or 0) for ln in sale_lines)
    cogs = sum(float(ln.qty or 0) * float(ln.batch.cost_rate or 0) for ln in sale_lines)

    return_lines = (
        SaleReturnLine.query.join(SaleReturn).join(ConsignmentBatch, SaleReturnLine.batch_id == ConsignmentBatch.id)
        .filter(SaleReturn.facility_id == org_id, SaleReturn.returned_on >= since)
        .all()
    )
    revenue -= sum(float(ln.taxable or 0) for ln in return_lines)
    cogs -= sum(float(ln.qty or 0) * float(ln.batch.cost_rate or 0) for ln in return_lines)
    return revenue, cogs


def pnl_report(org_id: int, days: int = 30) -> dict:
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    sales = float(
        db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
        .filter(Bill.facility_id == org_id, Bill.billed_on >= since).scalar() or 0
    )
    returns = float(
        db.session.query(func.coalesce(func.sum(SaleReturn.grand_total), 0))
        .filter(SaleReturn.facility_id == org_id, SaleReturn.returned_on >= since).scalar() or 0
    )
    purchases = float(
        db.session.query(func.coalesce(func.sum(AccountEntry.debit), 0))
        .filter(AccountEntry.org_id == org_id, AccountEntry.entry_type == "PURCHASE", AccountEntry.ts >= since).scalar() or 0
    )
    net_sales = sales - returns
    revenue, cogs = _margin_totals(org_id, since)
    gross_profit = revenue - cogs
    margin_pct = (gross_profit / revenue * 100) if revenue else 0.0
    return {
        "sales": sales,
        "returns": returns,
        "net_sales": net_sales,
        "purchases": purchases,
        "revenue_taxable": revenue,
        "cogs": cogs,
        "gross_profit": gross_profit,
        "gross_profit_est": gross_profit,
        "margin_pct": margin_pct,
        "period_days": days,
    }


def margin_report(org_id: int, days: int = 30) -> dict:
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    revenue, cogs = _margin_totals(org_id, since)
    gross = revenue - cogs
    margin_pct = (gross / revenue * 100) if revenue else 0.0

    rows = (
        db.session.query(
            Item.code,
            Item.name,
            func.coalesce(func.sum(BillLine.taxable), 0).label("revenue"),
            func.coalesce(func.sum(BillLine.qty * ConsignmentBatch.cost_rate), 0).label("cogs"),
        )
        .join(Bill, BillLine.bill_id == Bill.id)
        .join(Item, BillLine.item_id == Item.id)
        .join(ConsignmentBatch, BillLine.batch_id == ConsignmentBatch.id)
        .filter(Bill.facility_id == org_id, Bill.billed_on >= since)
        .group_by(Item.id, Item.code, Item.name)
        .order_by(func.sum(BillLine.taxable).desc())
        .all()
    )
    breakdown = []
    for r in rows:
        rev = float(r.revenue or 0)
        cost = float(r.cogs or 0)
        profit = rev - cost
        breakdown.append({
            "code": r.code,
            "name": r.name,
            "revenue": rev,
            "cogs": cost,
            "profit": profit,
            "margin_pct": (profit / rev * 100) if rev else 0.0,
        })

    return {
        "revenue": revenue,
        "cogs": cogs,
        "gross_profit": gross,
        "margin_pct": margin_pct,
        "breakdown": breakdown,
        "period_days": days,
    }


def expiry_report(distributor_id: int, within_days: int = 90) -> list[dict]:
    from datetime import date, timedelta
    cutoff = date.today() + timedelta(days=within_days)
    batches = (
        ConsignmentBatch.query.filter_by(distributor_id=distributor_id)
        .filter(ConsignmentBatch.expiry <= cutoff, ConsignmentBatch.qty_on_hand > 0)
        .order_by(ConsignmentBatch.expiry)
        .all()
    )
    return [
        {"facility": b.facility.name, "item": b.item.name, "batch": b.batch_no,
         "expiry": b.expiry.isoformat(), "qty": float(b.qty_on_hand),
         "value": float(b.qty_on_hand * b.cost_rate)}
        for b in batches
    ]


def slow_moving(distributor_id: int, days: int = 60) -> list[dict]:
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(days=days)
    facility_ids = [f.id for f in customer_facilities(distributor_id)]
    sold_ids = set()
    if facility_ids:
        sold_ids = set(
            r[0]
            for r in db.session.query(BillLine.item_id)
            .join(Bill)
            .filter(Bill.facility_id.in_(facility_ids), Bill.billed_on >= since)
            .distinct()
            .all()
        )
    batches = ConsignmentBatch.query.filter_by(distributor_id=distributor_id).filter(ConsignmentBatch.qty_on_hand > 0).all()
    dead: dict[tuple, dict] = {}
    for b in batches:
        if b.item_id in sold_ids:
            continue
        key = (b.facility_id, b.item_id)
        if key not in dead:
            dead[key] = {"facility": b.facility.name, "item": b.item.name, "qty": 0.0, "value": 0.0}
        dead[key]["qty"] += float(b.qty_on_hand)
        dead[key]["value"] += float(b.qty_on_hand * b.cost_rate)
    return sorted(dead.values(), key=lambda x: -x["value"])


def gstr2_summary(org_id: int, year: int, month: int) -> dict:
    """Inward supplies (purchases) and debit notes (purchase returns) for GSTR-2 style reporting."""
    from ..models import PurchaseBill

    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)

    purchases = (
        PurchaseBill.query.filter(
            PurchaseBill.org_id == org_id,
            PurchaseBill.purchased_on >= start,
            PurchaseBill.purchased_on < end,
        )
        .order_by(PurchaseBill.purchased_on)
        .all()
    )
    debit_notes = (
        PurchaseReturn.query.filter(
            PurchaseReturn.org_id == org_id,
            PurchaseReturn.returned_on >= start,
            PurchaseReturn.returned_on < end,
        )
        .order_by(PurchaseReturn.returned_on)
        .all()
    )

    def _sum(rows, field):
        return float(sum(getattr(r, field) or 0 for r in rows))

    pur_taxable = _sum(purchases, "taxable")
    pur_cgst = _sum(purchases, "cgst")
    pur_sgst = _sum(purchases, "sgst")
    pur_igst = _sum(purchases, "igst")
    dn_taxable = _sum(debit_notes, "taxable")
    dn_cgst = _sum(debit_notes, "cgst")
    dn_sgst = _sum(debit_notes, "sgst")
    dn_igst = _sum(debit_notes, "igst")

    return {
        "period": f"{year}-{month:02d}",
        "purchase_count": len(purchases),
        "debit_note_count": len(debit_notes),
        "taxable": pur_taxable,
        "cgst": pur_cgst,
        "sgst": pur_sgst,
        "igst": pur_igst,
        "total": _sum(purchases, "grand_total"),
        "debit_taxable": dn_taxable,
        "debit_cgst": dn_cgst,
        "debit_sgst": dn_sgst,
        "debit_igst": dn_igst,
        "debit_total": _sum(debit_notes, "grand_total"),
        "net_taxable": pur_taxable - dn_taxable,
        "net_cgst": pur_cgst - dn_cgst,
        "net_sgst": pur_sgst - dn_sgst,
        "net_igst": pur_igst - dn_igst,
        "net_total": _sum(purchases, "grand_total") - _sum(debit_notes, "grand_total"),
        "purchases": [
            {
                "number": p.number,
                "date": p.purchased_on.date().isoformat(),
                "supplier": p.supplier.name,
                "gstin": p.supplier.gstin,
                "warehouse": p.warehouse.code if p.warehouse else "—",
                "taxable": float(p.taxable or 0),
                "cgst": float(p.cgst or 0),
                "sgst": float(p.sgst or 0),
                "igst": float(p.igst or 0),
                "total": float(p.grand_total or 0),
            }
            for p in purchases
        ],
        "debit_notes": [
            {
                "number": dn.number,
                "date": dn.returned_on.date().isoformat(),
                "supplier": dn.supplier.name,
                "original_purchase": dn.purchase.number,
                "taxable": float(dn.taxable or 0),
                "cgst": float(dn.cgst or 0),
                "sgst": float(dn.sgst or 0),
                "igst": float(dn.igst or 0),
                "total": float(dn.grand_total or 0),
            }
            for dn in debit_notes
        ],
    }


def distributor_gstr1_summary(distributor_id: int, year: int, month: int) -> dict:
    """Aggregate outward supplies across all customer facilities."""
    facilities = customer_facilities(distributor_id)
    invoices: list[dict] = []
    credit_notes: list[dict] = []
    totals = {k: 0.0 for k in ("taxable", "cgst", "sgst", "igst", "total", "credit_taxable", "credit_cgst",
                               "credit_sgst", "credit_igst", "credit_total", "b2c_count", "b2b_count", "credit_note_count")}

    for fac in facilities:
        s = gstr1_summary(fac.id, year, month)
        totals["b2c_count"] += s["b2c_count"]
        totals["b2b_count"] += s["b2b_count"]
        totals["credit_note_count"] += s["credit_note_count"]
        totals["taxable"] += s["taxable"]
        totals["cgst"] += s["cgst"]
        totals["sgst"] += s["sgst"]
        totals["igst"] += s["igst"]
        totals["total"] += s["total"]
        totals["credit_taxable"] += s["credit_taxable"]
        totals["credit_cgst"] += s["credit_cgst"]
        totals["credit_sgst"] += s["credit_sgst"]
        totals["credit_igst"] += s["credit_igst"]
        totals["credit_total"] += s["credit_total"]
        for inv in s["invoices"]:
            invoices.append({**inv, "facility": fac.name})
        for cn in s["credit_notes"]:
            credit_notes.append({**cn, "facility": fac.name})

    return {
        "period": f"{year}-{month:02d}",
        "facility_count": len(facilities),
        "b2c_count": int(totals["b2c_count"]),
        "b2b_count": int(totals["b2b_count"]),
        "credit_note_count": int(totals["credit_note_count"]),
        "taxable": totals["taxable"],
        "cgst": totals["cgst"],
        "sgst": totals["sgst"],
        "igst": totals["igst"],
        "total": totals["total"],
        "credit_taxable": totals["credit_taxable"],
        "credit_cgst": totals["credit_cgst"],
        "credit_sgst": totals["credit_sgst"],
        "credit_igst": totals["credit_igst"],
        "credit_total": totals["credit_total"],
        "net_taxable": totals["taxable"] - totals["credit_taxable"],
        "net_cgst": totals["cgst"] - totals["credit_cgst"],
        "net_sgst": totals["sgst"] - totals["credit_sgst"],
        "net_igst": totals["igst"] - totals["credit_igst"],
        "net_total": totals["total"] - totals["credit_total"],
        "invoices": invoices,
        "credit_notes": credit_notes,
    }


def sale_register(org_id: int, days: int = 30) -> list[dict]:
    from datetime import timedelta

    since = datetime.utcnow() - timedelta(days=days)
    bills = (
        Bill.query.filter(Bill.facility_id == org_id, Bill.billed_on >= since)
        .order_by(Bill.billed_on.desc())
        .all()
    )
    rows = []
    for b in bills:
        rows.append({
            "number": b.number,
            "date": b.billed_on.strftime("%d-%b-%Y"),
            "type": b.bill_type,
            "customer": b.customer_name,
            "payment": b.payment_mode,
            "taxable": float(b.taxable or 0),
            "cgst": float(b.cgst or 0),
            "sgst": float(b.sgst or 0),
            "igst": float(b.igst or 0),
            "total": float(b.grand_total or 0),
        })
    returns = (
        SaleReturn.query.filter(SaleReturn.facility_id == org_id, SaleReturn.returned_on >= since)
        .order_by(SaleReturn.returned_on.desc())
        .all()
    )
    for r in returns:
        rows.append({
            "number": r.number,
            "date": r.returned_on.strftime("%d-%b-%Y"),
            "type": "RETURN",
            "customer": r.bill.customer_name if r.bill else "—",
            "payment": "—",
            "taxable": -float(r.taxable or 0),
            "cgst": -float(r.cgst or 0),
            "sgst": -float(r.sgst or 0),
            "igst": -float(r.igst or 0),
            "total": -float(r.grand_total or 0),
        })
    rows.sort(key=lambda x: x["date"], reverse=True)
    return rows


def purchase_register(org_id: int, days: int = 30) -> list[dict]:
    from datetime import timedelta
    from ..models import PurchaseBill, PurchaseReturn

    since = datetime.utcnow() - timedelta(days=days)
    purchases = (
        PurchaseBill.query.filter(PurchaseBill.org_id == org_id, PurchaseBill.purchased_on >= since)
        .order_by(PurchaseBill.purchased_on.desc())
        .all()
    )
    rows = []
    for p in purchases:
        rows.append({
            "number": p.number,
            "date": p.purchased_on.strftime("%d-%b-%Y"),
            "type": "PURCHASE",
            "party": p.supplier.name,
            "invoice": p.invoice_no or "—",
            "taxable": float(p.taxable or 0),
            "total": float(p.grand_total or 0),
        })
    prs = (
        PurchaseReturn.query.filter(PurchaseReturn.org_id == org_id, PurchaseReturn.returned_on >= since)
        .order_by(PurchaseReturn.returned_on.desc())
        .all()
    )
    for pr in prs:
        rows.append({
            "number": pr.number,
            "date": pr.returned_on.strftime("%d-%b-%Y"),
            "type": "DEBIT NOTE",
            "party": pr.supplier.name,
            "invoice": pr.purchase.number,
            "taxable": -float(pr.taxable or 0),
            "total": -float(pr.grand_total or 0),
        })
    rows.sort(key=lambda x: x["date"], reverse=True)
    return rows


def outstanding_report(org_id: int) -> dict:
    from ..models import Organization, PartyLedger, Supplier
    from ..models.customer import RetailCustomer

    org = db.session.get(Organization, org_id)
    if org and org.kind == "DISTRIBUTOR":
        return network_outstanding_report(org_id)

    customers = (
        RetailCustomer.query.filter_by(facility_id=org_id)
        .filter(RetailCustomer.outstanding > 0)
        .order_by(RetailCustomer.outstanding.desc())
        .all()
    )
    parties = (
        PartyLedger.query.filter_by(org_id=org_id)
        .filter(PartyLedger.outstanding > 0)
        .order_by(PartyLedger.outstanding.desc())
        .all()
    )
    suppliers = (
        Supplier.query.filter_by(org_id=org_id)
        .filter(Supplier.outstanding > 0)
        .order_by(Supplier.outstanding.desc())
        .all()
    )
    return _outstanding_payload(customers, parties, suppliers)


def network_outstanding_report(distributor_id: int) -> dict:
    from ..models import Organization, PartyLedger, Supplier
    from ..models.customer import RetailCustomer

    facilities = Organization.query.filter_by(parent_id=distributor_id, is_active=True).all()
    fac_ids = [f.id for f in facilities]
    customers = (
        RetailCustomer.query.filter(RetailCustomer.facility_id.in_(fac_ids))
        .filter(RetailCustomer.outstanding > 0)
        .order_by(RetailCustomer.outstanding.desc())
        .all()
        if fac_ids else []
    )
    parties = (
        PartyLedger.query.filter(PartyLedger.org_id.in_(fac_ids))
        .filter(PartyLedger.outstanding > 0)
        .order_by(PartyLedger.outstanding.desc())
        .all()
        if fac_ids else []
    )
    suppliers = (
        Supplier.query.filter_by(org_id=distributor_id)
        .filter(Supplier.outstanding > 0)
        .order_by(Supplier.outstanding.desc())
        .all()
    )
    return _outstanding_payload(customers, parties, suppliers, facilities=facilities)


def _outstanding_payload(customers, parties, suppliers, *, facilities=None) -> dict:
    fac_map = {f.id: f.name for f in (facilities or [])}
    return {
        "customers": [{
            "name": c.name,
            "phone": c.phone,
            "facility": fac_map.get(c.facility_id, ""),
            "outstanding": float(c.outstanding or 0),
            "limit": float(c.credit_limit or 0),
            "credit_days": int(c.credit_days or 0),
        } for c in customers],
        "parties": [{
            "name": p.party_name,
            "gstin": p.party_gstin,
            "facility": fac_map.get(p.org_id, ""),
            "outstanding": float(p.outstanding or 0),
            "limit": float(p.credit_limit or 0),
            "credit_days": int(p.credit_days or 0),
        } for p in parties],
        "suppliers": [{"name": s.name, "gstin": s.gstin,
                       "outstanding": float(s.outstanding or 0)} for s in suppliers],
        "total_receivable": sum(float(c.outstanding or 0) for c in customers)
        + sum(float(p.outstanding or 0) for p in parties),
        "total_payable": sum(float(s.outstanding or 0) for s in suppliers),
        "is_network": bool(facilities),
    }


def item_ledger(org_id: int, item_id: int, days: int = 90) -> list[dict]:
    from datetime import timedelta
    from ..models import StockLedger

    since = datetime.utcnow() - timedelta(days=days)
    rows = (
        StockLedger.query.join(ConsignmentBatch)
        .filter(ConsignmentBatch.facility_id == org_id, ConsignmentBatch.item_id == item_id)
        .filter(StockLedger.ts >= since)
        .order_by(StockLedger.ts.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "date": r.ts.strftime("%d-%b-%Y %H:%M"),
            "movement": r.movement,
            "batch": r.batch.batch_no if r.batch else "—",
            "qty": float(r.qty_delta),
            "reference": r.reference,
            "note": r.note or "",
        }
        for r in rows
    ]
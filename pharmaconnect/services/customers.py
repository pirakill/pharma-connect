from __future__ import annotations

from decimal import Decimal

from sqlalchemy import desc, func

from .. import db
from ..models import Bill, BillLine, CustomerFavourite, CustomerRegularMed, RetailCustomer


def customer_history(customer_id: int, limit: int = 20) -> list[dict]:
    c = db.session.get(RetailCustomer, customer_id)
    if not c:
        return []
    bills = (
        Bill.query.filter_by(facility_id=c.facility_id, retail_customer_id=customer_id)
        .order_by(Bill.billed_on.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "number": b.number,
            "date": b.billed_on.strftime("%d-%b-%Y"),
            "total": float(b.grand_total or 0),
            "items": [ln.item.name for ln in b.lines],
        }
        for b in bills
    ]


def frequent_items(customer_id: int, limit: int = 8) -> list[dict]:
    c = db.session.get(RetailCustomer, customer_id)
    if not c:
        return []
    rows = (
        db.session.query(BillLine.item_id, BillLine.item, func.sum(BillLine.qty).label("qty"))
        .join(Bill)
        .filter(Bill.retail_customer_id == customer_id)
        .group_by(BillLine.item_id)
        .order_by(desc("qty"))
        .limit(limit)
        .all()
    )
    return [{"item_id": r.item_id, "name": r.item.name, "mrp": float(r.item.mrp or 0), "qty": float(r.qty)} for r in rows]


def regular_meds_list(customer_id: int) -> list[CustomerRegularMed]:
    return CustomerRegularMed.query.filter_by(customer_id=customer_id).all()


def facility_favourites(facility_id: int) -> list[CustomerFavourite]:
    return (
        CustomerFavourite.query.filter_by(facility_id=facility_id)
        .order_by(CustomerFavourite.sort_order)
        .all()
    )


def record_credit_sale(customer: RetailCustomer, amount: Decimal) -> None:
    customer.outstanding = Decimal(str(customer.outstanding or 0)) + amount


def points_for_amount(amount: Decimal) -> int:
    """Earn 1 loyalty point per ₹100 spent (rounded down)."""
    return int(amount // Decimal("100"))


def earn_loyalty(customer: RetailCustomer, amount: Decimal) -> int:
    earned = points_for_amount(amount)
    if earned > 0:
        customer.loyalty_points = int(customer.loyalty_points or 0) + earned
    return earned


def redeem_loyalty(customer: RetailCustomer, points: int) -> Decimal:
    """Redeem loyalty points as bill discount (1 point = ₹1)."""
    if points <= 0:
        return Decimal("0")
    available = int(customer.loyalty_points or 0)
    if points > available:
        raise ValueError(f"Only {available} loyalty points available")
    customer.loyalty_points = available - points
    return Decimal(str(points))
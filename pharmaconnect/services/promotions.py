from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from ..models import Scheme

TWO = Decimal("0.01")


def active_schemes(org_id: int, item_id: int | None = None) -> list[Scheme]:
    today = date.today()
    q = Scheme.query.filter_by(org_id=org_id, is_active=True)
    if item_id:
        q = q.filter((Scheme.item_id == item_id) | (Scheme.item_id.is_(None)))
    rows = q.all()
    return [s for s in rows if (not s.valid_from or s.valid_from <= today) and (not s.valid_to or s.valid_to >= today)]


def apply_scheme_discount(org_id: int, item_id: int, qty: Decimal, rate: Decimal) -> Decimal:
    gross = (qty * rate).quantize(TWO, ROUND_HALF_UP)
    discount = Decimal("0")
    for scheme in active_schemes(org_id, item_id):
        if scheme.item_id and scheme.item_id != item_id:
            continue
        if scheme.kind == "PERCENT":
            discount += (gross * Decimal(str(scheme.value)) / Decimal("100")).quantize(TWO, ROUND_HALF_UP)
        elif scheme.kind == "FLAT":
            discount += Decimal(str(scheme.value))
        elif scheme.kind == "BOGO" and qty >= scheme.min_qty:
            free = int(qty) // scheme.min_qty * scheme.free_qty
            discount += (Decimal(free) * rate).quantize(TWO, ROUND_HALF_UP)
    return min(discount, gross)
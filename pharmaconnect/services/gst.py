from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

TWO = Decimal("0.01")


def split_gst(taxable: Decimal, gst_rate: Decimal, seller_state: str, buyer_state: str) -> dict:
    tax = (taxable * gst_rate / Decimal("100")).quantize(TWO, ROUND_HALF_UP)
    if seller_state == buyer_state:
        half = (tax / 2).quantize(TWO, ROUND_HALF_UP)
        return {"cgst": half, "sgst": half, "igst": Decimal("0")}
    return {"cgst": Decimal("0"), "sgst": Decimal("0"), "igst": tax}


def line_tax(line_taxable: Decimal, gst_rate: Decimal, seller_state: str, buyer_state: str | None) -> dict:
    buyer = buyer_state or seller_state
    parts = split_gst(line_taxable, gst_rate, seller_state, buyer)
    total_tax = parts["cgst"] + parts["sgst"] + parts["igst"]
    return {**parts, "total_tax": total_tax}
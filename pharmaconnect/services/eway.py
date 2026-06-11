from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal

from ..models import Bill

EWAY_THRESHOLD = Decimal("50000")


def eway_required(bill: Bill) -> bool:
    return Decimal(str(bill.grand_total or 0)) >= EWAY_THRESHOLD


def eway_payload(bill: Bill) -> dict:
    """GST e-way bill JSON stub for portal integration."""
    lines = []
    for ln in bill.lines:
        lines.append({
            "hsn": ln.item.hsn or "",
            "name": ln.item.name,
            "qty": float(ln.qty),
            "taxable": float(ln.taxable or 0),
            "cgst": float(ln.cgst or 0),
            "sgst": float(ln.sgst or 0),
            "igst": float(ln.igst or 0),
        })
    return {
        "version": "EWB1.0",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "doc_type": "INV",
        "doc_no": bill.number,
        "doc_date": bill.billed_on.strftime("%d/%m/%Y"),
        "eway_no": bill.eway_no or "",
        "from_gstin": bill.facility.gstin or "",
        "from_name": bill.facility.name,
        "to_name": bill.customer_name,
        "to_gstin": bill.customer_gstin or "",
        "taxable_value": float(bill.taxable or 0),
        "cgst": float(bill.cgst or 0),
        "sgst": float(bill.sgst or 0),
        "igst": float(bill.igst or 0),
        "total_value": float(bill.grand_total or 0),
        "trans_mode": "1",
        "distance_km": 0,
        "items": lines,
        "note": "PharmaConnect e-way stub — integrate with NIC portal for live generation",
    }


def eway_json(bill: Bill) -> str:
    return json.dumps(eway_payload(bill), indent=2, ensure_ascii=False)
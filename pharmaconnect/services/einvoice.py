from __future__ import annotations

import json
from datetime import datetime

from ..models import Bill


def einvoice_payload(bill: Bill) -> dict:
    """NIC e-invoice portal JSON stub (IRN generation requires live API credentials)."""
    fac = bill.facility
    item_list = []
    for ln in bill.lines:
        gst_rate = float(ln.item.tax_slab.rate) if ln.item.tax_slab else 0.0
        item_list.append({
            "SlNo": len(item_list) + 1,
            "PrdDesc": ln.item.name,
            "HsnCd": ln.item.hsn or "",
            "Qty": float(ln.qty),
            "Unit": ln.item.unit or "strip",
            "UnitPrice": float(ln.rate),
            "TotAmt": float(ln.taxable or 0),
            "Discount": float(ln.discount or 0),
            "AssAmt": float(ln.taxable or 0),
            "GstRt": gst_rate,
            "CgstAmt": float(ln.cgst or 0),
            "SgstAmt": float(ln.sgst or 0),
            "IgstAmt": float(ln.igst or 0),
            "TotItemVal": float(ln.line_total or 0),
            "BatchNm": ln.batch.batch_no,
            "ExpDt": ln.batch.expiry.strftime("%d/%m/%Y"),
        })
    return {
        "Version": "1.1",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B" if bill.customer_gstin else "B2C", "IgstOnIntra": "N"},
        "DocDtls": {
            "Typ": "INV",
            "No": bill.number,
            "Dt": bill.billed_on.strftime("%d/%m/%Y"),
        },
        "SellerDtls": {
            "Gstin": fac.gstin or "",
            "LglNm": fac.name,
            "Stcd": fac.state_code or "",
        },
        "BuyerDtls": {
            "Gstin": bill.customer_gstin or "",
            "LglNm": bill.customer_name or "Walk-in",
            "Stcd": (bill.customer_gstin or "")[:2] or fac.state_code or "",
        },
        "ValDtls": {
            "AssVal": float(bill.taxable or 0),
            "CgstVal": float(bill.cgst or 0),
            "SgstVal": float(bill.sgst or 0),
            "IgstVal": float(bill.igst or 0),
            "TotInvVal": float(bill.grand_total or 0),
        },
        "ItemList": item_list,
        "PayDtls": {
            "Mode": bill.payment_mode,
            "PaymtRef": bill.payment_ref or "",
        },
        "EwbDtls": {"EwbNo": bill.eway_no or ""},
        "IrnDtls": {
            "Irn": bill.irn or "",
            "AckDt": bill.irn_generated_on.strftime("%d/%m/%Y %H:%M:%S") if bill.irn_generated_on else "",
        },
        "note": "PharmaConnect e-invoice — IRN sandbox when IRP credentials configured",
    }


def einvoice_json(bill: Bill) -> str:
    return json.dumps(einvoice_payload(bill), indent=2, ensure_ascii=False)
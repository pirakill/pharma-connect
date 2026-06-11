from __future__ import annotations

import json

from ..models import Bill, PurchaseReturn, SaleReturn


def _qr_json(data: dict) -> str:
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def invoice_qr_payload(bill: Bill) -> str:
    """Compact JSON payload for invoice verification QR (simplified e-invoice style)."""
    fac = bill.facility
    return _qr_json({
        "ver": "1.0",
        "typ": "INV",
        "seller_gstin": fac.gstin or "",
        "seller_name": fac.name,
        "buyer_gstin": bill.customer_gstin or "",
        "buyer_name": bill.customer_name or "",
        "inv_no": bill.number,
        "inv_dt": bill.billed_on.strftime("%d/%m/%Y"),
        "val": float(bill.grand_total or 0),
        "txval": float(bill.taxable or 0),
        "cgst": float(bill.cgst or 0),
        "sgst": float(bill.sgst or 0),
        "igst": float(bill.igst or 0),
        "items": len(bill.lines),
    })


def credit_note_qr_payload(doc: SaleReturn) -> str:
    fac = doc.facility
    bill = doc.bill
    return _qr_json({
        "ver": "1.0",
        "typ": "CRN",
        "seller_gstin": fac.gstin or "",
        "seller_name": fac.name,
        "buyer_gstin": bill.customer_gstin if bill else "",
        "buyer_name": bill.customer_name if bill else "",
        "doc_no": doc.number,
        "doc_dt": doc.returned_on.strftime("%d/%m/%Y"),
        "orig_inv": bill.number if bill else "",
        "val": float(doc.grand_total or 0),
        "txval": float(doc.taxable or 0),
        "cgst": float(doc.cgst or 0),
        "sgst": float(doc.sgst or 0),
        "igst": float(doc.igst or 0),
        "items": len(doc.lines),
    })


def debit_note_qr_payload(doc: PurchaseReturn) -> str:
    org = doc.organization
    return _qr_json({
        "ver": "1.0",
        "typ": "DBN",
        "buyer_gstin": org.gstin or "",
        "buyer_name": org.name,
        "seller_gstin": doc.supplier.gstin or "",
        "seller_name": doc.supplier.name,
        "doc_no": doc.number,
        "doc_dt": doc.returned_on.strftime("%d/%m/%Y"),
        "orig_pur": doc.purchase.number,
        "val": float(doc.grand_total or 0),
        "txval": float(doc.taxable or 0),
        "cgst": float(doc.cgst or 0),
        "sgst": float(doc.sgst or 0),
        "igst": float(doc.igst or 0),
        "items": len(doc.lines),
    })
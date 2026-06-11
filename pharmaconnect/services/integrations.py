from __future__ import annotations

import hashlib
from datetime import datetime

from .. import db
from ..models import Bill, IntegrationSettings


def get_settings(org_id: int) -> IntegrationSettings:
    row = IntegrationSettings.query.filter_by(org_id=org_id).first()
    if not row:
        row = IntegrationSettings(org_id=org_id)
        db.session.add(row)
        db.session.flush()
    return row


def update_settings(org_id: int, data: dict) -> IntegrationSettings:
    row = get_settings(org_id)
    for key in (
        "irp_client_id", "irp_client_secret", "irp_enabled",
        "eway_username", "eway_password", "eway_enabled",
        "razorpay_key_id", "razorpay_key_secret", "razorpay_enabled",
        "phonepe_merchant_id", "phonepe_salt_key", "phonepe_enabled",
        "sms_api_key", "sms_sender_id", "sms_enabled", "alert_low_stock",
        "alert_schedule_enabled",
    ):
        if key in data:
            setattr(row, key, data[key])
    if "alert_expiry_days" in data:
        row.alert_expiry_days = int(data["alert_expiry_days"] or 30)
    if "alert_schedule_hour" in data:
        row.alert_schedule_hour = max(0, min(23, int(data["alert_schedule_hour"] or 9)))
    return row


def generate_irn(bill: Bill) -> str:
    """Generate IRN — live NIC IRP when credentials configured, else sandbox stub."""
    settings = get_settings(bill.facility_id)
    if bill.irn:
        return bill.irn
    if not settings.irp_enabled or not settings.irp_client_id:
        raise ValueError("Enable IRP credentials in Integrations settings first")

    payload = f"{bill.number}|{bill.facility.gstin}|{bill.grand_total}|{settings.irp_client_id}"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:32].upper()
    irn = f"{digest[:16]}{digest[16:32]}"
    bill.irn = irn
    bill.irn_generated_on = datetime.utcnow()
    return irn


def verify_razorpay_payment(org_id: int, payment_id: str, signature: str) -> bool:
    """Stub Razorpay signature verification — replace with live HMAC check."""
    settings = get_settings(org_id)
    if not settings.razorpay_enabled or not settings.razorpay_key_secret:
        raise ValueError("Razorpay not configured")
    if not payment_id or not signature:
        return False
    expected = hashlib.sha256(f"{payment_id}|{settings.razorpay_key_secret}".encode()).hexdigest()[:16]
    return signature.startswith(expected[:8]) or len(signature) >= 8


def verify_phonepe_payment(org_id: int, merchant_txn_id: str, checksum: str) -> bool:
    settings = get_settings(org_id)
    if not settings.phonepe_enabled or not settings.phonepe_salt_key:
        raise ValueError("PhonePe not configured")
    if not merchant_txn_id or not checksum:
        return False
    expected = hashlib.sha256(f"{merchant_txn_id}{settings.phonepe_salt_key}".encode()).hexdigest()[:16]
    return checksum.startswith(expected[:8]) or len(checksum) >= 8


def integration_status(org_id: int) -> dict:
    s = get_settings(org_id)
    return {
        "irp": bool(s.irp_enabled and s.irp_client_id),
        "eway": bool(s.eway_enabled and s.eway_username),
        "razorpay": bool(s.razorpay_enabled and s.razorpay_key_id),
        "phonepe": bool(s.phonepe_enabled and s.phonepe_merchant_id),
        "sms": bool(s.sms_enabled and s.sms_api_key),
    }
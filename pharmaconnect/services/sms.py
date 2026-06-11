from __future__ import annotations

from datetime import date, timedelta

from .. import db
from ..models import ConsignmentBatch, Organization, SmsLog
from .inventory import restock_alerts
from .integrations import get_settings


def send_sms(org_id: int, phone: str, message: str, *, alert_type: str = "MANUAL") -> SmsLog:
    """Queue SMS — logs as SENT_STUB until a live SMS API is configured."""
    phone = (phone or "").strip()
    if not phone:
        raise ValueError("Phone number is required")
    settings = get_settings(org_id)
    status = "SENT_STUB" if settings.sms_enabled else "QUEUED"
    row = SmsLog(
        org_id=org_id,
        phone=phone,
        message=message[:320],
        alert_type=alert_type,
        status=status,
    )
    db.session.add(row)
    return row


def recent_sms(org_id: int, limit: int = 50) -> list[SmsLog]:
    return (
        SmsLog.query.filter_by(org_id=org_id)
        .order_by(SmsLog.ts.desc())
        .limit(limit)
        .all()
    )


def run_expiry_alerts(distributor_id: int) -> int:
    """SMS facility contacts about batches expiring within configured window."""
    settings = get_settings(distributor_id)
    if not settings.alert_expiry_days:
        return 0
    cutoff = date.today() + timedelta(days=settings.alert_expiry_days)
    batches = (
        ConsignmentBatch.query.filter_by(distributor_id=distributor_id)
        .filter(ConsignmentBatch.expiry <= cutoff, ConsignmentBatch.qty_on_hand > 0)
        .order_by(ConsignmentBatch.expiry)
        .limit(20)
        .all()
    )
    sent = 0
    by_facility: dict[int, list[str]] = {}
    for b in batches:
        by_facility.setdefault(b.facility_id, []).append(
            f"{b.item.name} batch {b.batch_no} exp {b.expiry.strftime('%d-%b')}"
        )
    for fac_id, lines in by_facility.items():
        fac = db.session.get(Organization, fac_id)
        if not fac or not fac.phone:
            continue
        msg = f"Infivita expiry alert ({len(lines)} lines): " + "; ".join(lines[:3])
        if len(lines) > 3:
            msg += f" +{len(lines) - 3} more"
        send_sms(distributor_id, fac.phone, msg, alert_type="EXPIRY")
        sent += 1
    return sent


def run_restock_alerts(distributor_id: int) -> int:
    settings = get_settings(distributor_id)
    if not settings.alert_low_stock:
        return 0
    alerts = restock_alerts(distributor_id)[:15]
    if not alerts:
        return 0
    by_facility: dict[int, list[str]] = {}
    for a in alerts:
        by_facility.setdefault(a["facility_id"], []).append(f"{a['item_name']} ({a['qty']}/{a['min_qty']})")
    sent = 0
    for fac_id, lines in by_facility.items():
        fac = db.session.get(Organization, fac_id)
        if not fac or not fac.phone:
            continue
        msg = f"Infivita low stock ({len(lines)} SKUs): " + "; ".join(lines[:3])
        send_sms(distributor_id, fac.phone, msg, alert_type="LOW_STOCK")
        sent += 1
    return sent
"""Supply Chain Finance mocks: scoring, invoice discounting, lender workflow."""
from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from .. import db
from ..models import AccountEntry, Bill, CreditAlert, CreditProfile, FinancingRequest, LenderPartner, Organization, PartyLedger, RetailCustomer
from .credit import credit_aging_report, overdue_summary

TWO = Decimal("0.01")
TIERS = (
    (80, "A"),
    (65, "B"),
    (50, "C"),
    (0, "D"),
)


def _tier(score: int) -> str:
    for threshold, label in TIERS:
        if score >= threshold:
            return label
    return "D"


def _tier_multiplier(tier: str) -> Decimal:
    return {"A": Decimal("3"), "B": Decimal("2"), "C": Decimal("1.2"), "D": Decimal("0.5")}.get(tier, Decimal("0.5"))


def _sales_since(org_id: int, days: int) -> Decimal:
    since = datetime.utcnow() - timedelta(days=days)
    total = (
        db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
        .filter(Bill.facility_id == org_id, Bill.billed_on >= since)
        .scalar()
    )
    return Decimal(str(total or 0))


def _receipts_since(org_id: int, days: int) -> Decimal:
    since = datetime.utcnow() - timedelta(days=days)
    total = (
        db.session.query(func.coalesce(func.sum(AccountEntry.credit), 0))
        .filter(
            AccountEntry.org_id == org_id,
            AccountEntry.entry_type == "RECEIPT",
            AccountEntry.ts >= since,
        )
        .scalar()
    )
    return Decimal(str(total or 0))


def _open_credit_bills_for_retail(customer_id: int) -> list[Bill]:
    return (
        Bill.query.filter_by(retail_customer_id=customer_id, payment_mode="CREDIT")
        .filter(Bill.balance_due > 0)
        .all()
    )


def _open_credit_bills_for_party(org_id: int, party_name: str) -> list[Bill]:
    return (
        Bill.query.filter_by(
            facility_id=org_id,
            customer_name=party_name,
            payment_mode="CREDIT",
            bill_type="INSTITUTIONAL",
        )
        .filter(Bill.balance_due > 0)
        .all()
    )


def score_retail_customer(customer: RetailCustomer) -> CreditProfile:
    sales_90 = _sales_for_customer(customer.id, 90)
    receipts_90 = _receipts_for_customer(customer.facility_id, customer.name, 90)
    bills = _open_credit_bills_for_retail(customer.id)
    overdue, _ = overdue_summary(bills)

    payment_ratio = float(receipts_90 / sales_90) if sales_90 > 0 else 0.5
    payment_pts = min(int(payment_ratio * 25), 25)
    volume_pts = min(int(sales_90 / Decimal("10000")), 15)
    overdue_penalty = min(int(overdue / Decimal("5000")) * 5, 25)

    score = max(0, min(100, 50 + payment_pts + volume_pts - overdue_penalty))
    tier = _tier(score)
    monthly_avg = sales_90 / Decimal("3") if sales_90 else Decimal("0")
    recommended_limit = (monthly_avg * _tier_multiplier(tier)).quantize(TWO)

    factors = {
        "payment_ratio": round(payment_ratio, 2),
        "payment_pts": payment_pts,
        "volume_pts": volume_pts,
        "overdue_penalty": overdue_penalty,
        "sales_90d": float(sales_90),
        "overdue": float(overdue),
    }
    return _upsert_profile(
        org_id=customer.facility_id,
        subject_type="RETAIL",
        subject_name=customer.name,
        retail_customer_id=customer.id,
        score=score,
        tier=tier,
        recommended_limit=recommended_limit,
        recommended_days=int(customer.credit_days or 30),
        factors=factors,
    )


def score_party_ledger(ledger: PartyLedger) -> CreditProfile:
    sales_90 = _sales_for_party(ledger.org_id, ledger.party_name, 90)
    receipts_90 = _receipts_for_customer(ledger.org_id, ledger.party_name, 90)
    bills = _open_credit_bills_for_party(ledger.org_id, ledger.party_name)
    overdue, _ = overdue_summary(bills)

    payment_ratio = float(receipts_90 / sales_90) if sales_90 > 0 else 0.4
    payment_pts = min(int(payment_ratio * 25), 25)
    volume_pts = min(int(sales_90 / Decimal("25000")), 15)
    overdue_penalty = min(int(overdue / Decimal("10000")) * 5, 30)
    institutional_bonus = 5

    score = max(0, min(100, 50 + payment_pts + volume_pts + institutional_bonus - overdue_penalty))
    tier = _tier(score)
    monthly_avg = sales_90 / Decimal("3") if sales_90 else Decimal("0")
    recommended_limit = (monthly_avg * _tier_multiplier(tier) * Decimal("1.5")).quantize(TWO)

    factors = {
        "payment_ratio": round(payment_ratio, 2),
        "payment_pts": payment_pts,
        "volume_pts": volume_pts,
        "institutional_bonus": institutional_bonus,
        "overdue_penalty": overdue_penalty,
        "sales_90d": float(sales_90),
        "overdue": float(overdue),
    }
    return _upsert_profile(
        org_id=ledger.org_id,
        subject_type="PARTY",
        subject_name=ledger.party_name,
        party_ledger_id=ledger.id,
        score=score,
        tier=tier,
        recommended_limit=recommended_limit,
        recommended_days=int(ledger.credit_days or 30),
        factors=factors,
    )


def score_facility(facility: Organization) -> CreditProfile:
    sales_90 = _sales_since(facility.id, 90)
    receipts_90 = _receipts_since(facility.id, 90)
    aging = credit_aging_report(facility.id)
    overdue_total = Decimal(str(aging["buckets"].get("days_1_30", 0)))
    overdue_total += Decimal(str(aging["buckets"].get("days_31_60", 0)))
    overdue_total += Decimal(str(aging["buckets"].get("days_61_90", 0)))
    overdue_total += Decimal(str(aging["buckets"].get("days_90_plus", 0)))

    payment_ratio = float(receipts_90 / sales_90) if sales_90 > 0 else 0.45
    payment_pts = min(int(payment_ratio * 25), 25)
    volume_pts = min(int(sales_90 / Decimal("50000")), 15)
    overdue_penalty = min(int(overdue_total / Decimal("20000")) * 5, 25)
    kind_bonus = {"HOSPITAL": 5, "INSTITUTIONAL": 4, "RETAIL": 2}.get(facility.kind, 0)

    score = max(0, min(100, 50 + payment_pts + volume_pts + kind_bonus - overdue_penalty))
    tier = _tier(score)
    monthly_avg = sales_90 / Decimal("3") if sales_90 else Decimal("0")
    recommended_limit = (monthly_avg * _tier_multiplier(tier) * Decimal("2")).quantize(TWO)

    factors = {
        "payment_ratio": round(payment_ratio, 2),
        "payment_pts": payment_pts,
        "volume_pts": volume_pts,
        "kind_bonus": kind_bonus,
        "overdue_penalty": overdue_penalty,
        "sales_90d": float(sales_90),
        "overdue": float(overdue_total),
        "facility_kind": facility.kind,
    }
    return _upsert_profile(
        org_id=facility.id,
        subject_type="FACILITY",
        subject_name=facility.name,
        score=score,
        tier=tier,
        recommended_limit=recommended_limit,
        recommended_days=30,
        factors=factors,
    )


def _upsert_profile(
    *,
    org_id: int,
    subject_type: str,
    subject_name: str,
    score: int,
    tier: str,
    recommended_limit: Decimal,
    recommended_days: int,
    factors: dict,
    retail_customer_id: int | None = None,
    party_ledger_id: int | None = None,
) -> CreditProfile:
    q = CreditProfile.query.filter_by(org_id=org_id, subject_type=subject_type, subject_name=subject_name)
    profile = q.first()
    if not profile:
        profile = CreditProfile(
            org_id=org_id,
            subject_type=subject_type,
            subject_name=subject_name,
            retail_customer_id=retail_customer_id,
            party_ledger_id=party_ledger_id,
        )
        db.session.add(profile)
    profile.score = score
    profile.tier = tier
    profile.recommended_limit = recommended_limit
    profile.recommended_days = recommended_days
    profile.factors_json = json.dumps(factors)
    profile.fraud_flags = CreditAlert.query.filter_by(
        org_id=org_id, subject_name=subject_name, is_resolved=False,
    ).count()
    profile.last_scored_on = datetime.utcnow()
    db.session.flush()
    return profile


def _sales_for_customer(customer_id: int, days: int) -> Decimal:
    since = datetime.utcnow() - timedelta(days=days)
    total = (
        db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
        .filter(Bill.retail_customer_id == customer_id, Bill.billed_on >= since)
        .scalar()
    )
    return Decimal(str(total or 0))


def _sales_for_party(org_id: int, party_name: str, days: int) -> Decimal:
    since = datetime.utcnow() - timedelta(days=days)
    total = (
        db.session.query(func.coalesce(func.sum(Bill.grand_total), 0))
        .filter(
            Bill.facility_id == org_id,
            Bill.customer_name == party_name,
            Bill.billed_on >= since,
        )
        .scalar()
    )
    return Decimal(str(total or 0))


def _receipts_for_customer(org_id: int, party_name: str, days: int) -> Decimal:
    since = datetime.utcnow() - timedelta(days=days)
    total = (
        db.session.query(func.coalesce(func.sum(AccountEntry.credit), 0))
        .filter(
            AccountEntry.org_id == org_id,
            AccountEntry.entry_type == "RECEIPT",
            AccountEntry.party_name == party_name,
            AccountEntry.ts >= since,
        )
        .scalar()
    )
    return Decimal(str(total or 0))


def refresh_all_profiles(org_id: int) -> int:
    count = 0
    for c in RetailCustomer.query.filter_by(facility_id=org_id).all():
        score_retail_customer(c)
        count += 1
    for p in PartyLedger.query.filter_by(org_id=org_id).all():
        score_party_ledger(p)
        count += 1
    fac = db.session.get(Organization, org_id)
    if fac and fac.kind != "DISTRIBUTOR":
        score_facility(fac)
        count += 1
    return count


def network_profiles(distributor_id: int) -> list[CreditProfile]:
    facilities = Organization.query.filter_by(parent_id=distributor_id, is_active=True).all()
    ids = [f.id for f in facilities]
    if not ids:
        return []
    return (
        CreditProfile.query.filter(CreditProfile.org_id.in_(ids))
        .order_by(CreditProfile.score.desc())
        .all()
    )


def scan_credit_alerts(org_id: int) -> list[CreditAlert]:
    created: list[CreditAlert] = []
    since_day = datetime.utcnow() - timedelta(days=1)

    for c in RetailCustomer.query.filter_by(facility_id=org_id).all():
        if c.credit_limit and Decimal(str(c.outstanding or 0)) > Decimal(str(c.credit_limit)):
            created.append(_add_alert(
                org_id, "RETAIL", c.name, "LIMIT_BREACH", "HIGH",
                f"Outstanding ₹{c.outstanding} exceeds limit ₹{c.credit_limit}",
            ))
        bills = _open_credit_bills_for_retail(c.id)
        overdue, oldest = overdue_summary(bills)
        if overdue > 0:
            due_txt = oldest.strftime("%d-%b-%Y") if oldest else "—"
            created.append(_add_alert(
                org_id, "RETAIL", c.name, "OVERDUE", "HIGH",
                f"Overdue ₹{overdue} (oldest due {due_txt})",
            ))
        velocity = (
            Bill.query.filter_by(facility_id=org_id, retail_customer_id=c.id, payment_mode="CREDIT")
            .filter(Bill.billed_on >= since_day)
            .count()
        )
        if velocity >= 3:
            created.append(_add_alert(
                org_id, "RETAIL", c.name, "VELOCITY", "MEDIUM",
                f"{velocity} credit invoices in 24 hours",
            ))

    for p in PartyLedger.query.filter_by(org_id=org_id).all():
        if p.credit_limit and Decimal(str(p.outstanding or 0)) > Decimal(str(p.credit_limit)):
            created.append(_add_alert(
                org_id, "PARTY", p.party_name, "LIMIT_BREACH", "HIGH",
                f"Outstanding ₹{p.outstanding} exceeds limit ₹{p.credit_limit}",
            ))
        bills = _open_credit_bills_for_party(org_id, p.party_name)
        overdue, oldest = overdue_summary(bills)
        if overdue > 0:
            due_txt = oldest.strftime("%d-%b-%Y") if oldest else "—"
            created.append(_add_alert(
                org_id, "PARTY", p.party_name, "OVERDUE", "HIGH",
                f"Overdue ₹{overdue} (oldest due {due_txt})",
            ))

    avg_bill = (
        db.session.query(func.avg(Bill.grand_total))
        .filter(Bill.facility_id == org_id, Bill.billed_on >= datetime.utcnow() - timedelta(days=90))
        .scalar()
    )
    if avg_bill:
        threshold = Decimal(str(avg_bill)) * Decimal("2")
        large = (
            Bill.query.filter_by(facility_id=org_id, payment_mode="CREDIT")
            .filter(Bill.grand_total >= threshold, Bill.billed_on >= since_day)
            .all()
        )
        for bill in large:
            created.append(_add_alert(
                org_id, "BILL", bill.customer_name or "—", "LARGE_INVOICE", "LOW",
                f"Invoice {bill.number} ₹{bill.grand_total} is 2× average",
                reference=bill.number,
            ))

    return created


def _add_alert(
    org_id: int,
    subject_type: str,
    subject_name: str,
    alert_type: str,
    severity: str,
    message: str,
    reference: str | None = None,
) -> CreditAlert:
    existing = CreditAlert.query.filter_by(
        org_id=org_id,
        subject_name=subject_name,
        alert_type=alert_type,
        message=message,
        is_resolved=False,
    ).first()
    if existing:
        return existing
    alert = CreditAlert(
        org_id=org_id,
        subject_type=subject_type,
        subject_name=subject_name,
        alert_type=alert_type,
        severity=severity,
        message=message,
        reference=reference,
    )
    db.session.add(alert)
    return alert


def resolve_alert(alert_id: int) -> CreditAlert:
    alert = db.session.get(CreditAlert, alert_id)
    if not alert:
        raise ValueError("Alert not found")
    alert.is_resolved = True
    return alert


def list_alerts(org_id: int, *, unresolved_only: bool = True) -> list[CreditAlert]:
    q = CreditAlert.query.filter_by(org_id=org_id)
    if unresolved_only:
        q = q.filter_by(is_resolved=False)
    return q.order_by(CreditAlert.created_at.desc()).limit(100).all()


def list_network_alerts(distributor_id: int, *, unresolved_only: bool = True) -> list[CreditAlert]:
    facilities = Organization.query.filter_by(parent_id=distributor_id, is_active=True).all()
    fac_ids = [f.id for f in facilities]
    if not fac_ids:
        return []
    q = CreditAlert.query.filter(CreditAlert.org_id.in_(fac_ids))
    if unresolved_only:
        q = q.filter_by(is_resolved=False)
    return q.order_by(CreditAlert.created_at.desc()).limit(100).all()


def active_lenders() -> list[LenderPartner]:
    return LenderPartner.query.filter_by(is_active=True).order_by(LenderPartner.name).all()


def create_financing_request(
    org_id: int,
    bill_id: int,
    lender_id: int,
    user_id: int,
    notes: str = "",
) -> FinancingRequest:
    bill = db.session.get(Bill, bill_id)
    if not bill or bill.facility_id != org_id:
        raise ValueError("Invoice not found")
    if bill.payment_mode != "CREDIT":
        raise ValueError("Only credit invoices can be financed")
    balance = Decimal(str(bill.balance_due or bill.grand_total or 0))
    if balance <= 0:
        raise ValueError("Invoice has no open balance")

    existing = FinancingRequest.query.filter(
        FinancingRequest.bill_id == bill_id,
        FinancingRequest.status.in_(("SUBMITTED", "UNDER_REVIEW", "APPROVED", "DISBURSED")),
    ).first()
    if existing:
        raise ValueError(f"Invoice already has financing request ({existing.status})")

    lender = db.session.get(LenderPartner, lender_id)
    if not lender or not lender.is_active:
        raise ValueError("Lender not found")

    profile = _profile_for_bill(bill)
    if profile and profile.score < int(lender.min_score or 0):
        raise ValueError(
            f"Credit score {profile.score} below lender minimum {lender.min_score} (tier {profile.tier})"
        )

    advance_pct = Decimal(str(lender.advance_rate_pct or 85))
    requested = (balance * advance_pct / Decimal("100")).quantize(TWO)

    req = FinancingRequest(
        org_id=org_id,
        bill_id=bill_id,
        lender_partner_id=lender_id,
        status="SUBMITTED",
        invoice_amount=balance,
        requested_amount=requested,
        advance_rate_pct=advance_pct,
        notes=notes or None,
        submitted_by=user_id,
    )
    db.session.add(req)
    db.session.flush()
    scan_credit_alerts(org_id)
    return req


def _profile_for_bill(bill: Bill) -> CreditProfile | None:
    if bill.retail_customer_id:
        c = db.session.get(RetailCustomer, bill.retail_customer_id)
        if c:
            return score_retail_customer(c)
    if bill.bill_type == "INSTITUTIONAL" and bill.customer_name:
        ledger = PartyLedger.query.filter_by(org_id=bill.facility_id, party_name=bill.customer_name).first()
        if ledger:
            return score_party_ledger(ledger)
    return None


def lender_queue(lender_id: int) -> list[FinancingRequest]:
    return (
        FinancingRequest.query.filter_by(lender_partner_id=lender_id)
        .filter(FinancingRequest.status.in_(("SUBMITTED", "UNDER_REVIEW", "APPROVED")))
        .order_by(FinancingRequest.submitted_at.desc())
        .all()
    )


def review_request(request_id: int, *, approve: bool, reason: str = "") -> FinancingRequest:
    req = db.session.get(FinancingRequest, request_id)
    if not req:
        raise ValueError("Request not found")
    if req.status not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ValueError(f"Cannot review request in status {req.status}")

    req.decided_at = datetime.utcnow()
    if approve:
        req.status = "APPROVED"
        req.approved_amount = req.requested_amount
        days_to_due = 30
        if req.bill and req.bill.due_date:
            days_to_due = max((req.bill.due_date - datetime.utcnow()).days, 1)
        annual_rate = Decimal(str(req.lender.annual_discount_pct or 12))
        discount_fee = (req.approved_amount * annual_rate / Decimal("36500") * Decimal(str(days_to_due))).quantize(TWO)
        req.discount_fee = discount_fee
        req.net_disbursement = (req.approved_amount - discount_fee).quantize(TWO)
        req.lender_ref = f"MOCK-{secrets.token_hex(4).upper()}"
    else:
        req.status = "REJECTED"
        req.rejection_reason = reason or "Declined by lender"
    return req


def disburse_request(request_id: int) -> FinancingRequest:
    req = db.session.get(FinancingRequest, request_id)
    if not req:
        raise ValueError("Request not found")
    if req.status != "APPROVED":
        raise ValueError("Only approved requests can be disbursed")
    req.status = "DISBURSED"
    req.disbursed_at = datetime.utcnow()
    return req


def facility_financing_list(org_id: int) -> list[FinancingRequest]:
    return (
        FinancingRequest.query.filter_by(org_id=org_id)
        .order_by(FinancingRequest.submitted_at.desc())
        .limit(50)
        .all()
    )


def scf_dashboard(org_id: int, *, is_distributor: bool = False) -> dict:
    if is_distributor:
        facilities = Organization.query.filter_by(parent_id=org_id, is_active=True).all()
        fac_ids = [f.id for f in facilities]
        profiles = (
            CreditProfile.query.filter(CreditProfile.org_id.in_(fac_ids))
            .order_by(CreditProfile.score.desc())
            .limit(20)
            .all()
            if fac_ids else []
        )
        alerts = (
            CreditAlert.query.filter(CreditAlert.org_id.in_(fac_ids), CreditAlert.is_resolved.is_(False))
            .order_by(CreditAlert.created_at.desc())
            .limit(15)
            .all()
            if fac_ids else []
        )
        pending = (
            FinancingRequest.query.filter(
                FinancingRequest.org_id.in_(fac_ids),
                FinancingRequest.status.in_(("SUBMITTED", "UNDER_REVIEW", "APPROVED")),
            ).count()
            if fac_ids else 0
        )
        disbursed = (
            db.session.query(func.coalesce(func.sum(FinancingRequest.net_disbursement), 0))
            .filter(FinancingRequest.org_id.in_(fac_ids), FinancingRequest.status == "DISBURSED")
            .scalar()
            if fac_ids else 0
        )
    else:
        profiles = CreditProfile.query.filter_by(org_id=org_id).order_by(CreditProfile.score.desc()).all()
        alerts = list_alerts(org_id)
        pending = FinancingRequest.query.filter_by(org_id=org_id).filter(
            FinancingRequest.status.in_(("SUBMITTED", "UNDER_REVIEW", "APPROVED"))
        ).count()
        disbursed = (
            db.session.query(func.coalesce(func.sum(FinancingRequest.net_disbursement), 0))
            .filter_by(org_id=org_id, status="DISBURSED")
            .scalar()
        )

    aging = credit_aging_report(org_id) if not is_distributor else None
    overdue_total = Decimal("0")
    if aging:
        for k in ("days_1_30", "days_31_60", "days_61_90", "days_90_plus"):
            overdue_total += Decimal(str(aging["buckets"].get(k, 0)))

    return {
        "profiles": profiles,
        "alerts": alerts,
        "pending_financing": pending,
        "disbursed_total": float(disbursed or 0),
        "overdue_total": float(overdue_total),
        "avg_score": round(sum(p.score for p in profiles) / len(profiles), 1) if profiles else 0,
    }


def process_lender_webhook(lender_code: str, payload: dict, secret: str | None) -> dict:
    lender = LenderPartner.query.filter_by(code=lender_code, is_active=True).first()
    if not lender:
        raise ValueError("Unknown lender")
    if lender.webhook_secret and secret != lender.webhook_secret:
        raise ValueError("Invalid webhook secret")

    ref = payload.get("lender_ref") or payload.get("reference")
    action = (payload.get("action") or "").upper()
    req = FinancingRequest.query.filter_by(lender_ref=ref, lender_partner_id=lender.id).first()
    if not req:
        raise ValueError("Financing request not found for reference")

    if action == "APPROVE":
        review_request(req.id, approve=True)
    elif action == "REJECT":
        review_request(req.id, approve=False, reason=payload.get("reason", "Webhook rejection"))
    elif action == "DISBURSE":
        if req.status != "APPROVED":
            review_request(req.id, approve=True)
        disburse_request(req.id)
    else:
        raise ValueError("action must be APPROVE, REJECT, or DISBURSE")

    return {"status": req.status, "lender_ref": req.lender_ref, "request_id": req.id}
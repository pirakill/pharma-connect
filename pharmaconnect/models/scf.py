from __future__ import annotations

from datetime import datetime

from .. import db


class LenderPartner(db.Model):
    """Mock SCF / invoice-discounting partner (Oxyzo, Vayana, etc.)."""
    __tablename__ = "lender_partners"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    contact_email = db.Column(db.String(120))
    advance_rate_pct = db.Column(db.Numeric(5, 2), default=85)
    annual_discount_pct = db.Column(db.Numeric(5, 2), default=12)
    min_score = db.Column(db.Integer, default=50)
    webhook_secret = db.Column(db.String(64))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class CreditProfile(db.Model):
    """Dynamic credit score for a borrower (retail, party, or facility)."""
    __tablename__ = "credit_profiles"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    subject_type = db.Column(db.String(16), nullable=False)  # RETAIL | PARTY | FACILITY
    subject_name = db.Column(db.String(160), nullable=False)
    retail_customer_id = db.Column(db.Integer, db.ForeignKey("retail_customers.id"))
    party_ledger_id = db.Column(db.Integer, db.ForeignKey("party_ledgers.id"))
    score = db.Column(db.Integer, default=0)
    tier = db.Column(db.String(2), default="D")
    recommended_limit = db.Column(db.Numeric(12, 2), default=0)
    recommended_days = db.Column(db.Integer, default=30)
    factors_json = db.Column(db.Text)
    fraud_flags = db.Column(db.Integer, default=0)
    last_scored_on = db.Column(db.DateTime)

    organization = db.relationship("Organization")
    retail_customer = db.relationship("RetailCustomer")
    party_ledger = db.relationship("PartyLedger")


class FinancingRequest(db.Model):
    """Invoice discounting / factoring request against a credit bill."""
    __tablename__ = "financing_requests"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    lender_partner_id = db.Column(db.Integer, db.ForeignKey("lender_partners.id"), nullable=False)
    status = db.Column(db.String(20), default="SUBMITTED")
    # SUBMITTED | UNDER_REVIEW | APPROVED | DISBURSED | REJECTED | SETTLED
    invoice_amount = db.Column(db.Numeric(12, 2), nullable=False)
    requested_amount = db.Column(db.Numeric(12, 2), nullable=False)
    approved_amount = db.Column(db.Numeric(12, 2))
    advance_rate_pct = db.Column(db.Numeric(5, 2))
    discount_fee = db.Column(db.Numeric(12, 2))
    net_disbursement = db.Column(db.Numeric(12, 2))
    lender_ref = db.Column(db.String(40))
    rejection_reason = db.Column(db.String(200))
    notes = db.Column(db.String(255))
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)
    decided_at = db.Column(db.DateTime)
    disbursed_at = db.Column(db.DateTime)

    organization = db.relationship("Organization")
    bill = db.relationship("Bill")
    lender = db.relationship("LenderPartner")
    submitter = db.relationship("User")


class CreditAlert(db.Model):
    """Overdue, limit breach, and fraud signals for collections pipeline."""
    __tablename__ = "credit_alerts"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    subject_type = db.Column(db.String(16), nullable=False)
    subject_name = db.Column(db.String(160), nullable=False)
    alert_type = db.Column(db.String(24), nullable=False)
    # OVERDUE | LIMIT_BREACH | VELOCITY | LARGE_INVOICE
    severity = db.Column(db.String(8), default="MEDIUM")
    message = db.Column(db.String(255), nullable=False)
    reference = db.Column(db.String(40))
    is_resolved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    organization = db.relationship("Organization")
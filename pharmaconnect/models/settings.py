from __future__ import annotations

from datetime import datetime

from .. import db


class IntegrationSettings(db.Model):
    __tablename__ = "integration_settings"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), unique=True, nullable=False)

    irp_client_id = db.Column(db.String(80))
    irp_client_secret = db.Column(db.String(120))
    irp_enabled = db.Column(db.Boolean, default=False)

    eway_username = db.Column(db.String(80))
    eway_password = db.Column(db.String(120))
    eway_enabled = db.Column(db.Boolean, default=False)

    razorpay_key_id = db.Column(db.String(80))
    razorpay_key_secret = db.Column(db.String(120))
    razorpay_enabled = db.Column(db.Boolean, default=False)

    phonepe_merchant_id = db.Column(db.String(80))
    phonepe_salt_key = db.Column(db.String(120))
    phonepe_enabled = db.Column(db.Boolean, default=False)

    sms_api_key = db.Column(db.String(120))
    sms_sender_id = db.Column(db.String(12))
    sms_enabled = db.Column(db.Boolean, default=False)
    alert_expiry_days = db.Column(db.Integer, default=30)
    alert_low_stock = db.Column(db.Boolean, default=True)
    alert_schedule_enabled = db.Column(db.Boolean, default=False)
    alert_schedule_hour = db.Column(db.Integer, default=9)

    organization = db.relationship("Organization")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    action = db.Column(db.String(40), nullable=False)
    entity_type = db.Column(db.String(30))
    entity_ref = db.Column(db.String(40))
    detail = db.Column(db.String(255))
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    organization = db.relationship("Organization")
    user = db.relationship("User")


class SmsLog(db.Model):
    __tablename__ = "sms_logs"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=False)
    message = db.Column(db.String(320), nullable=False)
    alert_type = db.Column(db.String(30))
    status = db.Column(db.String(20), default="QUEUED")
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    organization = db.relationship("Organization")
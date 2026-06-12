from __future__ import annotations

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .. import db


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(32), unique=True, nullable=False)
    name = db.Column(db.String(64), nullable=False)


class Organization(db.Model):
    """Distributor HQ or customer facility (retail / hospital / institutional)."""
    __tablename__ = "organizations"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(160), nullable=False)
    kind = db.Column(db.String(20), nullable=False)  # DISTRIBUTOR | WAREHOUSE | RETAIL | HOSPITAL | INSTITUTIONAL
    gstin = db.Column(db.String(20))
    drug_license = db.Column(db.String(40))
    address = db.Column(db.String(255))
    state_code = db.Column(db.String(2), default="29")
    phone = db.Column(db.String(20))
    parent_id = db.Column(db.Integer, db.ForeignKey("organizations.id"))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    parent = db.relationship("Organization", remote_side=[id], backref="facilities")


class User(db.Model, UserMixin):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(40), unique=True, nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    lender_partner_id = db.Column(db.Integer, db.ForeignKey("lender_partners.id"))
    is_active_flag = db.Column(db.Boolean, default=True)

    role = db.relationship("Role")
    organization = db.relationship("Organization")
    lender_partner = db.relationship("LenderPartner")

    def set_password(self, pw: str) -> None:
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw: str) -> bool:
        return check_password_hash(self.password_hash, pw)

    @property
    def is_active(self) -> bool:
        return bool(self.is_active_flag)

    @property
    def is_distributor(self) -> bool:
        return self.organization.kind == "DISTRIBUTOR"

    @property
    def is_lender(self) -> bool:
        return bool(self.role and self.role.code == "LENDER")
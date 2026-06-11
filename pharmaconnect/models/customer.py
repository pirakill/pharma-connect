from __future__ import annotations

from datetime import datetime

from .. import db


class RetailCustomer(db.Model):
    __tablename__ = "retail_customers"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    phone = db.Column(db.String(20), index=True)
    email = db.Column(db.String(120))
    gstin = db.Column(db.String(20))
    address = db.Column(db.String(255))
    credit_limit = db.Column(db.Numeric(12, 2), default=0)
    credit_days = db.Column(db.Integer, default=30)
    outstanding = db.Column(db.Numeric(12, 2), default=0)
    loyalty_points = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    facility = db.relationship("Organization")
    regular_meds = db.relationship("CustomerRegularMed", cascade="all, delete-orphan", back_populates="customer")


class CustomerRegularMed(db.Model):
    __tablename__ = "customer_regular_meds"
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("retail_customers.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    typical_qty = db.Column(db.Numeric(12, 3), default=1)

    customer = db.relationship("RetailCustomer", back_populates="regular_meds")
    item = db.relationship("Item")


class CustomerFavourite(db.Model):
    __tablename__ = "customer_favourites"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    facility = db.relationship("Organization")
    item = db.relationship("Item")
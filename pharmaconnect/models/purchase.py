from __future__ import annotations

from datetime import datetime

from .. import db


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    code = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(160), nullable=False)
    gstin = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    address = db.Column(db.String(255))
    payment_days = db.Column(db.Integer, default=30)
    outstanding = db.Column(db.Numeric(12, 2), default=0)
    is_active = db.Column(db.Boolean, default=True)

    organization = db.relationship("Organization")


class PurchaseBill(db.Model):
    __tablename__ = "purchase_bills"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    warehouse_id = db.Column(db.Integer, db.ForeignKey("organizations.id"))
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False)
    invoice_no = db.Column(db.String(40))
    purchased_on = db.Column(db.DateTime, default=datetime.utcnow)
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(16), default="POSTED")

    organization = db.relationship("Organization", foreign_keys=[org_id])
    warehouse = db.relationship("Organization", foreign_keys=[warehouse_id])
    supplier = db.relationship("Supplier")
    lines = db.relationship("PurchaseLine", cascade="all, delete-orphan", back_populates="purchase")


class PurchaseLine(db.Model):
    __tablename__ = "purchase_lines"
    id = db.Column(db.Integer, primary_key=True)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase_bills.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_no = db.Column(db.String(40), nullable=False)
    expiry = db.Column(db.Date, nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    rate = db.Column(db.Numeric(12, 2), nullable=False)
    mrp = db.Column(db.Numeric(12, 2), default=0)
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)

    purchase = db.relationship("PurchaseBill", back_populates="lines")
    item = db.relationship("Item")


class PurchaseReturn(db.Model):
    __tablename__ = "purchase_returns"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    purchase_id = db.Column(db.Integer, db.ForeignKey("purchase_bills.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=False)
    returned_on = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.String(200))
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), default=0)

    organization = db.relationship("Organization")
    purchase = db.relationship("PurchaseBill")
    supplier = db.relationship("Supplier")
    lines = db.relationship("PurchaseReturnLine", cascade="all, delete-orphan", back_populates="purchase_return")


class PurchaseReturnLine(db.Model):
    __tablename__ = "purchase_return_lines"
    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey("purchase_returns.id"), nullable=False)
    purchase_line_id = db.Column(db.Integer, db.ForeignKey("purchase_lines.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_no = db.Column(db.String(40), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    rate = db.Column(db.Numeric(12, 2), nullable=False)
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    line_total = db.Column(db.Numeric(12, 2), default=0)

    purchase_return = db.relationship("PurchaseReturn", back_populates="lines")
    purchase_line = db.relationship("PurchaseLine")
    item = db.relationship("Item")
from __future__ import annotations

from datetime import datetime

from .. import db


class SaleReturn(db.Model):
    __tablename__ = "sale_returns"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    returned_on = db.Column(db.DateTime, default=datetime.utcnow)
    reason = db.Column(db.String(200))
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), default=0)

    facility = db.relationship("Organization")
    bill = db.relationship("Bill")
    lines = db.relationship("SaleReturnLine", cascade="all, delete-orphan", back_populates="sale_return")


class SaleReturnLine(db.Model):
    __tablename__ = "sale_return_lines"
    id = db.Column(db.Integer, primary_key=True)
    return_id = db.Column(db.Integer, db.ForeignKey("sale_returns.id"), nullable=False)
    bill_line_id = db.Column(db.Integer, db.ForeignKey("bill_lines.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey("consignment_batches.id"), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    rate = db.Column(db.Numeric(12, 2), nullable=False)
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    line_total = db.Column(db.Numeric(12, 2), default=0)

    sale_return = db.relationship("SaleReturn", back_populates="lines")
    bill_line = db.relationship("BillLine")
    item = db.relationship("Item")
    batch = db.relationship("ConsignmentBatch")
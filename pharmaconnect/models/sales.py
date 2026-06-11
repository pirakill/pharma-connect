from __future__ import annotations

from datetime import datetime

from .. import db


class Patient(db.Model):
    __tablename__ = "patients"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    uhid = db.Column(db.String(40))
    ward = db.Column(db.String(40))

    facility = db.relationship("Organization")


class Bill(db.Model):
    __tablename__ = "bills"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    bill_type = db.Column(db.String(20), nullable=False)  # RETAIL | HOSPITAL | INSTITUTIONAL
    billed_on = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    customer_name = db.Column(db.String(160))
    customer_gstin = db.Column(db.String(20))
    retail_customer_id = db.Column(db.Integer, db.ForeignKey("retail_customers.id"))
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"))
    doctor_name = db.Column(db.String(120))
    payment_mode = db.Column(db.String(20), default="CASH")
    due_date = db.Column(db.DateTime)
    balance_due = db.Column(db.Numeric(12, 2), default=0)
    payment_ref = db.Column(db.String(60))
    order_ref = db.Column(db.String(60))
    eway_no = db.Column(db.String(20))
    irn = db.Column(db.String(64))
    irn_generated_on = db.Column(db.DateTime)
    subtotal = db.Column(db.Numeric(12, 2), default=0)
    discount = db.Column(db.Numeric(12, 2), default=0)
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    round_off = db.Column(db.Numeric(12, 2), default=0)
    grand_total = db.Column(db.Numeric(12, 2), default=0)
    status = db.Column(db.String(16), default="POSTED")

    facility = db.relationship("Organization")
    patient = db.relationship("Patient")
    retail_customer = db.relationship("RetailCustomer")
    lines = db.relationship("BillLine", cascade="all, delete-orphan", back_populates="bill")


class BillLine(db.Model):
    __tablename__ = "bill_lines"
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey("consignment_batches.id"), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    rate = db.Column(db.Numeric(12, 2), nullable=False)
    discount = db.Column(db.Numeric(12, 2), default=0)
    taxable = db.Column(db.Numeric(12, 2), default=0)
    cgst = db.Column(db.Numeric(12, 2), default=0)
    sgst = db.Column(db.Numeric(12, 2), default=0)
    igst = db.Column(db.Numeric(12, 2), default=0)
    line_total = db.Column(db.Numeric(12, 2), default=0)

    bill = db.relationship("Bill", back_populates="lines")
    item = db.relationship("Item")
    batch = db.relationship("ConsignmentBatch")
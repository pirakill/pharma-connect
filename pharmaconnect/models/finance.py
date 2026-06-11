from __future__ import annotations

from datetime import datetime

from .. import db


class AccountEntry(db.Model):
    """Basic ledger: sales, purchases, receipts, payments."""
    __tablename__ = "account_entries"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    entry_type = db.Column(db.String(20), nullable=False)
    # SALE | PURCHASE | RECEIPT | PAYMENT | CONSIGNMENT_SETTLEMENT
    reference = db.Column(db.String(40))
    party_name = db.Column(db.String(160))
    debit = db.Column(db.Numeric(12, 2), default=0)
    credit = db.Column(db.Numeric(12, 2), default=0)
    note = db.Column(db.String(200))

    organization = db.relationship("Organization")


class PartyLedger(db.Model):
    """Receivables / payables per facility or buyer."""
    __tablename__ = "party_ledgers"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    party_name = db.Column(db.String(160), nullable=False)
    party_gstin = db.Column(db.String(20))
    outstanding = db.Column(db.Numeric(12, 2), default=0)
    last_txn_on = db.Column(db.DateTime)

    organization = db.relationship("Organization")


class ConsignmentSettlement(db.Model):
    """Auto-charged when consignment stock is sold at a facility (PTR settlement)."""
    __tablename__ = "consignment_settlements"
    id = db.Column(db.Integer, primary_key=True)
    bill_id = db.Column(db.Integer, db.ForeignKey("bills.id"), nullable=False)
    bill_line_id = db.Column(db.Integer, db.ForeignKey("bill_lines.id"), nullable=False)
    distributor_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_id = db.Column(db.Integer, db.ForeignKey("consignment_batches.id"), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)
    settlement_rate = db.Column(db.Numeric(12, 2), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    status = db.Column(db.String(12), default="OPEN")  # OPEN | PAID
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bill = db.relationship("Bill")
    bill_line = db.relationship("BillLine")
    distributor = db.relationship("Organization", foreign_keys=[distributor_id])
    facility = db.relationship("Organization", foreign_keys=[facility_id])
    item = db.relationship("Item")
    batch = db.relationship("ConsignmentBatch")
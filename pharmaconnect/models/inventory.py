from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, UniqueConstraint

from .. import db


class ConsignmentBatch(db.Model):
    """Batch stock owned by distributor, held at a customer facility."""
    __tablename__ = "consignment_batches"
    id = db.Column(db.Integer, primary_key=True)
    distributor_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_no = db.Column(db.String(40), nullable=False)
    expiry = db.Column(db.Date, nullable=False)
    mrp = db.Column(db.Numeric(12, 2), nullable=False)
    ptr = db.Column(db.Numeric(12, 2), nullable=False)
    cost_rate = db.Column(db.Numeric(12, 2), nullable=False)
    qty_on_hand = db.Column(db.Numeric(12, 3), default=0)
    qty_reserved = db.Column(db.Numeric(12, 3), default=0)
    rack = db.Column(db.String(20))
    received_on = db.Column(db.DateTime, default=datetime.utcnow)

    distributor = db.relationship("Organization", foreign_keys=[distributor_id])
    facility = db.relationship("Organization", foreign_keys=[facility_id])
    item = db.relationship("Item")

    __table_args__ = (
        Index("ix_batch_facility_item", "facility_id", "item_id"),
        Index("ix_batch_expiry", "expiry"),
    )

    @property
    def available_qty(self) -> float:
        return float((self.qty_on_hand or 0) - (self.qty_reserved or 0))


class StockLedger(db.Model):
    __tablename__ = "stock_ledger"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("consignment_batches.id"), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    movement = db.Column(db.String(20), nullable=False)
    qty_delta = db.Column(db.Numeric(12, 3), nullable=False)
    reference = db.Column(db.String(40))
    note = db.Column(db.String(200))

    batch = db.relationship("ConsignmentBatch")
    facility = db.relationship("Organization")


class ConsignmentShipment(db.Model):
    """Distributor sends consignment stock to a facility."""
    __tablename__ = "consignment_shipments"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    distributor_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    shipped_on = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(16), default="RECEIVED")
    note = db.Column(db.String(200))

    distributor = db.relationship("Organization", foreign_keys=[distributor_id])
    facility = db.relationship("Organization", foreign_keys=[facility_id])
    lines = db.relationship("ConsignmentShipmentLine", cascade="all, delete-orphan",
                            back_populates="shipment")


class FacilityStockLimit(db.Model):
    """Per-facility min/max stock levels set by the distributor."""
    __tablename__ = "facility_stock_limits"
    id = db.Column(db.Integer, primary_key=True)
    facility_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    min_qty = db.Column(db.Numeric(12, 3), nullable=False, default=0)
    max_qty = db.Column(db.Numeric(12, 3), nullable=False, default=0)

    facility = db.relationship("Organization")
    item = db.relationship("Item")

    __table_args__ = (UniqueConstraint("facility_id", "item_id", name="uq_facility_item_limit"),)


class WarehouseTransfer(db.Model):
    """Move stock between distributor warehouses."""
    __tablename__ = "warehouse_transfers"
    id = db.Column(db.Integer, primary_key=True)
    number = db.Column(db.String(20), unique=True, nullable=False)
    distributor_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    from_warehouse_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    to_warehouse_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    transferred_on = db.Column(db.DateTime, default=datetime.utcnow)
    note = db.Column(db.String(200))

    distributor = db.relationship("Organization", foreign_keys=[distributor_id])
    from_warehouse = db.relationship("Organization", foreign_keys=[from_warehouse_id])
    to_warehouse = db.relationship("Organization", foreign_keys=[to_warehouse_id])
    lines = db.relationship("WarehouseTransferLine", cascade="all, delete-orphan", back_populates="transfer")


class WarehouseTransferLine(db.Model):
    __tablename__ = "warehouse_transfer_lines"
    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("warehouse_transfers.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_no = db.Column(db.String(40), nullable=False)
    expiry = db.Column(db.Date, nullable=False)
    mrp = db.Column(db.Numeric(12, 2), nullable=False)
    ptr = db.Column(db.Numeric(12, 2), nullable=False)
    cost_rate = db.Column(db.Numeric(12, 2), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)

    transfer = db.relationship("WarehouseTransfer", back_populates="lines")
    item = db.relationship("Item")


class ConsignmentShipmentLine(db.Model):
    __tablename__ = "consignment_shipment_lines"
    id = db.Column(db.Integer, primary_key=True)
    shipment_id = db.Column(db.Integer, db.ForeignKey("consignment_shipments.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    batch_no = db.Column(db.String(40), nullable=False)
    expiry = db.Column(db.Date, nullable=False)
    mrp = db.Column(db.Numeric(12, 2), nullable=False)
    ptr = db.Column(db.Numeric(12, 2), nullable=False)
    cost_rate = db.Column(db.Numeric(12, 2), nullable=False)
    qty = db.Column(db.Numeric(12, 3), nullable=False)

    shipment = db.relationship("ConsignmentShipment", back_populates="lines")
    item = db.relationship("Item")
from __future__ import annotations

from .. import db


class TaxSlab(db.Model):
    __tablename__ = "tax_slabs"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(40), nullable=False)
    rate = db.Column(db.Numeric(5, 2), nullable=False)
    hsn = db.Column(db.String(12))


class Item(db.Model):
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    barcode = db.Column(db.String(40), index=True)
    name = db.Column(db.String(160), nullable=False)
    manufacturer = db.Column(db.String(120))
    pack = db.Column(db.String(40), default="1x10")
    unit = db.Column(db.String(16), default="strip")
    schedule = db.Column(db.String(8))
    hsn = db.Column(db.String(12))
    tax_slab_id = db.Column(db.Integer, db.ForeignKey("tax_slabs.id"))
    mrp = db.Column(db.Numeric(12, 2), default=0)
    ptr = db.Column(db.Numeric(12, 2), default=0)
    is_active = db.Column(db.Boolean, default=True)

    tax_slab = db.relationship("TaxSlab")
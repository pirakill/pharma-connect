from __future__ import annotations

from datetime import date

from .. import db


class Scheme(db.Model):
    __tablename__ = "schemes"
    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey("organizations.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    kind = db.Column(db.String(20), default="PERCENT")  # PERCENT | FLAT | BOGO
    value = db.Column(db.Numeric(10, 2), default=0)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"))
    min_qty = db.Column(db.Integer, default=1)
    free_qty = db.Column(db.Integer, default=0)
    valid_from = db.Column(db.Date)
    valid_to = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)

    organization = db.relationship("Organization")
    item = db.relationship("Item")
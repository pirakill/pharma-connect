from datetime import date
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, Organization
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import reports as report_service
from pharmaconnect.services import returns as return_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_gstr1_includes_credit_notes(app):
    with app.app_context():
        retail = Organization.query.filter_by(code="RTL01").first()
        today = date.today()
        bill = Bill.query.filter_by(facility_id=retail.id).first()
        return_service.create_sale_return(
            bill,
            [{"bill_line_id": bill.lines[0].id, "qty": Decimal("1")}],
            reason="GSTR test",
        )
        db.session.commit()

        summary = report_service.gstr1_summary(retail.id, today.year, today.month)
        assert summary["credit_note_count"] >= 1
        assert summary["credit_taxable"] > 0
        assert summary["net_taxable"] < summary["taxable"]

        g3 = report_service.gstr3b_summary(retail.id, today.year, today.month)
        assert g3["net_outward_taxable"] == summary["net_taxable"]


def test_warehouse_transfer(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        whs = inventory_service.warehouses(dist.id)
        assert len(whs) >= 2
        from_wh = next(w for w in whs if w.code == "WH01")
        to_wh = next(w for w in whs if w.code == "WH02")

        batches = inventory_service.warehouse_batches(from_wh.id)
        assert batches
        b = batches[0]
        qty = Decimal("3")
        before_from = inventory_service.stock_on_hand(b["item_id"], from_wh.id)
        before_to = inventory_service.stock_on_hand(b["item_id"], to_wh.id)

        xfer = inventory_service.transfer_warehouse_stock(
            dist,
            from_wh,
            to_wh,
            [{
                "item_id": b["item_id"],
                "batch_no": b["batch_no"],
                "expiry": b["expiry"],
                "mrp": b["mrp"],
                "ptr": b["ptr"],
                "cost_rate": b["cost_rate"],
                "qty": qty,
            }],
            note="Test transfer",
        )
        db.session.commit()

        assert xfer.number.startswith("WT")
        assert inventory_service.stock_on_hand(b["item_id"], from_wh.id) == before_from - qty
        assert inventory_service.stock_on_hand(b["item_id"], to_wh.id) == before_to + qty


def test_barcode_lookup_for_purchase(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/api/items/barcode/890101001001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["code"] == "PCM500"
        assert data["rate"] > 0
        assert "ptr" in data
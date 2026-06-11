from datetime import date
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Organization
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import reports as report_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_reports_hub_slow_moving_no_crash(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        rows = report_service.slow_moving(dist.id)
        assert isinstance(rows, list)


def test_gstr2_includes_purchases(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        today = date.today()
        summary = report_service.gstr2_summary(dist.id, today.year, today.month)
        assert summary["purchase_count"] >= 1
        assert summary["taxable"] > 0


def test_distributor_gstr1_aggregation(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        today = date.today()
        summary = report_service.distributor_gstr1_summary(dist.id, today.year, today.month)
        assert summary["facility_count"] == 2
        assert len(summary["invoices"]) >= 1


def test_transfer_challan_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})

        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        whs = inventory_service.warehouses(dist.id)
        from_wh = next(w for w in whs if w.code == "WH01")
        to_wh = next(w for w in whs if w.code == "WH02")
        b = inventory_service.warehouse_batches(from_wh.id)[0]

        xfer = inventory_service.transfer_warehouse_stock(
            dist, from_wh, to_wh,
            [{"item_id": b["item_id"], "batch_no": b["batch_no"], "expiry": b["expiry"],
              "mrp": b["mrp"], "ptr": b["ptr"], "cost_rate": b["cost_rate"], "qty": Decimal("1")}],
        )
        db.session.commit()

        resp = client.get(f"/inventory/transfer/{xfer.id}/challan")
        assert resp.status_code == 200
        assert b"Internal Stock Transfer" in resp.data
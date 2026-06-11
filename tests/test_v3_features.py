from datetime import date, timedelta
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, Organization, Supplier
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import purchase as purchase_service
from pharmaconnect.services import returns as return_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_multi_warehouse_and_targeted_purchase(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        whs = inventory_service.warehouses(dist.id)
        assert len(whs) >= 2

        wh02 = next(w for w in whs if w.code == "WH02")
        supplier = Supplier.query.filter_by(org_id=dist.id).first()
        item_id = 1

        purchase_service.create_purchase(
            dist,
            supplier,
            [{
                "item_id": item_id,
                "batch_no": "MW-TEST-01",
                "expiry": date.today() + timedelta(days=400),
                "qty": Decimal("12"),
                "rate": Decimal("20"),
            }],
            invoice_no="MW-TEST",
            warehouse_id=wh02.id,
        )
        db.session.commit()

        assert inventory_service.stock_on_hand(item_id, wh02.id) >= Decimal("12")
        rows = purchase_service.batch_purchase_history(dist.id, batch_no="MW-TEST")
        assert rows
        assert rows[0]["warehouse"] == wh02.name


def test_sale_return_credit_note_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})

        bill = Bill.query.filter_by(facility_id=Organization.query.filter_by(code="RTL01").first().id).first()
        line = bill.lines[0]
        sr = return_service.create_sale_return(
            bill,
            [{"bill_line_id": line.id, "qty": Decimal("1")}],
            reason="Credit note test",
        )
        db.session.commit()

        resp = client.get(f"/returns/{sr.id}/credit-note")
        assert resp.status_code == 200
        assert b"Credit Note" in resp.data
        assert sr.number.encode() in resp.data


def test_purchase_return_debit_note_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})

        from pharmaconnect.models import PurchaseBill

        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        history = purchase_service.batch_purchase_history(dist.id, batch_no="WH-PCM500")
        assert history
        purchase_bill = PurchaseBill.query.filter_by(number=history[0]["purchase_number"]).first()
        line = purchase_bill.lines[0]

        pr = purchase_service.create_purchase_return(
            dist,
            purchase_bill,
            [{"purchase_line_id": line.id, "qty": Decimal("2")}],
            reason="Debit note test",
        )
        db.session.commit()

        resp = client.get(f"/purchase/return/{pr.id}/credit-note")
        assert resp.status_code == 200
        assert b"Debit Note" in resp.data
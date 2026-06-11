import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import ConsignmentBatch, Organization, RetailCustomer, Supplier
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import purchase as purchase_service
from pharmaconnect.services import reports as report_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule


def test_sale_register_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/reports/sale-register")
        assert resp.status_code == 200
        assert b"Sale Register" in resp.data


def test_purchase_register_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/reports/purchase-register")
        assert resp.status_code == 200
        assert b"Purchase Register" in resp.data
        rows = report_service.purchase_register(
            Organization.query.filter_by(kind="DISTRIBUTOR").first().id, days=30
        )
        assert any(r["type"] == "PURCHASE" for r in rows)


def test_outstanding_report_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/reports/outstanding")
        assert resp.status_code == 200
        assert b"Outstanding Report" in resp.data


def test_schemes_routes(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/schemes/")
        assert resp.status_code == 200
        assert b"Monsoon 5% Off" in resp.data

        resp = client.get("/schemes/new")
        assert resp.status_code == 200
        resp = client.post(
            "/schemes/new",
            data={
                "name": "Test Flat Off",
                "kind": "FLAT",
                "value": "10",
                "item_id": "1",
                "min_qty": "1",
                "free_qty": "0",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Test Flat Off" in resp.data


def test_patients_routes(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/patients/")
        assert resp.status_code == 200
        assert b"Ravi Kumar" in resp.data

        resp = client.post(
            "/patients/new",
            data={"name": "Test Patient", "uhid": "UHID-9999", "ward": "OPD"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Test Patient" in resp.data


def test_supplier_payment(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        supplier = Supplier.query.filter_by(org_id=dist.id).first()
        before = Decimal(str(supplier.outstanding))
        assert before > 0

        purchase_service.record_supplier_payment(dist.id, supplier.id, Decimal("100"), note="Test pay")
        db.session.commit()
        assert Decimal(str(supplier.outstanding)) == before - Decimal("100")

        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.post(
            "/purchase/suppliers",
            data={"supplier_id": supplier.id, "amount": "50", "note": "UI pay"},
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Supplier payment recorded" in resp.data


def test_credit_limit_blocks_sale(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        rc = RetailCustomer.query.filter_by(facility_id=fac.id).first()
        rc.outstanding = Decimal("4900")
        rc.credit_limit = Decimal("5000")
        db.session.commit()

        with pytest.raises(ValueError, match="Credit limit exceeded"):
            billing_service.create_bill(
                fac,
                "RETAIL",
                [{"item_id": 1, "qty": Decimal("5"), "rate": Decimal("35")}],
                retail_customer_id=rc.id,
                payment_mode="CREDIT",
            )


def test_fefo_blocks_expired_batch(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        batches = ConsignmentBatch.query.filter_by(facility_id=fac.id, item_id=1).all()
        for b in batches:
            b.qty_on_hand = Decimal("0")
        expired = ConsignmentBatch(
            distributor_id=fac.parent_id,
            facility_id=fac.id,
            item_id=1,
            batch_no="EXP-OLD",
            expiry=date.today() - timedelta(days=30),
            mrp=Decimal("35"),
            ptr=Decimal("28"),
            cost_rate=Decimal("24"),
            qty_on_hand=Decimal("50"),
        )
        db.session.add(expired)
        db.session.commit()

        with pytest.raises(ValueError, match="Insufficient stock"):
            billing_service.create_bill(
                fac,
                "RETAIL",
                [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
            )


def test_write_off_expired_batch(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        batch = ConsignmentBatch(
            distributor_id=fac.parent_id,
            facility_id=fac.id,
            item_id=2,
            batch_no="EXP-WO",
            expiry=date.today() - timedelta(days=10),
            mrp=Decimal("120"),
            ptr=Decimal("95"),
            cost_rate=Decimal("80"),
            qty_on_hand=Decimal("12"),
        )
        db.session.add(batch)
        db.session.commit()

        inventory_service.write_off_batch(batch, Decimal("5"), reason="Expired")
        db.session.commit()
        assert Decimal(str(batch.qty_on_hand)) == Decimal("7")

        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/inventory/expired")
        assert resp.status_code == 200
        assert b"EXP-WO" in resp.data


def test_bill_whatsapp_and_hsn(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
        )
        db.session.commit()

        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get(f"/billing/{bill.id}")
        assert resp.status_code == 200
        assert b"Share on WhatsApp" in resp.data
        assert b"wa.me" in resp.data
        assert b"3004" in resp.data
        assert b"HSN" in resp.data


def test_item_ledger_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/reports/item-ledger?item_id=1&days=90")
        assert resp.status_code == 200
        assert b"Item Stock Ledger" in resp.data

        fac = Organization.query.filter_by(code="RTL01").first()
        rows = report_service.item_ledger(fac.id, 1, days=90)
        assert isinstance(rows, list)
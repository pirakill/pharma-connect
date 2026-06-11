import json
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Organization
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import einvoice as einvoice_service
from pharmaconnect.services import reports as report_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_payment_ref_on_upi_bill(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
            payment_mode="UPI",
            payment_ref="UPI123456789",
        )
        db.session.commit()
        assert bill.payment_ref == "UPI123456789"
        assert bill.payment_mode == "UPI"


def test_payment_register(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("2"), "rate": Decimal("35")}],
            payment_mode="CARD",
            payment_ref="CARD-4242",
        )
        db.session.commit()
        rows = report_service.payment_register(fac.id, days=30)
        assert any(r["ref"] == "CARD-4242" for r in rows)


def test_network_summary(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        data = report_service.network_summary(dist.id, days=30)
        assert len(data["branches"]) >= 2
        assert data["totals"]["sales"] > 0


def test_einvoice_export(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
        )
        db.session.commit()
        payload = einvoice_service.einvoice_payload(bill)
        assert payload["Version"] == "1.1"
        assert payload["DocDtls"]["No"] == bill.number
        assert len(payload["ItemList"]) >= 1

        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get(f"/billing/{bill.id}/einvoice-export")
        assert resp.status_code == 200
        parsed = json.loads(resp.data)
        assert parsed["ValDtls"]["TotInvVal"] == float(bill.grand_total)


def test_network_dashboard_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/reports/network")
        assert resp.status_code == 200
        assert b"Multi-Branch Network Dashboard" in resp.data


def test_payment_register_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/reports/payments")
        assert resp.status_code == 200
        assert b"Digital Payment Register" in resp.data


def test_barcode_labels_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/items/labels")
        assert resp.status_code == 200
        assert b"890101001001" in resp.data
        assert b"JsBarcode" in resp.data


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
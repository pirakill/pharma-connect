import json
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Organization, PurchaseBill
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import accounting as accounting_service
from pharmaconnect.services import gst_export as gst_export_service
from pharmaconnect.services import invoice_qr
from pharmaconnect.services import purchase as purchase_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_purchase_return_challan_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        pb = PurchaseBill.query.filter_by(org_id=dist.id).first()
        line = pb.lines[0]
        pr = purchase_service.create_purchase_return(
            dist, pb, [{"purchase_line_id": line.id, "qty": Decimal("3")}], reason="Challan test"
        )
        db.session.commit()

        resp = client.get(f"/purchase/return/{pr.id}/challan")
        assert resp.status_code == 200
        assert b"Purchase Return Challan" in resp.data
        assert pr.number.encode() in resp.data


def test_purchase_returns_list_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/purchase/returns")
        assert resp.status_code == 200
        assert b"Purchase Returns" in resp.data


def test_debit_note_has_qr(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        pb = PurchaseBill.query.filter_by(org_id=dist.id).first()
        pr = purchase_service.create_purchase_return(
            dist, pb, [{"purchase_line_id": pb.lines[0].id, "qty": Decimal("2")}]
        )
        db.session.commit()
        payload = invoice_qr.debit_note_qr_payload(pr)
        parsed = json.loads(payload)
        assert parsed["typ"] == "DBN"
        assert parsed["doc_no"] == pr.number

        resp = client.get(f"/purchase/return/{pr.id}/credit-note")
        assert resp.status_code == 200
        assert b"invoice-qr" in resp.data


def test_create_institutional_party(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="HSP01").first()
        before = len(accounting_service.list_parties(fac.id))
        accounting_service.create_party(fac.id, "Test Corp", "36TEST001E1Z5")
        db.session.commit()
        assert len(accounting_service.list_parties(fac.id)) == before + 1

        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/accounting/parties")
        assert resp.status_code == 200
        assert b"Test Corp" in resp.data


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule


def test_gstr1_portal_json_structure(app):
    with app.app_context():
        from datetime import date

        retail = Organization.query.filter_by(code="RTL01").first()
        today = date.today()
        payload = gst_export_service.export_gstr1_portal_json(retail, today.year, today.month)
        assert payload["version"] == "GST2.0"
        assert payload["fp"] == f"{today.month:02d}{today.year}"
        assert "b2b" in payload
        assert "b2cs" in payload
        assert "cdnr" in payload

        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get(f"/reports/gstr1/portal-export?year={today.year}&month={today.month}")
        assert resp.status_code == 200
        assert "GSTR1_PORTAL" in resp.headers.get("Content-Disposition", "")
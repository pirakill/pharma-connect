import json
from datetime import date
from pathlib import Path

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, Organization
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services.gst_export import export_gstr1_json, export_gstr2_json, export_gstr3b_json
from pharmaconnect.services.invoice_qr import invoice_qr_payload


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_gst_json_export_structure(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        retail = Organization.query.filter_by(code="RTL01").first()
        today = date.today()

        g1 = export_gstr1_json(retail, today.year, today.month)
        assert g1["report"] == "GSTR-1"
        assert g1["period"] == f"{today.year}-{today.month:02d}"
        assert "invoices" in g1
        assert "credit_notes" in g1

        g1n = export_gstr1_json(dist, today.year, today.month, network=True)
        assert g1n["scope"] == "distributor_network"

        g2 = export_gstr2_json(dist, today.year, today.month)
        assert g2["report"] == "GSTR-2"
        assert g2["summary"]["purchase_count"] >= 1

        g3 = export_gstr3b_json(retail, today.year, today.month)
        assert g3["report"] == "GSTR-3B"
        assert "net_total_tax" in g3["summary"]


def test_gst_export_download_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        today = date.today()
        resp = client.get(f"/reports/gstr1/export?year={today.year}&month={today.month}")
        assert resp.status_code == 200
        assert resp.mimetype == "application/json"
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        data = json.loads(resp.data)
        assert data["report"] == "GSTR-1"


def test_invoice_qr_payload(app):
    with app.app_context():
        bill = Bill.query.first()
        payload = invoice_qr_payload(bill)
        parsed = json.loads(payload)
        assert parsed["inv_no"] == bill.number
        assert parsed["seller_gstin"] == bill.facility.gstin
        assert parsed["val"] == float(bill.grand_total)


def test_bill_view_has_qr(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        bill = Bill.query.filter_by(facility_id=Organization.query.filter_by(code="RTL01").first().id).first()
        resp = client.get(f"/billing/{bill.id}")
        assert resp.status_code == 200
        assert b"invoice-qr" in resp.data
        assert b"qrcode.min.js" in resp.data


def test_pwa_icons_exist():
    static = Path(__file__).resolve().parents[1] / "pharmaconnect" / "static"
    assert (static / "icon-192.png").exists()
    assert (static / "icon-512.png").exists()
    assert (static / "icon-192.png").stat().st_size > 100
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import ConsignmentBatch, Organization, RetailCustomer, Supplier
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import eway as eway_service
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


def test_margin_report_uses_real_cogs(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        data = report_service.margin_report(fac.id, days=30)
        assert "revenue" in data
        assert "cogs" in data
        assert data["gross_profit"] == data["revenue"] - data["cogs"]
        pnl = report_service.pnl_report(fac.id, days=30)
        assert pnl["gross_profit"] == pnl["revenue_taxable"] - pnl["cogs"]


def test_loyalty_earn_and_redeem(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        rc = RetailCustomer.query.filter_by(facility_id=fac.id).first()
        rc.loyalty_points = 50
        db.session.commit()

        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("10"), "rate": Decimal("35")}],
            retail_customer_id=rc.id,
            payment_mode="CASH",
            loyalty_redeem=20,
        )
        db.session.commit()
        assert bill.discount >= Decimal("20")
        assert rc.loyalty_points == 50 - 20 + int(bill.grand_total // 100)


def test_rack_assignment(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="HSP01").first()
        batch = ConsignmentBatch.query.filter_by(facility_id=fac.id).first()
        inventory_service.set_batch_rack(batch, "b3")
        db.session.commit()
        assert batch.rack == "B3"

        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/inventory/racks")
        assert resp.status_code == 200
        assert b"B3" in resp.data


def test_purchase_csv_import(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        supplier = Supplier.query.filter_by(org_id=dist.id).first()
        from pharmaconnect.models import Item, PurchaseBill

        item = Item.query.first()
        expiry = (date.today() + timedelta(days=400)).isoformat()
        csv_text = (
            "supplier_code,invoice_no,item_code,batch_no,expiry,qty,rate,mrp,warehouse_code,rack\n"
            f"{supplier.code},CSV-TEST-001,{item.code},CSV-BATCH-01,{expiry},25,20,35,WH01,C2\n"
        )
        before = PurchaseBill.query.filter_by(org_id=dist.id).count()
        result = purchase_service.import_purchase_csv(dist, csv_text)
        db.session.commit()
        assert result["created"] == 1
        assert PurchaseBill.query.filter_by(org_id=dist.id).count() == before + 1
        batch = ConsignmentBatch.query.filter_by(batch_no="CSV-BATCH-01").first()
        assert batch is not None
        assert batch.rack == "C2"


def test_eway_stub(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
            customer_name="Big Corp",
            payment_mode="CASH",
        )
        bill.grand_total = Decimal("55000")
        db.session.commit()
        assert eway_service.eway_required(bill)
        payload = eway_service.eway_payload(bill)
        assert payload["version"] == "EWB1.0"
        assert payload["doc_no"] == bill.number

        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get(f"/billing/{bill.id}/eway-export")
        assert resp.status_code == 200
        parsed = json.loads(resp.data)
        assert parsed["total_value"] == float(bill.grand_total)


def test_margin_report_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/reports/margin")
        assert resp.status_code == 200
        assert b"Gross Margin Report" in resp.data


def test_purchase_import_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/purchase/import")
        assert resp.status_code == 200
        assert b"Import Purchase Bills" in resp.data


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
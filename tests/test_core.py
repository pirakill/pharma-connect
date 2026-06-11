from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import ConsignmentSettlement, Organization, PartyLedger
from pharmaconnect.seed import DISTRIBUTOR_NAME, seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import gst as gst_service
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import reports as report_service
from pharmaconnect.services import settlement as settlement_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_gst_intra_state(app):
    parts = gst_service.split_gst(Decimal("100"), Decimal("12"), "36", "36")
    assert parts["cgst"] == Decimal("6.00")
    assert parts["sgst"] == Decimal("6.00")
    assert parts["igst"] == Decimal("0")


def test_gst_inter_state(app):
    parts = gst_service.split_gst(Decimal("100"), Decimal("12"), "36", "27")
    assert parts["igst"] == Decimal("12.00")


def test_infivita_seed(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        assert dist.name == "Infivita Pharmaceuticals"
        assert dist.gstin == "36AHEPD1696A4Z0"
        assert dist.state_code == "36"
        assert len(inventory_service.customer_facilities(dist.id)) == 2
        assert inventory_service.get_or_create_warehouse(dist.id).kind == "WAREHOUSE"


def test_consignment_and_live_stock(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        fac = Organization.query.filter_by(kind="RETAIL").first()
        snapshot = inventory_service.live_stock_snapshot(distributor_id=dist.id)
        assert any(s["facility_id"] == fac.id for s in snapshot)
        summary = inventory_service.facility_stock_summary(dist.id)
        assert len(summary) == 2


def test_billing_reduces_stock(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        item_id = 1
        before = inventory_service.stock_on_hand(item_id, fac.id)
        bill = billing_service.create_bill(
            fac, "RETAIL",
            [{"item_id": item_id, "qty": Decimal("5"), "rate": Decimal("35")}],
        )
        db.session.commit()
        after = inventory_service.stock_on_hand(item_id, fac.id)
        assert after == before - Decimal("5")
        assert bill.grand_total > 0


def test_consignment_settlement_on_sale(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        before_payable = settlement_service.facility_payable_to_distributor(fac.id, dist.name)
        billing_service.create_bill(
            fac, "RETAIL",
            [{"item_id": 1, "qty": Decimal("3"), "rate": Decimal("35")}],
        )
        db.session.commit()
        after_payable = settlement_service.facility_payable_to_distributor(fac.id, dist.name)
        assert after_payable == before_payable + Decimal("84.00")  # 3 x PTR 28
        assert ConsignmentSettlement.query.filter_by(facility_id=fac.id, status="OPEN").count() >= 1


def test_settlement_payment(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        payable = settlement_service.facility_payable_to_distributor(fac.id, dist.name)
        assert payable > 0
        settlement_service.record_settlement_payment(fac.id, dist.id, Decimal("50.00"))
        db.session.commit()
        assert settlement_service.facility_payable_to_distributor(fac.id, dist.name) == payable - Decimal("50.00")


def test_stock_limits_and_restock_alerts(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        retail = Organization.query.filter_by(code="RTL01").first()
        item = 1
        inventory_service.upsert_stock_limit(retail.id, item, Decimal("100"), Decimal("200"))
        db.session.commit()
        alerts = inventory_service.restock_alerts(dist.id, facility_id=retail.id)
        pcm_alerts = [a for a in alerts if a["item_id"] == item]
        assert pcm_alerts
        assert pcm_alerts[0]["qty"] <= pcm_alerts[0]["min_qty"]
        assert pcm_alerts[0]["suggest_qty"] > 0

        enriched = inventory_service.stock_with_limits(facility_id=retail.id)
        pcm = next(r for r in enriched if r["item_id"] == item)
        assert pcm["min_qty"] == 100
        assert pcm["status"] == "LOW"


def test_gstr1(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        from datetime import date
        today = date.today()
        summary = report_service.gstr1_summary(fac.id, today.year, today.month)
        assert summary["total"] >= 0
        assert "invoices" in summary
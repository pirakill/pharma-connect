from datetime import date, timedelta
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Item, Organization, Supplier
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import purchase as purchase_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_distributor_purchase_goes_to_warehouse(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        warehouse = inventory_service.get_or_create_warehouse(dist.id)
        item = Item.query.filter_by(code="PCM500").first()
        supplier = Supplier.query.filter_by(org_id=dist.id).first()
        before = inventory_service.stock_on_hand(item.id, warehouse.id)

        purchase_service.create_purchase(
            dist,
            supplier,
            [{
                "item_id": item.id,
                "batch_no": "PB-TEST-01",
                "expiry": date.today() + timedelta(days=400),
                "qty": Decimal("25"),
                "rate": Decimal("20"),
                "mrp": item.mrp,
            }],
            invoice_no="INV-TEST",
        )
        db.session.commit()

        after = inventory_service.stock_on_hand(item.id, warehouse.id)
        assert after == before + Decimal("25")


def test_restock_ship_from_warehouse(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        retail = Organization.query.filter_by(code="RTL01").first()
        warehouse = inventory_service.get_or_create_warehouse(dist.id)
        item = Item.query.filter_by(code="PCM500").first()

        wh_before = inventory_service.stock_on_hand(item.id, warehouse.id)
        fac_before = inventory_service.stock_on_hand(item.id, retail.id)

        lines = inventory_service.build_restock_shipment_lines(dist.id, retail.id)
        pcm_lines = [ln for ln in lines if ln["item_id"] == item.id]
        assert pcm_lines, "Expected restock line for low PCM500 at retail"

        ship_qty = sum(Decimal(str(ln["qty"])) for ln in pcm_lines)
        inventory_service.receive_consignment(
            dist, retail, pcm_lines, note="Test restock", from_warehouse=True
        )
        db.session.commit()

        assert inventory_service.stock_on_hand(item.id, warehouse.id) == wh_before - ship_qty
        assert inventory_service.stock_on_hand(item.id, retail.id) == fac_before + ship_qty
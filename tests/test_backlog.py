from datetime import date, timedelta
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, ConsignmentSettlement, Organization, PurchaseBill, Supplier
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import inventory as inventory_service
from pharmaconnect.services import purchase as purchase_service
from pharmaconnect.services import returns as return_service
from pharmaconnect.services import settlement as settlement_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_sale_return_reverses_settlement(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        before_payable = settlement_service.facility_payable_to_distributor(fac.id, dist.name)

        bill = Bill.query.filter_by(facility_id=fac.id).order_by(Bill.id.desc()).first()
        line = bill.lines[0]
        return_qty = Decimal("2")

        return_service.create_sale_return(
            bill,
            [{"bill_line_id": line.id, "qty": return_qty}],
            reason="Test return",
        )
        db.session.commit()

        after_payable = settlement_service.facility_payable_to_distributor(fac.id, dist.name)
        expected_reversal = (return_qty * Decimal(str(line.batch.ptr))).quantize(Decimal("0.01"))
        assert after_payable == before_payable - expected_reversal

        cs = ConsignmentSettlement.query.filter_by(bill_line_id=line.id).first()
        assert cs is not None
        assert Decimal(str(cs.amount)) < Decimal(str(line.qty)) * Decimal(str(line.batch.ptr))


def test_consignment_challan_route(app):
    with app.app_context():
        client = app.test_client()
        with client.session_transaction() as sess:
            pass
        # login as distributor
        resp = client.post("/auth/login", data={"username": "distributor", "password": "admin"}, follow_redirects=True)
        assert resp.status_code == 200

        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        retail = Organization.query.filter_by(code="RTL01").first()
        shipment = inventory_service.receive_consignment(
            dist,
            retail,
            [{
                "item_id": 1,
                "batch_no": "CH-TEST",
                "expiry": date.today() + timedelta(days=300),
                "mrp": Decimal("35"),
                "ptr": Decimal("28"),
                "cost_rate": Decimal("23.80"),
                "qty": Decimal("10"),
            }],
            note="Challan test",
        )
        db.session.commit()

        resp = client.get(f"/inventory/consignment/{shipment.id}/challan")
        assert resp.status_code == 200
        assert shipment.number.encode() in resp.data
        assert b"Delivery Challan" in resp.data


def test_purchase_return_reduces_stock_and_supplier(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        warehouse = inventory_service.get_or_create_warehouse(dist.id)
        supplier = Supplier.query.filter_by(org_id=dist.id).first()
        pb = PurchaseBill.query.filter_by(org_id=dist.id).first()
        line = pb.lines[0]

        wh_before = inventory_service.stock_on_hand(line.item_id, warehouse.id)
        sup_before = Decimal(str(supplier.outstanding or 0))

        pr = purchase_service.create_purchase_return(
            dist,
            pb,
            [{"purchase_line_id": line.id, "qty": Decimal("5")}],
            reason="Excess",
        )
        db.session.commit()

        assert inventory_service.stock_on_hand(line.item_id, warehouse.id) == wh_before - Decimal("5")
        assert Decimal(str(supplier.outstanding)) == sup_before - pr.grand_total
        assert pr.number.startswith("PR")
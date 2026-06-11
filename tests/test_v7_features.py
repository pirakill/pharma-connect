import csv
import io
import json
from datetime import date
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, Organization, PartyLedger
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import gst_export as gst_export_service
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


def test_gst_csv_export(app):
    with app.app_context():
        retail = Organization.query.filter_by(code="RTL01").first()
        today = date.today()
        csv_text = gst_export_service.export_gstr1_csv(retail, today.year, today.month)
        rows = list(csv.reader(io.StringIO(csv_text)))
        assert rows[0] == ["report", "GSTR-1"]
        assert any(r and r[0] == "doc_type" for r in rows)

        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get(f"/reports/gstr1/export?format=csv&year={today.year}&month={today.month}")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert ".csv" in resp.headers.get("Content-Disposition", "")


def test_gstr1_export_credit_notes_only(app):
    with app.app_context():
        retail = Organization.query.filter_by(code="RTL01").first()
        today = date.today()
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get(
            f"/reports/gstr1/export?year={today.year}&month={today.month}&sections=credit_notes"
        )
        data = json.loads(resp.data)
        assert data["invoices"] == []
        assert "credit_notes" in data


def test_paid_settlement_return_reversal(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        payable_before = settlement_service.facility_payable_to_distributor(fac.id, dist.name)
        assert payable_before > 0

        settlement_service.record_settlement_payment(fac.id, dist.id, payable_before)
        db.session.commit()
        assert settlement_service.facility_payable_to_distributor(fac.id, dist.name) == Decimal("0")

        bill = (
            Bill.query.filter_by(facility_id=fac.id, bill_type="RETAIL")
            .order_by(Bill.id.desc())
            .first()
        )
        line = bill.lines[0]
        return_qty = Decimal("1")
        return_service.create_sale_return(
            bill,
            [{"bill_line_id": line.id, "qty": return_qty}],
            reason="Paid settlement return test",
        )
        db.session.commit()

        expected_credit = (return_qty * Decimal(str(line.batch.ptr))).quantize(Decimal("0.01"))
        payable_after = settlement_service.facility_payable_to_distributor(fac.id, dist.name)
        assert payable_after == -expected_credit


def test_institutional_credit_bill_and_return(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        party = PartyLedger.query.filter_by(
            org_id=fac.id, party_name="Telangana State Medical Corp"
        ).first()
        assert party is not None

        inst_bill = Bill.query.filter_by(
            facility_id=fac.id, bill_type="INSTITUTIONAL", order_ref="PO-TGMC-2026-0142"
        ).first()
        assert inst_bill is not None
        assert inst_bill.payment_mode == "CREDIT"
        assert Decimal(str(party.outstanding or 0)) >= inst_bill.grand_total

        before = Decimal(str(party.outstanding))
        return_service.create_sale_return(
            inst_bill,
            [{"bill_line_id": inst_bill.lines[0].id, "qty": Decimal("5")}],
            reason="Institutional partial return",
        )
        db.session.commit()
        db.session.refresh(party)
        assert Decimal(str(party.outstanding)) < before


def test_distributor_reports_hub_kpis(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/reports/")
        assert resp.status_code == 200
        assert b"30-Day Network Sales" in resp.data
        assert b"Consignment Value" in resp.data
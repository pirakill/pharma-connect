"""v19: credit management by days of credit."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, Organization, PartyLedger, RetailCustomer
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import customers as customer_service
from pharmaconnect.services.credit import credit_aging_report


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def _retail_facility():
    return Organization.query.filter_by(code="RTL01").first()


def _retail_customer():
    fac = _retail_facility()
    return RetailCustomer.query.filter_by(facility_id=fac.id).first()


def test_credit_bill_sets_due_date_and_balance(app):
    with app.app_context():
        fac = _retail_facility()
        rc = _retail_customer()
        rc.credit_days = 15
        db.session.commit()

        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("100")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )
        db.session.commit()

        assert bill.due_date is not None
        assert bill.balance_due == bill.grand_total
        expected_due = bill.billed_on + timedelta(days=15)
        assert abs((bill.due_date - expected_due).total_seconds()) < 2


def test_overdue_blocks_new_credit_sale(app):
    with app.app_context():
        fac = _retail_facility()
        rc = _retail_customer()
        rc.credit_days = 7
        db.session.commit()

        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("50")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )
        bill.due_date = datetime.utcnow() - timedelta(days=3)
        bill.balance_due = bill.grand_total
        db.session.commit()

        with pytest.raises(ValueError, match="Overdue balance"):
            billing_service.create_bill(
                fac,
                "RETAIL",
                [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("10")}],
                retail_customer_id=rc.id,
                payment_mode="CREDIT",
            )


def test_customer_payment_clears_overdue(app):
    with app.app_context():
        fac = _retail_facility()
        rc = _retail_customer()
        rc.credit_days = 7
        db.session.commit()

        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("2"), "rate": Decimal("50")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )
        bill.due_date = datetime.utcnow() - timedelta(days=5)
        bill.balance_due = bill.grand_total
        db.session.commit()
        due_before = Decimal(str(rc.outstanding or 0))

        customer_service.record_payment(rc, due_before)
        db.session.commit()

        db.session.refresh(rc)
        db.session.refresh(bill)
        assert rc.outstanding == Decimal("0")
        assert bill.balance_due == Decimal("0")

        billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("25")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )


def test_institutional_party_credit_days(app):
    with app.app_context():
        fac = _retail_facility()
        party = PartyLedger.query.filter_by(party_name="Telangana State Medical Corp").first()
        assert party.credit_days == 45

        bill = billing_service.create_bill(
            fac,
            "INSTITUTIONAL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("200")}],
            customer_name=party.party_name,
            customer_gstin=party.party_gstin,
            payment_mode="CREDIT",
        )
        db.session.commit()
        assert bill.due_date is not None
        assert bill.balance_due == bill.grand_total


def test_credit_aging_report_buckets(app):
    with app.app_context():
        fac = _retail_facility()
        rc = _retail_customer()

        current = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("100")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )
        overdue = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("200")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )
        overdue.due_date = datetime.utcnow() - timedelta(days=15)
        db.session.commit()

        report = credit_aging_report(fac.id)
        assert report["total_open"] > 0
        assert report["buckets"]["current"] >= float(current.balance_due or 0)
        assert report["buckets"]["days_1_30"] >= float(overdue.balance_due or 0)
        assert len(report["rows"]) >= 2


def test_credit_aging_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail_admin", "password": "admin"})
        resp = client.get("/reports/credit-aging")
        assert resp.status_code == 200
        assert b"Credit Aging" in resp.data


def test_billing_context_includes_credit_days(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        rc = _retail_customer()
        resp = client.get(f"/api/customers/{rc.id}/billing-context")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "credit_days" in data
        assert data["credit_days"] == 30
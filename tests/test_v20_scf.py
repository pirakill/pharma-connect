"""v20: SCF mock — scoring, financing workflow, lender desk, webhook."""
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Bill, FinancingRequest, LenderPartner, Organization, RetailCustomer
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import scf as scf_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_seed_has_lenders_and_financing_request(app):
    with app.app_context():
        assert LenderPartner.query.filter_by(code="OXYZO").count() == 1
        assert FinancingRequest.query.count() >= 1


def test_credit_profile_scoring(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        rc = RetailCustomer.query.filter_by(facility_id=fac.id).first()
        profile = scf_service.score_retail_customer(rc)
        db.session.commit()
        assert 0 <= profile.score <= 100
        assert profile.tier in ("A", "B", "C", "D")
        assert profile.recommended_limit >= 0


def test_financing_request_flow(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        rc = RetailCustomer.query.filter_by(facility_id=fac.id).first()
        from pharmaconnect.services import billing as billing_service

        bill = billing_service.create_bill(
            fac,
            "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("100")}],
            retail_customer_id=rc.id,
            payment_mode="CREDIT",
        )
        db.session.commit()
        lender = LenderPartner.query.filter_by(code="OXYZO").first()
        req = scf_service.create_financing_request(fac.id, bill.id, lender.id, user_id=1)
        db.session.commit()
        assert req.status == "SUBMITTED"
        scf_service.review_request(req.id, approve=True)
        scf_service.disburse_request(req.id)
        db.session.commit()
        db.session.refresh(req)
        assert req.status == "DISBURSED"
        assert req.net_disbursement > 0


def test_lender_desk_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "lender1", "password": "admin"})
        resp = client.get("/scf/lender/")
        assert resp.status_code == 200
        assert b"Lender Desk" in resp.data


def test_scf_hub_for_facility_admin(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail_admin", "password": "admin"})
        resp = client.get("/scf/")
        assert resp.status_code == 200
        assert b"Supply Chain Finance" in resp.data


def test_credit_alerts_scan(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        alerts = scf_service.scan_credit_alerts(fac.id)
        db.session.commit()
        assert isinstance(alerts, list)


def test_lender_webhook_approve(app):
    with app.app_context():
        req = FinancingRequest.query.filter_by(status="SUBMITTED").first()
        scf_service.review_request(req.id, approve=True)
        db.session.commit()
        db.session.refresh(req)
        ref = req.lender_ref
        result = scf_service.process_lender_webhook(
            "OXYZO",
            {"action": "DISBURSE", "lender_ref": ref},
            "oxyzo-demo-secret",
        )
        db.session.commit()
        assert result["status"] == "DISBURSED"


def test_scf_webhook_api(app):
    with app.app_context():
        req = FinancingRequest.query.filter_by(status="SUBMITTED").first()
        scf_service.review_request(req.id, approve=True)
        db.session.commit()
        ref = req.lender_ref
        client = app.test_client()
        resp = client.post(
            "/api/scf/webhook/OXYZO",
            json={"action": "DISBURSE", "lender_ref": ref},
            headers={"X-Webhook-Secret": "oxyzo-demo-secret"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
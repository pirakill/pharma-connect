import hashlib
import json
from decimal import Decimal

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import AuditLog, Organization, SmsLog
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import audit as audit_service
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import integrations as integration_service
from pharmaconnect.services import sms as sms_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_audit_log_on_bill(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        bill = billing_service.create_bill(
            fac, "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
        )
        audit_service.log_action(fac.id, "BILL_POST", user_id=1, entity_ref=bill.number)
        db.session.commit()
        logs = audit_service.recent_logs(fac.id)
        assert any(l.action == "BILL_POST" for l in logs)


def test_irn_generation(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        integration_service.update_settings(fac.id, {
            "irp_client_id": "test-client",
            "irp_client_secret": "secret",
            "irp_enabled": True,
        })
        bill = billing_service.create_bill(
            fac, "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
        )
        db.session.commit()
        irn = integration_service.generate_irn(bill)
        db.session.commit()
        assert len(irn) == 32
        assert bill.irn == irn


def test_sms_stub(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        integration_service.update_settings(fac.id, {"sms_enabled": True, "sms_api_key": "key"})
        sms_service.send_sms(fac.id, "9876543210", "Test message", alert_type="TEST")
        db.session.commit()
        row = SmsLog.query.filter_by(org_id=fac.id).first()
        assert row.status == "SENT_STUB"


def test_expiry_sms_alerts(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        integration_service.update_settings(dist.id, {"sms_enabled": True, "sms_api_key": "k", "alert_expiry_days": 365})
        n = sms_service.run_expiry_alerts(dist.id)
        db.session.commit()
        assert n >= 1


def test_razorpay_verify_stub(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        secret = "rzp_test_secret"
        integration_service.update_settings(fac.id, {
            "razorpay_enabled": True,
            "razorpay_key_secret": secret,
            "razorpay_key_id": "rzp_test",
        })
        db.session.commit()
        payment_id = "pay_123"
        expected = hashlib.sha256(f"{payment_id}|{secret}".encode()).hexdigest()[:16]
        assert integration_service.verify_razorpay_payment(fac.id, payment_id, expected)


def test_integrations_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/settings/integrations")
        assert resp.status_code == 200
        assert b"API Integrations" in resp.data


def test_audit_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/settings/audit")
        assert resp.status_code == 200
        assert b"Audit Trail" in resp.data


def test_login_creates_audit(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        fac = Organization.query.filter_by(code="RTL01").first()
        assert AuditLog.query.filter_by(org_id=fac.id, action="LOGIN").count() >= 1


def test_payment_verify_api(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="HSP01").first()
        secret = "rzp_live_secret"
        integration_service.update_settings(fac.id, {
            "razorpay_enabled": True,
            "razorpay_key_secret": secret,
        })
        db.session.commit()
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        sig = hashlib.sha256(f"pay_xyz|{secret}".encode()).hexdigest()[:16]
        resp = client.post(
            "/api/payments/verify",
            data=json.dumps({"gateway": "razorpay", "payment_id": "pay_xyz", "signature": sig}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.get_json()["verified"] is True


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
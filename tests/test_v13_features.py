import json
from datetime import datetime

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Organization, SmsLog
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import alerts as alerts_service
from pharmaconnect.services import integrations as integration_service
from pharmaconnect.services import permissions as perm_service


@pytest.fixture
def app():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
        "CRON_SECRET": "test-cron-secret",
    })
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_cashier_lacks_purchases_permission(app):
    with app.app_context():
        from pharmaconnect.models import User
        cashier = User.query.filter_by(username="retail1").first()
        assert perm_service.role_code(cashier) == "CASHIER"
        assert not perm_service.has_permission(cashier, "purchases")
        assert perm_service.has_permission(cashier, "billing")


def test_facility_admin_has_integrations(app):
    with app.app_context():
        from pharmaconnect.models import User
        admin = User.query.filter_by(username="hospital1").first()
        assert perm_service.has_permission(admin, "integrations")
        assert perm_service.has_permission(admin, "purchases")


def test_distributor_admin_full_access(app):
    with app.app_context():
        from pharmaconnect.models import User
        dist = User.query.filter_by(username="distributor").first()
        assert perm_service.has_permission(dist, "items_master")
        assert perm_service.has_permission(dist, "purchases")


def test_cashier_blocked_from_purchases(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/purchase/", follow_redirects=True)
        assert resp.status_code == 200
        assert b"do not have permission" in resp.data


def test_cashier_blocked_from_integrations(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/settings/integrations", follow_redirects=True)
        assert resp.status_code == 200
        assert b"do not have permission" in resp.data


def test_cashier_can_bill(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/billing/new")
        assert resp.status_code == 200


def test_distributor_can_open_new_bill(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/billing/new", follow_redirects=True)
        assert resp.status_code == 200
        assert b"Bill at Facility" in resp.data
        assert b"Secunderabad" in resp.data


def test_distributor_can_post_bill(app):
    with app.app_context():
        from pharmaconnect.models import Bill, Item, Organization

        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        fac = Organization.query.filter_by(code="RTL01").first()
        item = Item.query.filter_by(code="PCM500").first()
        before = Bill.query.filter_by(facility_id=fac.id).count()
        lines = json.dumps([
            {"item_id": item.id, "qty": 1, "rate": float(item.mrp), "discount": 0},
        ])
        resp = client.post(
            "/billing/new",
            data={
                "facility_id": fac.id,
                "bill_type": "RETAIL",
                "customer_name": "Distributor Test",
                "payment_mode": "CASH",
                "lines_json": lines,
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert Bill.query.filter_by(facility_id=fac.id).count() == before + 1


def test_scheduled_alerts_respects_hour(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        integration_service.update_settings(dist.id, {
            "sms_enabled": True,
            "sms_api_key": "k",
            "alert_schedule_enabled": True,
            "alert_schedule_hour": 7,
            "alert_expiry_days": 365,
        })
        db.session.commit()
        result = alerts_service.run_scheduled_alerts(hour=7)
        assert result["ran"] >= 1
        result_skip = alerts_service.run_scheduled_alerts(hour=8)
        assert result_skip["ran"] == 0


def test_scheduled_alerts_force(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        integration_service.update_settings(dist.id, {
            "sms_enabled": True,
            "sms_api_key": "k",
            "alert_schedule_enabled": False,
            "alert_expiry_days": 365,
        })
        db.session.commit()
        before = SmsLog.query.count()
        result = alerts_service.run_scheduled_alerts(force=True)
        assert result["ran"] >= 1
        assert SmsLog.query.count() > before


def test_cron_alerts_api(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        integration_service.update_settings(dist.id, {
            "sms_enabled": True,
            "sms_api_key": "k",
            "alert_schedule_enabled": True,
            "alert_schedule_hour": datetime.now().hour,
            "alert_expiry_days": 365,
        })
        db.session.commit()
        client = app.test_client()
        bad = client.post("/api/cron/alerts")
        assert bad.status_code == 401
        ok = client.post(
            "/api/cron/alerts?force=1",
            headers={"X-Cron-Secret": "test-cron-secret"},
        )
        assert ok.status_code == 200
        data = ok.get_json()
        assert data["ran"] >= 1


def test_run_alerts_cli(app):
    with app.app_context():
        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        integration_service.update_settings(dist.id, {
            "sms_enabled": True,
            "sms_api_key": "k",
            "alert_expiry_days": 365,
        })
        db.session.commit()
        runner = app.test_cli_runner()
        result = runner.invoke(args=["run-alerts", "--force"])
        assert result.exit_code == 0
        assert "distributor" in result.output.lower() or result.output.strip()


def test_schedule_settings_saved(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.post(
            "/settings/integrations",
            data={
                "sms_enabled": "1",
                "sms_api_key": "key",
                "alert_schedule_enabled": "1",
                "alert_schedule_hour": "11",
                "alert_low_stock": "1",
                "alert_expiry_days": "45",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        fac = Organization.query.filter_by(code="HSP01").first()
        settings = integration_service.get_settings(fac.id)
        assert settings.alert_schedule_enabled is True
        assert settings.alert_schedule_hour == 11


def test_wsgi_import():
    import wsgi
    assert wsgi.app is not None


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
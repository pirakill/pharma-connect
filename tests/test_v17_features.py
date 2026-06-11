from decimal import Decimal

import os
import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Organization
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import billing as billing_service
from pharmaconnect.services import reports as report_service


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_cashier_summary_counts_today_bills(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        billing_service.create_bill(
            fac, "RETAIL",
            [{"item_id": 1, "qty": Decimal("2"), "rate": Decimal("35")}],
            customer_name="Walk-in Test",
        )
        db.session.commit()
        summary = report_service.cashier_summary(fac.id)
        assert summary["bill_count"] >= 1
        assert summary["sales_today"] >= 70


def test_cashier_dashboard_route(app):
    with app.app_context():
        fac = Organization.query.filter_by(code="RTL01").first()
        billing_service.create_bill(
            fac, "RETAIL",
            [{"item_id": 1, "qty": Decimal("1"), "rate": Decimal("35")}],
        )
        db.session.commit()
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert b"Today" in resp.data
        assert b"New Bill" in resp.data
        assert b"Mobile POS" in resp.data
        assert b"30-Day Sales" not in resp.data


def test_facility_admin_gets_full_dashboard(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail_admin", "password": "admin"})
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert b"30-Day Sales" in resp.data


def test_ci_workflow_file():
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, ".github", "workflows", "ci.yml")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "pytest tests/" in content
    assert "docker build" in content
    assert "api/health" in content


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
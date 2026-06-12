import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import Organization, RetailCustomer
from pharmaconnect.seed import seed_if_empty


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_lender_dashboard_redirects_to_lender_hub(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "lender1", "password": "admin"})
        resp = client.get("/dashboard/", follow_redirects=False)
        assert resp.status_code == 302
        assert "/scf/lender" in resp.headers.get("Location", "")


def test_lender_not_treated_as_distributor(app):
    with app.app_context():
        from pharmaconnect.models import User

        lender = User.query.filter_by(username="lender1").first()
        assert lender.is_lender
        assert not lender.is_distributor


def test_cross_facility_customer_api_blocked(app):
    with app.app_context():
        retail = Organization.query.filter_by(code="RTL01").first()
        customer = RetailCustomer.query.filter_by(facility_id=retail.id).first()
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get(f"/api/customers/{customer.id}/billing-context")
        assert resp.status_code == 404


def test_distributor_network_outstanding(app):
    with app.app_context():
        from pharmaconnect.services import reports as report_service

        dist = Organization.query.filter_by(kind="DISTRIBUTOR").first()
        data = report_service.outstanding_report(dist.id)
        assert data["is_network"] is True
        assert "customers" in data
        assert "parties" in data


def test_distributor_scf_alerts_lists_network(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/scf/alerts")
        assert resp.status_code == 200


def test_distributor_can_manage_customers(app):
    with app.app_context():
        retail = Organization.query.filter_by(code="RTL01").first()
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get(f"/customers/?facility_id={retail.id}")
        assert resp.status_code == 200
        assert b"Add Customer" in resp.data
        resp = client.post(
            "/customers/new",
            data={
                "facility_id": retail.id,
                "name": "Network Walk-in Test",
                "phone": "9999999999",
                "credit_limit": "5000",
                "credit_days": "15",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Network Walk-in Test" in resp.data
        customer = RetailCustomer.query.filter_by(name="Network Walk-in Test").first()
        assert customer is not None
        assert customer.facility_id == retail.id


def test_distributor_customer_api_for_billing(app):
    with app.app_context():
        retail = Organization.query.filter_by(code="RTL01").first()
        customer = RetailCustomer.query.filter_by(facility_id=retail.id).first()
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get(f"/api/customers/{customer.id}/billing-context")
        assert resp.status_code == 200
        assert resp.get_json()["name"] == customer.name


def test_distributor_can_add_medicine(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "distributor", "password": "admin"})
        resp = client.get("/items/new")
        assert resp.status_code == 200
        resp = client.post(
            "/items/new",
            data={
                "code": "DIST01",
                "name": "Distributor Added Med",
                "pack": "1x10",
                "unit": "strip",
                "gst_rate": "12",
                "mrp": "99",
                "ptr": "75",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"DIST01" in resp.data


def test_lender_cannot_access_items_master(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "lender1", "password": "admin"})
        resp = client.get("/items/", follow_redirects=True)
        assert resp.status_code == 200
        assert b"do not have permission" in resp.data
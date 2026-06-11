import os
import tempfile

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import User
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import permissions as perm_service
from pharmaconnect.services import users as user_service


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


@pytest.fixture
def file_db_app(tmp_path):
    db_file = tmp_path / "pharma.db"
    uri = f"sqlite:///{db_file.as_posix()}"
    app = create_app({"SQLALCHEMY_DATABASE_URI": uri, "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app, str(db_file)
        db.session.remove()
        db.engine.dispose()


def test_users_manage_permission(app):
    with app.app_context():
        admin = User.query.filter_by(username="hospital1").first()
        cashier = User.query.filter_by(username="retail1").first()
        assert perm_service.has_permission(admin, "users_manage")
        assert not perm_service.has_permission(cashier, "users_manage")


def test_create_facility_user(app):
    with app.app_context():
        admin = User.query.filter_by(username="hospital1").first()
        org = admin.organization
        user_service.create_user(
            org, username="cashier2", full_name="Night Cashier",
            role_code="CASHIER", password="secret",
        )
        db.session.commit()
        u = User.query.filter_by(username="cashier2").first()
        assert u is not None
        assert u.role.code == "CASHIER"


def test_cannot_deactivate_self(app):
    with app.app_context():
        admin = User.query.filter_by(username="hospital1").first()
        with pytest.raises(ValueError, match="own account"):
            user_service.toggle_user_active(admin.id, admin.org_id, actor_id=admin.id)


def test_users_route_admin(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/settings/users")
        assert resp.status_code == 200
        assert b"Team Users" in resp.data


def test_users_route_blocked_for_cashier(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/settings/users", follow_redirects=True)
        assert b"do not have permission" in resp.data


def test_profile_password_change(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.post(
            "/settings/profile",
            data={
                "current_password": "admin",
                "new_password": "newpass",
                "confirm_password": "newpass",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert b"Password updated" in resp.data
        user = User.query.filter_by(username="retail1").first()
        assert user.check_password("newpass")


def test_cashier_blocked_from_accounting(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/accounting/", follow_redirects=True)
        assert b"do not have permission" in resp.data


def test_health_endpoints(app):
    with app.app_context():
        client = app.test_client()
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.get_json()["status"] == "ok"
        ready = client.get("/api/ready")
        assert ready.status_code == 200
        assert ready.get_json()["database"] == "ok"


def test_backup_db_cli(file_db_app):
    app, _db_path = file_db_app
    with app.app_context():
        out_dir = tempfile.mkdtemp()
        runner = app.test_cli_runner()
        result = runner.invoke(args=["backup-db", "--out", out_dir])
        assert result.exit_code == 0
        files = os.listdir(out_dir)
        assert any(f.startswith("pharmaconnect_") and f.endswith(".db") for f in files)


def test_create_user_via_form(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.post(
            "/settings/users",
            data={
                "action": "create",
                "username": "pharma2",
                "full_name": "Second Pharmacist",
                "role_code": "FACILITY_ADMIN",
                "password": "pass123",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert User.query.filter_by(username="pharma2").first() is not None


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
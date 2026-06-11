import os

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.models import User
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import backup as backup_service
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


def test_retail_admin_seeded(app):
    with app.app_context():
        admin = User.query.filter_by(username="retail_admin").first()
        assert admin is not None
        assert admin.role.code == "FACILITY_ADMIN"
        assert admin.organization.code == "RTL01"
        assert perm_service.has_permission(admin, "users_manage")


def test_retail_admin_can_manage_team(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail_admin", "password": "admin"})
        resp = client.get("/settings/users")
        assert resp.status_code == 200
        assert b"Team Users" in resp.data


def test_cashier_api_payment_verify_forbidden(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.post(
            "/api/payments/verify",
            json={"gateway": "razorpay", "payment_id": "x", "signature": "y"},
        )
        assert resp.status_code == 403


def test_cashier_api_barcode_allowed(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/api/items/barcode/890101001001")
        assert resp.status_code == 200


def test_cashier_blocked_from_patients_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/patients/", follow_redirects=True)
        assert b"do not have permission" in resp.data


def test_restore_db_roundtrip(file_db_app, tmp_path):
    app, db_path = file_db_app
    with app.app_context():
        backup_path = backup_service.backup_database(str(tmp_path))
        User.query.filter_by(username="retail_admin").delete()
        db.session.commit()
        assert User.query.filter_by(username="retail_admin").first() is None

        backup_service.restore_database(backup_path, safety_copy=True)
        db.engine.dispose()

        assert os.path.isfile(db_path)
        assert User.query.filter_by(username="retail_admin").first() is not None


def test_restore_db_cli(file_db_app, tmp_path):
    app, _ = file_db_app
    with app.app_context():
        backup_path = backup_service.backup_database(str(tmp_path))
        User.query.filter_by(username="distributor").delete()
        db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["restore-db", backup_path, "--yes"])
    assert result.exit_code == 0
    with app.app_context():
        assert User.query.filter_by(username="distributor").first() is not None


def test_alerts_loop_script_exists():
    script = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "scripts",
        "run_alerts_loop.sh",
    )
    assert os.path.isfile(script)
    with open(script, encoding="utf-8") as fh:
        content = fh.read()
    assert "flask run-alerts" in content
    assert "sleep 3600" in content


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
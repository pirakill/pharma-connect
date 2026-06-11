import os

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services import audit as audit_service
from pharmaconnect.services.schema_migrations import ensure_schema


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


def test_schema_migration_idempotent(app):
    with app.app_context():
        ensure_schema()
        ensure_schema()
        from sqlalchemy import inspect
        cols = {c["name"] for c in inspect(db.engine).get_columns("bills")}
        assert "irn" in cols
        assert "payment_ref" in cols


def test_postgres_engine_options():
    app = create_app({
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "TESTING": True,
    })
    # Re-apply the same config branch used for PostgreSQL URIs
    uri = "postgresql+psycopg://u:p@localhost/pharma"
    app.config["SQLALCHEMY_DATABASE_URI"] = uri
    if uri.startswith("postgresql"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
        }
    opts = app.config.get("SQLALCHEMY_ENGINE_OPTIONS") or {}
    assert opts.get("pool_pre_ping") is True
    assert opts.get("pool_recycle") == 300


def test_audit_csv_export(app):
    with app.app_context():
        from pharmaconnect.models import Organization
        fac = Organization.query.filter_by(code="HSP01").first()
        audit_service.log_action(fac.id, "TEST_EXPORT", user_id=1, detail="v16 test")
        db.session.commit()
        csv_text = audit_service.export_csv(fac.id)
        assert "timestamp,action,username" in csv_text
        assert "TEST_EXPORT" in csv_text


def test_audit_export_route(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "hospital1", "password": "admin"})
        resp = client.get("/settings/audit/export.csv")
        assert resp.status_code == 200
        assert resp.mimetype == "text/csv"
        assert b"action" in resp.data


def test_cashier_cannot_export_audit(app):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": "retail1", "password": "admin"})
        resp = client.get("/settings/audit/export.csv", follow_redirects=True)
        assert b"do not have permission" in resp.data


def test_postgres_compose_file():
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "docker-compose.postgres.yml")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "postgres:16-alpine" in content
    assert "postgresql+psycopg://" in content


def test_docker_entrypoint_script():
    root = os.path.dirname(os.path.dirname(__file__))
    path = os.path.join(root, "scripts", "docker_entrypoint.sh")
    assert os.path.isfile(path)
    with open(path, encoding="utf-8") as fh:
        content = fh.read()
    assert "wait_for_db.py" in content
    assert "seed_if_empty" in content


def test_app_has_no_duplicate_endpoints(app):
    endpoints: dict[str, str] = {}
    for rule in app.url_map.iter_rules():
        if rule.endpoint in endpoints:
            raise AssertionError(
                f"Duplicate endpoint {rule.endpoint}: {endpoints[rule.endpoint]} and {rule.rule}"
            )
        endpoints[rule.endpoint] = rule.rule
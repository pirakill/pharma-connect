"""v18: whole-app UI consistency smoke tests."""

import pytest

from pharmaconnect import create_app, db
from pharmaconnect.seed import seed_if_empty


@pytest.fixture
def app():
    app = create_app({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:", "TESTING": True})
    with app.app_context():
        db.create_all()
        seed_if_empty(force=True)
        yield app
        db.session.remove()


PAGES = [
    ("distributor", "/dashboard/", ["kpi-card", "topbar-actions"]),
    ("retail1", "/billing/", ["table-wrap", "topbar-actions"]),
    ("retail1", "/reports/", ["link-list", "stat-card", "Report Catalogue"]),
    ("distributor", "/inventory/live", ["live-dot", "table-wrap"]),
    ("distributor", "/settings/integrations", ["checkbox-row"]),
    ("retail_admin", "/items/", ["kpi-card", "filter-bar"]),
    ("distributor", "/reports/network", ["kpi-card", "table-wrap"]),
]


@pytest.mark.parametrize("user,path,markers", PAGES)
def test_ui_markers_present(app, user, path, markers):
    with app.app_context():
        client = app.test_client()
        client.post("/auth/login", data={"username": user, "password": "admin"})
        res = client.get(path)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    for marker in markers:
        assert marker in html, f"Expected '{marker}' on {path}"


def test_landing_has_hero(app):
    with app.app_context():
        client = app.test_client()
        res = client.get("/")
    assert res.status_code in (200, 302)
    if res.status_code == 302:
        res = client.get(res.headers["Location"])
    html = res.get_data(as_text=True)
    assert "hero" in html or "PharmaConnect" in html


def test_login_page_uses_design_tokens(app):
    with app.app_context():
        client = app.test_client()
        res = client.get("/auth/login")
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "login-logo" in html
    assert "login-wrap" in html
    assert "login-tagline" in html
    assert "login-hint" in html
    assert "btn-lg" in html
    assert "app.css" in html
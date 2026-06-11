from __future__ import annotations

import os

from flask import Flask, redirect, url_for
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    base = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    db_path = os.path.join(base, "pharmaconnect.db")

    db_uri = os.environ.get("PHARMACONNECT_DB", f"sqlite:///{db_path}")
    app.config.update(
        SECRET_KEY=os.environ.get("PHARMACONNECT_SECRET", "dev-pharma-connect"),
        SQLALCHEMY_DATABASE_URI=db_uri,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JSON_SORT_KEYS=False,
        CRON_SECRET=os.environ.get("PHARMACONNECT_CRON_SECRET", ""),
    )
    if db_uri.startswith("postgresql"):
        app.config.setdefault("SQLALCHEMY_ENGINE_OPTIONS", {
            "pool_pre_ping": True,
            "pool_recycle": 300,
        })
    if config:
        app.config.update(config)

    db.init_app(app)
    login_manager.init_app(app)

    from .models import User  # noqa: WPS433

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(User, int(user_id))

    from .routes.auth import bp as auth_bp
    from .routes.landing import bp as landing_bp
    from .routes.dashboard import bp as dashboard_bp
    from .routes.inventory import bp as inventory_bp
    from .routes.billing import bp as billing_bp
    from .routes.accounting import bp as accounting_bp
    from .routes.reports import bp as reports_bp
    from .routes.api import bp as api_bp
    from .routes.customers import bp as customers_bp
    from .routes.returns import bp as returns_bp
    from .routes.purchase import bp as purchase_bp
    from .routes.items import bp as items_bp
    from .routes.schemes import bp as schemes_bp
    from .routes.patients import bp as patients_bp
    from .routes.settings import bp as settings_bp

    for bp in (
        auth_bp, landing_bp, dashboard_bp, inventory_bp, billing_bp, accounting_bp,
        reports_bp, api_bp, customers_bp, returns_bp, purchase_bp, items_bp,
        schemes_bp, patients_bp, settings_bp,
    ):
        app.register_blueprint(bp)

    @app.route("/")
    def index():
        from flask_login import current_user
        if current_user.is_authenticated:
            return redirect(url_for("dashboard.home"))
        return redirect(url_for("landing.welcome"))

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        from .services.permissions import has_permission

        def can(perm: str) -> bool:
            return has_permission(current_user, perm)

        return {"APP_NAME": "Infivita PharmaConnect", "can": can}

    _register_cli(app)

    with app.app_context():
        from .services.schema_migrations import ensure_schema

        db.create_all()
        ensure_schema()

    return app


def _register_cli(app: Flask) -> None:
    import click

    from .services import alerts as alerts_service
    from .services import backup as backup_service
    from .seed import seed_if_empty

    @app.cli.command("seed")
    def seed_cmd():
        with app.app_context():
            seed_if_empty(force=True)
            print("Demo data seeded.")

    @app.cli.command("run-alerts")
    @click.option("--force", is_flag=True, help="Ignore schedule hour and enabled flag")
    @click.option("--hour", type=int, default=None, help="Override hour (0-23) for schedule match")
    def run_alerts_cmd(force, hour):
        with app.app_context():
            result = alerts_service.run_scheduled_alerts(force=force, hour=hour)
            print(f"Alerts run for {result['ran']} distributor(s) at hour {result['hour']}")
            for row in result["results"]:
                print(
                    f"  {row['code']}: expiry→{row['expiry_facilities']} facilities, "
                    f"restock→{row['restock_facilities']} facilities"
                )

    @app.cli.command("backup-db")
    @click.option("--out", "out_dir", default=None, help="Backup directory (default: ./backups)")
    def backup_db_cmd(out_dir):
        with app.app_context():
            path = backup_service.backup_database(out_dir)
            print(f"Database backed up to {path}")

    @app.cli.command("restore-db")
    @click.argument("backup_path")
    @click.option("--yes", is_flag=True, help="Skip confirmation prompt")
    @click.option("--no-safety-copy", is_flag=True, help="Do not keep a pre-restore copy of the live DB")
    def restore_db_cmd(backup_path, yes, no_safety_copy):
        if not yes:
            click.confirm(
                f"Restore database from {backup_path}? This overwrites the live DB.",
                abort=True,
            )
        with app.app_context():
            path = backup_service.restore_database(
                backup_path, safety_copy=not no_safety_copy,
            )
            print(f"Database restored from {backup_path} to {path}")
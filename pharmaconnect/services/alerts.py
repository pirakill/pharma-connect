"""Scheduled SMS alert runner for distributor networks."""
from __future__ import annotations

from datetime import datetime

from .. import db
from ..models import IntegrationSettings, Organization
from .integrations import get_settings
from .sms import run_expiry_alerts, run_restock_alerts


def run_scheduled_alerts(*, force: bool = False, hour: int | None = None) -> dict:
    """Run expiry and low-stock SMS for distributors with scheduling enabled."""
    now_hour = hour if hour is not None else datetime.now().hour
    distributors = Organization.query.filter_by(kind="DISTRIBUTOR", is_active=True).all()
    results: list[dict] = []

    for dist in distributors:
        settings = get_settings(dist.id)
        if not settings.sms_enabled:
            continue
        if not force:
            if not settings.alert_schedule_enabled:
                continue
            sched_hour = settings.alert_schedule_hour if settings.alert_schedule_hour is not None else 9
            if sched_hour != now_hour:
                continue

        expiry_n = run_expiry_alerts(dist.id)
        restock_n = run_restock_alerts(dist.id)
        results.append({
            "org_id": dist.id,
            "code": dist.code,
            "expiry_facilities": expiry_n,
            "restock_facilities": restock_n,
        })

    db.session.commit()
    return {"hour": now_hour, "force": force, "ran": len(results), "results": results}


def distributors_with_schedule() -> list[IntegrationSettings]:
    return (
        IntegrationSettings.query.join(Organization)
        .filter(
            Organization.kind == "DISTRIBUTOR",
            Organization.is_active.is_(True),
            IntegrationSettings.alert_schedule_enabled.is_(True),
            IntegrationSettings.sms_enabled.is_(True),
        )
        .all()
    )
from __future__ import annotations

import csv
from io import StringIO

from .. import db
from ..models import AuditLog


def log_action(
    org_id: int,
    action: str,
    *,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_ref: str | None = None,
    detail: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        org_id=org_id,
        user_id=user_id,
        action=action,
        entity_type=entity_type,
        entity_ref=entity_ref,
        detail=(detail or "")[:255] or None,
    )
    db.session.add(entry)
    return entry


def recent_logs(org_id: int, limit: int = 100) -> list[AuditLog]:
    return (
        AuditLog.query.filter_by(org_id=org_id)
        .order_by(AuditLog.ts.desc())
        .limit(limit)
        .all()
    )


def export_csv(org_id: int, limit: int = 500) -> str:
    rows = recent_logs(org_id, limit=limit)
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "action", "username", "entity_type", "entity_ref", "detail"])
    for row in rows:
        writer.writerow([
            row.ts.isoformat() if row.ts else "",
            row.action,
            row.user.username if row.user else "",
            row.entity_type or "",
            row.entity_ref or "",
            row.detail or "",
        ])
    return buf.getvalue()
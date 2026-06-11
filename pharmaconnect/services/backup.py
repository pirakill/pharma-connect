"""SQLite database backup helpers."""
from __future__ import annotations

import os
import shutil
from datetime import datetime
from urllib.parse import unquote, urlparse

from flask import current_app


def sqlite_path_from_uri(uri: str) -> str | None:
    if not uri.startswith("sqlite:"):
        return None
    parsed = urlparse(uri)
    path = unquote(parsed.path or "")
    if os.name == "nt" and path.startswith("/") and len(path) > 2 and path[2] == ":":
        path = path[1:]
    return path or None


def backup_database(out_dir: str | None = None) -> str:
    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    db_path = sqlite_path_from_uri(uri)
    if not db_path or not os.path.isfile(db_path):
        raise ValueError("Backup only supported for on-disk SQLite databases")

    base = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    dest_dir = out_dir or os.path.join(base, "backups")
    os.makedirs(dest_dir, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"pharmaconnect_{stamp}.db"
    dest = os.path.join(dest_dir, filename)
    shutil.copy2(db_path, dest)
    return dest


def restore_database(backup_path: str, *, safety_copy: bool = True) -> str:
    """Replace the live SQLite DB with a backup file."""
    from .. import db

    backup_path = os.path.abspath(backup_path)
    if not os.path.isfile(backup_path):
        raise ValueError(f"Backup not found: {backup_path}")

    uri = current_app.config.get("SQLALCHEMY_DATABASE_URI", "")
    db_path = sqlite_path_from_uri(uri)
    if not db_path:
        raise ValueError("Restore only supported for on-disk SQLite databases")

    db.session.remove()
    db.engine.dispose()

    if safety_copy and os.path.isfile(db_path):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety = f"{db_path}.pre_restore_{stamp}"
        shutil.copy2(db_path, safety)

    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    shutil.copy2(backup_path, db_path)
    return db_path
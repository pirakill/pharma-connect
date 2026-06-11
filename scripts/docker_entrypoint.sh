#!/bin/sh
set -e

python scripts/wait_for_db.py

python - <<'PY'
from app import app, db
from pharmaconnect.seed import seed_if_empty
from pharmaconnect.services.schema_migrations import ensure_schema

with app.app_context():
    db.create_all()
    ensure_schema()
    seed_if_empty()
PY

exec gunicorn --bind 0.0.0.0:5000 --workers "${GUNICORN_WORKERS:-2}" wsgi:app
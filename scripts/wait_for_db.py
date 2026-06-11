"""Block until PHARMACONNECT_DB accepts connections (Docker / PostgreSQL startup)."""
from __future__ import annotations

import os
import sys
import time

from sqlalchemy import create_engine, text

URI = os.environ.get("PHARMACONNECT_DB", "")
MAX_WAIT = int(os.environ.get("PHARMACONNECT_DB_WAIT", "60"))


def main() -> int:
    if not URI or not URI.startswith("postgresql"):
        return 0

    engine = create_engine(URI, pool_pre_ping=True)
    for attempt in range(1, MAX_WAIT + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            print(f"Database ready (attempt {attempt})")
            return 0
        except Exception as exc:
            print(f"Waiting for database ({attempt}/{MAX_WAIT}): {exc}")
            time.sleep(1)

    print("Database not ready", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
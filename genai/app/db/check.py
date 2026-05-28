from __future__ import annotations

import json
import sys

from app.core import get_settings
from app.db import get_database_backend, ping_database_backend


def build_database_status_payload() -> dict[str, object]:
    """Return a JSON-serializable snapshot of database configuration and reachability."""
    settings = get_settings()
    database_ok, database_error = ping_database_backend()

    return {
        "database_backend": get_database_backend(),
        "database_ok": database_ok,
        "database_error": database_error,
        "postgres_dsn_configured": bool(settings.postgres_dsn),
        "sqlite_path": settings.sqlite_path,
    }


def main() -> int:
    payload = build_database_status_payload()
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if payload["database_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
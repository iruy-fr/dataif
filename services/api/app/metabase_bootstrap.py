from __future__ import annotations

import sys
import time

from fastapi import HTTPException

from .config import settings
from .metabase_admin import MetabaseAdminClient


def main() -> int:
    client = MetabaseAdminClient(
        base_url=settings.metabase_api_url,
        admin_email=settings.metabase_admin_email,
        admin_password=settings.metabase_admin_password,
        timeout_seconds=max(settings.nilo_timeout_seconds, 30.0),
    )

    deadline = time.monotonic() + 180
    last_error = "Metabase did not become ready"
    while time.monotonic() < deadline:
        try:
            outcome = client.ensure_initial_admin(
                first_name=settings.metabase_admin_first_name,
                last_name=settings.metabase_admin_last_name,
                site_name=settings.metabase_site_name,
                allow_tracking=settings.metabase_allow_tracking,
            )
            state = "bootstrapped" if outcome.get("bootstrapped") else "already_configured"
            print(f"metabase_bootstrap={state}")
            return 0
        except HTTPException as exc:
            last_error = str(exc.detail)
        except Exception as exc:  # pragma: no cover - defensive bootstrap path
            last_error = str(exc)
        time.sleep(3)

    print(f"metabase_bootstrap_failed={last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

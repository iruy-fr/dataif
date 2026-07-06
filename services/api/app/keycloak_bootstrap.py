from __future__ import annotations

from time import sleep

from fastapi import HTTPException

from .config import settings
from .keycloak_admin import KeycloakAdminClient


def main() -> None:
    client = KeycloakAdminClient(
        base_url=settings.keycloak_url,
        realm=settings.keycloak_realm,
        admin_realm=settings.keycloak_admin_realm,
        admin_client_id=settings.keycloak_admin_client_id,
        admin_username=settings.keycloak_admin_username,
        admin_password=settings.keycloak_admin_password,
        timeout_seconds=max(settings.nilo_timeout_seconds, 30.0),
    )

    last_error: Exception | None = None
    for attempt in range(1, 31):
        try:
            user = client.upsert_admin_user(
                username=settings.dataif_admin_username,
                email=settings.dataif_admin_email,
                password=settings.dataif_admin_password,
                first_name=settings.dataif_admin_first_name,
                last_name=settings.dataif_admin_last_name,
                enabled=True,
            )
            print(
                "keycloak_bootstrap_ok "
                f"realm={settings.keycloak_realm} "
                f"username={user['username']} "
                f"email={user['email']}"
            )
            return
        except HTTPException as exc:
            last_error = exc
            print(f"keycloak_bootstrap_wait attempt={attempt} detail={exc.detail}")
            sleep(5)

    raise SystemExit(f"keycloak_bootstrap_failed={getattr(last_error, 'detail', last_error)}")


if __name__ == "__main__":
    main()

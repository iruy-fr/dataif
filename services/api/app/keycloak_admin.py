from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException


class KeycloakAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        realm: str,
        admin_realm: str,
        admin_client_id: str,
        admin_username: str,
        admin_password: str,
        timeout_seconds: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.admin_realm = admin_realm
        self.admin_client_id = admin_client_id
        self.admin_username = admin_username
        self.admin_password = admin_password
        self.timeout_seconds = timeout_seconds

    def list_admin_users(self) -> list[dict[str, Any]]:
        users = self._request(
            "GET",
            f"/admin/realms/{quote(self.realm, safe='')}/roles/admin/users",
            expected_status={200},
        )
        if not isinstance(users, list):
            return []
        return [
            {
                "id": item.get("id"),
                "username": item.get("username"),
                "email": item.get("email") or "",
                "first_name": item.get("firstName") or "",
                "last_name": item.get("lastName") or "",
                "enabled": bool(item.get("enabled", True)),
                "email_verified": bool(item.get("emailVerified", False)),
            }
            for item in users
            if isinstance(item, dict)
        ]

    def get_admin_user(self, user_id: str) -> dict[str, Any] | None:
        for item in self.list_admin_users():
            if str(item.get("id") or "") == user_id:
                return item
        return None

    def create_admin_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        enabled: bool,
    ) -> dict[str, Any]:
        payload = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": enabled,
            "emailVerified": False,
        }
        self._request(
            "POST",
            f"/admin/realms/{quote(self.realm, safe='')}/users",
            json=payload,
            expected_status={201, 204},
        )
        user = self._lookup_user_by_username(username)
        if not user or not user.get("id"):
            raise HTTPException(status_code=502, detail="Keycloak did not return the created user")

        user_id = str(user["id"])
        self._request(
            "PUT",
            f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}/reset-password",
            json={"type": "password", "temporary": False, "value": password},
            expected_status={204},
        )
        self._request(
            "POST",
            f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}/role-mappings/realm",
            json=[self._realm_role("admin")],
            expected_status={204},
        )
        return {
            "id": user_id,
            "username": user.get("username") or username,
            "email": user.get("email") or email,
            "first_name": user.get("firstName") or first_name,
            "last_name": user.get("lastName") or last_name,
            "enabled": bool(user.get("enabled", enabled)),
            "email_verified": bool(user.get("emailVerified", False)),
        }

    def upsert_admin_user(
        self,
        *,
        username: str,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        user = self._lookup_user_by_username(username)
        if not user:
            return self.create_admin_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
                enabled=enabled,
            )

        user_id = str(user["id"])
        self._request(
            "PUT",
            f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}",
            json={
                "username": username,
                "email": email,
                "firstName": first_name,
                "lastName": last_name,
                "enabled": enabled,
                "emailVerified": bool(user.get("emailVerified", False)),
            },
            expected_status={204},
        )
        if password:
            self._request(
                "PUT",
                f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}/reset-password",
                json={"type": "password", "temporary": False, "value": password},
                expected_status={204},
            )
        self.ensure_realm_role(user_id=user_id, role_name="admin")
        refreshed = self._lookup_user_by_username(username) or user
        return {
            "id": user_id,
            "username": refreshed.get("username") or username,
            "email": refreshed.get("email") or email,
            "first_name": refreshed.get("firstName") or first_name,
            "last_name": refreshed.get("lastName") or last_name,
            "enabled": bool(refreshed.get("enabled", enabled)),
            "email_verified": bool(refreshed.get("emailVerified", False)),
        }

    def ensure_realm_role(self, *, user_id: str, role_name: str) -> None:
        role = self._realm_role(role_name)
        existing_roles = self._request(
            "GET",
            f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}/role-mappings/realm",
            expected_status={200},
        )
        if isinstance(existing_roles, list):
            for item in existing_roles:
                if isinstance(item, dict) and item.get("name") == role_name:
                    return
        self._request(
            "POST",
            f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}/role-mappings/realm",
            json=[role],
            expected_status={204},
        )

    def delete_user(self, user_id: str) -> None:
        self._request(
            "DELETE",
            f"/admin/realms/{quote(self.realm, safe='')}/users/{quote(user_id, safe='')}",
            expected_status={204},
        )

    def _lookup_user_by_username(self, username: str) -> dict[str, Any] | None:
        items = self._request(
            "GET",
            f"/admin/realms/{quote(self.realm, safe='')}/users",
            params={"username": username, "exact": "true"},
            expected_status={200},
        )
        if not isinstance(items, list):
            return None
        for item in items:
            if isinstance(item, dict) and item.get("username") == username:
                return item
        return None

    def _realm_role(self, role_name: str) -> dict[str, Any]:
        role = self._request(
            "GET",
            f"/admin/realms/{quote(self.realm, safe='')}/roles/{quote(role_name, safe='')}",
            expected_status={200},
        )
        if not isinstance(role, dict) or not role.get("name"):
            raise HTTPException(status_code=502, detail=f"Keycloak role {role_name} was not returned correctly")
        return role

    def _admin_token(self) -> str:
        token_url = f"{self.base_url}/realms/{quote(self.admin_realm, safe='')}/protocol/openid-connect/token"
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.post(
                    token_url,
                    data={
                        "grant_type": "password",
                        "client_id": self.admin_client_id,
                        "username": self.admin_username,
                        "password": self.admin_password,
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Keycloak admin token request failed: {exc}") from exc

        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=_error_detail(response, "Keycloak admin token request failed"))

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Keycloak admin token response was not valid JSON") from exc

        token = payload.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise HTTPException(status_code=502, detail="Keycloak admin token response did not include access_token")
        return token

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        params: dict[str, str] | None = None,
        expected_status: set[int],
    ) -> Any:
        token = self._admin_token()
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Keycloak admin request failed: {exc}") from exc

        if response.status_code not in expected_status:
            raise HTTPException(status_code=response.status_code, detail=_error_detail(response, "Keycloak admin request failed"))

        if response.status_code == 204 or not response.text.strip():
            return None

        try:
            return response.json()
        except ValueError:
            return response.text


def _error_detail(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("error_description") or payload.get("errorMessage") or payload.get("error") or payload.get("message")
        if isinstance(detail, str) and detail.strip():
            return detail
    text = response.text.strip()
    return text or fallback

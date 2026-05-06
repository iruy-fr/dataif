from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException


class MetabaseAdminClient:
    def __init__(
        self,
        *,
        base_url: str,
        admin_email: str,
        admin_password: str,
        timeout_seconds: float,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_email = admin_email
        self.admin_password = admin_password
        self.timeout_seconds = timeout_seconds

    def session_properties(self) -> dict[str, Any]:
        return self._raw_request("GET", "/api/session/properties", expected_status={200}, auth_mode="none")

    def list_admin_users(self) -> list[dict[str, Any]]:
        items = self._request("GET", "/api/user", expected_status={200})
        if not isinstance(items, list):
            return []
        return [self._normalize_user(item) for item in items if isinstance(item, dict) and bool(item.get("is_superuser"))]

    def find_user_by_email(self, email: str) -> dict[str, Any] | None:
        target = email.strip().lower()
        if not target:
            return None
        for item in self.list_admin_users():
            if str(item.get("email") or "").strip().lower() == target:
                return item
        return None

    def create_admin_user(
        self,
        *,
        email: str,
        password: str,
        first_name: str,
        last_name: str,
    ) -> dict[str, Any]:
        existing = self.find_user_by_email(email)
        if existing:
            raise HTTPException(status_code=409, detail=f"Metabase admin already exists for email: {email}")

        payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "password": password,
            "is_superuser": True,
        }
        created = self._request("POST", "/api/user", json=payload, expected_status={200})
        if not isinstance(created, dict):
            raise HTTPException(status_code=502, detail="Metabase did not return the created user")
        return self._normalize_user(created)

    def delete_user(self, user_id: int | str) -> None:
        self._request("DELETE", f"/api/user/{user_id}", expected_status={200, 204})

    def ensure_initial_admin(
        self,
        *,
        first_name: str,
        last_name: str,
        site_name: str,
        allow_tracking: bool,
    ) -> dict[str, Any]:
        properties = self.session_properties()
        if bool(properties.get("has-user-setup", True)):
            existing = self.find_user_by_email(self.admin_email)
            if existing:
                return {"bootstrapped": False, "user": existing}
            return {"bootstrapped": False, "user": None}

        setup_token = str(properties.get("setup-token") or "").strip()
        if not setup_token:
            raise HTTPException(status_code=502, detail="Metabase setup token was not returned")

        payload = {
            "token": setup_token,
            "user": {
                "email": self.admin_email,
                "first_name": first_name,
                "last_name": last_name,
                "password": self.admin_password,
            },
            "prefs": {
                "site_name": site_name,
                "allow_tracking": allow_tracking,
            },
        }
        self._raw_request("POST", "/api/setup", json=payload, expected_status={200}, auth_mode="none")
        user = self.find_user_by_email(self.admin_email)
        return {"bootstrapped": True, "user": user}

    def _normalize_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": payload.get("id"),
            "email": payload.get("email") or "",
            "first_name": payload.get("first_name") or "",
            "last_name": payload.get("last_name") or "",
            "is_superuser": bool(payload.get("is_superuser")),
            "is_active": bool(payload.get("is_active", True)),
            "common_name": payload.get("common_name") or "",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        expected_status: set[int],
    ) -> Any:
        return self._raw_request(method, path, json=json, expected_status=expected_status, auth_mode="session")

    def _raw_request(
        self,
        method: str,
        path: str,
        *,
        json: object | None = None,
        expected_status: set[int],
        auth_mode: str,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        if auth_mode == "session":
            headers["X-Metabase-Session"] = self._session_id()

        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.request(method, url, json=json, headers=headers)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Metabase request failed: {exc}") from exc

        if response.status_code not in expected_status:
            raise HTTPException(status_code=response.status_code, detail=_metabase_error_detail(response, "Metabase request failed"))

        if response.status_code == 204 or not response.text.strip():
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def _session_id(self) -> str:
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.post(
                    f"{self.base_url}/api/session",
                    json={"username": self.admin_email, "password": self.admin_password},
                )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Metabase session request failed: {exc}") from exc

        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=_metabase_error_detail(response, "Metabase session request failed"))

        try:
            payload = response.json()
        except ValueError as exc:
            raise HTTPException(status_code=502, detail="Metabase session response was not valid JSON") from exc

        session_id = payload.get("id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise HTTPException(status_code=502, detail="Metabase session response did not include an id")
        return session_id


def _metabase_error_detail(response: httpx.Response, fallback: str) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        detail = payload.get("message") or payload.get("errors") or payload.get("error")
        if isinstance(detail, str) and detail.strip():
            return detail
        if isinstance(detail, dict):
            return str(detail)
    text = response.text.strip()
    return text or fallback

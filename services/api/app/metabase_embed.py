from __future__ import annotations

import time

import jwt


def build_signed_dashboard_url(site_url: str, embed_secret: str, dashboard_id: int, params: dict[str, object] | None = None) -> str:
    payload = {
        "resource": {"dashboard": int(dashboard_id)},
        "params": params or {},
        "exp": int(time.time()) + (10 * 60),
    }
    token = jwt.encode(payload, embed_secret, algorithm="HS256")
    return f"{site_url}/embed/dashboard/{token}#bordered=true&titled=true"

from __future__ import annotations

import httpx
from fastapi import HTTPException


async def ask_vanna(vanna_service_url: str, question: str) -> dict[str, object]:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{vanna_service_url}/ask",
                json={"question": question},
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503, detail=f"Vanna service unavailable: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise HTTPException(status_code=response.status_code, detail=detail)

    return response.json()

"""HTTP client for the DJUtil sync API."""

from __future__ import annotations

import time
from typing import Any, cast

import httpx


class SyncError(RuntimeError):
    pass


class SyncClient:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout,
            transport=transport,
        )
        self.max_retries = max_retries

    def close(self) -> None:
        self._client.close()

    def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> httpx.Response:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                last = exc
            else:
                if resp.status_code < 500:
                    return resp
                last = SyncError(f"{method} {path} -> {resp.status_code}")
            if attempt < self.max_retries:
                time.sleep(min(2 ** attempt, 8))
        assert last is not None
        if isinstance(last, SyncError):
            raise last
        raise SyncError(f"{method} {path} failed: {last}") from last

    def _json(self, method: str, path: str, **kwargs: Any) -> Any:
        resp = self._request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise SyncError(
                f"{method} {path} -> {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json()

    # -- sync API ------------------------------------------------------------

    def get_state(self) -> dict[str, int | None]:
        data = self._json("GET", "/api/sync/state")
        return cast("dict[str, int | None]", data["entities"])

    def post_batch(self, payload: dict[str, Any]) -> dict[str, Any]:
        return cast("dict[str, Any]", self._json("POST", "/api/sync/batch", json=payload))

    def post_ids(self, entity: str, ids: list[str]) -> dict[str, Any]:
        return cast(
            "dict[str, Any]",
            self._json("POST", "/api/sync/ids", json={"entity": entity, "ids": ids}),
        )

    def artwork_exists(self, sha256: str) -> bool:
        resp = self._request("HEAD", f"/api/artwork/{sha256}")
        return resp.status_code == 200

    def upload_artwork(self, sha256: str, data: bytes) -> None:
        resp = self._request(
            "PUT",
            f"/api/artwork/{sha256}",
            content=data,
            headers={"Content-Type": "application/octet-stream"},
        )
        if resp.status_code >= 400:
            raise SyncError(f"artwork upload -> {resp.status_code}")

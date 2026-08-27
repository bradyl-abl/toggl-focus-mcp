"""Async HTTP client for the Toggl Focus API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .config import Config

REVOKED_KEY_HINT = (
    "The API key was rejected. Note that Toggl allows one active key per user, "
    "so creating a new key revokes the previous one."
)


class FocusAPIError(Exception):
    """Raised when the Focus API returns an error status."""

    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(f"Toggl API error {status}: {message}")


def to_rfc3339(value: datetime) -> str:
    """Render a datetime the way the Focus API demands.

    Plain dates are rejected with HTTP 400, so this always emits a full
    timestamp normalised to UTC.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class FocusClient:
    """Owns every HTTP call. Returns parsed data, never raw responses."""

    def __init__(self, config: Config, http: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http

    @property
    def scope(self) -> str:
        cfg = self._config
        return f"{cfg.api_base}/organizations/{cfg.org_id}/workspaces/{cfg.workspace_id}"

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
    ) -> Any | None:
        """Call a workspace-scoped endpoint. Returns None for 204."""
        response = await self._http.request(
            method,
            f"{self.scope}{path}",
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {self._config.api_key}"},
        )
        return self._handle(response)

    def _handle(self, response: httpx.Response) -> Any | None:
        if response.status_code == 204:
            return None
        if response.is_success:
            return response.json()
        raise FocusAPIError(response.status_code, self._error_message(response))

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        if response.status_code == 401:
            return REVOKED_KEY_HINT
        try:
            body = response.json()
        except ValueError:
            return response.text or response.reason_phrase
        return body.get("error_description") or body.get("error") or response.text

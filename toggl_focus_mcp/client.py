"""Async HTTP client for the Toggl Focus API."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, NamedTuple

import httpx

from .config import Config

REVOKED_KEY_HINT = (
    "The API key was rejected. Note that Toggl allows one active key per user, "
    "so creating a new key revokes the previous one."
)

FORBIDDEN_HINT = (
    "The API key was accepted but is not allowed to do this. Either the key "
    "lacks permission for this workspace, or TOGGL_ORG_ID is wrong. Check both "
    "against the Toggl 2.0 URL: "
    "https://focus.toggl.com/{organization_id}/workspaces/{workspace_id}/calendar"
)

# Stop paging after this many requests. A 30 day window at 50 entries a page
# fits well inside it, and the cap keeps a misbehaving API from looping forever.
MAX_PAGES = 20


class TimeEntryResult(NamedTuple):
    """Entries plus whether paging stopped at the cap before running out."""

    entries: list[dict]
    truncated: bool


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
        self._workspace_id = config.workspace_id

    @property
    def scope(self) -> str:
        cfg = self._config
        return f"{cfg.api_base}/organizations/{cfg.org_id}/workspaces/{self._workspace_id}"

    async def _scoped_url(self, path: str) -> str:
        """Resolve the workspace on first use, then build the URL."""
        if self._workspace_id is None:
            self._workspace_id = await self.resolve_workspace_id()
        return f"{self.scope}{path}"

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
            await self._scoped_url(path),
            params=params,
            json=json,
            headers={"Authorization": f"Bearer {self._config.api_key}"},
        )
        return self._handle(response)

    async def get_current_timer(self) -> dict | None:
        """The running entry, or None when nothing is being tracked."""
        return await self.request("GET", "/tracking/current")

    async def start_timer(self, description: str, project_id: int | None = None) -> dict:
        """Start tracking. Any running entry is stopped by the API first."""
        payload: dict = {"type": "activity", "description": description}
        if project_id is not None:
            payload["project_id"] = project_id
        return await self.request("POST", "/tracking/start", json=payload)

    async def stop_timer(self) -> dict | None:
        """Stop tracking. Returns None when nothing was running."""
        try:
            return await self.request("POST", "/tracking/stop")
        except FocusAPIError as error:
            if error.status == 404:
                return None
            raise

    async def list_time_entries(
        self,
        date_from: datetime,
        date_to: datetime,
        per_page: int = 50,
    ) -> TimeEntryResult:
        """Every entry in a window. Both bounds are required by the API.

        Walks pages until one comes back short, so a busy month does not get
        silently cut to the first page. Gives up at MAX_PAGES and flags the
        result as truncated, so the caller can say the list is incomplete
        rather than presenting a partial total as the whole period.
        """
        per_page = max(1, per_page)
        entries: list[dict] = []
        for page_number in range(1, MAX_PAGES + 1):
            page = await self.request(
                "GET",
                "/time-entries",
                params={
                    "date_from": to_rfc3339(date_from),
                    "date_to": to_rfc3339(date_to),
                    "page": page_number,
                    "per_page": per_page,
                    "include_taskless": "true",
                },
            )
            batch = (page or {}).get("data") or []
            entries.extend(batch)
            if len(batch) < per_page:
                return TimeEntryResult(entries, False)
        return TimeEntryResult(entries, True)

    async def resolve_workspace_id(self) -> str:
        """Look up the default workspace when none is configured."""
        response = await self._http.get(
            f"{self._config.api_base}/users/me/settings",
            headers={"Authorization": f"Bearer {self._config.api_key}"},
        )
        settings = self._handle(response) or {}
        return str(settings["current_workspace_id"])

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
        if response.status_code == 403:
            return FORBIDDEN_HINT
        try:
            body = response.json()
        except ValueError:
            return response.text or response.reason_phrase
        return body.get("error_description") or body.get("error") or response.text

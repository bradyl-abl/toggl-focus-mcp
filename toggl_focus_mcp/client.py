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


class ProjectLookup(NamedTuple):
    """Names for the projects that time entries point at.

    Both dicts are keyed by project ID rendered as a string, because the API
    returns IDs as numbers in some payloads and as strings in others.
    """

    project_names: dict[str, str]
    client_names: dict[str, str]


EMPTY_LOOKUP = ProjectLookup({}, {})


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


def _as_id(value: Any) -> str | None:
    """Normalise an ID to a string key, or None when there is nothing to key on."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _embedded_client_name(project: dict) -> str:
    """The client name carried on the project itself, when the API sends one."""
    name = project.get("client_name")
    if name:
        return str(name)
    client = project.get("client")
    if isinstance(client, dict) and client.get("name"):
        return str(client["name"])
    if isinstance(client, str) and client.strip():
        return client.strip()
    return ""


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
        """Every entry in a window. Both bounds are required by the API."""
        entries, truncated = await self._paged(
            "/time-entries",
            {
                "date_from": to_rfc3339(date_from),
                "date_to": to_rfc3339(date_to),
                "include_taskless": "true",
            },
            per_page,
        )
        return TimeEntryResult(entries, truncated)

    async def project_lookup(self) -> ProjectLookup:
        """Map project IDs to their project name and client name.

        Time entries carry only project_id, so the names take a second call.
        Clients are one hop further out: a project carries client_id, not the
        client name, unless the payload happens to embed it.
        """
        projects, _ = await self._paged("/projects", {})
        project_names: dict[str, str] = {}
        client_names: dict[str, str] = {}
        unresolved: dict[str, str] = {}

        for project in projects:
            if not isinstance(project, dict):
                continue
            project_id = _as_id(project.get("id"))
            if project_id is None:
                continue
            name = project.get("name")
            if name:
                project_names[project_id] = str(name)
            embedded = _embedded_client_name(project)
            if embedded:
                client_names[project_id] = embedded
                continue
            client_id = _as_id(project.get("client_id"))
            if client_id is not None:
                unresolved[project_id] = client_id

        if unresolved:
            by_client_id = await self._client_names()
            for project_id, client_id in unresolved.items():
                name = by_client_id.get(client_id)
                if name:
                    client_names[project_id] = name

        return ProjectLookup(project_names, client_names)

    async def _client_names(self) -> dict[str, str]:
        """Client ID to client name.

        A 403 or 404 here means this account cannot read clients, or the route
        is not there. Names are a label, not the answer, so return nothing and
        let the caller print the project on its own.
        """
        try:
            clients, _ = await self._paged("/clients", {})
        except FocusAPIError as error:
            if error.status in (403, 404):
                return {}
            raise
        names: dict[str, str] = {}
        for record in clients:
            if not isinstance(record, dict):
                continue
            client_id = _as_id(record.get("id"))
            name = record.get("name")
            if client_id is not None and name:
                names[client_id] = str(name)
        return names

    async def _paged(
        self,
        path: str,
        params: dict,
        per_page: int = 50,
    ) -> tuple[list[dict], bool]:
        """Walk a paged collection until a page comes back short.

        Stops at MAX_PAGES and reports truncation, so a busy month is never
        silently cut to the first page and never loops forever either. An
        endpoint that answers with a bare array does not page at all, so that
        array is the whole set.
        """
        per_page = max(1, per_page)
        items: list[dict] = []
        for page_number in range(1, MAX_PAGES + 1):
            payload = await self.request(
                "GET",
                path,
                params={**params, "page": page_number, "per_page": per_page},
            )
            if isinstance(payload, list):
                return payload, False
            batch = (payload or {}).get("data") or []
            items.extend(batch)
            if len(batch) < per_page:
                return items, False
        return items, True

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

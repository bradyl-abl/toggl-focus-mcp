# toggl-focus-mcp v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an MCP server that lets Claude read and control time tracking on Toggl 2.0 accounts through the Focus API.

**Architecture:** Five focused modules. `config.py` loads and validates environment. `client.py` owns all HTTP and returns parsed data so status-code handling never leaks upward. `formatting.py` is pure functions from payloads to text. `tools.py` defines the four MCP tools. `server.py` wires it together. Tests stub HTTP with `respx`, so no test touches the network.

**Tech Stack:** Python 3.11+, `mcp[cli]>=2.0.0` (the `MCPServer` API), `httpx` for async HTTP, `pytest` with `pytest-asyncio` and `respx`.

**Spec:** `docs/superpowers/specs/2026-08-27-toggl-focus-mcp-design.md`

## Global Constraints

- Base URL default: `https://focus.toggl.com/api`
- Auth: `Authorization: Bearer <key>`, keys start with `toggl_sk_`
- Every data path is scoped: `/organizations/{org_id}/workspaces/{workspace_id}/...`
- `GET .../tracking/current` returns **204 with an empty body** when no timer runs. Never call `.json()` unconditionally.
- `POST .../tracking/stop` returns **404** when nothing is running. This is a normal outcome, not an error.
- `POST .../tracking/start` requires `type`, an enum of exactly `"activity"` or `"break"`. Starting a timer auto-stops any running one.
- `GET .../time-entries` **requires** `date_from` and `date_to` as RFC3339 datetimes (`2026-07-28T00:00:00Z`). A plain date returns 400.
- Paged responses are shaped `{page, per_page, data: [...]}`.
- No em dashes in code comments, docs, or commit messages. Active voice, no hedging.
- MIT license.

---

### Task 1: Project scaffolding and configuration

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `toggl_focus_mcp/__init__.py`
- Create: `toggl_focus_mcp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing
- Produces: `Config` frozen dataclass with fields `api_key: str`, `org_id: str`, `workspace_id: str | None`, `api_base: str`; exception `ConfigError(Exception)`; function `load_config(env: Mapping[str, str]) -> Config`

- [ ] **Step 1: Create the dependency files and package directory**

`requirements.txt`:

```
mcp[cli]>=2.0.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

`requirements-dev.txt`:

```
-r requirements.txt
pytest>=8.0.0
pytest-asyncio>=0.23.0
respx>=0.21.0
```

Create empty `toggl_focus_mcp/__init__.py` and `tests/__init__.py`.

Create `pytest.ini`:

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

- [ ] **Step 2: Write the failing tests**

`tests/test_config.py`:

```python
import pytest

from toggl_focus_mcp.config import Config, ConfigError, load_config

VALID_KEY = "toggl_sk_" + "a" * 32


def test_loads_all_values():
    cfg = load_config({
        "TOGGL_API_KEY": VALID_KEY,
        "TOGGL_ORG_ID": "21631262",
        "TOGGL_WORKSPACE_ID": "21630499",
        "TOGGL_API_BASE": "https://example.test/api",
    })
    assert cfg == Config(
        api_key=VALID_KEY,
        org_id="21631262",
        workspace_id="21630499",
        api_base="https://example.test/api",
    )


def test_api_base_defaults():
    cfg = load_config({"TOGGL_API_KEY": VALID_KEY, "TOGGL_ORG_ID": "1"})
    assert cfg.api_base == "https://focus.toggl.com/api"


def test_workspace_id_is_optional():
    cfg = load_config({"TOGGL_API_KEY": VALID_KEY, "TOGGL_ORG_ID": "1"})
    assert cfg.workspace_id is None


def test_trailing_slash_stripped_from_api_base():
    cfg = load_config({
        "TOGGL_API_KEY": VALID_KEY,
        "TOGGL_ORG_ID": "1",
        "TOGGL_API_BASE": "https://example.test/api/",
    })
    assert cfg.api_base == "https://example.test/api"


def test_missing_api_key_names_the_variable():
    with pytest.raises(ConfigError, match="TOGGL_API_KEY"):
        load_config({"TOGGL_ORG_ID": "1"})


def test_missing_org_id_explains_where_to_find_it():
    with pytest.raises(ConfigError) as exc:
        load_config({"TOGGL_API_KEY": VALID_KEY})
    message = str(exc.value)
    assert "TOGGL_ORG_ID" in message
    assert "focus.toggl.com/" in message


def test_track_v9_token_is_rejected_with_a_pointer_to_the_other_server():
    with pytest.raises(ConfigError) as exc:
        load_config({
            "TOGGL_API_KEY": "1971800d4d82861d8f2c1651fea4d212",
            "TOGGL_ORG_ID": "1",
        })
    message = str(exc.value)
    assert "Track v9" in message
    assert "toggl_sk_" in message
    assert "vontell/toggl-track-mcp" in message


def test_unrecognised_key_format_is_rejected():
    with pytest.raises(ConfigError, match="toggl_sk_"):
        load_config({"TOGGL_API_KEY": "nonsense", "TOGGL_ORG_ID": "1"})


def test_whitespace_is_stripped():
    cfg = load_config({
        "TOGGL_API_KEY": f"  {VALID_KEY}  ",
        "TOGGL_ORG_ID": " 21631262 ",
    })
    assert cfg.api_key == VALID_KEY
    assert cfg.org_id == "21631262"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toggl_focus_mcp.config'`

- [ ] **Step 4: Write the implementation**

`toggl_focus_mcp/config.py`:

```python
"""Environment loading and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

DEFAULT_API_BASE = "https://focus.toggl.com/api"

# A Toggl Track v9 token: 32 hex characters, no prefix.
TRACK_V9_TOKEN = re.compile(r"^[0-9a-f]{32}$")

# A Toggl 2.0 key.
FOCUS_KEY_PREFIX = "toggl_sk_"

TRACK_TOKEN_MESSAGE = (
    "That looks like a Toggl Track v9 API token, not a Toggl 2.0 key.\n"
    "This server needs a key starting with toggl_sk_ from your Toggl 2.0 settings.\n"
    "For Track v9 accounts, use github.com/vontell/toggl-track-mcp instead."
)

ORG_ID_MESSAGE = (
    "TOGGL_ORG_ID is required and cannot be discovered through the API.\n"
    "Open Toggl 2.0 in a browser and read it from the URL:\n"
    "  https://focus.toggl.com/{organization_id}/workspaces/{workspace_id}/calendar"
)


class ConfigError(Exception):
    """Raised when the environment is missing or malformed."""


@dataclass(frozen=True)
class Config:
    api_key: str
    org_id: str
    workspace_id: str | None
    api_base: str


def load_config(env: Mapping[str, str]) -> Config:
    """Build a Config from environment values, or raise ConfigError."""
    api_key = (env.get("TOGGL_API_KEY") or "").strip()
    if not api_key:
        raise ConfigError("TOGGL_API_KEY is required. Create one in your Toggl 2.0 settings.")

    if TRACK_V9_TOKEN.match(api_key):
        raise ConfigError(TRACK_TOKEN_MESSAGE)

    if not api_key.startswith(FOCUS_KEY_PREFIX):
        raise ConfigError(
            f"TOGGL_API_KEY does not look like a Toggl 2.0 key. Expected it to start with {FOCUS_KEY_PREFIX}."
        )

    org_id = (env.get("TOGGL_ORG_ID") or "").strip()
    if not org_id:
        raise ConfigError(ORG_ID_MESSAGE)

    workspace_id = (env.get("TOGGL_WORKSPACE_ID") or "").strip() or None
    api_base = ((env.get("TOGGL_API_BASE") or "").strip() or DEFAULT_API_BASE).rstrip("/")

    return Config(
        api_key=api_key,
        org_id=org_id,
        workspace_id=workspace_id,
        api_base=api_base,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS, 9 tests

- [ ] **Step 6: Commit**

```bash
git add requirements.txt requirements-dev.txt pytest.ini toggl_focus_mcp/ tests/
git commit -m "Add configuration loading with Track v9 token detection"
```

---

### Task 2: HTTP client core

**Files:**
- Create: `toggl_focus_mcp/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: `Config` from Task 1
- Produces: `FocusAPIError(Exception)` with attributes `status: int` and `message: str`; `to_rfc3339(dt: datetime) -> str`; `FocusClient(config: Config, http: httpx.AsyncClient)` with property `scope: str` and method `async request(method: str, path: str, *, params: dict | None = None, json: dict | None = None) -> Any | None`

- [ ] **Step 1: Write the failing tests**

`tests/test_client.py`:

```python
from datetime import datetime, timezone

import httpx
import pytest
import respx

from toggl_focus_mcp.client import FocusAPIError, FocusClient, to_rfc3339
from toggl_focus_mcp.config import Config

CONFIG = Config(
    api_key="toggl_sk_" + "a" * 32,
    org_id="21631262",
    workspace_id="21630499",
    api_base="https://focus.toggl.com/api",
)

SCOPE = "https://focus.toggl.com/api/organizations/21631262/workspaces/21630499"


def make_client(http: httpx.AsyncClient) -> FocusClient:
    return FocusClient(CONFIG, http)


def test_to_rfc3339_adds_utc_to_naive_datetime():
    assert to_rfc3339(datetime(2026, 7, 28, 0, 0, 0)) == "2026-07-28T00:00:00Z"


def test_to_rfc3339_normalises_aware_datetime_to_utc():
    aware = datetime(2026, 7, 28, 0, 0, 0, tzinfo=timezone.utc)
    assert to_rfc3339(aware) == "2026-07-28T00:00:00Z"


def test_scope_builds_org_and_workspace_prefix():
    client = FocusClient(CONFIG, httpx.AsyncClient())
    assert client.scope == SCOPE


@respx.mock
async def test_request_sends_bearer_token():
    route = respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    async with httpx.AsyncClient() as http:
        await make_client(http).request("GET", "/tracking/current")
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {CONFIG.api_key}"


@respx.mock
async def test_request_returns_parsed_json():
    respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(200, json={"id": 33579428, "description": "writing"})
    )
    async with httpx.AsyncClient() as http:
        result = await make_client(http).request("GET", "/tracking/current")
    assert result == {"id": 33579428, "description": "writing"}


@respx.mock
async def test_204_returns_none_without_parsing_body():
    respx.get(f"{SCOPE}/tracking/current").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        assert await make_client(http).request("GET", "/tracking/current") is None


@respx.mock
async def test_401_mentions_key_revocation():
    respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(401, json={"error": "invalid_session"})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(FocusAPIError) as exc:
            await make_client(http).request("GET", "/tracking/current")
    assert exc.value.status == 401
    assert "revokes" in str(exc.value)


@respx.mock
async def test_403_reports_permissions():
    respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(403, json={"error_description": "forbidden"})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(FocusAPIError) as exc:
            await make_client(http).request("GET", "/tracking/current")
    assert exc.value.status == 403


@respx.mock
async def test_error_body_description_is_surfaced():
    respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(400, json={"error_description": "bad dates"})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(FocusAPIError, match="bad dates"):
            await make_client(http).request("GET", "/tracking/current")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toggl_focus_mcp.client'`

- [ ] **Step 3: Write the implementation**

`toggl_focus_mcp/client.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_client.py -v`
Expected: PASS, 9 tests

- [ ] **Step 5: Commit**

```bash
git add toggl_focus_mcp/client.py tests/test_client.py
git commit -m "Add Focus API HTTP client with 204 and error handling"
```

---

### Task 3: Tracking and time entry methods

**Files:**
- Modify: `toggl_focus_mcp/client.py`
- Modify: `tests/test_client.py`

**Interfaces:**
- Consumes: `FocusClient.request` and `to_rfc3339` from Task 2
- Produces: on `FocusClient`, the methods `async get_current_timer() -> dict | None`, `async start_timer(description: str, project_id: int | None = None) -> dict`, `async stop_timer() -> dict | None`, `async list_time_entries(date_from: datetime, date_to: datetime, per_page: int = 50) -> list[dict]`, `async resolve_workspace_id() -> str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_client.py`:

```python
@respx.mock
async def test_get_current_timer_returns_none_when_idle():
    respx.get(f"{SCOPE}/tracking/current").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        assert await make_client(http).get_current_timer() is None


@respx.mock
async def test_get_current_timer_returns_entry_when_running():
    respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(200, json={"id": 7, "description": "writing"})
    )
    async with httpx.AsyncClient() as http:
        assert (await make_client(http).get_current_timer())["description"] == "writing"


@respx.mock
async def test_start_timer_sends_required_type_field():
    route = respx.post(f"{SCOPE}/tracking/start").mock(
        return_value=httpx.Response(200, json={"id": 7})
    )
    async with httpx.AsyncClient() as http:
        await make_client(http).start_timer("writing docs")
    body = json_body(route)
    assert body["type"] == "activity"
    assert body["description"] == "writing docs"
    assert "project_id" not in body


@respx.mock
async def test_start_timer_includes_project_when_given():
    route = respx.post(f"{SCOPE}/tracking/start").mock(
        return_value=httpx.Response(200, json={"id": 7})
    )
    async with httpx.AsyncClient() as http:
        await make_client(http).start_timer("writing", project_id=1605053)
    assert json_body(route)["project_id"] == 1605053


@respx.mock
async def test_stop_timer_returns_none_when_nothing_running():
    respx.post(f"{SCOPE}/tracking/stop").mock(
        return_value=httpx.Response(404, json={"error": "not tracking"})
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).stop_timer() is None


@respx.mock
async def test_stop_timer_returns_the_stopped_entry():
    respx.post(f"{SCOPE}/tracking/stop").mock(
        return_value=httpx.Response(200, json={"id": 7, "duration": 1800})
    )
    async with httpx.AsyncClient() as http:
        assert (await make_client(http).stop_timer())["duration"] == 1800


@respx.mock
async def test_list_time_entries_sends_rfc3339_dates():
    route = respx.get(f"{SCOPE}/time-entries").mock(
        return_value=httpx.Response(200, json={"page": 1, "per_page": 50, "data": []})
    )
    async with httpx.AsyncClient() as http:
        await make_client(http).list_time_entries(
            datetime(2026, 7, 28), datetime(2026, 8, 27)
        )
    params = route.calls.last.request.url.params
    assert params["date_from"] == "2026-07-28T00:00:00Z"
    assert params["date_to"] == "2026-08-27T00:00:00Z"


@respx.mock
async def test_list_time_entries_unwraps_the_data_page():
    respx.get(f"{SCOPE}/time-entries").mock(
        return_value=httpx.Response(
            200, json={"page": 1, "per_page": 50, "data": [{"id": 1}, {"id": 2}]}
        )
    )
    async with httpx.AsyncClient() as http:
        entries = await make_client(http).list_time_entries(
            datetime(2026, 7, 28), datetime(2026, 8, 27)
        )
    assert [e["id"] for e in entries] == [1, 2]


@respx.mock
async def test_resolve_workspace_id_reads_current_workspace():
    respx.get("https://focus.toggl.com/api/users/me/settings").mock(
        return_value=httpx.Response(200, json={"current_workspace_id": 21630499})
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).resolve_workspace_id() == "21630499"
```

Add this helper near the top of the file, below `make_client`:

```python
import json as jsonlib


def json_body(route) -> dict:
    return jsonlib.loads(route.calls.last.request.content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_client.py -v -k "timer or entries or workspace"`
Expected: FAIL with `AttributeError: 'FocusClient' object has no attribute 'get_current_timer'`

- [ ] **Step 3: Write the implementation**

Append these methods to `FocusClient` in `toggl_focus_mcp/client.py`:

```python
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
    ) -> list[dict]:
        """Entries in a window. Both bounds are required by the API."""
        page = await self.request(
            "GET",
            "/time-entries",
            params={
                "date_from": to_rfc3339(date_from),
                "date_to": to_rfc3339(date_to),
                "per_page": per_page,
                "include_taskless": "true",
            },
        )
        return (page or {}).get("data", [])

    async def resolve_workspace_id(self) -> str:
        """Look up the default workspace when none is configured."""
        response = await self._http.get(
            f"{self._config.api_base}/users/me/settings",
            headers={"Authorization": f"Bearer {self._config.api_key}"},
        )
        settings = self._handle(response) or {}
        return str(settings["current_workspace_id"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_client.py -v`
Expected: PASS, 18 tests

- [ ] **Step 5: Commit**

```bash
git add toggl_focus_mcp/client.py tests/test_client.py
git commit -m "Add tracking and time entry client methods"
```

---

### Task 4: Formatting

**Files:**
- Create: `toggl_focus_mcp/formatting.py`
- Test: `tests/test_formatting.py`

**Interfaces:**
- Consumes: nothing, these are pure functions over plain dicts
- Produces: `format_duration(seconds: int) -> str`, `format_current_timer(entry: dict | None, now: datetime) -> str`, `format_time_entries(entries: list[dict]) -> str`, `format_stopped_timer(entry: dict | None) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_formatting.py`:

```python
from datetime import datetime, timezone

from toggl_focus_mcp.formatting import (
    format_current_timer,
    format_duration,
    format_stopped_timer,
    format_time_entries,
)

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_format_duration_seconds_only():
    assert format_duration(45) == "45s"


def test_format_duration_minutes():
    assert format_duration(90) == "1m 30s"


def test_format_duration_hours():
    assert format_duration(3661) == "1h 1m"


def test_format_duration_zero():
    assert format_duration(0) == "0s"


def test_no_timer_running():
    assert format_current_timer(None, NOW) == "No timer is currently running."


def test_running_timer_shows_description_and_elapsed():
    entry = {"description": "writing docs", "start": "2026-08-27T11:30:00Z"}
    result = format_current_timer(entry, NOW)
    assert "writing docs" in result
    assert "30m 0s" in result


def test_running_timer_without_description():
    entry = {"description": "", "start": "2026-08-27T11:30:00Z"}
    assert "(no description)" in format_current_timer(entry, NOW)


def test_empty_time_entries():
    assert format_time_entries([]) == "No time entries in that period."


def test_time_entries_listed_with_duration():
    entries = [
        {
            "description": "#ZL# Brady / Spencer",
            "planned_start": "2026-08-26T17:00:00Z",
            "planned_duration": 1800,
        }
    ]
    result = format_time_entries(entries)
    assert "#ZL# Brady / Spencer" in result
    assert "30m 0s" in result
    assert "2026-08-26" in result


def test_time_entries_reports_the_total():
    entries = [
        {"description": "a", "planned_start": "2026-08-26T17:00:00Z", "planned_duration": 1800},
        {"description": "b", "planned_start": "2026-08-26T18:00:00Z", "planned_duration": 1800},
    ]
    assert "Total: 1h 0m" in format_time_entries(entries)


def test_stopped_timer_when_nothing_ran():
    assert format_stopped_timer(None) == "No timer was running."


def test_stopped_timer_reports_duration():
    assert "30m 0s" in format_stopped_timer({"description": "writing", "duration": 1800})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_formatting.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toggl_focus_mcp.formatting'`

- [ ] **Step 3: Write the implementation**

`toggl_focus_mcp/formatting.py`:

```python
"""Turn Focus API payloads into text for the model. Pure functions only."""

from __future__ import annotations

from datetime import datetime, timezone

NO_DESCRIPTION = "(no description)"


def format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def _parse(value: str) -> datetime:
    """Parse an API timestamp. Handles the Z suffix and fractional seconds."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _describe(entry: dict) -> str:
    return entry.get("description") or NO_DESCRIPTION


def format_current_timer(entry: dict | None, now: datetime) -> str:
    if entry is None:
        return "No timer is currently running."
    started = _parse(entry["start"])
    elapsed = int((now - started).total_seconds())
    return f"Running: {_describe(entry)}\nElapsed: {format_duration(elapsed)}"


def format_stopped_timer(entry: dict | None) -> str:
    if entry is None:
        return "No timer was running."
    duration = entry.get("duration") or 0
    return f"Stopped: {_describe(entry)}\nDuration: {format_duration(duration)}"


def format_time_entries(entries: list[dict]) -> str:
    if not entries:
        return "No time entries in that period."

    lines = []
    total = 0
    for entry in entries:
        seconds = entry.get("planned_duration") or entry.get("duration") or 0
        total += seconds
        start = entry.get("planned_start") or entry.get("start")
        day = _parse(start).astimezone(timezone.utc).strftime("%Y-%m-%d") if start else "unknown"
        lines.append(f"  {day}  {format_duration(seconds):>8}  {_describe(entry)}")

    header = f"{len(entries)} time entries"
    return f"{header}\n" + "\n".join(lines) + f"\n\nTotal: {format_duration(total)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_formatting.py -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Commit**

```bash
git add toggl_focus_mcp/formatting.py tests/test_formatting.py
git commit -m "Add output formatting for timers and time entries"
```

---

### Task 5: MCP tools and server entry point

**Files:**
- Create: `toggl_focus_mcp/tools.py`
- Create: `toggl_focus_mcp/server.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `FocusClient` from Tasks 2 and 3, formatters from Task 4, `load_config` from Task 1
- Produces: `register_tools(mcp: MCPServer, client: FocusClient) -> None`; `build_server() -> MCPServer`; `main() -> None`

The four tools are `get_current_timer()`, `start_timer(description, project_id=None)`, `stop_current_timer()`, and `get_time_entries(days=7)`.

- [ ] **Step 1: Write the failing tests**

`tests/test_tools.py`:

```python
from datetime import datetime, timezone

import pytest
from mcp.server.mcpserver import MCPServer

from toggl_focus_mcp.tools import register_tools


class FakeClient:
    """Stands in for FocusClient. Records calls, returns canned payloads."""

    def __init__(self, current=None, entries=None, stopped=None):
        self._current = current
        self._entries = entries or []
        self._stopped = stopped
        self.started = None
        self.entry_window = None

    async def get_current_timer(self):
        return self._current

    async def start_timer(self, description, project_id=None):
        self.started = (description, project_id)
        return {"id": 1, "description": description}

    async def stop_timer(self):
        return self._stopped

    async def list_time_entries(self, date_from, date_to, per_page=50):
        self.entry_window = (date_from, date_to)
        return self._entries


async def call(mcp: MCPServer, name: str, args: dict) -> str:
    result = await mcp.call_tool(name, args)
    return result[0][0].text


@pytest.fixture
def server_and_client():
    def build(**kwargs):
        mcp = MCPServer("test")
        client = FakeClient(**kwargs)
        register_tools(mcp, client)
        return mcp, client

    return build


async def test_all_four_tools_are_registered(server_and_client):
    mcp, _ = server_and_client()
    names = {tool.name for tool in await mcp.list_tools()}
    assert names == {
        "get_current_timer",
        "start_timer",
        "stop_current_timer",
        "get_time_entries",
    }


async def test_get_current_timer_reports_idle(server_and_client):
    mcp, _ = server_and_client(current=None)
    assert "No timer is currently running" in await call(mcp, "get_current_timer", {})


async def test_get_current_timer_reports_running(server_and_client):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mcp, _ = server_and_client(current={"description": "writing", "start": now})
    assert "writing" in await call(mcp, "get_current_timer", {})


async def test_start_timer_passes_description_through(server_and_client):
    mcp, client = server_and_client()
    await call(mcp, "start_timer", {"description": "writing docs"})
    assert client.started == ("writing docs", None)


async def test_start_timer_passes_project_id(server_and_client):
    mcp, client = server_and_client()
    await call(mcp, "start_timer", {"description": "writing", "project_id": 1605053})
    assert client.started == ("writing", 1605053)


async def test_stop_timer_when_nothing_running(server_and_client):
    mcp, _ = server_and_client(stopped=None)
    assert "No timer was running" in await call(mcp, "stop_current_timer", {})


async def test_get_time_entries_uses_the_requested_window(server_and_client):
    mcp, client = server_and_client(entries=[])
    await call(mcp, "get_time_entries", {"days": 3})
    date_from, date_to = client.entry_window
    assert (date_to - date_from).days == 3


async def test_get_time_entries_formats_results(server_and_client):
    mcp, _ = server_and_client(entries=[
        {"description": "standup", "planned_start": "2026-08-26T17:00:00Z", "planned_duration": 1800}
    ])
    assert "standup" in await call(mcp, "get_time_entries", {"days": 7})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toggl_focus_mcp.tools'`

- [ ] **Step 3: Write the tools module**

`toggl_focus_mcp/tools.py`:

```python
"""MCP tool definitions. Each one calls the client and formats the result."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.server.mcpserver import MCPServer

from .client import FocusClient
from .formatting import (
    format_current_timer,
    format_stopped_timer,
    format_time_entries,
)


def register_tools(mcp: MCPServer, client: FocusClient) -> None:
    """Attach the v1 tools to the server."""

    @mcp.tool()
    async def get_current_timer() -> str:
        """Get the currently running Toggl timer, if any."""
        entry = await client.get_current_timer()
        return format_current_timer(entry, datetime.now(timezone.utc))

    @mcp.tool()
    async def start_timer(description: str, project_id: int | None = None) -> str:
        """Start a Toggl timer. Any timer already running is stopped first."""
        entry = await client.start_timer(description, project_id)
        return f"Started: {entry.get('description') or '(no description)'}"

    @mcp.tool()
    async def stop_current_timer() -> str:
        """Stop the running Toggl timer."""
        return format_stopped_timer(await client.stop_timer())

    @mcp.tool()
    async def get_time_entries(days: int = 7) -> str:
        """List Toggl time entries from the last N days."""
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(days=days)
        entries = await client.list_time_entries(date_from, date_to)
        return format_time_entries(entries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tools.py -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Write the server entry point**

`toggl_focus_mcp/server.py`:

```python
"""Entry point. Wires configuration, client, and tools onto an MCPServer."""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from .client import FocusClient
from .config import ConfigError, load_config
from .tools import register_tools


def build_server() -> MCPServer:
    """Build the configured server, or exit with a readable message."""
    load_dotenv()
    try:
        config = load_config(os.environ)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

    http = httpx.AsyncClient(timeout=30.0)
    client = FocusClient(config, http)

    mcp = MCPServer("Toggl Focus")
    register_tools(mcp, client)
    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
```

Note the config error goes to **stderr**, never stdout. Stdout carries JSON-RPC and any stray write corrupts the stream.

- [ ] **Step 6: Run the whole suite**

Run: `pytest -v`
Expected: PASS, 48 tests

- [ ] **Step 7: Commit**

```bash
git add toggl_focus_mcp/tools.py toggl_focus_mcp/server.py tests/test_tools.py
git commit -m "Add MCP tools and server entry point"
```

---

### Task 6: Documentation, license, and live verification

**Files:**
- Create: `README.md`
- Create: `.env.example`
- Create: `LICENSE`

**Interfaces:**
- Consumes: everything from Tasks 1 through 5
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write `.env.example`**

```
# Toggl 2.0 API key. Create one in your Toggl 2.0 settings.
# Only one key is active per user: creating a new key revokes the previous one.
TOGGL_API_KEY=toggl_sk_your_key_here

# Organization ID. Required, and not discoverable through the API.
# Read it from your Toggl 2.0 URL:
#   https://focus.toggl.com/{organization_id}/workspaces/{workspace_id}/calendar
TOGGL_ORG_ID=

# Optional. Defaults to the current_workspace_id on your account.
# TOGGL_WORKSPACE_ID=

# Optional. Point at a compatible or self-hosted backend.
# TOGGL_API_BASE=https://focus.toggl.com/api
```

- [ ] **Step 2: Write the LICENSE**

Standard MIT license text, copyright 2026 Brady Labrum.

- [ ] **Step 3: Write the README**

Cover, in this order: what it is and which Toggl it serves, the Track v9 distinction with a link to `vontell/toggl-track-mcp`, installation, how to find the organization ID, the Claude Desktop config block, the four tools, and a development section covering `pytest`.

The Claude Desktop block:

```json
{
  "mcpServers": {
    "Toggl Focus": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "toggl_focus_mcp.server"],
      "env": {
        "TOGGL_API_KEY": "toggl_sk_your_key_here",
        "TOGGL_ORG_ID": "your_org_id"
      }
    }
  }
}
```

State plainly that this server does not work with Toggl Track v9 tokens, and that the server says so at startup if it sees one.

- [ ] **Step 4: Verify against the live API**

This step needs real credentials and stays out of the automated suite.

```bash
TOGGL_API_KEY=<real key> TOGGL_ORG_ID=21631262 TOGGL_WORKSPACE_ID=21630499 \
  .venv/bin/python -c "
import asyncio, os, httpx
from toggl_focus_mcp.config import load_config
from toggl_focus_mcp.client import FocusClient
async def main():
    cfg = load_config(os.environ)
    async with httpx.AsyncClient() as http:
        c = FocusClient(cfg, http)
        print('current timer:', await c.get_current_timer())
        from datetime import datetime, timedelta, timezone
        to = datetime.now(timezone.utc)
        print('entries:', len(await c.list_time_entries(to - timedelta(days=30), to)))
asyncio.run(main())
"
```

Expected: `current timer: None` when idle, and a non-negative entry count. A 401 means the key was revoked by a later key creation.

- [ ] **Step 5: Verify the stdio handshake**

```bash
printf '%s\n' \
 '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"1"}}}' \
 '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
 '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
 | TOGGL_API_KEY=<real key> TOGGL_ORG_ID=21631262 .venv/bin/python -m toggl_focus_mcp.server
```

Expected: the first stdout byte is `{`, and `tools/list` returns 4 tools.

- [ ] **Step 6: Commit**

```bash
git add README.md .env.example LICENSE
git commit -m "Add README, license, and environment example"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task. Config surface and the four env vars are Task 1. Bearer auth, base URL, scoped paths, the 204 behaviour, and error mapping are Task 2. RFC3339 dates and the four endpoints are Task 3. The two documented gaps, `get_workspaces` and `get_time_summary`, are correctly absent. The Track v9 token detection the user asked for is Task 1, tested by `test_track_v9_token_is_rejected_with_a_pointer_to_the_other_server`.

**Placeholder scan.** No TBD or TODO. Every code step carries runnable code. The one prose-only step is the README in Task 6, where the required sections are enumerated.

**Type consistency.** `Config` fields match across Tasks 1, 2, and 6. `FocusClient.request` keeps the same signature in Tasks 2 and 3. `format_current_timer(entry, now)` takes `now` in both Task 4 and Task 5. `stop_timer` returns `dict | None` in Task 3 and `format_stopped_timer` accepts `dict | None` in Task 4.

**One known risk.** `start_timer` and `stop_timer` are covered by stubbed tests only. Neither has been exercised against the live API, because doing so would start and stop a real timer on a live account. Task 6 Step 4 covers the read paths. Starting a real timer should be a deliberate manual check.

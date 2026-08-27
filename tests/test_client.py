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

import json as jsonlib
from datetime import datetime, timezone

import httpx
import pytest
import respx

from toggl_focus_mcp.client import MAX_PAGES, FocusAPIError, FocusClient, to_rfc3339
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


def json_body(route) -> dict:
    return jsonlib.loads(route.calls.last.request.content)


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
    message = str(exc.value)
    assert "permission" in message
    assert "TOGGL_ORG_ID" in message


@respx.mock
async def test_error_body_description_is_surfaced():
    respx.get(f"{SCOPE}/tracking/current").mock(
        return_value=httpx.Response(400, json={"error_description": "bad dates"})
    )
    async with httpx.AsyncClient() as http:
        with pytest.raises(FocusAPIError, match="bad dates"):
            await make_client(http).request("GET", "/tracking/current")


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
        entries, truncated = await make_client(http).list_time_entries(
            datetime(2026, 7, 28), datetime(2026, 8, 27)
        )
    assert [e["id"] for e in entries] == [1, 2]
    assert truncated is False


@respx.mock
async def test_list_time_entries_stops_after_one_short_page():
    """A page smaller than per_page is the last one. Do not ask for another."""
    route = respx.get(f"{SCOPE}/time-entries").mock(
        return_value=httpx.Response(200, json={"page": 1, "per_page": 2, "data": [{"id": 1}]})
    )
    async with httpx.AsyncClient() as http:
        await make_client(http).list_time_entries(
            datetime(2026, 7, 28), datetime(2026, 8, 27), per_page=2
        )
    assert route.call_count == 1


@respx.mock
async def test_list_time_entries_walks_every_page():
    pages = [
        httpx.Response(200, json={"page": 1, "per_page": 2, "data": [{"id": 1}, {"id": 2}]}),
        httpx.Response(200, json={"page": 2, "per_page": 2, "data": [{"id": 3}, {"id": 4}]}),
        httpx.Response(200, json={"page": 3, "per_page": 2, "data": [{"id": 5}]}),
    ]
    route = respx.get(f"{SCOPE}/time-entries").mock(side_effect=pages)
    async with httpx.AsyncClient() as http:
        entries, truncated = await make_client(http).list_time_entries(
            datetime(2026, 7, 28), datetime(2026, 8, 27), per_page=2
        )
    assert [e["id"] for e in entries] == [1, 2, 3, 4, 5]
    assert truncated is False
    assert route.call_count == 3
    assert [call.request.url.params["page"] for call in route.calls] == ["1", "2", "3"]


@respx.mock
async def test_list_time_entries_flags_truncation_at_the_page_cap():
    """A full page every time means more entries exist. Say so, do not loop."""
    route = respx.get(f"{SCOPE}/time-entries").mock(
        return_value=httpx.Response(200, json={"page": 1, "per_page": 2, "data": [{"id": 1}, {"id": 2}]})
    )
    async with httpx.AsyncClient() as http:
        entries, truncated = await make_client(http).list_time_entries(
            datetime(2026, 7, 28), datetime(2026, 8, 27), per_page=2
        )
    assert truncated is True
    assert route.call_count == MAX_PAGES
    assert len(entries) == MAX_PAGES * 2


@respx.mock
async def test_resolve_workspace_id_reads_current_workspace():
    respx.get("https://focus.toggl.com/api/users/me/settings").mock(
        return_value=httpx.Response(200, json={"current_workspace_id": 21630499})
    )
    async with httpx.AsyncClient() as http:
        assert await make_client(http).resolve_workspace_id() == "21630499"


@respx.mock
async def test_request_resolves_workspace_when_not_configured():
    config = Config(
        api_key=CONFIG.api_key,
        org_id="21631262",
        workspace_id=None,
        api_base="https://focus.toggl.com/api",
    )
    respx.get("https://focus.toggl.com/api/users/me/settings").mock(
        return_value=httpx.Response(200, json={"current_workspace_id": 21630499})
    )
    route = respx.get(f"{SCOPE}/tracking/current").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        assert await FocusClient(config, http).request("GET", "/tracking/current") is None
    assert route.called


@respx.mock
async def test_workspace_is_resolved_only_once():
    config = Config(
        api_key=CONFIG.api_key,
        org_id="21631262",
        workspace_id=None,
        api_base="https://focus.toggl.com/api",
    )
    settings = respx.get("https://focus.toggl.com/api/users/me/settings").mock(
        return_value=httpx.Response(200, json={"current_workspace_id": 21630499})
    )
    respx.get(f"{SCOPE}/tracking/current").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        client = FocusClient(config, http)
        await client.request("GET", "/tracking/current")
        await client.request("GET", "/tracking/current")
    assert settings.call_count == 1

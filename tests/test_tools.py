from datetime import datetime, timezone

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError

from toggl_focus_mcp.client import FocusAPIError, TimeEntryResult
from toggl_focus_mcp.tools import register_tools

# Distinguishes "the test did not configure this" from "the API returned None".
UNSET = object()


class FakeClient:
    """Stands in for FocusClient. Records calls, returns canned payloads."""

    def __init__(self, current=None, entries=None, stopped=None, started=UNSET,
                 truncated=False, error=None):
        self._current = current
        self._entries = entries or []
        self._stopped = stopped
        self._started = started
        self._truncated = truncated
        self._error = error
        self.started = None
        self.entry_window = None

    def _raise_if_configured(self):
        if self._error is not None:
            raise self._error

    async def get_current_timer(self):
        self._raise_if_configured()
        return self._current

    async def start_timer(self, description, project_id=None):
        self.started = (description, project_id)
        self._raise_if_configured()
        if self._started is not UNSET:
            return self._started
        return {"id": 1, "description": description}

    async def stop_timer(self):
        self._raise_if_configured()
        return self._stopped

    async def list_time_entries(self, date_from, date_to, per_page=50):
        self.entry_window = (date_from, date_to)
        self._raise_if_configured()
        return TimeEntryResult(self._entries, self._truncated)


async def call(mcp: MCPServer, name: str, args: dict) -> str:
    result = await mcp.call_tool(name, args)
    return result.content[0].text


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


async def test_get_time_entries_rejects_negative_days(server_and_client):
    mcp, client = server_and_client(entries=[])
    result = await call(mcp, "get_time_entries", {"days": -1})
    assert "days must be zero or greater" in result
    assert client.entry_window is None


async def test_get_time_entries_allows_zero_days(server_and_client):
    mcp, client = server_and_client(entries=[])
    result = await call(mcp, "get_time_entries", {"days": 0})
    assert client.entry_window is not None
    assert "No time entries in that period." in result


async def test_get_time_entries_warns_when_truncated(server_and_client):
    mcp, _ = server_and_client(
        entries=[{"description": "standup", "planned_start": "2026-08-26T17:00:00Z",
                  "planned_duration": 1800}],
        truncated=True,
    )
    assert "incomplete" in await call(mcp, "get_time_entries", {"days": 30})


async def test_start_timer_reports_the_description_the_api_returned(server_and_client):
    mcp, _ = server_and_client(started={"id": 1, "description": "writing docs"})
    assert await call(mcp, "start_timer", {"description": "writing docs"}) == "Started: writing docs"


async def test_start_timer_survives_a_bodyless_response(server_and_client):
    """request() returns None on a 204. The tool must not call .get on it."""
    mcp, _ = server_and_client(started=None)
    assert "started" in (await call(mcp, "start_timer", {"description": "writing"})).lower()


async def test_stop_timer_reports_the_stopped_entry(server_and_client):
    mcp, _ = server_and_client(stopped={"description": "writing", "duration": 1800})
    result = await call(mcp, "stop_current_timer", {})
    assert "writing" in result
    assert "30m 0s" in result


# Every tool must turn a FocusAPIError into a ToolError. Anything else is a
# crash to the SDK, which throws the message away and shows the model only
# "Error executing tool <name>".
API_ERROR_CASES = [
    ("get_current_timer", {}),
    ("start_timer", {"description": "writing"}),
    ("stop_current_timer", {}),
    ("get_time_entries", {"days": 7}),
]


@pytest.mark.parametrize("name,args", API_ERROR_CASES)
async def test_api_errors_reach_the_model_as_tool_errors(server_and_client, name, args):
    error = FocusAPIError(401, "creating a new key revokes the previous one")
    mcp, _ = server_and_client(error=error)
    with pytest.raises(ToolError) as exc:
        await call(mcp, name, args)
    message = str(exc.value)
    assert "creating a new key revokes the previous one" in message
    assert "401" in message
    # The SDK prefixes a ToolError with "Error executing tool <name>: " and keeps
    # the text. A crash gets that prefix and nothing else, which is the whole bug.
    assert message != f"Error executing tool {name}"


@pytest.mark.parametrize("name,args", API_ERROR_CASES)
async def test_api_errors_are_not_reported_as_crashes(server_and_client, name, args):
    """UnexpectedToolError is the SDK's crash wrapper. These are not crashes."""
    mcp, _ = server_and_client(error=FocusAPIError(500, "upstream exploded"))
    with pytest.raises(ToolError) as exc:
        await call(mcp, name, args)
    assert not isinstance(exc.value, UnexpectedToolError)
    assert "upstream exploded" in str(exc.value)


@pytest.mark.parametrize("name,args", API_ERROR_CASES)
async def test_a_real_crash_still_loses_its_message(server_and_client, name, args):
    """Contrast case. This is what every API error used to look like."""
    mcp, _ = server_and_client(error=RuntimeError("secret internal detail"))
    with pytest.raises(UnexpectedToolError) as exc:
        await call(mcp, name, args)
    assert str(exc.value) == f"Error executing tool {name}"

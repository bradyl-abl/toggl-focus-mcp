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

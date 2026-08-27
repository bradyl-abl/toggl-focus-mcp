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

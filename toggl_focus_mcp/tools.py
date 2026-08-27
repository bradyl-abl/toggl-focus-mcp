"""MCP tool definitions. Each one calls the client and formats the result."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import FocusAPIError, FocusClient
from .formatting import (
    format_current_timer,
    format_started_timer,
    format_stopped_timer,
    format_time_entries,
)


def _tool_error(error: FocusAPIError) -> ToolError:
    """Re-package an API failure so the model actually reads the message.

    The SDK treats any exception other than ToolError as a crash and replaces
    the text with "Error executing tool <name>". The client already builds a
    useful message for each status, so hand that over instead of losing it.
    """
    return ToolError(f"Toggl API error {error.status}: {error.message}")


def register_tools(mcp: MCPServer, client: FocusClient) -> None:
    """Attach the v1 tools to the server."""

    @mcp.tool()
    async def get_current_timer() -> str:
        """Get the Toggl timer that is running right now.

        Returns the description and how long it has been running. If nothing is
        being tracked, that is reported as a normal result, not a failure.
        """
        try:
            entry = await client.get_current_timer()
        except FocusAPIError as error:
            raise _tool_error(error) from error
        return format_current_timer(entry, datetime.now(timezone.utc))

    @mcp.tool()
    async def start_timer(description: str, project_id: int | None = None) -> str:
        """Start a Toggl timer with the given description.

        Any timer already running is stopped by Toggl first, so this both
        switches tasks and starts fresh.

        project_id is Toggl's numeric ID for a project, not its name. This
        version of the server ships no tool for listing projects, so there is
        no way to look an ID up here. Only pass project_id when the user has
        given you the number. Never guess it and never infer it from a project
        name: this writes to the user's real timesheet, and a wrong ID files
        their time against the wrong project. When the user names a project but
        gives no ID, start the timer without project_id and tell them the
        project was not set.
        """
        try:
            entry = await client.start_timer(description, project_id)
        except FocusAPIError as error:
            raise _tool_error(error) from error
        return format_started_timer(entry)

    @mcp.tool()
    async def stop_current_timer() -> str:
        """Stop the Toggl timer that is currently running.

        Reports the description and duration of the timer that was stopped.
        Finding that no timer was running is a normal outcome, not an error:
        report it plainly and do not retry.
        """
        try:
            entry = await client.stop_timer()
        except FocusAPIError as error:
            raise _tool_error(error) from error
        return format_stopped_timer(entry)

    @mcp.tool()
    async def get_time_entries(days: int = 7) -> str:
        """List Toggl time entries from a rolling window ending now.

        The window is the last `days` times 24 hours counting back from the
        current moment. These are not calendar days: days=1 means the last 24
        hours, which is not the same as today, and days=0 returns an empty
        window. For "today" or "yesterday", pick a `days` value large enough to
        cover the day you want and read the dates in the output.

        Each line shows the entry's date, its duration, and its description.
        Durations are planned durations, what the entry was scheduled for, not
        measured stopwatch time.

        If the result says the list is incomplete, the total undercounts the
        period. Ask for a shorter window in that case.
        """
        if days < 0:
            return "days must be zero or greater."
        date_to = datetime.now(timezone.utc)
        date_from = date_to - timedelta(days=days)
        try:
            entries, truncated = await client.list_time_entries(date_from, date_to)
        except FocusAPIError as error:
            raise _tool_error(error) from error
        return format_time_entries(entries, truncated=truncated)

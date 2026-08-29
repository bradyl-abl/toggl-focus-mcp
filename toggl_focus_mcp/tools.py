"""MCP tool definitions. Each one calls the client and formats the result."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .client import EMPTY_LOOKUP, FocusAPIError, FocusClient, ProjectLookup
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


DAY_FORMAT = "%Y-%m-%d"


def _parse_day(value: str) -> date | None:
    """Read a YYYY-MM-DD date, or None when it is not one."""
    try:
        return datetime.strptime(value.strip(), DAY_FORMAT).date()
    except ValueError:
        return None


def _day_bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """Turn two calendar dates into an inclusive UTC window.

    Entries are rendered in UTC, so the window is built in UTC too. Anything
    else puts entries in the output that fall outside the dates asked for.
    """
    return (
        datetime.combine(first, time.min, tzinfo=timezone.utc),
        datetime.combine(last, time.max, tzinfo=timezone.utc),
    )


def register_tools(mcp: MCPServer, client: FocusClient) -> None:
    """Attach the v1 tools to the server."""

    async def lookup_for(entries: list[dict]) -> ProjectLookup:
        """Project and client names for whatever these entries point at.

        Skips the extra calls when nothing is filed against a project. A
        failure here loses only the labels, so it falls back to no names
        instead of failing a listing that already came back fine.
        """
        if not any(entry.get("project_id") for entry in entries):
            return EMPTY_LOOKUP
        try:
            return await client.project_lookup()
        except FocusAPIError:
            return EMPTY_LOOKUP

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
        lookup = await lookup_for([entry] if entry else [])
        return format_current_timer(
            entry,
            datetime.now(timezone.utc),
            project_names=lookup.project_names,
            client_names=lookup.client_names,
        )

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
    async def get_time_entries(
        days: int = 7,
        date_from: str | None = None,
        date_to: str | None = None,
        include_planned: bool = False,
    ) -> str:
        """List Toggl time entries, either from a rolling window or exact dates.

        By default this returns only time the user actually tracked. That is
        the number to quote for "how long did I work on X".

        Two ways to pick the period, and date_from and date_to win when given:

        - `days` is a rolling window ending now: the last `days` times 24 hours
          counting back from the current moment. These are not calendar days.
          days=1 means the last 24 hours, which is not the same as today, and
          days=0 returns an empty window.
        - `date_from` and `date_to` are calendar dates in YYYY-MM-DD form, in
          UTC, and both ends are included. Pass them together, both or neither.
          Use these for "August", "last week", or any exact range. A single day
          is the same date in both.

        Toggl returns two different kinds of record from one endpoint, and this
        tool keeps them apart:

        - Tracked entries. Time the user really spent, with a measured
          duration. Always shown.
        - Planned calendar blocks. Meetings mirrored in from a connected
          calendar, carrying only a scheduled length. Nobody tracked them and
          they may never have happened, so a cancelled meeting still appears.
          Hidden unless `include_planned` is true, and counted separately when
          shown. An account with no calendar connected has none of these.

        NEVER add the tracked total to the planned total. They measure
        different things, and on a calendar-heavy account the planned figure
        dwarfs the tracked one. Quoting their sum, or quoting the planned
        figure as time worked, overstates the user's hours by a wide margin.
        Set `include_planned` only when the user asks about their schedule,
        their calendar, or meetings rather than about tracked or worked time.

        Each line shows the date, the duration, the project as
        `[client / project]` when it has one, the description, and any tags.

        If the result says the list is incomplete, the totals undercount the
        period. Ask for a shorter window in that case.
        """
        if (date_from is None) != (date_to is None):
            return "date_from and date_to go together. Pass both, as YYYY-MM-DD, or neither."

        if date_from is not None and date_to is not None:
            first, last = _parse_day(date_from), _parse_day(date_to)
            if first is None:
                return f"date_from must be a calendar date as YYYY-MM-DD. Got: {date_from}"
            if last is None:
                return f"date_to must be a calendar date as YYYY-MM-DD. Got: {date_to}"
            if last < first:
                return "date_to must fall on or after date_from."
            window_from, window_to = _day_bounds(first, last)
        else:
            if days < 0:
                return "days must be zero or greater."
            window_to = datetime.now(timezone.utc)
            window_from = window_to - timedelta(days=days)

        try:
            entries, truncated = await client.list_time_entries(window_from, window_to)
        except FocusAPIError as error:
            raise _tool_error(error) from error
        lookup = await lookup_for(entries)
        return format_time_entries(
            entries,
            truncated=truncated,
            project_names=lookup.project_names,
            client_names=lookup.client_names,
            include_planned=include_planned,
        )

"""Turn Focus API payloads into text for the model. Pure functions only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping

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
    """Parse an API timestamp into an aware datetime.

    Handles the Z suffix and fractional seconds. A value with no offset is
    read as UTC, matching what client.to_rfc3339 does on the way out. Without
    that, a naive timestamp breaks the elapsed-time subtraction and shifts the
    rendered day to whatever timezone the host machine happens to run in.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _describe(entry: dict) -> str:
    return entry.get("description") or NO_DESCRIPTION


def _project_text(
    entry: dict,
    project_names: Mapping[str, str] | None,
    client_names: Mapping[str, str] | None,
) -> str:
    """Client and project for one entry, as far as either is known.

    An entry with a project always says so. When the name lookup came back
    empty, the raw ID is still better than dropping the fact that the entry is
    filed against a project at all.
    """
    project_id = entry.get("project_id")
    if project_id is None or str(project_id).strip() == "":
        return ""
    key = str(project_id).strip()
    project = (project_names or {}).get(key)
    client = (client_names or {}).get(key)
    if project and client:
        return f"{client} / {project}"
    if project:
        return project
    if client:
        return client
    return f"project {key}"


def _tag_names(tags: object) -> list[str]:
    """Tag names out of whatever shape the API sent.

    Tags arrive as plain strings or as objects with a name. An entry that
    carries bare tag IDs has no names to print, so those are dropped rather
    than rendered as meaningless numbers.
    """
    if not isinstance(tags, list):
        return []
    names = []
    for tag in tags:
        if isinstance(tag, str) and tag.strip():
            names.append(tag.strip())
        elif isinstance(tag, dict) and tag.get("name"):
            names.append(str(tag["name"]).strip())
    return [name for name in names if name]


def _tag_text(entry: dict) -> str:
    return " ".join(f"#{name}" for name in _tag_names(entry.get("tags")))


def format_current_timer(
    entry: dict | None,
    now: datetime,
    project_names: Mapping[str, str] | None = None,
    client_names: Mapping[str, str] | None = None,
) -> str:
    if entry is None:
        return "No timer is currently running."

    lines = [f"Running: {_describe(entry)}"]
    project = _project_text(entry, project_names, client_names)
    if project:
        lines.append(f"Project: {project}")
    tags = _tag_text(entry)
    if tags:
        lines.append(f"Tags: {tags}")

    start = entry.get("start")
    if start is None:
        lines.append("Elapsed: unknown (no start time reported)")
    else:
        elapsed = int((now - _parse(start)).total_seconds())
        lines.append(f"Elapsed: {format_duration(elapsed)}")
    return "\n".join(lines)


def format_started_timer(entry: dict | None) -> str:
    """Report a timer the API just started."""
    if entry is None:
        return "Timer started. The API reported no details about it."
    return f"Started: {_describe(entry)}"


def format_stopped_timer(entry: dict | None) -> str:
    if entry is None:
        return "No timer was running."
    duration = entry.get("duration")
    if duration is None:
        # A missing field is not a zero-length timer. Say so, the same way the
        # current-timer path does when start is absent.
        return f"Stopped: {_describe(entry)}\nDuration: unknown (no duration reported)"
    return f"Stopped: {_describe(entry)}\nDuration: {format_duration(duration)}"


def is_tracked(entry: dict) -> bool:
    """Whether this is genuinely tracked time or a planned calendar block.

    A tracked entry has a real duration. A running timer has a start but no
    duration yet, and still counts. A planned block has neither: only
    planned_start and planned_duration, alongside the calendar event it
    mirrors. Toggl returns both shapes from the same endpoint, and adding
    scheduled time to worked time produces a number that is simply wrong.
    """
    if entry.get("duration") is not None:
        return True
    return entry.get("start") is not None and entry.get("calendar_event_id") is None


def _seconds(entry: dict) -> int:
    """How long this entry ran, or was scheduled for.

    A tracked entry reports what was worked, a planned block what was
    scheduled. Zero is a real value, so the fallback tests for None rather
    than truthiness: an entry that genuinely ran no time must not borrow a
    number from the other field.
    """
    if is_tracked(entry):
        primary, fallback = entry.get("duration"), entry.get("planned_duration")
    else:
        primary, fallback = entry.get("planned_duration"), entry.get("duration")
    if primary is not None:
        return primary
    return fallback if fallback is not None else 0


def _day(entry: dict) -> str:
    """The UTC day this entry belongs to."""
    if is_tracked(entry):
        start = entry.get("start") or entry.get("planned_start")
    else:
        start = entry.get("planned_start") or entry.get("start")
    if not start:
        return "unknown"
    return _parse(start).astimezone(timezone.utc).strftime("%Y-%m-%d")


def _render_entries(
    entries: list[dict],
    project_names: Mapping[str, str] | None,
    client_names: Mapping[str, str] | None,
) -> tuple[list[str], int]:
    """One line per entry, plus the total seconds across them."""
    lines = []
    total = 0
    for entry in entries:
        seconds = _seconds(entry)
        total += seconds
        day = _day(entry)

        parts = [f"  {day}", f"{format_duration(seconds):>8}"]
        project = _project_text(entry, project_names, client_names)
        if project:
            parts.append(f"[{project}]")
        parts.append(_describe(entry))
        tags = _tag_text(entry)
        if tags:
            parts.append(tags)
        lines.append("  ".join(parts))
    return lines, total


def _section(
    entries: list[dict],
    header: str,
    total_label: str,
    project_names: Mapping[str, str] | None,
    client_names: Mapping[str, str] | None,
) -> str:
    lines, total = _render_entries(entries, project_names, client_names)
    return f"{header}\n" + "\n".join(lines) + f"\n\n{total_label}: {format_duration(total)}"


def format_time_entries(
    entries: list[dict],
    truncated: bool = False,
    project_names: Mapping[str, str] | None = None,
    client_names: Mapping[str, str] | None = None,
    include_planned: bool = False,
) -> str:
    if not entries:
        return "No time entries in that period."

    tracked = [entry for entry in entries if is_tracked(entry)]
    planned = [entry for entry in entries if not is_tracked(entry)]

    sections = []
    if tracked:
        count = len(tracked)
        noun = "entry" if count == 1 else "entries"
        sections.append(
            _section(
                tracked,
                f"{count} tracked time {noun}",
                "Total tracked",
                project_names,
                client_names,
            )
        )
    else:
        sections.append("No tracked time entries in that period.")

    if planned:
        count = len(planned)
        noun = "block" if count == 1 else "blocks"
        if include_planned:
            sections.append(
                _section(
                    planned,
                    f"{count} planned calendar {noun} (scheduled, not tracked time)",
                    "Total planned",
                    project_names,
                    client_names,
                )
            )
        else:
            sections.append(
                f"{count} planned calendar {noun} in this period were left out. "
                "These mirror calendar events and were never tracked, so they are "
                "not worked time. Pass include_planned=true to list them."
            )

    body = "\n\n".join(sections)
    if truncated:
        body += (
            "\n\nWarning: this list is incomplete. Paging stopped at the page "
            "limit, so there are more entries in this period and the totals "
            "above undercount it. Ask for a shorter window."
        )
    return body

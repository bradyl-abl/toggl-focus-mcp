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


def format_current_timer(entry: dict | None, now: datetime) -> str:
    if entry is None:
        return "No timer is currently running."
    start = entry.get("start")
    if start is None:
        return f"Running: {_describe(entry)}\nElapsed: unknown (no start time reported)"
    started = _parse(start)
    elapsed = int((now - started).total_seconds())
    return f"Running: {_describe(entry)}\nElapsed: {format_duration(elapsed)}"


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


def format_time_entries(entries: list[dict]) -> str:
    if not entries:
        return "No time entries in that period."

    lines = []
    total = 0
    for entry in entries:
        seconds = entry.get("planned_duration")
        if seconds is None:
            seconds = entry.get("duration")
        if seconds is None:
            seconds = 0
        total += seconds
        start = entry.get("planned_start")
        if start is None:
            start = entry.get("start")
        day = _parse(start).astimezone(timezone.utc).strftime("%Y-%m-%d") if start else "unknown"
        lines.append(f"  {day}  {format_duration(seconds):>8}  {_describe(entry)}")

    count = len(entries)
    header = f"{count} time entry" if count == 1 else f"{count} time entries"
    return f"{header}\n" + "\n".join(lines) + f"\n\nTotal: {format_duration(total)}"

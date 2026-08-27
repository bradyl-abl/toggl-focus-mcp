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

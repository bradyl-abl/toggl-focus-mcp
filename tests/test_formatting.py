from datetime import datetime, timezone

from toggl_focus_mcp.formatting import (
    _parse,
    format_current_timer,
    format_duration,
    format_started_timer,
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


def test_running_timer_without_start_reports_unknown_elapsed():
    """A running entry legally omits start per the Focus API schema. Must not raise."""
    entry = {"description": "writing docs"}
    result = format_current_timer(entry, NOW)
    assert "writing docs" in result
    assert "unknown" in result.lower()


def test_running_timer_with_start_still_computes_elapsed():
    """Regression guard: the start-present path must be unaffected by the .get() fix."""
    entry = {"description": "writing docs", "start": "2026-08-27T11:30:00Z"}
    result = format_current_timer(entry, NOW)
    assert "writing docs" in result
    assert "30m 0s" in result
    assert "unknown" not in result.lower()


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


def test_time_entries_warns_when_the_list_was_truncated():
    entries = [{"description": "a", "planned_start": "2026-08-26T17:00:00Z", "planned_duration": 1800}]
    result = format_time_entries(entries, truncated=True)
    assert "incomplete" in result
    assert "Total: 30m 0s" in result


def test_time_entries_stays_quiet_when_the_list_is_complete():
    entries = [{"description": "a", "planned_start": "2026-08-26T17:00:00Z", "planned_duration": 1800}]
    assert "incomplete" not in format_time_entries(entries)


def test_stopped_timer_when_nothing_ran():
    assert format_stopped_timer(None) == "No timer was running."


def test_stopped_timer_reports_duration():
    assert "30m 0s" in format_stopped_timer({"description": "writing", "duration": 1800})


def test_stopped_timer_without_duration_reports_unknown():
    """A missing duration field is not a zero-length timer."""
    result = format_stopped_timer({"description": "writing"})
    assert "writing" in result
    assert "unknown" in result.lower()
    assert "0s" not in result


def test_stopped_timer_with_zero_duration_still_prints_zero():
    """A duration that is genuinely zero must render as 0s, not as unknown."""
    result = format_stopped_timer({"description": "writing", "duration": 0})
    assert "Duration: 0s" in result
    assert "unknown" not in result.lower()


def test_stopped_timer_without_description():
    assert "(no description)" in format_stopped_timer({"duration": 1800})


def test_started_timer_reports_description():
    assert format_started_timer({"id": 1, "description": "writing docs"}) == "Started: writing docs"


def test_started_timer_without_description_uses_the_placeholder():
    assert "(no description)" in format_started_timer({"id": 1, "description": ""})


def test_started_timer_handles_a_bodyless_response():
    """A 204 leaves the client with None. Say something rather than crashing."""
    result = format_started_timer(None)
    assert "started" in result.lower()


def test_parse_tags_a_naive_timestamp_as_utc():
    """Deterministic guard: the day tests above are silent on a UTC host."""
    assert _parse("2026-08-26T23:30:00") == datetime(2026, 8, 26, 23, 30, tzinfo=timezone.utc)


def test_parse_keeps_an_explicit_offset():
    assert _parse("2026-08-26T23:30:00Z") == datetime(2026, 8, 26, 23, 30, tzinfo=timezone.utc)


def test_naive_start_is_read_as_utc_not_local_time():
    """A start with no offset must not break the elapsed subtraction."""
    entry = {"description": "writing docs", "start": "2026-08-27T11:30:00"}
    result = format_current_timer(entry, NOW)
    assert "30m 0s" in result


def test_naive_timestamp_in_time_entries_renders_the_utc_day():
    """A naive planned_start must not shift the day to the host timezone."""
    entry = {
        "description": "late night",
        "planned_start": "2026-08-26T23:30:00",
        "planned_duration": 1800,
    }
    assert "2026-08-26" in format_time_entries([entry])


def test_planned_duration_zero_preferred_over_tracked():
    """Entry with planned_duration: 0 should render 0s, not fall back to duration."""
    entry = {
        "description": "scheduled",
        "planned_duration": 0,
        "duration": 1800,
        "planned_start": "2026-08-26T17:00:00Z",
    }
    result = format_time_entries([entry])
    assert "0s" in result
    assert "30m 0s" not in result


def test_fallback_to_tracked_fields_when_planned_absent():
    """Entry with only duration and start (no planned fields) should fall back correctly."""
    entry = {
        "description": "tracked",
        "duration": 1800,
        "start": "2026-08-26T17:00:00Z",
    }
    result = format_time_entries([entry])
    assert "30m 0s" in result
    assert "2026-08-26" in result


def test_time_entries_singular_plural():
    """Single entry renders '1 time entry', multiple render 'N time entries'."""
    single = [{"description": "a", "planned_start": "2026-08-26T17:00:00Z", "planned_duration": 1800}]
    result_single = format_time_entries(single)
    assert "1 time entry" in result_single
    assert "1 time entries" not in result_single

    multiple = [
        {"description": "a", "planned_start": "2026-08-26T17:00:00Z", "planned_duration": 1800},
        {"description": "b", "planned_start": "2026-08-26T18:00:00Z", "planned_duration": 1800},
    ]
    result_multiple = format_time_entries(multiple)
    assert "2 time entries" in result_multiple
    assert "2 time entry" not in result_multiple

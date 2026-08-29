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
            "start": "2026-08-26T17:00:00Z",
            "duration": 1800,
        }
    ]
    result = format_time_entries(entries)
    assert "#ZL# Brady / Spencer" in result
    assert "30m 0s" in result
    assert "2026-08-26" in result


def test_time_entries_reports_the_total():
    entries = [
        {"description": "a", "start": "2026-08-26T17:00:00Z", "duration": 1800},
        {"description": "b", "start": "2026-08-26T18:00:00Z", "duration": 1800},
    ]
    assert "Total tracked: 1h 0m" in format_time_entries(entries)


def test_time_entries_warns_when_the_list_was_truncated():
    entries = [{"description": "a", "start": "2026-08-26T17:00:00Z", "duration": 1800}]
    result = format_time_entries(entries, truncated=True)
    assert "incomplete" in result
    assert "Total tracked: 30m 0s" in result


def test_time_entries_stays_quiet_when_the_list_is_complete():
    entries = [{"description": "a", "start": "2026-08-26T17:00:00Z", "duration": 1800}]
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
        "start": "2026-08-26T23:30:00",
        "duration": 1800,
    }
    assert "2026-08-26" in format_time_entries([entry])


def test_planned_block_with_zero_duration_renders_zero():
    """A zero-length scheduled block is real, not a missing value to skip."""
    entry = {
        "description": "scheduled",
        "planned_duration": 0,
        "duration": None,
        "planned_start": "2026-08-26T17:00:00Z",
        "calendar_event_id": 1,
    }
    result = format_time_entries([entry], include_planned=True)
    assert "0s" in result
    assert "Total planned: 0s" in result


def test_tracked_entry_uses_its_tracked_duration_not_the_planned_one():
    """What you worked, not what you scheduled, for an entry carrying both."""
    entry = {
        "description": "worked",
        "duration": 0,
        "planned_duration": 1800,
        "start": "2026-08-26T17:00:00Z",
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
    single = [{"description": "a", "start": "2026-08-26T17:00:00Z", "duration": 1800}]
    result_single = format_time_entries(single)
    assert "1 tracked time entry" in result_single
    assert "1 tracked time entries" not in result_single

    multiple = [
        {"description": "a", "start": "2026-08-26T17:00:00Z", "duration": 1800},
        {"description": "b", "start": "2026-08-26T18:00:00Z", "duration": 1800},
    ]
    result_multiple = format_time_entries(multiple)
    assert "2 tracked time entries" in result_multiple
    assert "2 time entry" not in result_multiple


PROJECT_NAMES = {"1605053": "Website Rebuild"}
CLIENT_NAMES = {"1605053": "Acme Corp"}


def test_time_entry_shows_client_and_project():
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "project_id": 1605053,
    }]
    result = format_time_entries(
        entries, project_names=PROJECT_NAMES, client_names=CLIENT_NAMES
    )
    assert "[Acme Corp / Website Rebuild]" in result
    assert "standup" in result


def test_time_entry_shows_the_project_alone_when_it_has_no_client():
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "project_id": 1605053,
    }]
    result = format_time_entries(entries, project_names=PROJECT_NAMES, client_names={})
    assert "[Website Rebuild]" in result


def test_time_entry_falls_back_to_the_project_id_when_lookup_is_empty():
    """Losing the names must not lose the fact that the entry has a project."""
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "project_id": 1605053,
    }]
    assert "[project 1605053]" in format_time_entries(entries)


def test_time_entry_without_a_project_gets_no_bracket():
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
    }]
    result = format_time_entries(entries, project_names=PROJECT_NAMES)
    assert "[" not in result


def test_project_ids_match_across_string_and_number():
    """The API sends IDs as numbers in one payload and strings in another."""
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "project_id": "1605053",
    }]
    result = format_time_entries(entries, project_names=PROJECT_NAMES)
    assert "[Website Rebuild]" in result


def test_time_entry_shows_string_tags():
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "tags": ["billable", "meeting"],
    }]
    result = format_time_entries(entries)
    assert "#billable #meeting" in result


def test_time_entry_shows_object_tags():
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "tags": [{"id": 4, "name": "billable"}],
    }]
    assert "#billable" in format_time_entries(entries)


def test_time_entry_drops_tags_that_carry_no_name():
    """A bare tag ID is not a name. Printing the number would just mislead."""
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
        "tags": [41, {"id": 4}, ""],
    }]
    result = format_time_entries(entries)
    assert "#" not in result
    assert "standup" in result


def test_time_entry_with_no_tags_field_renders_unchanged():
    entries = [{
        "description": "standup",
        "start": "2026-08-26T17:00:00Z",
        "duration": 1800,
    }]
    assert format_time_entries(entries) == format_time_entries(
        [dict(entries[0], tags=[])]
    )


def test_current_timer_shows_client_project_and_tags():
    entry = {
        "description": "writing docs",
        "start": "2026-08-27T11:30:00Z",
        "project_id": 1605053,
        "tags": ["billable"],
    }
    result = format_current_timer(
        entry, NOW, project_names=PROJECT_NAMES, client_names=CLIENT_NAMES
    )
    assert "Project: Acme Corp / Website Rebuild" in result
    assert "Tags: #billable" in result
    assert "Elapsed: 30m 0s" in result


def test_current_timer_omits_project_and_tag_lines_when_there_are_none():
    entry = {"description": "writing docs", "start": "2026-08-27T11:30:00Z"}
    result = format_current_timer(entry, NOW)
    assert "Project:" not in result
    assert "Tags:" not in result
    assert result == "Running: writing docs\nElapsed: 30m 0s"


def test_current_timer_without_start_still_shows_its_project():
    entry = {"description": "writing docs", "project_id": 1605053}
    result = format_current_timer(entry, NOW, project_names=PROJECT_NAMES)
    assert "Project: Website Rebuild" in result
    assert "unknown" in result.lower()


# Shapes taken from the live API. A tracked entry has a real duration and no
# calendar link. A planned block has only planned_* fields and a calendar id.
TRACKED = {
    "id": 33579487,
    "description": "Test Time Entry",
    "start": "2026-08-27T17:34:00Z",
    "duration": 3623,
    "project_id": 1605053,
    "calendar_event_id": None,
}

PLANNED = {
    "id": 33579428,
    "description": "#ZL# Brady / Spencer",
    "planned_start": "2026-08-26T17:00:00Z",
    "planned_duration": 1800,
    "duration": None,
    "calendar_event_id": 934558626,
}


def test_planned_calendar_blocks_are_excluded_by_default():
    result = format_time_entries([TRACKED, PLANNED])
    assert "Test Time Entry" in result
    assert "#ZL# Brady / Spencer" not in result


def test_excluded_planned_blocks_are_still_counted_in_the_output():
    """Silently dropping 240 rows would read as 'you have no calendar data'."""
    result = format_time_entries([TRACKED] + [PLANNED] * 3)
    assert "3 planned" in result
    assert "include_planned" in result


def test_no_planned_note_when_there_were_none_to_exclude():
    assert "planned" not in format_time_entries([TRACKED]).lower()


def test_include_planned_lists_them_in_their_own_section():
    result = format_time_entries([TRACKED, PLANNED], include_planned=True)
    assert "Test Time Entry" in result
    assert "#ZL# Brady / Spencer" in result
    assert "planned" in result.lower()


def test_tracked_and_planned_totals_are_reported_separately():
    """Adding scheduled time to worked time produces a number that is a lie."""
    result = format_time_entries([TRACKED, PLANNED], include_planned=True)
    assert "Total tracked: 1h 0m" in result
    assert "Total planned: 30m 0s" in result
    assert "1h 30m" not in result


def test_only_planned_blocks_reports_no_tracked_time():
    result = format_time_entries([PLANNED, PLANNED])
    assert "No tracked time entries" in result
    assert "2 planned" in result


def test_a_running_entry_counts_as_tracked():
    """A running timer has a start but no duration yet. Not a calendar block."""
    running = {"description": "writing docs", "start": "2026-08-27T11:30:00Z"}
    assert "writing docs" in format_time_entries([running])


def test_planned_blocks_keep_their_project_and_tag_labels():
    block = dict(PLANNED, project_id=1605053, tags=["Boomi"])
    result = format_time_entries(
        [block], include_planned=True, project_names={"1605053": "Website Rebuild"}
    )
    assert "[Website Rebuild]" in result
    assert "#Boomi" in result

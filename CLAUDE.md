# toggl-focus-mcp

An MCP server exposing Toggl 2.0 time tracking to Claude, through Toggl's Focus
API. Targets Toggl 2.0 only. Toggl Track v9 is a separate product with a
different host, auth scheme, and path structure, and is out of scope.

## Architecture

Five modules, each with one job. Keep them that way.

| File | Owns |
| --- | --- |
| `config.py` | Environment loading and validation. Raises before any tool runs. |
| `client.py` | All HTTP. Returns parsed data, never raw responses, so status handling never leaks upward. |
| `formatting.py` | Pure functions from API payloads to text. No I/O, no imports from the rest of the package. |
| `tools.py` | The four MCP tool definitions. Calls the client, formats, returns a string. |
| `server.py` | Entry point. Builds the server and runs stdio. |

Tests stub HTTP with `respx`. No test touches the network. If you find yourself
adding a test that makes a real request, that is a signal you are testing the
wrong layer.

## API behaviour that is easy to get wrong

All of this was confirmed against the live API, not read off documentation.

- `GET .../tracking/current` returns **204 with an empty body** when no timer is
  running. Calling `.json()` unconditionally crashes on the most common case.
- `GET .../time-entries` **requires** `date_from` and `date_to`, as RFC3339
  datetimes. A plain date like `2026-07-28` returns HTTP 400.
- `POST .../tracking/start` requires a `type` field, enum `activity` or `break`.
  Starting a timer auto-stops any running one.
- `POST .../tracking/stop` returns **404** when nothing is running. That is a
  normal outcome, returned as `None`, not an error.
- Paged responses are `{page, per_page, data: [...]}`. Send `page` to advance.
  Not every collection endpoint pages, so `_paged` also accepts a bare array
  and treats it as the whole set.
- A time entry names its project only by `project_id`, so project names take a
  second call to `/projects`. Client names are one hop further out: a project
  carries `client_id`. `/clients` was never confirmed live, so a 403 or 404
  there drops client names instead of failing the tool.
- `models.TimeEntry` does not require `start` or `duration`. Never index them
  directly. Report unknown rather than a confident zero.
- `GET .../time-entries` returns **two kinds of record**. Tracked entries carry
  a real `duration`. Planned calendar blocks carry `duration: null`, a
  `planned_duration`, and a `calendar_event_id`, and are meetings mirrored from
  a connected calendar. Confirmed live: an account read 241 rows for a year of
  which 240 were calendar blocks and 1 was tracked. Summing the two produces a
  number that is simply wrong, so `formatting.is_tracked` splits them and the
  totals stay separate. Disconnecting the calendar stops new imports but leaves
  the rows already written.
- There is **no deletion flag** on a time entry. An exhaustive walk of every
  key path found no `deleted_at`, `is_deleted`, `active`, or `status`. Deleted
  records simply stop being returned. A cancelled meeting is still returned,
  marked only by `Canceled:` in the description text.
- Cancelled meetings stay in the planned total **on purpose**. They still hold
  the slot on the calendar even after they flip to free, so the time is really
  blocked. Do not filter on the `Canceled:` string: it is Google's wording, not
  an API contract, and dropping those rows would understate blocked time.
- `GET .../clients` **does not exist**, it returns 404. Client names arrive
  embedded on the project as `client: {id, name}`.
- Every data path is scoped `/organizations/{org_id}/workspaces/{workspace_id}/`.
- The organization ID **cannot** be discovered through the API. The whole spec
  has three endpoints without path parameters and none returns it.

## Errors must reach the model

The MCP SDK discards the text of any exception that is not a `ToolError`. A tool
that lets a `FocusAPIError` escape shows the model only
`Error executing tool <name>`, and every curated message in `client.py` becomes
unreachable. Catch `FocusAPIError` in the tool and re-raise as
`ToolError` (from `mcp.server.mcpserver.exceptions`).

Never write to stdout. It carries JSON-RPC framing and a stray `print` corrupts
the stream. Config errors go to stderr.

## Conventions

- No em dashes, in code, comments, docs, or commit messages. Use a colon, comma,
  or plain hyphen.
- No AI jargon: leveraged, utilized, comprehensive, robust, seamlessly,
  streamlined, ensure, delve.
- Active voice, no hedging. Short sentences.
- Commit messages say what changed and why, nothing more.
- Error messages tell the user what to do next, not just what failed.

## Commands

```bash
./.venv/bin/pytest              # full suite
./.venv/bin/pip install -e .    # installable, provides the toggl-focus-mcp script
```

## Scope

v1 ships four tools: `get_current_timer`, `start_timer`, `stop_current_timer`,
`get_time_entries`.

`get_time_entries` and `get_current_timer` label entries with client, project,
and tags, which reads `/projects`. That is a lookup behind the existing tools,
not a tool of its own. Names are a label: losing them must never lose the
entries, so a lookup failure degrades to `[project <id>]`.

`get_time_entries` returns tracked time only unless `include_planned=true`.
The tool docstring is the only place the model learns that planned blocks are
not worked time, so keep that warning in it.

Deferred on purpose: tools for browsing projects and tasks, search, summaries.
`GET .../projects` and `GET .../tasks` are both confirmed working, so these are
scheduled, not blocked.

Not planned: a `get_workspaces` equivalent, since Focus exposes no endpoint
listing a user's workspaces, and a `get_time_summary`, since there is no summary
endpoint and the `timesheets` routes are an approvals feature. Any summary has
to be computed from time entries.

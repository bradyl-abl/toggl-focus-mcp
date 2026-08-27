# toggl-focus-mcp design

Date: 2026-08-27

## Purpose

An MCP server for Toggl 2.0, so Claude can read and control time tracking on
accounts that use the Focus API.

Toggl now runs two separate products with incompatible APIs. New signups land on
Toggl 2.0. The existing community server, `vontell/toggl-track-mcp`, targets the
legacy Toggl Track v9 API and cannot talk to a Toggl 2.0 account at all. This
project fills that gap.

This is a clean-room implementation. No code is copied from
`vontell/toggl-track-mcp`, which carries no license.

## Verified API facts

Everything below was confirmed against the live API on 2026-08-27, not taken
from documentation.

**Authentication.** Bearer token in the `Authorization` header. Keys start with
`toggl_sk_` and are issued in Toggl 2.0 settings. Only one key is active per
user, and creating a new key revokes the previous one.

```
Authorization: Bearer toggl_sk_...
```

**Base URL.** `https://focus.toggl.com/api`

**Path scoping.** Nearly every endpoint is scoped to both an organization and a
workspace:

```
/organizations/{organization_id}/workspaces/{workspace_id}/...
```

**Organization ID is not discoverable.** The entire OpenAPI spec has only three
endpoints without path parameters: `/accounts/me/metadata`, `/users/me/settings`,
and `/version`. None returns an organization ID. `/workspaces/{id}/context`
returns 403. The ID has to come from the user, who can read it from the Toggl 2.0
web app URL:

```
https://focus.toggl.com/{organization_id}/workspaces/{workspace_id}/calendar
```

**Workspace ID is discoverable.** `GET /users/me/settings` returns
`current_workspace_id`.

**Endpoints for v1:**

| Purpose | Endpoint |
| --- | --- |
| Current timer | `GET .../tracking/current` |
| Start timer | `POST .../tracking/start` |
| Stop timer | `POST .../tracking/stop` |
| List entries | `GET .../time-entries` |

**Two behaviours that will bite anyone who assumes otherwise:**

1. `tracking/current` returns **HTTP 204 with an empty body** when no timer is
   running. It does not return 200 with a null payload. Code that calls
   `response.json()` unconditionally will crash on the common case.

2. `time-entries` **requires** `date_from` and `date_to`, and both must be
   RFC3339 datetimes, not plain dates. Passing `2026-07-28` returns HTTP 400
   with `parsing time "2026-07-28" as "2006-01-02T15:04:05Z07:00"`. The correct
   form is `2026-07-28T00:00:00Z`.

**Time entry response shape.** A page is `{page, per_page, data[]}`. Each entry
carries `id`, `description`, `planned_start`, `planned_duration` (seconds),
`project_id`, `task_id`, `billable`, `tags`, and `timezone`.

## Scope

**v1 ships four tools:**

- `get_current_timer`
- `start_timer`
- `stop_current_timer`
- `get_time_entries`

That is the daily-driver loop, and every one maps to a single Focus endpoint.

**Deferred to later versions:** projects, tasks, search, and summaries.
`GET .../projects` and `GET .../tasks` are both confirmed working, so these are
scheduled work rather than open questions.

**Two tools from the Track v9 server have no clean equivalent and are not
planned:**

- `get_workspaces`. Focus exposes no endpoint listing a user's workspaces, only
  `current_workspace_id`.
- `get_time_summary`. There is no summary endpoint. The `timesheets` routes are
  an approvals feature, not an aggregate. Any summary has to be computed from
  time entries.

## Architecture

Five focused modules rather than one large file.

```
toggl_focus_mcp/
  config.py      Env loading, validation, workspace resolution
  client.py      Async HTTP, Bearer auth, error mapping
  formatting.py  API payloads to text for the model
  tools.py       MCP tool definitions
  server.py      Entry point, wires MCPServer
tests/
```

**config.py** reads and validates environment, then resolves the workspace ID by
calling `/users/me/settings` when one is not set explicitly. Validation failures
raise before any tool runs, so misconfiguration surfaces at startup rather than
as a confusing error mid-conversation.

**client.py** owns all HTTP. It builds the org and workspace scoped URL prefix
once, attaches the Bearer header, and maps HTTP status codes to typed exceptions.
It returns parsed data, never raw responses, which keeps status-code handling
(including the 204 case) out of the tool layer.

Keeping this boundary narrow leaves room to add a Track v9 backend later without
touching the tools. That possibility is not built now.

**formatting.py** is pure functions from API payloads to strings. No I/O, so it
tests without stubs.

**tools.py** holds the MCP tool definitions. Each one calls the client, passes
the result to a formatter, and returns a string.

**server.py** constructs `MCPServer`, registers the tools, and runs stdio.

The server targets mcp SDK 2.x directly. There is no 1.x legacy to support, so
`requirements.txt` pins `mcp[cli]>=2.0.0`.

## Configuration

| Variable | Required | Default |
| --- | --- | --- |
| `TOGGL_API_KEY` | yes | none |
| `TOGGL_ORG_ID` | yes | none, not discoverable via API |
| `TOGGL_WORKSPACE_ID` | no | `current_workspace_id` from `/users/me/settings` |
| `TOGGL_API_BASE` | no | `https://focus.toggl.com/api` |

`TOGGL_API_BASE` is included from the start. It costs one line and it lets people
point the server at a compatible or self-hosted backend.

## Error handling

Errors must say what to do next, not just what failed.

**Wrong token format.** If `TOGGL_API_KEY` is 32 hex characters with no prefix,
that is a Toggl Track v9 token and it will never work here. Detect it at startup
and say so:

```
That looks like a Toggl Track v9 API token, not a Toggl 2.0 key.
This server needs a key starting with toggl_sk_ from your Toggl 2.0 settings.
For Track v9 accounts, use github.com/vontell/toggl-track-mcp instead.
```

This exists because diagnosing precisely this mismatch cost four token refreshes
and a long debugging session. The check is a few lines and it saves the next
person that time.

**Missing organization ID.** Name where to find it, including the URL shape,
rather than reporting a 403.

**401 and 403 from the API.** Distinguish an invalid or revoked key from a
permissions problem. Mention that creating a new key revokes the old one, since
that surprises people.

## Testing

Test-first, using pytest with `respx` to stub HTTP. `httpx` is chosen over
`aiohttp` mainly because `respx` makes stubbing clean.

Coverage must include the two behaviours above, since both are easy to get wrong
and neither is obvious from the endpoint list:

- `tracking/current` returning 204 yields "no timer running", not a crash
- date arguments are serialised as RFC3339, and a plain date is never sent

Formatting functions are tested directly as pure functions. Config validation is
tested including the Track-token detection path.

One end-to-end check against the live API stays outside the automated suite,
since it needs real credentials.

## Out of scope for v1

- Any Track v9 compatibility path. Separate products, separate servers.
- Projects, tasks, search, summaries. Planned, not now.
- Writing time entries beyond starting and stopping a timer.

## Open questions

None blocking. Organization and workspace IDs are confirmed, auth is confirmed,
and all four v1 endpoints have been exercised against the live API.

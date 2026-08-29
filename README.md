# Toggl Focus MCP

An MCP server that exposes Toggl 2.0 time tracking to Claude, through Toggl's
Focus API at `https://focus.toggl.com/api`.

## Which Toggl this is for

Toggl runs two products with separate APIs. This server talks to Toggl 2.0,
through the Focus API.

Your key tells you which account you have. A Toggl 2.0 key starts with
`toggl_sk_` and comes from your Toggl 2.0 settings. A Toggl Track v9 token is
32 hex characters with no prefix and will not work here. Point this server at
one and it says so at startup, rather than failing with a confusing 403 on
every call.

Only one Toggl 2.0 key is active per user at a time. Creating a new key revokes
whichever key was active before it, which surprises people.

For Toggl Track v9 accounts, [vontell/toggl-track-mcp](https://github.com/vontell/toggl-track-mcp)
covers that API.

## Installation

Needs Python 3.10 or later.

```bash
git clone https://github.com/bradyl-abl/toggl-focus-mcp.git
cd toggl-focus-mcp
python3 -m venv .venv
./.venv/bin/pip install -e .
```

That installs the package itself, not just its dependencies, and puts a
`toggl-focus-mcp` command in `.venv/bin`. Your MCP client runs that command,
so the server starts from any working directory.

## Finding your organization ID

`TOGGL_ORG_ID` is required and the API has no endpoint that returns it. Of
the entire Focus OpenAPI spec, only three endpoints take no path parameters,
and none of them returns the organization ID either. You have to read it out
of the browser URL yourself.

Open Toggl 2.0 in a browser and look at the address bar:

```
https://focus.toggl.com/{organization_id}/workspaces/{workspace_id}/calendar
```

The first segment after `focus.toggl.com/` is your organization ID. The
segment after `workspaces/` is your workspace ID, though you usually don't
need to set that one, see below.

## Configuration

| Variable | Required | Default |
|---|---|---|
| `TOGGL_API_KEY` | yes | none |
| `TOGGL_ORG_ID` | yes | none, not discoverable through the API |
| `TOGGL_WORKSPACE_ID` | no | the account's `current_workspace_id`, resolved automatically on first call |
| `TOGGL_API_BASE` | no | `https://focus.toggl.com/api` |

Copy `.env.example` to `.env` and fill in your values, or set the variables
directly in your MCP client config (see below).

## Claude Desktop setup

Add this to your Claude Desktop MCP config, with the absolute path to the
`toggl-focus-mcp` command the install step created, and your real key and
org ID:

```json
{
  "mcpServers": {
    "Toggl Focus": {
      "command": "/absolute/path/to/.venv/bin/toggl-focus-mcp",
      "args": [],
      "env": {
        "TOGGL_API_KEY": "toggl_sk_your_key_here",
        "TOGGL_ORG_ID": "your_org_id"
      }
    }
  }
}
```

## Tools

- **`get_current_timer()`** - returns the running timer, or a message saying
  none is running. Shows the client and project it is filed against, and its
  tags, when it has them.
- **`start_timer(description, project_id=None)`** - starts a timer with the
  given description. If a timer is already running, the API stops it first.
  `project_id` is Toggl's numeric project ID. v1 ships no tool for listing
  projects, so you have to supply the number yourself.
- **`stop_current_timer()`** - stops the running timer. Reports plainly when
  nothing was running.
- **`get_time_entries(days=7, date_from=None, date_to=None, include_planned=False)`**
  - lists time entries. Two ways to pick the period:
  - `days` is a rolling window of the last N times 24 hours, counting back from
    now. These are not calendar days: `days=1` is the last 24 hours, not today.
  - `date_from` and `date_to` are calendar dates as `YYYY-MM-DD`, in UTC, with
    both ends included. Pass them together, both or neither. They override
    `days`. One day is the same date in both.

  Each line reads `date  duration  [client / project]  description  #tags`.
  The bracket is dropped for an entry with no project, and falls back to
  `[project <id>]` if the project names cannot be read.

  By default only genuinely **tracked** time is returned. See below.

### Tracked time versus planned calendar blocks

`GET /time-entries` returns two different kinds of record from one endpoint:

| | Tracked entry | Planned calendar block |
|---|---|---|
| What it is | time the user really spent | a meeting mirrored from a connected calendar |
| `duration` | a measured value | `null` |
| `calendar_event_id` | absent | set |
| Shown by default | yes | no |

If you connect a calendar to Toggl, every meeting becomes a row here. They were
never tracked and may never have happened: a cancelled meeting still arrives,
with the cancellation only in the description text. On a calendar-heavy account
they outnumber real entries by a wide margin, so counting them as worked time
overstates hours badly.

`get_time_entries` therefore returns only tracked time by default and reports
how many planned blocks it left out. Pass `include_planned=true` to list them,
and they appear in their own section under a separate `Total planned`. The two
totals are never added together. An account with no calendar connected has no
planned blocks and sees no difference.

Project and client names cost extra calls. `get_time_entries` and
`get_current_timer` read `/projects`, and `/clients` on top of that when a
project carries a `client_id` rather than the name itself. Both are skipped
when no entry has a project, and a failure there drops the names rather than
the entries.

Errors from the API come back with the status code and a readable message,
including the hint about Toggl revoking your previous key when you create a
new one.

## Development

Install the package with its development dependencies:

```bash
./.venv/bin/pip install -e ".[dev]"
```

Run the test suite:

```bash
./.venv/bin/pytest
```

## License

MIT. See [LICENSE](LICENSE).

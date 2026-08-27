# Toggl Focus MCP

An MCP server that exposes Toggl 2.0 time tracking to Claude, through Toggl's
Focus API at `https://focus.toggl.com/api`.

## Which Toggl this is for

Toggl has two separate products with separate APIs: Toggl 2.0 (Focus) and
Toggl Track v9. This server talks to Toggl 2.0 only.

If you have a Toggl Track v9 account, your API token is 32 hex characters
with no prefix, and it will not work here. Use
[vontell/toggl-track-mcp](https://github.com/vontell/toggl-track-mcp)
instead. If you point this server at a Track v9 token, it detects the
mismatch at startup and tells you so instead of failing silently.

A Toggl 2.0 key starts with `toggl_sk_` and comes from your Toggl 2.0
settings. Only one key is active per user at a time: creating a new key
revokes whichever key was active before it.

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
  none is running.
- **`start_timer(description, project_id=None)`** - starts a timer with the
  given description. If a timer is already running, the API stops it first.
  `project_id` is Toggl's numeric project ID. v1 ships no tool for listing
  projects, so you have to supply the number yourself.
- **`stop_current_timer()`** - stops the running timer. Reports plainly when
  nothing was running.
- **`get_time_entries(days=7)`** - lists time entries from a rolling window of
  the last N times 24 hours, counting back from now. These are not calendar
  days: `days=1` is the last 24 hours, not today. Durations shown are planned
  durations.

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

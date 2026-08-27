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

```bash
git clone <this repo>
cd toggl-focus-mcp
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
```

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

Add this to your Claude Desktop MCP config, with the path to your virtual
environment's Python and your real key and org ID:

```json
{
  "mcpServers": {
    "Toggl Focus": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "toggl_focus_mcp.server"],
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
- **`stop_current_timer()`** - stops the running timer.
- **`get_time_entries(days=7)`** - lists time entries from the last N days.

## Development

Install the development dependencies, which include the base requirements:

```bash
./.venv/bin/pip install -r requirements-dev.txt
```

Run the test suite:

```bash
./.venv/bin/pytest
```

## License

MIT. See [LICENSE](LICENSE).

"""Environment loading and validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

DEFAULT_API_BASE = "https://focus.toggl.com/api"

# A Toggl Track v9 token: 32 hex characters, no prefix. Toggl renders these in
# lowercase, but match either case so a pasted uppercase token still gets the
# helpful message instead of the generic "does not look like a key" one.
TRACK_V9_TOKEN = re.compile(r"^[0-9a-f]{32}$", re.IGNORECASE)

# A Toggl 2.0 key.
FOCUS_KEY_PREFIX = "toggl_sk_"

TRACK_TOKEN_MESSAGE = (
    "That looks like a Toggl Track v9 API token, not a Toggl 2.0 key.\n"
    "This server needs a key starting with toggl_sk_ from your Toggl 2.0 settings.\n"
    "For Track v9 accounts, use github.com/vontell/toggl-track-mcp instead."
)

ORG_ID_MESSAGE = (
    "TOGGL_ORG_ID is required and cannot be discovered through the API.\n"
    "Open Toggl 2.0 in a browser and read it from the URL:\n"
    "  https://focus.toggl.com/{organization_id}/workspaces/{workspace_id}/calendar"
)


class ConfigError(Exception):
    """Raised when the environment is missing or malformed."""


@dataclass(frozen=True)
class Config:
    api_key: str
    org_id: str
    workspace_id: str | None
    api_base: str


def load_config(env: Mapping[str, str]) -> Config:
    """Build a Config from environment values, or raise ConfigError."""
    api_key = (env.get("TOGGL_API_KEY") or "").strip()
    if not api_key:
        raise ConfigError("TOGGL_API_KEY is required. Create one in your Toggl 2.0 settings.")

    if TRACK_V9_TOKEN.match(api_key):
        raise ConfigError(TRACK_TOKEN_MESSAGE)

    if not api_key.startswith(FOCUS_KEY_PREFIX):
        raise ConfigError(
            f"TOGGL_API_KEY does not look like a Toggl 2.0 key. Expected it to start with {FOCUS_KEY_PREFIX}."
        )

    org_id = (env.get("TOGGL_ORG_ID") or "").strip()
    if not org_id:
        raise ConfigError(ORG_ID_MESSAGE)

    workspace_id = (env.get("TOGGL_WORKSPACE_ID") or "").strip() or None
    api_base = ((env.get("TOGGL_API_BASE") or "").strip() or DEFAULT_API_BASE).rstrip("/")

    return Config(
        api_key=api_key,
        org_id=org_id,
        workspace_id=workspace_id,
        api_base=api_base,
    )

"""Entry point. Wires configuration, client, and tools onto an MCPServer."""

from __future__ import annotations

import os
import sys

import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

from .client import FocusClient
from .config import ConfigError, load_config
from .tools import register_tools


def build_server() -> MCPServer:
    """Build the configured server, or exit with a readable message."""
    load_dotenv()
    try:
        config = load_config(os.environ)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)

    http = httpx.AsyncClient(timeout=30.0)
    client = FocusClient(config, http)

    mcp = MCPServer("Toggl Focus")
    register_tools(mcp, client)
    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()

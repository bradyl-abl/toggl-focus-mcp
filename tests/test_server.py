import re
from pathlib import Path

import pytest

from toggl_focus_mcp.config import ConfigError, load_config
from toggl_focus_mcp.server import SERVER_VERSION

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def pyproject_value(key: str) -> str:
    """Read one top-level [project] string. Avoids tomllib, absent on 3.10."""
    match = re.search(rf'^{key} = "([^"]+)"$', PYPROJECT.read_text(), re.MULTILINE)
    assert match, f"{key} not found in pyproject.toml"
    return match.group(1)


def test_server_version_matches_pyproject():
    """The initialize response reports this. Do not let the two drift."""
    assert SERVER_VERSION == pyproject_value("version")


def test_console_script_points_at_the_real_entry_point():
    """The README tells users to run this command. It has to resolve."""
    text = PYPROJECT.read_text()
    assert 'toggl-focus-mcp = "toggl_focus_mcp.server:main"' in text
    from toggl_focus_mcp.server import main

    assert callable(main)


def test_build_server_reports_a_missing_key_instead_of_crashing():
    """load_config is what build_server turns into a readable exit message."""
    with pytest.raises(ConfigError, match="TOGGL_API_KEY"):
        load_config({})

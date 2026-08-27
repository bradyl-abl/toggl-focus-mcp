import pytest

from toggl_focus_mcp.config import Config, ConfigError, load_config

VALID_KEY = "toggl_sk_" + "a" * 32


def test_loads_all_values():
    cfg = load_config({
        "TOGGL_API_KEY": VALID_KEY,
        "TOGGL_ORG_ID": "21631262",
        "TOGGL_WORKSPACE_ID": "21630499",
        "TOGGL_API_BASE": "https://example.test/api",
    })
    assert cfg == Config(
        api_key=VALID_KEY,
        org_id="21631262",
        workspace_id="21630499",
        api_base="https://example.test/api",
    )


def test_api_base_defaults():
    cfg = load_config({"TOGGL_API_KEY": VALID_KEY, "TOGGL_ORG_ID": "1"})
    assert cfg.api_base == "https://focus.toggl.com/api"


def test_workspace_id_is_optional():
    cfg = load_config({"TOGGL_API_KEY": VALID_KEY, "TOGGL_ORG_ID": "1"})
    assert cfg.workspace_id is None


def test_trailing_slash_stripped_from_api_base():
    cfg = load_config({
        "TOGGL_API_KEY": VALID_KEY,
        "TOGGL_ORG_ID": "1",
        "TOGGL_API_BASE": "https://example.test/api/",
    })
    assert cfg.api_base == "https://example.test/api"


def test_missing_api_key_names_the_variable():
    with pytest.raises(ConfigError, match="TOGGL_API_KEY"):
        load_config({"TOGGL_ORG_ID": "1"})


def test_missing_org_id_explains_where_to_find_it():
    with pytest.raises(ConfigError) as exc:
        load_config({"TOGGL_API_KEY": VALID_KEY})
    message = str(exc.value)
    assert "TOGGL_ORG_ID" in message
    assert "focus.toggl.com/" in message


def test_track_v9_token_is_rejected_with_a_pointer_to_the_other_server():
    with pytest.raises(ConfigError) as exc:
        load_config({
            "TOGGL_API_KEY": "1971800d4d82861d8f2c1651fea4d212",
            "TOGGL_ORG_ID": "1",
        })
    message = str(exc.value)
    assert "Track v9" in message
    assert "toggl_sk_" in message
    assert "vontell/toggl-track-mcp" in message


def test_unrecognised_key_format_is_rejected():
    with pytest.raises(ConfigError, match="toggl_sk_"):
        load_config({"TOGGL_API_KEY": "nonsense", "TOGGL_ORG_ID": "1"})


def test_whitespace_is_stripped():
    cfg = load_config({
        "TOGGL_API_KEY": f"  {VALID_KEY}  ",
        "TOGGL_ORG_ID": " 21631262 ",
    })
    assert cfg.api_key == VALID_KEY
    assert cfg.org_id == "21631262"

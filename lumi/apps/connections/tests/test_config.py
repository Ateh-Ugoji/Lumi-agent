from __future__ import annotations

import pytest

from apps.connections.config import ConfigError, ConnectionsConfig


def test_defaults_are_safe() -> None:
    config = ConnectionsConfig.from_env({})
    assert config.x_live_enabled is False
    assert config.public_base_url == "http://localhost:8000"
    assert config.linkedin_api_version == "202609"
    assert config.meta_graph_version == "v26.0"


def test_redirect_uri_format_matches_the_console_instructions() -> None:
    config = ConnectionsConfig.from_env(
        {"PUBLIC_BASE_URL": "https://lumi.example.com/"}
    )
    assert (
        config.redirect_uri("meta")
        == "https://lumi.example.com/api/v1/connections/meta/callback"
    )


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_x_live_true_spellings(value: str) -> None:
    assert ConnectionsConfig.from_env({"X_LIVE_ENABLED": value}).x_live_enabled is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off", "FALSE"])
def test_x_live_false_spellings(value: str) -> None:
    assert ConnectionsConfig.from_env({"X_LIVE_ENABLED": value}).x_live_enabled is False


def test_typo_in_the_x_switch_fails_instead_of_guessing() -> None:
    with pytest.raises(ConfigError):
        ConnectionsConfig.from_env({"X_LIVE_ENABLED": "tru"})


def test_version_formats_are_validated() -> None:
    with pytest.raises(ConfigError):
        ConnectionsConfig.from_env({"LINKEDIN_API_VERSION": "2026-09"})
    with pytest.raises(ConfigError):
        ConnectionsConfig.from_env({"META_GRAPH_VERSION": "26"})


def test_secrets_stay_out_of_repr() -> None:
    config = ConnectionsConfig.from_env(
        {
            "META_APP_SECRET": "m-s3cret",
            "LINKEDIN_CLIENT_SECRET": "l-s3cret",
            "X_CLIENT_SECRET": "x-s3cret",
        }
    )
    text = repr(config)
    assert "s3cret" not in text

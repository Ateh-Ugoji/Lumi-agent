from __future__ import annotations

import pytest

from apps.connections.config import ConfigError, ConnectionsConfig


def test_defaults_are_safe() -> None:
    config = ConnectionsConfig.from_env({})
    assert config.x_live_enabled is False
    assert config.frontend_url == "http://localhost:3010"
    assert not hasattr(config, "public_base_url")
    assert config.linkedin_api_version == "202609"
    assert config.meta_graph_version == "v26.0"


def test_redirect_uri_format_matches_the_console_instructions() -> None:
    """The provider redirects to a FRONTEND page, never to the API."""
    config = ConnectionsConfig.from_env({"FRONTEND_URL": "https://app.lumi.example/"})
    assert (
        config.redirect_uri("meta")
        == "https://app.lumi.example/connections/meta/callback"
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


def test_xpoz_and_pfm_defaults_never_spend() -> None:
    config = ConnectionsConfig.from_env({})
    assert config.xpoz_live_enabled is False
    assert config.xpoz_run_credit_budget == 12
    assert config.xpoz_platform_budgets == {}
    assert config.xpoz_budget_for("instagram") == 12
    assert config.handle_cache_ttl_minutes == 60
    assert config.xpoz_api_keys == ()


def test_xpoz_keys_keep_rotation_order_and_drop_blanks() -> None:
    config = ConnectionsConfig.from_env({"XPOZ_API_KEY": " ", "XPOZ_API_KEY_2": "k2"})
    assert config.xpoz_api_keys == ("k2",)
    both = ConnectionsConfig.from_env({"XPOZ_API_KEY": "k1", "XPOZ_API_KEY_2": "k2"})
    assert both.xpoz_api_keys == ("k1", "k2")


@pytest.mark.parametrize("name", ["XPOZ_RUN_CREDIT_BUDGET", "HANDLE_CACHE_TTL_MINUTES"])
@pytest.mark.parametrize("value", ["ten", "-1", "1.5"])
def test_numeric_settings_reject_bad_values_by_name(name: str, value: str) -> None:
    with pytest.raises(ConfigError) as caught:
        ConnectionsConfig.from_env({name: value})
    assert name in str(caught.value) and value not in str(caught.value)


def test_xpoz_switch_typo_fails() -> None:
    with pytest.raises(ConfigError):
        ConnectionsConfig.from_env({"XPOZ_LIVE_ENABLED": "yess"})


def test_pfm_and_xpoz_secrets_stay_out_of_repr() -> None:
    config = ConnectionsConfig.from_env(
        {
            "PFM_JWT_TOKEN": "pfm-s3cret",
            "XPOZ_API_KEY": "xp-s3cret",
            "XPOZ_API_KEY_2": "xp2-s3cret",
        }
    )
    assert "s3cret" not in repr(config)


def test_platform_budgets_override_the_shared_one_and_ignore_blanks() -> None:
    config = ConnectionsConfig.from_env(
        {
            "XPOZ_RUN_CREDIT_BUDGET": "4",
            "XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM": "12",
            "XPOZ_RUN_CREDIT_BUDGET_X": "0",
            "XPOZ_RUN_CREDIT_BUDGET_TIKTOK": "  ",
        }
    )
    assert config.xpoz_platform_budgets == {"instagram": 12, "x": 0}
    assert [config.xpoz_budget_for(p) for p in ("instagram", "x", "tiktok")] == [
        12,
        0,
        4,
    ]


@pytest.mark.parametrize("value", ["-1", "many"])
def test_a_bad_platform_budget_is_a_config_error(value) -> None:
    with pytest.raises(ConfigError, match="XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM"):
        ConnectionsConfig.from_env({"XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM": value})

"""The AI app registers one key probe per provider and never forces a variable on startup."""

import importlib

import pytest

from apps.core import keys

EXPECTED = {"groq", "openrouter", "openlux", "jev", "neatlogs", "video"}


@pytest.fixture
def fresh_registry(monkeypatch):
    monkeypatch.setattr(keys, "_REGISTRY", {})
    for var in (
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENLUX_API_KEY",
        "TYPESAFE_API_KEY",
        "NEATLOGS_API_KEY",
        "VIDEO_PROVIDER",
        "VIDEO_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


def _ready():
    from apps.intelligence.apps import IntelligenceConfig

    IntelligenceConfig(
        "apps.intelligence", importlib.import_module("apps.intelligence")
    ).ready()
    return {spec.name: spec for spec in keys.all_specs()}


def test_every_provider_is_registered_once(fresh_registry):
    specs = _ready()
    assert set(specs) == EXPECTED
    assert specs["groq"].required and specs["groq"].env_vars == ("GROQ_API_KEY",)
    assert all(not specs[n].required for n in EXPECTED - {"groq"})


def test_ready_twice_is_a_no_op(fresh_registry):
    _ready()
    assert set(_ready()) == EXPECTED


def test_only_groq_blocks_startup_and_model_variables_are_never_required(
    fresh_registry,
):
    _ready()
    assert keys.missing_required() == ["GROQ_API_KEY"]
    listed = {v for spec in keys.all_specs() for v in spec.env_vars}
    assert not {v for v in listed if "MODEL" in v}


def test_optional_providers_without_a_key_are_skipped_not_failed(fresh_registry):
    specs = _ready()
    for name in EXPECTED - {"groq"}:
        result = keys.run_probe(specs[name])
        assert result.status == "skipped", (name, result)

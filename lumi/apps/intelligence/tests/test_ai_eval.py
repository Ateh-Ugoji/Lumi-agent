import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def run(*args: str) -> str:
    out = StringIO()
    call_command("ai_eval", *args, stdout=out)
    return out.getvalue()


def test_offline_golden_run_agrees_and_reports_json() -> None:
    data = json.loads(run("--suite", "golden", "--json"))
    assert data["mode"] == "offline" and data["synthetic"] is True
    assert data["agreement"] == 1.0 and data["mismatches"] == [] and data["cases"] >= 20


def test_a_minimum_above_the_agreement_exits_with_an_error(monkeypatch) -> None:
    from apps.intelligence.management.commands import ai_eval
    from lumi_ai.config import AIConfig

    monkeypatch.setattr(
        ai_eval.AIConfig, "from_env", lambda: AIConfig(quality_pass_mean=0.8)
    )
    with pytest.raises(CommandError, match="por debajo del mínimo"):
        run("--min-agreement", "1.0")


def test_live_without_any_key_refuses_instead_of_pretending(monkeypatch) -> None:
    for name in (
        "TYPESAFE_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENLUX_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(CommandError, match="--live necesita"):
        run("--live")

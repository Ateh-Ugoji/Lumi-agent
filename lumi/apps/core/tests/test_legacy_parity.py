"""The legacy parity matrix cannot drift: every legacy test is mapped to something real."""

from __future__ import annotations

import pytest

from apps.core.tests import legacy_parity as parity


def test_the_frozen_list_holds_the_418_legacy_tests() -> None:
    assert sum(count for _, _, count in parity.legacy_tests()) == parity.EXPECTED_TOTAL


def test_every_legacy_test_is_mapped_and_every_target_exists() -> None:
    bad = [(v.legacy_file, v.test, v.problems) for v in parity.judge() if v.problems]
    assert bad == []


def test_no_rule_is_dead() -> None:
    dead = parity.unused_rules(parity.judge())
    assert [(r.legacy_file, r.name_regex.pattern) for r in dead] == []


def test_every_status_is_known() -> None:
    assert {v.status for v in parity.judge()} <= set(parity.STATUSES)


def test_the_committed_report_matches_the_map() -> None:
    expected = parity.render(parity.judge())
    assert parity.REPORT.read_text(encoding="utf-8") == expected, (
        "regenerate with: uv run python -m apps.core.tests.legacy_parity --write"
    )


def test_the_frozen_names_match_lumi_tests_while_it_exists() -> None:
    on_disk = parity.legacy_names_on_disk()
    if on_disk is None:
        pytest.skip("lumi/tests is gone: the frozen list is the only record")
    frozen: dict[str, set[str]] = {}
    for legacy_file, test, _ in parity.legacy_tests():
        frozen.setdefault(legacy_file, set()).add(test)
    disk = {
        f: {n for n in names if n.startswith("test_")} for f, names in on_disk.items()
    }
    disk = {f: names for f, names in disk.items() if names}
    assert disk == frozen

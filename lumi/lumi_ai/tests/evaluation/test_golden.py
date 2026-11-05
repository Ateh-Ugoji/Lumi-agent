import pytest

from lumi_ai.config import AIConfig
from lumi_ai.evaluation.golden import RecordedScorer, load_cases, run_suite


def test_the_suite_has_at_least_twenty_cases_all_marked_synthetic() -> None:
    cases = load_cases()
    assert len(cases) >= 20 and all(c.synthetic for c in cases)
    assert {c.expected_decision for c in cases} == {"pass", "regenerate", "fail"}
    assert {c.brief.platform for c in cases} >= {
        "x",
        "linkedin",
        "facebook",
        "instagram",
        "tiktok",
    }


@pytest.mark.asyncio
async def test_replaying_the_recorded_scores_reaches_the_expected_decisions() -> None:
    cases = load_cases()
    report = await run_suite(cases, [RecordedScorer(cases)])
    assert report.mismatches == (), report.as_dict()["mismatches"]
    assert report.agreement == 1.0
    assert report.judges == {
        "rules": 10,
        "jev": 16,
    }  # 9 hard failures + the judge-absent case
    assert 0.3 < report.regeneration_rate < 0.7


@pytest.mark.asyncio
async def test_a_stricter_threshold_shows_up_as_disagreement() -> None:
    cases = load_cases()
    report = await run_suite(
        cases, [RecordedScorer(cases)], AIConfig(quality_pass_mean=0.8)
    )
    assert {r.case.id for r in report.mismatches} >= {
        "pass-tiktok-repurpose",
        "pass-boundary-mean-0.7",
    }
    assert report.agreement < 1.0


def test_a_case_with_missing_criteria_is_rejected(tmp_path) -> None:
    bad = tmp_path / "c.json"
    bad.write_text(
        '[{"id":"x","platform":"x","mode":"topic","topic":"t","source_text":null,'
        '"must_keep":[],"text":"t","scores":{"hook":1},"expected":{"decision":"pass","judge":"jev"}}]'
    )
    with pytest.raises(ValueError, match="must cover exactly"):
        load_cases(bad)

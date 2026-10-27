"""The database enforces the rules of SCHEMA.md section 7, not the service layer."""

import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.intelligence.models import (
    GenerationEvaluation,
    NichePreference,
    NichePreferenceKeyword,
    RepurposeAttempt,
    RepurposeRequest,
    UserAction,
    VoiceProfile,
)
from apps.profiles.models import Post, SocialHandle, SocialProfile

pytestmark = pytest.mark.django_db


@pytest.fixture
def handle():
    return SocialHandle.objects.create(platform="x", handle_normalized="somebody")


@pytest.fixture
def profile(handle):
    user = User.objects.create_user("owner@example.com")
    return SocialProfile.objects.create(user=user, handle=handle)


@pytest.fixture
def request_row(profile):
    return RepurposeRequest.objects.create(profile=profile, source_caption="hello")


@pytest.fixture
def attempt(request_row):
    return RepurposeAttempt.objects.create(
        request=request_row,
        platform="x",
        attempt_no=1,
        output="hi",
        must_keep_passed=True,
    )


def fails(fn):
    with pytest.raises(IntegrityError), transaction.atomic():
        fn()


def test_attempt_defaults_and_cascade_from_request(request_row, attempt):
    assert attempt.is_fallback is False  # db_default, not an invented value
    assert request_row.mode == "repurpose" and request_row.route_label is None
    request_row.delete()
    assert not RepurposeAttempt.objects.exists()


def test_attempt_rules(request_row, attempt):
    def make(**kw):
        base = {
            "request": request_row,
            "platform": "x",
            "attempt_no": 2,
            "output": "o",
            "must_keep_passed": False,
        }
        return lambda: RepurposeAttempt.objects.create(**{**base, **kw})

    make()()  # a second attempt number is fine
    fails(make(attempt_no=1))  # unique (request, platform, attempt_no)
    RepurposeAttempt.objects.create(  # another platform restarts numbering
        request=request_row,
        platform="linkedin",
        attempt_no=1,
        output="o",
        must_keep_passed=True,
    )
    fails(make(attempt_no=3, platform="myspace"))
    fails(make(attempt_no=3, judge_verdict="may"))
    fails(make(attempt_no=3, judge_confidence=1.5))
    fails(make(attempt_no=0))


def test_request_route_and_mode_checks(profile):
    ok = RepurposeRequest.objects.create(
        profile=profile, source_caption="t", route_label="hard", mode="topic", brief="b"
    )
    assert ok.mode == "topic"
    fails(
        lambda: RepurposeRequest.objects.create(
            profile=profile, source_caption="t", route_label="nope"
        )
    )
    fails(
        lambda: RepurposeRequest.objects.create(
            profile=profile, source_caption="t", mode="x"
        )
    )


def test_source_post_is_set_null_when_the_post_goes(profile, handle):
    post = Post.objects.create(author=handle, platform_post_id="100")
    req = RepurposeRequest.objects.create(
        profile=profile, source_caption="t", source_post=post
    )
    post.delete()
    req.refresh_from_db()
    assert req.source_post_id is None


def test_evaluation_needs_an_attempt_and_valid_decision(attempt):
    GenerationEvaluation.objects.create(
        attempt=attempt, decision="pass", evaluation={}, style_score=0.8
    )
    fails(
        lambda: GenerationEvaluation.objects.create(
            attempt_id=None, decision="pass", evaluation={}
        )
    )
    fails(
        lambda: GenerationEvaluation.objects.create(
            attempt=attempt, decision="maybe", evaluation={}
        )
    )
    fails(
        lambda: GenerationEvaluation.objects.create(
            attempt=attempt, decision="pass", evaluation={}, style_score=2
        )
    )


def test_user_action_edited_text_only_for_edit(attempt):
    UserAction.objects.create(attempt=attempt, action="accept")
    UserAction.objects.create(attempt=attempt, action="edit", edited_text="mine")
    fails(lambda: UserAction.objects.create(attempt=attempt, action="edit"))
    fails(
        lambda: UserAction.objects.create(
            attempt=attempt, action="reject", edited_text="x"
        )
    )


def test_one_current_voice_per_profile_and_platform(profile):
    def voice(**kw):
        base = {
            "profile": profile,
            "platform": "general",
            "version": 1,
            "source": "posts",
            "payload": {},
        }
        return lambda: VoiceProfile.objects.create(**{**base, **kw})

    voice(is_current=True)()
    voice(version=2)()  # an old version
    fails(voice(version=3, is_current=True))
    voice(platform="x", is_current=True)()  # another platform has its own current voice
    fails(voice(version=1))  # (profile, platform, version) is unique
    fails(voice(platform="myspace", version=9))


def test_one_active_niche_and_keywords_unique_ignoring_case(profile):
    def niche(key, **kw):
        return lambda: NichePreference.objects.create(
            profile=profile, niche_key=key, title=key, source="user", **kw
        )

    first = niche("ai:global", is_active=True)()
    niche("fitness:global", is_active=False)()
    fails(niche("cooking:global", is_active=True))
    fails(niche("ai:global", is_active=False))
    NichePreferenceKeyword.objects.create(preference=first, keyword="LLM")
    fails(
        lambda: NichePreferenceKeyword.objects.create(preference=first, keyword="llm")
    )

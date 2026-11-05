"""Rewrite requests and attempts, quality evaluations, user-requested accounts and the turn log."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from django.db import transaction

from apps.intelligence.models import (
    GenerationEvaluation,
    PathTaken,
    RepurposeAttempt,
    RepurposeRequest,
    RequestMode,
    RouteLabel,
    TurnClassification,
    UserAction,
    UserActionKind,
    UserSearchRequest,
)
from apps.intelligence.repos.aio import aio
from apps.profiles import services
from apps.profiles.models import HandleOrigin, Post, SocialProfile
from lumi_ai.ports import (
    AttemptIn,
    AttemptOut,
    EvaluationIn,
    EvaluationRecord,
    TurnRecord,
    UserRequestOut,
)


def _attempt_out(row: RepurposeAttempt) -> AttemptOut:
    return AttemptOut(
        id=row.pk,
        request_id=row.request_id,
        platform=row.platform,  # type: ignore[arg-type]
        output=row.output,
        attempt_no=row.attempt_no,
        must_keep_passed=row.must_keep_passed,
        judge_verdict=row.judge_verdict,
        judge_confidence=row.judge_confidence,
        created_at=row.created_at,
    )


def _evaluation_row(attempt_id: int, ev: EvaluationIn) -> GenerationEvaluation:
    return GenerationEvaluation(
        attempt_id=attempt_id,
        style_score=ev.style_similarity,
        decision=ev.decision,
        evaluation={
            "scores": dict(ev.scores),
            "reasons": dict(ev.reasons),
            "deterministic_failures": list(ev.deterministic_failures),
            "judge": ev.judge,
            "config_version": ev.config_version,
        },
    )


class RepurposeRepo:
    """``RepurposeStore``. A request and ALL its attempts are written in one transaction."""

    @aio
    def create_request_with_attempts(
        self,
        profile_id: int,
        source_text: str,
        route_label: str | None,
        attempts: Sequence[AttemptIn],
        *,
        mode: Literal["repurpose", "topic"] = "repurpose",
        brief: str | None = None,
        source_post_id: int | None = None,
        evaluations: Mapping[int, EvaluationIn] | None = None,
    ) -> tuple[int, list[AttemptOut]]:
        evaluations = evaluations or {}
        numbers = [a.attempt_no for a in attempts]
        unknown = set(evaluations) - set(numbers)
        if unknown:
            raise ValueError(f"evaluations for unknown attempts: {sorted(unknown)}")
        if evaluations and len(set(numbers)) != len(numbers):
            raise ValueError(
                "evaluations are keyed by attempt_no, which repeats across platforms here"
            )
        with transaction.atomic():
            if source_post_id is not None:
                owns = Post.objects.filter(
                    pk=source_post_id,
                    author__in=SocialProfile.objects.filter(pk=profile_id).values(
                        "handle"
                    ),
                ).exists()
                if not owns:
                    raise LookupError(
                        f"post {source_post_id} is not a post of profile {profile_id}"
                    )
            request = RepurposeRequest.objects.create(
                profile_id=profile_id,
                source_caption=source_text,
                source_post_id=source_post_id,
                route_label=RouteLabel(route_label) if route_label else None,
                mode=RequestMode(mode),
                brief=brief,
            )
            rows = RepurposeAttempt.objects.bulk_create(
                [
                    RepurposeAttempt(
                        request=request,
                        platform=a.platform,
                        tier=a.tier,
                        model=a.model,
                        provider=a.provider,
                        attempt_no=a.attempt_no,
                        output=a.output,
                        must_keep_passed=a.must_keep_passed,
                        judge_verdict=a.judge_verdict,
                        judge_confidence=a.judge_confidence,
                        is_fallback=a.is_fallback,
                    )
                    for a in attempts
                ]
            )
            by_no = {r.attempt_no: r for r in rows}
            if evaluations:
                GenerationEvaluation.objects.bulk_create(
                    [
                        _evaluation_row(by_no[no].pk, ev)
                        for no, ev in sorted(evaluations.items())
                    ]
                )
            # ``db_default=Now()`` is not echoed back by ``bulk_create``; read the stored rows.
            stored = RepurposeAttempt.objects.filter(pk__in=[r.pk for r in rows])
            by_id = {r.pk: r for r in stored}
        return request.pk, [_attempt_out(by_id[r.pk]) for r in rows]

    @aio
    def record_user_action(
        self,
        profile_id: int,
        attempt_id: int,
        action: Literal["accept", "edit", "reject"],
        edited_text: str | None = None,
    ) -> None:
        if not RepurposeAttempt.objects.filter(
            pk=attempt_id, request__profile_id=profile_id
        ).exists():
            raise LookupError(
                f"attempt {attempt_id} not found for profile {profile_id}"
            )
        if action == "edit" and not edited_text:
            raise ValueError("an edit needs the edited text")
        UserAction.objects.create(
            attempt_id=attempt_id,
            action=UserActionKind(action),
            edited_text=edited_text if action == "edit" else None,
        )


class EvalRepo:
    """``EvalStore``: ``generation_evaluations`` (one row per scored attempt)."""

    @aio
    def save_evaluation(self, record: EvaluationRecord) -> int:
        if not RepurposeAttempt.objects.filter(
            pk=record.attempt_id, request__profile_id=record.profile_id
        ).exists():
            raise LookupError(
                f"attempt {record.attempt_id} not found for profile {record.profile_id}"
            )
        row = _evaluation_row(record.attempt_id, record)
        row.save()
        return row.pk

    @aio
    def list_evaluations(
        self, profile_id: int, *, limit: int = 50
    ) -> list[EvaluationRecord]:
        rows = (
            GenerationEvaluation.objects.filter(attempt__request__profile_id=profile_id)
            .select_related("attempt")
            .order_by("-id")[: max(limit, 0)]
        )
        out = []
        for row in rows:
            data = row.evaluation
            out.append(
                EvaluationRecord(
                    profile_id=profile_id,
                    platform=row.attempt.platform,  # type: ignore[arg-type]
                    draft=row.attempt.output,
                    decision=row.decision,  # type: ignore[arg-type]
                    scores=data.get("scores", {}),
                    reasons=data.get("reasons", {}),
                    deterministic_failures=tuple(
                        data.get("deterministic_failures", ())
                    ),
                    style_similarity=row.style_score,
                    judge=data.get("judge"),
                    config_version=data.get("config_version"),
                    attempt_id=row.attempt_id,
                )
            )
        return out


class RequestRepo:
    """``RequestStore``: accounts the user asked about. The platform is the handle's."""

    @aio
    def save_user_request(
        self,
        profile_id: int,
        handle: str,
        note: str | None,
        *,
        platform: str | None = None,
    ) -> UserRequestOut:
        with transaction.atomic():
            if platform is None:
                platform = (
                    SocialProfile.objects.filter(pk=profile_id)
                    .values_list("handle__platform", flat=True)
                    .first()
                )
                if platform is None:
                    raise LookupError(f"profile {profile_id} not found")
            handle_id = services.get_or_create_handle(
                platform, handle, origin=HandleOrigin.LIVE
            )
            earlier = UserSearchRequest.objects.filter(
                profile_id=profile_id, handle_id=handle_id
            ).exists()
            row = UserSearchRequest.objects.create(
                profile_id=profile_id, handle_id=handle_id, request_note=note or ""
            )
        return _request_out(
            row, handle_normalized=row.handle.handle_normalized, earlier=earlier
        )

    @aio
    def list_user_requests(
        self, profile_id: int, *, limit: int = 50
    ) -> list[UserRequestOut]:
        rows = list(
            UserSearchRequest.objects.filter(profile_id=profile_id)
            .select_related("handle")
            .order_by("-id")[: max(limit, 0)]
        )
        # "Already requested" = an older row for the same handle exists, whatever the page cut.
        first_seen = {
            handle_id: first
            for handle_id, first in UserSearchRequest.objects.filter(
                profile_id=profile_id, handle_id__in={r.handle_id for r in rows}
            )
            .order_by("handle_id", "id")
            .values_list("handle_id", "id")
            .distinct("handle_id")
        }
        return [
            _request_out(
                r,
                handle_normalized=r.handle.handle_normalized,
                earlier=first_seen.get(r.handle_id, r.pk) != r.pk,
            )
            for r in rows
        ]


def _request_out(
    row: UserSearchRequest, *, handle_normalized: str, earlier: bool
) -> UserRequestOut:
    return UserRequestOut(
        id=row.pk,
        handle=handle_normalized,
        note=row.request_note or None,
        already_requested=earlier,
        created_at=row.created_at,
    )


class TurnLogRepo:
    """``TurnLogStore``: one ``turn_classifications`` row per turn."""

    @aio
    def record_turn(self, record: TurnRecord) -> int:
        row = TurnClassification.objects.create(
            profile_id=record.profile_id,
            message_id=record.message_id,
            message_text_hash=record.message_text_hash,
            message_preview=record.message_preview[:160],
            path_taken=PathTaken(record.path_taken),
            rule_class=record.rule_class,
            rule_matched=record.rule_matched,
            jev_called=record.judge_called,
            jev_class=record.judge_class,
            jev_probs=list(record.judge_probs)
            if record.judge_probs is not None
            else None,
            jev_confidence=record.judge_confidence,
            jev_latency_ms=record.judge_latency_ms,
            jev_error=record.judge_error,
            final_class=record.final_class,
            tools_called=list(record.tools_called),
            total_latency_ms=record.total_latency_ms,
            timings=dict(record.timings) if record.timings is not None else None,
        )
        return row.pk

    @aio
    def mark_corrected(self, record_id: int) -> None:
        TurnClassification.objects.filter(pk=record_id).update(user_corrected=True)

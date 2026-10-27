"""A write tool that timed out must not commit afterwards; a fast one still does.

Runs the real agent loop with the real ``@aio`` repositories on a transactional database: the slow
write finishes its ORM work in a worker thread *after* the loop gave up, which is exactly when a
commit used to slip through.
"""

from __future__ import annotations

import json
import time

import pytest
from asgiref.sync import async_to_sync

from apps.intelligence.models import MemoryNote
from apps.intelligence.repos import MemoryRepo, memory
from lumi_ai.config import AIConfig
from lumi_ai.ports import ProfileInfo
from lumi_ai.tests.agent.harness import call, make_rig, say, tool, use

pytestmark = pytest.mark.django_db(transaction=True)

REMEMBER = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
}


def _rig(profile, timeout: float):
    repo = MemoryRepo()

    async def remember(ctx, text):
        note, _ = await repo.add_note(ctx.profile_id, text)
        return {"id": note.id}

    rig = make_rig(
        [
            use(call("remember", {"text": "likes tea"})),
            say("Done."),
        ],
        [tool("remember", remember, cost="write", parameters=REMEMBER)],
        config=AIConfig(tool_timeout_seconds=timeout),
    )
    rig.loop.deps.profiles.profile = ProfileInfo(
        profile.id, "Ana", "ana", "linkedin", ("linkedin",)
    )
    return rig


def _slow_after_insert(monkeypatch, seconds: float):
    """The row is inserted, then the worker thread dawdles before the transaction commits."""
    real = memory._out

    def slow(row):
        time.sleep(seconds)
        return real(row)

    monkeypatch.setattr(memory, "_out", slow)


def test_a_slow_write_past_its_timeout_leaves_no_row(profile, monkeypatch):
    _slow_after_insert(monkeypatch, 0.4)
    rig = _rig(profile, timeout=0.1)
    async_to_sync(rig.run)("remember I like tea", profile.id)
    time.sleep(0.6)  # the abandoned worker thread has finished by now
    assert MemoryNote.objects.filter(profile_id=profile.id).count() == 0
    err = json.loads(rig.llm.tool_messages(1)[0]["content"])["error"]
    assert "timed out" in err and "already been saved" not in err


def test_a_fast_write_still_commits(profile):
    rig = _rig(profile, timeout=5)
    async_to_sync(rig.run)("remember I like tea", profile.id)
    assert list(
        MemoryNote.objects.filter(profile_id=profile.id).values_list(
            "content", flat=True
        )
    ) == ["likes tea"]
    assert "error" not in json.loads(rig.llm.tool_messages(1)[0]["content"])


def test_outside_a_tool_call_the_repo_is_untouched(profile):
    """No token in the context (endpoints, tasks, reads): no wrapper transaction, same behaviour."""
    note, created = async_to_sync(MemoryRepo().add_note)(profile.id, "plain write")
    assert created and MemoryNote.objects.filter(id=note.id).exists()

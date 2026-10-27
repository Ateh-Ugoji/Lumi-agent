"""CancelToken: a commit that has not started is refused after cancel; one in flight is reported."""

from __future__ import annotations

import threading

import pytest

from lumi_ai.cancel import CancelToken, WriteCancelled


def test_commit_before_cancel_is_counted():
    token = CancelToken()
    with token.commit_gate():
        pass
    assert token.cancel() == 1


def test_commit_after_cancel_is_refused_and_leaves_the_lock_free():
    token = CancelToken()
    token.cancel()
    with pytest.raises(WriteCancelled), token.commit_gate():
        pytest.fail("the gate must not open after cancel")
    assert token.commits == 0
    assert token.cancel() == 0  # would deadlock if the refused gate kept the lock


def test_a_failed_commit_is_not_counted():
    token = CancelToken()
    with pytest.raises(RuntimeError), token.commit_gate():
        raise RuntimeError("commit failed")
    assert token.cancel() == 0


def test_cancel_waits_for_a_commit_already_in_flight_and_reports_it():
    token = CancelToken()
    inside, release = threading.Event(), threading.Event()

    def committer():
        with token.commit_gate():
            inside.set()
            release.wait(5)

    t = threading.Thread(target=committer)
    t.start()
    assert inside.wait(5)
    seen: list[int] = []
    c = threading.Thread(target=lambda: seen.append(token.cancel()))
    c.start()
    c.join(0.1)
    assert c.is_alive()  # still waiting for the commit
    release.set()
    t.join(5)
    c.join(5)
    assert seen == [1]

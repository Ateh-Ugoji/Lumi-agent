"""Shared setup for the connections tests. No test here needs a key or the network."""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live: real provider call; skipped without LUMI_RUN_LIVE=1 and the needed key",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if os.environ.get("LUMI_RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(
        reason="live test: set LUMI_RUN_LIVE=1 and the provider key to run"
    )
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)

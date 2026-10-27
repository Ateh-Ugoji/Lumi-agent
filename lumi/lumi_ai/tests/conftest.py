"""Shared test setup for lumi_ai.

The ``live`` marker is registered here (``pyproject.toml`` belongs to LUMI-ARCHITECT). Tests marked
``live`` make real provider calls and are skipped unless ``LUMI_RUN_LIVE=1`` is set and the
test's own key variable is present.
"""

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

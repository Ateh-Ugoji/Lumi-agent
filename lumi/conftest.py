"""Root pytest hooks.

Tests marked ``live`` call a real service. They are collected everywhere but skipped unless
``LUMI_RUN_LIVE=1``, and each one still skips when the key it needs is missing. So a plain
``uv run pytest`` passes with no keys and no network.
"""

import os

import pytest

_REASON = "test live: pon LUMI_RUN_LIVE=1 y las keys en lumi/.env para correrlo"


def pytest_collection_modifyitems(config, items):
    if os.environ.get("LUMI_RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason=_REASON)
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)

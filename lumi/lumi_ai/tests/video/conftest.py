import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def gemini_ok() -> dict:
    return json.loads((FIXTURES / "gemini_generate_content_ok.json").read_text())


@pytest.fixture
def gemini_blocked() -> dict:
    return json.loads((FIXTURES / "gemini_generate_content_blocked.json").read_text())

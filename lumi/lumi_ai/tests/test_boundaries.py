"""lumi_ai must stay free of web-framework imports and of Ateh-specific constants."""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
FORBIDDEN_ROOTS = {"django", "rest_framework", "fastapi", "sqlmodel", "sqlalchemy", "app"}
FORBIDDEN_TEXT = ("AtehOfficial", "ateh_x_connect", "DEFAULT_NICHE_HANDLES")


def _python_files() -> list[Path]:
    return [p for p in PACKAGE.rglob("*.py") if "tests" not in p.relative_to(PACKAGE).parts]


def test_no_web_framework_imports() -> None:
    offenders: list[str] = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            roots: list[str] = []
            if isinstance(node, ast.Import):
                roots = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots = [node.module.split(".")[0]]
            offenders += [f"{path.relative_to(PACKAGE)}: imports {r}" for r in roots if r in FORBIDDEN_ROOTS]
    assert not offenders, offenders


def test_no_single_user_constants() -> None:
    offenders = [
        f"{p.relative_to(PACKAGE)}: {needle}"
        for p in _python_files()
        for needle in FORBIDDEN_TEXT
        if needle in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders

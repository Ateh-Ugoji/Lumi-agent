"""Every error code in the API is a generic one from CONTRATOS section 2 or ``<domain>.<reason>``.

The generic list is read from the contract table, so adding a code there is the only edit
needed. The scan covers ``ApiError(...)``, ``error_body(...)`` and ``JobError(...)`` calls in every
app: a job's ``error_code`` reaches the client in ``GET /jobs/{id}`` like any other code.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
APPS = ROOT / "apps"
CONTRACT = ROOT / "docs" / "CONTRATOS.md"
DOMAIN_CODE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")

#: Codes that predate the rule and belong to another team's files. Each one names its owner and
#: the new code. When the owner renames it, the test below fails until the entry is deleted here.
PENDING_RENAME: dict[str, str] = {}


def generic_codes() -> set[str]:
    text = CONTRACT.read_text()
    table = text.split("| `code` | HTTP | Cuándo |", 1)[1].split("\n\n", 1)[0]
    return set(re.findall(r"^\| `([a-z_]+)` \| \d{3} \|", table, flags=re.MULTILINE))


def used_codes() -> list[tuple[str, int, str]]:
    found = []
    for path in sorted(APPS.rglob("*.py")):
        rel = path.relative_to(ROOT)
        if "tests" in rel.parts or "migrations" in rel.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if func not in {"ApiError", "error_body", "JobError"} or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                found.append((str(rel), node.lineno, first.value))
            elif isinstance(first, ast.JoinedStr) and first.values:
                head = first.values[0]
                if isinstance(
                    head, ast.Constant
                ):  # f"domain.{reason}": judge the prefix
                    found.append((str(rel), node.lineno, str(head.value) + "x"))
    return found


def test_the_contract_lists_the_generic_codes():
    codes = generic_codes()
    assert {
        "validation_error",
        "unauthenticated",
        "not_found",
        "internal_error",
    } <= codes
    assert not any("." in code for code in codes)


def test_every_code_is_generic_or_domain_prefixed():
    generic = generic_codes()
    bad = [
        f"{path}:{line} {code}"
        for path, line, code in used_codes()
        if code not in generic
        and not DOMAIN_CODE.match(code)
        and code not in PENDING_RENAME
    ]
    assert not bad, (
        "Use a generic code from CONTRATOS section 2 or '<domain>.<reason>':\n"
        + "\n".join(bad)
    )


def test_a_pending_rename_is_removed_once_the_owner_renames_the_code():
    used = {code for _, _, code in used_codes()}
    done = sorted(code for code in PENDING_RENAME if code not in used)
    assert not done, f"Renamed already, delete from PENDING_RENAME: {done}"


def test_the_rule_rejects_a_bare_domain_code():
    assert not DOMAIN_CODE.match("chat_unavailable")
    assert not DOMAIN_CODE.match("a.b.c")
    assert DOMAIN_CODE.match("publish.not_connected")

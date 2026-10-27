"""Parity of the new test suite against the 422 legacy tests.

The legacy tests live in ``lumi/tests`` and go away with ``lumi/app``. Their names are frozen in
``legacy_tests.tsv`` so the matrix survives the deletion. ``legacy_parity_map.tsv`` maps each
legacy test (by file and name regex, first match wins) to a status:

* ``covered``   a Django or ``lumi_ai`` test checks the same behavior.
* ``replaced``  the component was redesigned; the behavior is checked in its new form.
* ``deviation`` an accepted difference, listed in CONTRATOS section 11 (``§11:N`` in the note).
* ``retired``   dropped on purpose with the feature it tested; the note gives the reason and is
  required. Targets are optional (a retired test may point at the test that now guards the nearest
  behavior).
* ``gap``       nothing checks it yet.

A legacy test whose name matches a new test (after dropping articles) is ``covered`` with no rule.
``python -m apps.core.tests.legacy_parity --write`` regenerates ``plan/estado/PARIDAD-LEGADO.md``;
a test fails when that file drifts.
"""

from __future__ import annotations

import ast
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # lumi/
REPORT = ROOT / "plan" / "estado" / "PARIDAD-LEGADO.md"
CONTRATOS = ROOT / "docs" / "CONTRATOS.md"
LEGACY_TESTS_DIR = ROOT / "tests"
STATUSES = ("covered", "replaced", "deviation", "retired", "gap")
MIN_REASON_LENGTH = 20
EXPECTED_TOTAL = 422
_NEW_TEST_GLOBS = ("apps/*/tests/**/test_*.py", "lumi_ai/tests/**/test_*.py")
_SKIP_PARTS = {"legacy_parity"}


@dataclass(frozen=True)
class Rule:
    legacy_file: str
    name_regex: re.Pattern[str]
    status: str
    owner: str
    targets: tuple[str, ...]
    note: str


@dataclass(frozen=True)
class Verdict:
    legacy_file: str
    test: str
    count: int
    status: str
    owner: str
    targets: tuple[str, ...]
    note: str
    problems: tuple[str, ...]


def _tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def legacy_tests() -> list[tuple[str, str, int]]:
    return [
        (r["legacy_file"], r["test"], int(r["count"]))
        for r in _tsv(HERE / "legacy_tests.tsv")
    ]


def rules() -> list[Rule]:
    return [
        Rule(
            r["legacy_file"],
            re.compile(r["name_regex"]),
            r["status"],
            r["owner"],
            tuple(t for t in r["targets"].split(";") if t),
            r["note"],
        )
        for r in _tsv(HERE / "legacy_parity_map.tsv")
    ]


def _test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
            and n.name.startswith("test_")
            or isinstance(n, ast.ClassDef)
            and n.name.startswith("Test")
        ):
            names.add(n.name)
    return names


def new_tests() -> dict[str, set[str]]:
    """Test function names per file, relative to ``lumi/`` (class methods included)."""
    out: dict[str, set[str]] = {}
    for pattern in _NEW_TEST_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if _SKIP_PARTS & set(path.parts):
                continue
            out[path.relative_to(ROOT).as_posix()] = _test_names(path)
    return out


def _norm(name: str) -> str:
    name = name.removeprefix("test_")
    name = re.sub(r"(^|_)(the|a|an|is|are|does|do|to|and|its|s)(?=_|$)", "", name)
    return name.replace("_", "")


def _bare(name: str) -> str:
    return name.removeprefix("test_")


def _check_target(target: str, files: dict[str, set[str]]) -> str | None:
    path, _, fragment = target.partition("::")
    names = files.get(path)
    if names is None:
        return f"target file does not exist: {path}"
    if not fragment:
        return None if names else f"target file has no tests: {path}"
    if not any(fragment in n for n in names):
        return f"no test in {path} contains {fragment!r}"
    return None


def _contratos_rows() -> set[int]:
    text = CONTRATOS.read_text(encoding="utf-8") if CONTRATOS.exists() else ""
    return {int(m) for m in re.findall(r"^\|\s*(\d+)\s*\|", text, flags=re.MULTILINE)}


def rule_problems(rule: Rule, section_rows: set[int]) -> list[str]:
    """Shape problems of one rule, apart from whether its targets exist."""
    problems: list[str] = []
    if rule.status not in STATUSES:
        problems.append(f"unknown status {rule.status!r}")
    if rule.status == "gap" and rule.targets:
        problems.append("a gap has no targets")
    if rule.status in ("covered", "replaced", "deviation") and not rule.targets:
        problems.append("no targets")
    if rule.status == "retired" and len(rule.note.strip()) < MIN_REASON_LENGTH:
        problems.append("a retired test needs a written reason")
    if rule.status == "deviation":
        m = re.search(r"§11:(\d+)", rule.note)
        if not m or int(m.group(1)) not in section_rows:
            problems.append("deviation without an existing CONTRATOS section 11 row")
    return problems


def judge() -> list[Verdict]:
    files = new_tests()
    by_norm: dict[str, list[str]] = defaultdict(list)
    for path, names in files.items():
        for n in names:
            by_norm[_norm(n)].append(path)
    section_rows = _contratos_rows()
    all_rules = rules()
    out: list[Verdict] = []
    for legacy_file, test, count in legacy_tests():
        bare = _bare(test)
        rule = next(
            (
                r
                for r in all_rules
                if r.legacy_file == legacy_file and r.name_regex.fullmatch(bare)
            ),
            None,
        )
        problems: list[str] = []
        if rule is None:
            hit = by_norm.get(_norm(test))
            if hit:
                out.append(
                    Verdict(
                        legacy_file,
                        test,
                        count,
                        "covered",
                        "-",
                        (hit[0],),
                        "same name",
                        (),
                    )
                )
            else:
                out.append(
                    Verdict(
                        legacy_file, test, count, "unmapped", "-", (), "", ("no rule",)
                    )
                )
            continue
        problems += rule_problems(rule, section_rows)
        problems += [p for t in rule.targets if (p := _check_target(t, files))]
        out.append(
            Verdict(
                legacy_file,
                test,
                count,
                rule.status,
                rule.owner,
                rule.targets,
                rule.note,
                tuple(problems),
            )
        )
    return out


def unused_rules(verdicts: list[Verdict]) -> list[Rule]:
    """Rules that no legacy test reaches. They are dead and hide drift."""
    hit: set[tuple[str, str, str]] = set()
    all_rules = rules()
    for legacy_file, test, _ in legacy_tests():
        for r in all_rules:
            if r.legacy_file == legacy_file and r.name_regex.fullmatch(_bare(test)):
                hit.add((r.legacy_file, r.name_regex.pattern, r.status))
                break
    return [
        r
        for r in all_rules
        if (r.legacy_file, r.name_regex.pattern, r.status) not in hit
    ]


def legacy_names_on_disk() -> dict[str, set[str]] | None:
    """Test names found in ``lumi/tests`` right now, or ``None`` once it is deleted."""
    if not LEGACY_TESTS_DIR.is_dir():
        return None
    return {p.stem: _test_names(p) for p in sorted(LEGACY_TESTS_DIR.glob("test_*.py"))}


def render(verdicts: list[Verdict]) -> str:
    total = sum(v.count for v in verdicts)
    by_status = Counter()
    for v in verdicts:
        by_status[v.status] += v.count

    def pct(n: int) -> str:
        return f"{100 * n / total:.1f} %"

    lines = [
        "# Paridad con los tests legados",
        "",
        "Generado por `python -m apps.core.tests.legacy_parity --write`. No se edita a mano.",
        "Un test (`test_legacy_parity.py`) falla si este archivo se desvía del mapa.",
        "",
        "El mapa se hizo por comportamiento y se comprobó por nombre de test y lectura de muestras,",
        "no aserción por aserción. `covered` y `replaced` dicen que existe un test nuevo que cubre",
        "la misma conducta, no que sea equivalente línea a línea.",
        "",
        "## Resumen",
        "",
        "| Estado | Tests legados | Parte |",
        "| --- | ---: | ---: |",
    ]
    for st in STATUSES:
        lines.append(f"| {st} | {by_status[st]} | {pct(by_status[st])} |")
    lines += [f"| **Total** | **{total}** | 100 % |", ""]
    lines += [
        "## Por archivo legado",
        "",
        "| Archivo | Total | covered | replaced | deviation | retired | gap |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    per: dict[str, Counter] = defaultdict(Counter)
    for v in verdicts:
        per[v.legacy_file][v.status] += v.count
    for f in sorted(per):
        c = per[f]
        lines.append(
            f"| `{f}` | {sum(c.values())} | {c['covered']} | {c['replaced']} | {c['deviation']} | {c['retired']} | {c['gap']} |"
        )
    gaps = [v for v in verdicts if v.status == "gap"]
    lines += ["", "## Huecos", ""]
    if not gaps:
        lines.append("Ninguno.")
    else:
        owners: dict[str, list[Verdict]] = defaultdict(list)
        for v in gaps:
            owners[v.owner].append(v)
        for owner in sorted(owners):
            n = sum(v.count for v in owners[owner])
            lines += [f"### {owner}: {n} tests", ""]
            for v in owners[owner]:
                lines.append(f"- `{v.legacy_file}::{v.test}`: {v.note}")
            lines.append("")
    retired = [v for v in verdicts if v.status == "retired"]
    lines += ["", "## Retirados", ""]
    if not retired:
        lines.append("Ninguno.")
    for v in retired:
        lines.append(f"- `{v.legacy_file}::{v.test}`: {v.note}")
    lines.append("")
    reps = [v for v in verdicts if v.status in ("replaced", "deviation")]
    lines += ["## Reemplazos y desviaciones", ""]
    seen: set[tuple[str, str]] = set()
    for v in reps:
        key = (v.legacy_file, v.note)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- `{v.legacy_file}` ({v.status}): {v.note}")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    verdicts = judge()
    text = render(verdicts)
    if "--write" in argv:
        REPORT.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 1 if any(v.problems for v in verdicts) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

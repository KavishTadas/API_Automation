#!/usr/bin/env python3
"""Score this repository against its own coding standards, and record the score.

KR3.2 asks for standards "followed, trend improving". A document alone cannot
show either: it states an intention, and an intention has no direction. So the
standards that a machine can check are checked here on every run, and the
result is appended to a history file. The number moves because the code moved,
not because somebody estimated it.

What this deliberately does not do is score judgement. Whether a commit message
explains why, whether a comment earns its place, whether an abstraction is the
right one -- those are real standards, they are in the document, and a regex
claiming to measure them would produce a confident number about nothing. They
carry a reviewer's score instead, recorded by hand in the same history file.

So the KR3.2 figure has two halves, kept apart on purpose:

    automated  -- this script, objective, every run
    reviewed   -- a person, monthly, against the document's review section

A first run establishes a baseline. A baseline is not a trend, and this script
says so rather than implying an improvement it cannot yet see.
"""

from __future__ import annotations

import argparse
import ast
import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "reports" / "standards" / "history.json"

#: Files implementing one global contract check: 01_..., 02_... and so on.
CHECK_FILES = sorted((ROOT / "test-cases" / "global").glob("[0-9]*.py"))


class Rule:
    """One machine-checkable standard.

    Scored ``met`` out of ``total`` rather than pass/fail: a standard followed
    by 23 of 28 files is not "failed", and recording it that way would hide the
    direction of travel, which is the only thing KR3.2 actually asks about.
    """

    def __init__(self, key: str, title: str, why: str) -> None:
        self.key, self.title, self.why = key, title, why
        self.met = 0
        self.total = 0
        self.offenders: list[str] = []

    def record(self, ok: bool, subject: str) -> None:
        self.total += 1
        if ok:
            self.met += 1
        else:
            self.offenders.append(subject)

    @property
    def score(self) -> float:
        return 1.0 if self.total == 0 else self.met / self.total

    def as_dict(self) -> dict:
        return {
            "rule": self.key,
            "title": self.title,
            "met": self.met,
            "total": self.total,
            "score": round(self.score, 4),
            "offenders": self.offenders,
        }


def _module_docstring(path: Path) -> str:
    """Read the docstring by parsing the module, never by matching quotes.

    The first version of this used a regex ending at the first ``\"\"\"``, and
    it reported 28_blank_name_input_is_rejected.py as undeclared. That file is
    fully compliant; its prose quotes a blank-name payload as six quote
    characters, which closed the match early and hid the declarations below it.

    A scorer that invents offenders is worse than no scorer -- it sends someone
    to fix a file that was already correct, and the number it produces cannot
    be trusted in either direction. So the docstring comes from the parser that
    defines what a docstring is.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return ""
    return ast.get_docstring(tree) or ""


def rule_has_module_docstring() -> Rule:
    rule = Rule(
        "has-module-docstring",
        "Every check opens with a docstring naming the standard it enforces",
        "The first line becomes the check's title in the report. A check whose "
        "purpose exists only inside its assertion message cannot be reviewed "
        "without running it.",
    )
    for path in CHECK_FILES:
        rule.record(bool(_module_docstring(path).strip()), path.name)
    return rule


def rule_declares_emitted_states() -> Rule:
    rule = Rule(
        "declares-emitted-states",
        "Every check declares which result states it can emit",
        "Whether a check can fail a build is the first thing a reader needs and "
        "the last thing they should have to derive from its body.",
    )
    for path in CHECK_FILES:
        rule.record("Emits:" in _module_docstring(path), path.name)
    return rule


def rule_declares_metadata_read() -> Rule:
    rule = Rule(
        "declares-metadata-read",
        "Every check declares the metadata fields it reads",
        "A metadata field nobody declares is one nobody knows to populate; the "
        "check then reports NOT_APPLICABLE forever and the gap looks like "
        "coverage.",
    )
    for path in CHECK_FILES:
        rule.record("Reads metadata field" in _module_docstring(path), path.name)
    return rule


def rule_no_committed_credentials() -> Rule:
    rule = Rule(
        "no-committed-credentials",
        "No credential-shaped string is committed",
        "This repository published a working password once. The scanner is the "
        "part that stops the next one.",
    )
    scanner = ROOT / "scripts" / "scan-credentials.py"
    if not scanner.exists():
        rule.record(False, "scripts/scan-credentials.py is missing")
        return rule
    proc = subprocess.run(
        [sys.executable, str(scanner)], cwd=ROOT, capture_output=True, text=True
    )
    rule.record(proc.returncode == 0, (proc.stdout + proc.stderr).strip()[:300])
    return rule


def rule_generated_output_matches_source() -> Rule:
    """The built console must match what the generator produces from its template.

    The template is the source and the built file is output. An edit made to
    the output survives until the next build and then vanishes, taking whoever
    relied on it by surprise -- so drift here is a defect, not a nit.
    """
    rule = Rule(
        "generated-output-not-hand-edited",
        "The built console matches a fresh build of its template",
        "An edit made to generated output is silently discarded by the next "
        "build.",
    )
    built = ROOT / "docs" / "platform-ui" / "unified-console.html"
    builder = ROOT / "scripts" / "build_unified_console.py"
    if not built.exists():
        rule.record(False, "unified-console.html has not been built")
        return rule
    before = built.read_bytes()
    proc = subprocess.run(
        [sys.executable, str(builder)], cwd=ROOT, capture_output=True, text=True
    )
    if proc.returncode != 0:
        rule.record(False, "the build itself failed: " + proc.stderr.strip()[:250])
        return rule
    after = built.read_bytes()

    # A rebuild stamps a fresh generatedAt, which is not drift. Everything else
    # differing means the output was edited by hand.
    def strip(blob: bytes) -> bytes:
        return re.sub(rb'"generatedAt":\s*"[^"]*"', b"", blob)

    rule.record(strip(before) == strip(after), "built output differs from its template")
    return rule


RULES = (
    rule_has_module_docstring,
    rule_declares_emitted_states,
    rule_declares_metadata_read,
    rule_no_committed_credentials,
    rule_generated_output_matches_source,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python scripts/score_standards.py",
        description="Score this repository against docs/standards/CODING-STANDARDS.md.",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="append this score to reports/standards/history.json",
    )
    parser.add_argument(
        "--reviewed",
        type=float,
        default=None,
        metavar="PCT",
        help="the reviewer's score for this period, 0-100; recorded beside the "
        "automated score and never averaged into it",
    )
    args = parser.parse_args(argv)

    results = [factory() for factory in RULES]
    met = sum(r.met for r in results)
    total = sum(r.total for r in results)
    overall = met / total if total else 0.0

    width = max(len(r.title) for r in results)
    print("\nCoding standards — API Automation")
    print("scored " + _dt.date.today().isoformat() + "\n")
    for rule in results:
        flag = "ok" if rule.score == 1 else "  "
        print(
            "  {0} {1:<{2}}  {3:>3}/{4:<3}  {5:6.1%}".format(
                flag, rule.title, width, rule.met, rule.total, rule.score
            )
        )
        for offender in rule.offenders[:4]:
            print("        - " + offender)
        if len(rule.offenders) > 4:
            print("        - and {0} more".format(len(rule.offenders) - 4))
    print("  " + "-" * (width + 21))
    print(
        "  {0:<{1}}  {2:>3}/{3:<3}  {4:6.1%}".format(
            "AUTOMATED SCORE", width + 3, met, total, overall
        )
    )
    if args.reviewed is not None:
        print(
            "  {0:<{1}}  {2:>7}  {3:6.1f}%".format(
                "REVIEW SCORE", width + 3, "", args.reviewed
            )
        )

    if not args.record:
        print("\n  Not recorded. Pass --record to append this to the history.")
        return 0

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    history = json.loads(HISTORY.read_text(encoding="utf-8")) if HISTORY.exists() else []
    history.append(
        {
            "date": _dt.date.today().isoformat(),
            "automatedScore": round(overall, 4),
            "met": met,
            "total": total,
            "reviewedScore": args.reviewed,
            "rules": [r.as_dict() for r in results],
        }
    )
    HISTORY.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    print("\n  recorded to {0} - entry {1}".format(HISTORY.relative_to(ROOT), len(history)))
    if len(history) == 1:
        print("  This is the baseline. One reading is not a trend; the next one "
              "is what makes it one.")
    else:
        previous = history[-2]["automatedScore"]
        delta = overall - previous
        direction = "improving" if delta > 0 else ("flat" if delta == 0 else "down")
        print("  Against {0}: {1:+.1%} - {2}.".format(history[-2]["date"], delta, direction))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Regression: the Python result emitter redacts credentials before writing.

Why this exists separately from ``verify-reporter-redaction.js``:
``scripts/reporter-config.js`` monkey-patches Node's ``fs`` and so protects only
what Node writes. ``tests/global_contract/result_emitter.py`` writes from Python
and is therefore outside that protection entirely — putting its output under
``reports/`` buys directory hygiene, not redaction.

Also checks every regex the emitter and its published contract depend on for
stray control characters. A literal ``0x08`` byte silently disabled a
JWT-detection pattern in Sprint 2 while every test still passed: a regex that
*cannot* match looks exactly like one with nothing to find, so this failure mode
is invisible unless something asserts against it.

Run:  python scripts/regression/verify-result-emitter-redaction.py
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tests.global_contract.result_emitter import (  # noqa: E402
    REDACTED,
    ResultCollector,
    ResultRecord,
    build_result_document,
    write_result_document,
)
from tests.global_contract.result_states import ResultState  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


# A deliberately planted credential set. None of these are real.
PLANTED = {
    "EMP_CODE": "PLANTED-EMP-CODE-9911",
    "EMP_PASSWORD": "PLANTED-PASSWORD-VALUE",
    "AUTH_TOKEN": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJwbGFudGVkIn0.plantedsignature",
}


def main() -> int:
    print("verify-result-emitter-redaction")

    collector = ResultCollector()
    # A credential planted in a response body, reaching the emitter through the
    # reason string — the realistic leak path, since a failing assertion quotes
    # what it saw.
    collector.add(
        ResultRecord(
            test_id="global_contract::test_no_credential_leakage_in_response",
            api_ref="post|/auth/token|auth|login",
            state=ResultState.FAIL.name,
            reason=(
                "response body contained "
                f'{{"empCode": "{PLANTED["EMP_CODE"]}", '
                f'"password": "{PLANTED["EMP_PASSWORD"]}", '
                f'"token": "{PLANTED["AUTH_TOKEN"]}"}} '
                f"sent with Authorization: Bearer {PLANTED['AUTH_TOKEN']}"
            ),
            provenance={
                "sourceType": "newman",
                "authorization": f"Bearer {PLANTED['AUTH_TOKEN']}",
                "empCode": PLANTED["EMP_CODE"],
                "owner": "QA Platform",
            },
        )
    )
    # A clean record, to prove redaction does not blank ordinary content.
    collector.add(
        ResultRecord(
            test_id="global_contract::test_status_code_matches_spec",
            api_ref="get|/leaves|leave|all",
            state=ResultState.PASS.name,
            reason="",
            provenance={"sourceType": "newman", "owner": "QA Platform"},
        )
    )
    # One SKIPPED_NO_TOKEN, whose *count key* contains the word TOKEN.
    collector.add(
        ResultRecord(
            test_id="global_contract::test_404_for_unknown_route",
            api_ref="get|/leaves|leave|all",
            state=ResultState.SKIPPED_NO_TOKEN.name,
            reason="did not get token",
        )
    )

    document = build_result_document(
        collector, run_id="redaction-probe", environment="UAT"
    )

    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "result.json"
        write_result_document(target, document, config=PLANTED)
        text = target.read_text(encoding="utf-8")
        payload = json.loads(text)

    for name, value in PLANTED.items():
        check(value not in text, f"planted {name} absent from emitted result")

    check(
        not re.search(r"eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.", text),
        "no JWT-shaped string survives in emitted result",
    )
    check(
        not re.search(r"Bearer\s+[A-Za-z0-9._~+/=-]{8,}", text),
        "no live-looking Bearer value survives in emitted result",
    )
    check(REDACTED in text, "redaction placeholder is present, so redaction ran")

    # Redaction must not eat the schema it is protecting.
    counts = payload["summary"]["counts"]
    check(
        counts.get(ResultState.SKIPPED_NO_TOKEN.name) == 1,
        "SKIPPED_NO_TOKEN count survives redaction as an integer",
    )
    check(
        all(isinstance(v, int) for v in counts.values()),
        "every state count is still an integer after redaction",
    )
    # Look the record up rather than indexing: reports are sorted by apiRef and
    # results by testId, so positional access silently inspects the wrong row.
    auth_api = next(
        api for api in payload["apis"] if api["apiRef"].startswith("post|")
    )
    leak_result = next(
        r for r in auth_api["results"] if r["testId"].endswith("no_credential_leakage_in_response")
    )
    check(
        leak_result["provenance"].get("owner") == "QA Platform",
        "non-sensitive provenance is preserved",
    )
    check(
        leak_result["provenance"].get("authorization") == REDACTED,
        "sensitive provenance key is redacted",
    )
    check(payload["status"] == "COMPLETED_WITH_ERRORS", "run status survives redaction")

    # Control-character sweep over every regex this sprint introduced.
    import tests.global_contract.result_emitter as emitter
    import tests.global_contract.result_states as states
    import tests.global_contract.run_manifest as manifest

    for module in (emitter, states, manifest):
        patterns = [
            (name, value.pattern)
            for name, value in vars(module).items()
            if isinstance(value, re.Pattern)
        ]
        check(
            bool(patterns)
            and all(
                not any(ord(c) < 32 for c in pattern) for _, pattern in patterns
            ),
            f"{module.__name__} regexes free of stray control characters "
            f"({len(patterns)} checked)",
        )

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} check(s)")
        return 1
    print("All redaction checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

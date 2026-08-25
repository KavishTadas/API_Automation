"""The result document the platform renders.

Sprint 3 published what *would* run. This emits what *did*, in a shape that
joins to the catalogue on the IDs Sprint 3 defined — no positional matching, no
re-derived vocabulary.

The invariant everything here answers to
----------------------------------------
**Pass rate is computed over PASS + FAIL only.** 37 of 43 Newman requests carry
no assertions; if those render as passes the platform's headline number is a lie
on day one. So ``NOT_ASSERTED``, ``NOT_APPLICABLE``, ``SKIPPED_NO_TOKEN``,
``WARN`` and ``INFORMATIONAL`` stay out of the denominator, stay individually
countable, and a batch with nothing in the denominator reports *no pass rate* —
never 100%.

Classification is on the reason prefix, never the pytest verdict
---------------------------------------------------------------
``WARN`` and ``INFORMATIONAL`` reach pytest as skips, because ``pytest.skip`` is
the only built-in non-failing outcome that carries a machine-readable reason.
Both mean the check *ran*. Reading ``report.outcome`` alone silently reclassifies
them as "did not execute".

Run status and test status are orthogonal
-----------------------------------------
A test ``FAIL`` is not a run failure. ``COMPLETED`` means every requested tier
executed, however many individual assertions failed. Conflating the two makes a
single failing assertion look like an engine outage.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from tests.global_contract.result_states import (
    EXECUTED_STATES,
    PASS_RATE_DENOMINATOR_STATES,
    ResultState,
    classify,
    extract_field,
    extract_measurement,
    split_reason,
)


__all__ = [
    "GatewayClassification",
    "ResultCollector",
    "ResultRecord",
    "RunStatus",
    "build_result_document",
    "classify_gateway_failure",
    "pass_rate",
    "redact",
    "sensitive_values",
    "write_result_document",
]


class RunStatus:
    """Run-level status. Deliberately independent of individual test outcomes."""

    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    ABORTED = "ABORTED"


class GatewayClassification:
    """Why a request was rejected, when the status alone cannot say.

    Mirrors ``scripts/allure-category-classifier.js``. Without this distinction
    the platform renders "blocked by the gateway before your API was reached" as
    "your API failed" — for the entire Attendance module, which currently returns
    the WAF fingerprint from this runner.
    """

    AUTH_FAILURE_401 = "AUTH_FAILURE_401"
    APPLICATION_AUTH_FAILURE_403 = "APPLICATION_AUTH_FAILURE_403"
    GATEWAY_WAF_EMPTY_BODY_403 = "GATEWAY_WAF_EMPTY_BODY_403"


def classify_gateway_failure(
    status_code: int | None,
    headers: dict[str, str] | None,
    body: str | None,
) -> str:
    """Classify an auth-shaped failure. Returns ``""`` when it is neither.

    An empty-bodied 403 with ``content-length: 0`` and a non-JSON content type
    is a gateway block: the request never reached the application, so nothing
    about the application has been demonstrated.
    """
    if status_code == 401:
        return GatewayClassification.AUTH_FAILURE_401
    if status_code != 403:
        return ""

    normalized = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    content_length = normalized.get("content-length", "").strip()
    content_type = normalized.get("content-type", "")
    body_text = str(body or "")

    if (
        content_length == "0"
        and not body_text.strip()
        and not re.search(r"json", content_type, re.IGNORECASE)
    ):
        return GatewayClassification.GATEWAY_WAF_EMPTY_BODY_403
    return GatewayClassification.APPLICATION_AUTH_FAILURE_403


@dataclass
class ResultRecord:
    """One test outcome for one API."""

    test_id: str
    api_ref: str
    state: str
    reason: str = ""
    missing_field: str = ""
    observed: float | None = None
    threshold: float | None = None
    duration_ms: float = 0.0
    #: True for a host-level probe measured once per host. Aggregation counts
    #: these per host, never per API — 45 APIs behind 3 hosts is 3 measurements.
    host_level: bool = False
    host: str = ""
    #: True when this API references a measurement carried by another API.
    references_host_result: bool = False
    gateway_classification: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    node_id: str = ""

    @property
    def result_state(self) -> ResultState:
        return ResultState[self.state]

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "testId": self.test_id,
            "apiRef": self.api_ref,
            "state": self.state,
            "reason": self.reason,
            "durationMs": round(self.duration_ms, 3),
            "executed": self.result_state in EXECUTED_STATES,
            "provenance": self.provenance,
        }
        if self.state == ResultState.NOT_APPLICABLE.name:
            # Required for NOT_APPLICABLE: naming the field is what lets a
            # consumer say "declare this" instead of "something is missing".
            payload["missingField"] = self.missing_field or None
        if self.state == ResultState.WARN.name:
            payload["observed"] = self.observed
            payload["threshold"] = self.threshold
        if self.host_level:
            payload["hostLevel"] = True
            payload["host"] = self.host or None
            payload["referencesHostResult"] = self.references_host_result
        if self.gateway_classification:
            payload["gatewayClassification"] = self.gateway_classification
        return payload


#: Decorations pytest prepends to a skip reason before it reaches longrepr.
#:
#: This is not cosmetic. ``pytest.skip("WARN: ...")`` surfaces as
#: ``"Skipped: WARN: ..."``, so classifying on the raw string finds the prefix
#: ``Skipped``, fails to match a state, and falls through to the verdict-based
#: default. Every state then collapses to NOT_APPLICABLE — and because
#: NOT_APPLICABLE is by far the most common outcome, the output looks entirely
#: plausible while WARN, INFORMATIONAL and SKIPPED_NO_TOKEN quietly vanish.
PYTEST_REASON_PREFIXES = ("Skipped: ", "Skipped ", "XFAIL ", "xfail: ")


def strip_pytest_decoration(reason: str | None) -> str:
    """Remove pytest's own prefix so the state prefix is first in the string."""
    text = str(reason or "").strip()
    changed = True
    while changed:
        changed = False
        for prefix in PYTEST_REASON_PREFIXES:
            if text.startswith(prefix):
                text = text[len(prefix) :].lstrip()
                changed = True
    return text


def classify_report(
    outcome: str,
    longrepr_reason: str | None,
    was_xfail: bool,
) -> tuple[ResultState, str]:
    """Map a pytest outcome to a result state. Returns ``(state, reason)``.

    The reason prefix wins wherever there is one. Only a report that carries no
    structured reason falls back to the pytest verdict — an ordinary pass, an
    ordinary failure, or a skip somebody wrote by hand.
    """
    reason = strip_pytest_decoration(longrepr_reason)
    state = classify(reason)
    if state is not None:
        return state, reason

    if was_xfail:
        # A known infrastructure block, expected and non-blocking. It ran.
        return ResultState.INFORMATIONAL, reason or "expected failure (xfail)"
    if outcome == "passed":
        return ResultState.PASS, reason
    if outcome == "failed":
        return ResultState.FAIL, reason
    return ResultState.NOT_APPLICABLE, reason or "skipped without a structured reason"


class ResultCollector:
    """Accumulates records during a run. Installed by ``conftest.py``."""

    def __init__(self) -> None:
        self.records: list[ResultRecord] = []
        self.api_provenance: dict[str, dict[str, Any]] = {}
        self.gateway_classifications: dict[str, str] = {}
        self.bootstrap_failures: dict[str, str] = {}
        self.aborted_reason: str = ""

    def add(self, record: ResultRecord) -> None:
        if not record.gateway_classification:
            record.gateway_classification = self.gateway_classifications.get(
                record.api_ref, ""
            )
        if not record.provenance:
            record.provenance = self.api_provenance.get(record.api_ref, {})
        self.records.append(record)

    def record_api(self, api_ref: str, provenance: dict[str, Any]) -> None:
        self.api_provenance[api_ref] = provenance

    def record_gateway(self, api_ref: str, classification: str) -> None:
        if classification:
            self.gateway_classifications[api_ref] = classification


def pass_rate(counts: dict[str, int]) -> float | None:
    """Pass rate over ``PASS + FAIL`` only, or ``None`` when the denominator is 0.

    ``None`` means *not applicable*, and callers must render it that way. A batch
    of entirely unasserted APIs has no pass rate; reporting 100% would be the
    exact failure this whole design exists to prevent.
    """
    denominator = sum(
        counts.get(state.name, 0) for state in PASS_RATE_DENOMINATOR_STATES
    )
    if denominator == 0:
        return None
    return round(counts.get(ResultState.PASS.name, 0) / denominator, 4)


def _counts(records: list[ResultRecord]) -> dict[str, int]:
    tally = Counter(record.state for record in records)
    return {state.name: tally.get(state.name, 0) for state in ResultState}


def _countable(records: list[ResultRecord]) -> list[ResultRecord]:
    """Drop records that merely reference a measurement carried elsewhere.

    A host-level probe runs once per host. Counting the 44 APIs that reference
    it as 44 NOT_APPLICABLE results inflates the denominator's neighbours and
    makes a batch look far more skipped than it is.
    """
    return [record for record in records if not record.references_host_result]


def _summary(records: list[ResultRecord]) -> dict[str, Any]:
    countable = _countable(records)
    counts = _counts(countable)
    rate = pass_rate(counts)
    return {
        "total": len(countable),
        "referencedHostResults": len(records) - len(countable),
        "counts": counts,
        "passRate": rate,
        "passRateApplicable": rate is not None,
        "passRateBasis": "PASS / (PASS + FAIL)",
        # A batch is only clean if nothing needs a human to look at it. One WARN
        # or one SKIPPED_NO_TOKEN is not a clean pass.
        "clean": (
            counts[ResultState.FAIL.name] == 0
            and counts[ResultState.WARN.name] == 0
            and counts[ResultState.SKIPPED_NO_TOKEN.name] == 0
            and rate is not None
        ),
    }


def build_result_document(
    collector: ResultCollector,
    *,
    run_id: str,
    environment: str,
    requested_tiers: tuple[str, ...] = (),
    catalogue_version: str = "",
) -> dict[str, Any]:
    """Assemble the run's result document: per-API reports and one combined.

    Both come from the same run — the platform needs a per-API view to show a
    single API's detail and a combined view for the batch headline, and
    recomputing one from the other is where inconsistencies creep in.
    """
    by_api: dict[str, list[ResultRecord]] = {}
    for record in collector.records:
        by_api.setdefault(record.api_ref, []).append(record)

    api_reports = [
        {
            "apiRef": api_ref,
            "provenance": collector.api_provenance.get(api_ref, {}),
            "gatewayClassification": collector.gateway_classifications.get(api_ref)
            or None,
            "summary": _summary(records),
            "results": [r.as_dict() for r in sorted(records, key=lambda x: x.test_id)],
        }
        for api_ref, records in sorted(by_api.items())
    ]

    # Derived from the records rather than tracked separately, so the run
    # status can never disagree with what the results actually say.
    blocked_apis = sorted(
        {
            record.api_ref
            for record in collector.records
            if record.state == ResultState.SKIPPED_NO_TOKEN.name
        }
    )
    collector.bootstrap_failures.update({ref: "" for ref in blocked_apis})

    status = RunStatus.COMPLETED
    if collector.aborted_reason:
        status = RunStatus.ABORTED
    elif blocked_apis:
        # A tier ran only partially: some APIs never executed because their auth
        # bootstrap failed. Individual test failures never reach this branch.
        status = RunStatus.COMPLETED_WITH_ERRORS

    return {
        "runId": run_id,
        "environment": environment,
        "requestedTiers": list(requested_tiers),
        "catalogueVersion": catalogue_version,
        "status": status,
        "statusReason": collector.aborted_reason
        or (
            "auth bootstrap failed for: "
            + ", ".join(sorted(collector.bootstrap_failures))
            if collector.bootstrap_failures
            else ""
        ),
        # Sprint 3 may predict PLANNED for a check that reports NOT_APPLICABLE
        # here — content_type_negotiation does this when an API returns a status
        # nothing declared. That transition is expected. The reverse is not.
        "applicabilityNote": (
            "A test predicted PLANNED by the catalogue may report NOT_APPLICABLE "
            "at run time; the reverse cannot happen. This is not an inconsistency."
        ),
        "summary": _summary(collector.records),
        "apis": api_reports,
    }


REDACTED = "***REDACTED***"

#: Field names whose *values* are replaced wholesale. Mirrors the key pattern in
#: ``scripts/reporter-config.js`` so both layers hide the same things.
SENSITIVE_KEY_PATTERN = re.compile(
    r"(authorization|emp[_.-]*code|emp[_.-]*password|password|passwd"
    r"|secret|token|api[_-]?key)",
    re.IGNORECASE,
)

#: Keys that match the sensitive pattern by accident and must survive intact.
#:
#: ``SKIPPED_NO_TOKEN`` is a state name used as a *count* key — redacting it
#: replaces an integer with a placeholder and silently destroys the tally the
#: whole pass-rate contract depends on. A redactor that eats its own schema is
#: worse than one that misses a secret, because nothing about the output looks
#: wrong afterwards.
SAFE_KEYS = frozenset(
    {state.name for state in ResultState}
    | {
        "gatewayClassification",
        "missingField",
        "credentialAliases",
        "authProviderApiId",
        "passRateBasis",
        "executedStates",
        "passRateDenominatorStates",
        "passRateExcludedStates",
    }
)

#: A JWT anywhere in free text — a reason string can quote a response body.
JWT_PATTERN = re.compile(r"eyJ[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]*")

#: ``Bearer <something>`` in free text.
BEARER_PATTERN = re.compile(r"(Bearer)\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE)


def sensitive_values(config: dict[str, str] | None = None) -> tuple[str, ...]:
    """Literal secret values to strike from output, longest first.

    Longest-first matters: redacting a short value that is a substring of a
    longer one would leave the rest of the longer one exposed.
    """
    import os

    source = {**os.environ, **(config or {})}
    return tuple(
        sorted(
            {
                str(value).strip()
                for key, value in source.items()
                if SENSITIVE_KEY_PATTERN.search(str(key))
                and isinstance(value, str)
                and len(value.strip()) > 3
                # Placeholders from .env.example are not secrets, and redacting
                # them would blank out perfectly readable sample output.
                and not value.strip().lower().startswith("your_")
            },
            key=len,
            reverse=True,
        )
    )


def redact(value: Any, values: tuple[str, ...] = ()) -> Any:
    """Strip credentials from a result document before it is written.

    ``scripts/reporter-config.js`` monkey-patches Node's ``fs``, so it protects
    Node writes only; this emitter writes from Python. Redaction has to happen
    here too — a path being under ``reports/`` is not by itself protection.
    """
    if isinstance(value, dict):
        return {
            key: REDACTED
            if str(key) not in SAFE_KEYS and SENSITIVE_KEY_PATTERN.search(str(key))
            else redact(child, values)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [redact(child, values) for child in value]
    if isinstance(value, str):
        text = value
        for secret in values:
            if secret and secret in text:
                text = text.replace(secret, REDACTED)
        text = JWT_PATTERN.sub(REDACTED, text)
        return BEARER_PATTERN.sub(r"\1 " + REDACTED, text)
    return value


def write_result_document(
    destination: str | Path,
    document: dict[str, Any],
    config: dict[str, str] | None = None,
) -> Path:
    """Redact and write the result document as JSON. Returns the path."""
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact(document, sensitive_values(config))
    path.write_text(
        json.dumps(safe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def record_from_report(
    *,
    test_id: str,
    api_ref: str,
    outcome: str,
    reason: str | None,
    was_xfail: bool,
    duration_ms: float,
    node_id: str = "",
    host_level: bool = False,
    host: str = "",
    references_host_result: bool = False,
    provenance: dict[str, Any] | None = None,
) -> ResultRecord:
    """Build a record from one pytest report."""
    state, full_reason = classify_report(outcome, reason, was_xfail)
    _, detail = split_reason(full_reason)
    observed, threshold = extract_measurement(full_reason)

    return ResultRecord(
        test_id=test_id,
        api_ref=api_ref,
        state=state.name,
        reason=detail or full_reason,
        missing_field=extract_field(full_reason),
        observed=observed,
        threshold=threshold,
        duration_ms=duration_ms,
        host_level=host_level,
        host=host,
        references_host_result=references_host_result,
        provenance=dict(provenance or {}),
        node_id=node_id,
    )


def _asdict(record: ResultRecord) -> dict[str, Any]:  # pragma: no cover - helper
    return asdict(record)

"""The seven result states the QA platform reports for every contract check.

Pytest natively reports pass/fail/skip. The platform needs finer grain: it must
tell "the assertion ran and succeeded" apart from "the request ran but nothing
asserted it" and from "this check cannot apply to this API at all". Collapsing
those into a single "skipped" bucket — or worse, into "passed" — would make the
platform's headline pass rate a lie.

Transport mechanism
-------------------
States travel as a structured prefix on the pytest skip/marker reason, produced
by :func:`format_reason` and read back by :func:`classify`::

    pytest.skip(format_reason(ResultState.NOT_APPLICABLE, "no inventory row"))
    # -> "NOT_APPLICABLE: no inventory row"

That keeps the state machine-readable downstream without parsing free text, and
without a pytest plugin. Sprint 4's result emitter imports this module rather
than re-deriving the vocabulary.

Pass-rate invariant
-------------------
Pass rate is computed over ``PASS + FAIL`` only. The remaining five states are
excluded from the denominator but stay individually countable — see
:data:`PASS_RATE_DENOMINATOR_STATES` and :data:`PASS_RATE_EXCLUDED_STATES`.
"""

from __future__ import annotations

import re
from enum import Enum


__all__ = [
    "ResultState",
    "PASS_RATE_DENOMINATOR_STATES",
    "PASS_RATE_EXCLUDED_STATES",
    "REASON_SEPARATOR",
    "classify",
    "counts_toward_pass_rate",
    "extract_field",
    "extract_measurement",
    "extract_provider",
    "format_reason",
    "split_reason",
]


REASON_SEPARATOR = ": "

#: Marks the metadata field a NOT_APPLICABLE result is missing.
FIELD_MARKER = re.compile(r"\[field=([A-Za-z0-9_.]+)\]")

#: Marks the auth provider whose bootstrap blocked a SKIPPED_NO_TOKEN result.
#:
#: A marker rather than prose for the same reason ``[field=...]`` is one: the
#: provider id is the thing a consumer acts on — it names which credential to
#: fix — and recovering it by parsing a sentence breaks the first time anyone
#: rewords the sentence. Provider ids are ``|``-delimited inventory
#: identifiers, so the character class is deliberately wider than
#: ``FIELD_MARKER``'s and stops at the closing bracket.
PROVIDER_MARKER = re.compile(r"\[provider=([^\]]+)\]")

#: A WARN carries both numbers so the threshold is never implicit.
MEASUREMENT_OBSERVED = re.compile(r"observed=([0-9]+(?:\.[0-9]+)?)")
MEASUREMENT_THRESHOLD = re.compile(r"threshold=([0-9]+(?:\.[0-9]+)?)")


class ResultState(Enum):
    """Every contract check resolves to exactly one of these."""

    PASS = "Assertion ran and succeeded"
    FAIL = "Assertion ran and failed"
    WARN = "Ran; an advisory threshold was exceeded; the run is not failed"
    SKIPPED_NO_TOKEN = "Auth bootstrap failed, so the API was never executed"
    NOT_APPLICABLE = "The check cannot apply because required metadata is absent"
    NOT_ASSERTED = "The request executed but no assertion exists for it"
    INFORMATIONAL = "Observes and records; asserts nothing about the response"

    @property
    def description(self) -> str:
        """Human-readable meaning, for report legends."""
        return self.value


#: The only two states that may appear in a pass-rate denominator.
PASS_RATE_DENOMINATOR_STATES = frozenset({ResultState.PASS, ResultState.FAIL})

#: Everything else. Excluded from the denominator, still individually counted.
#: Counting NOT_ASSERTED as a pass is the failure mode this guards against.
PASS_RATE_EXCLUDED_STATES = frozenset(ResultState) - PASS_RATE_DENOMINATOR_STATES

#: States that mean the check actually ran against the API.
#:
#: WARN and INFORMATIONAL belong here even though pytest reports them as skips —
#: they are emitted through ``pytest.skip`` only because that is the one
#: built-in non-failing outcome carrying a machine-readable reason. Treating
#: them as "did not execute" understates real coverage.
EXECUTED_STATES = frozenset(
    {
        ResultState.PASS,
        ResultState.FAIL,
        ResultState.WARN,
        ResultState.INFORMATIONAL,
    }
)


def format_reason(
    state: ResultState,
    detail: str = "",
    field: str = "",
    provider: str = "",
) -> str:
    """Render ``state`` and ``detail`` as a machine-readable reason string.

    >>> format_reason(ResultState.NOT_APPLICABLE, "no inventory row")
    'NOT_APPLICABLE: no inventory row'
    >>> format_reason(ResultState.NOT_APPLICABLE, "not declared", "documented_status_codes")
    'NOT_APPLICABLE: not declared [field=documented_status_codes]'
    >>> format_reason(ResultState.SKIPPED_NO_TOKEN, "blocked", provider="auth-api")
    'SKIPPED_NO_TOKEN: blocked [provider=auth-api]'

    ``field`` names the metadata that was missing. A consumer showing a
    NOT_APPLICABLE result needs to tell the user *what to fill in*; prose alone
    makes them guess.

    ``provider`` names the auth provider whose bootstrap failed, for the same
    reason: a blocked API is actionable only once you know *which* credential to
    go and fix. Both markers are stripped out of the human-readable detail by
    :func:`split_reason`, so they cost the prose nothing.
    """
    detail_text = str(detail).strip()
    field_text = str(field or "").strip()
    if field_text:
        detail_text = f"{detail_text} [field={field_text}]".strip()
    provider_text = str(provider or "").strip()
    if provider_text:
        detail_text = f"{detail_text} [provider={provider_text}]".strip()
    if not detail_text:
        return state.name
    return f"{state.name}{REASON_SEPARATOR}{detail_text}"


def extract_field(reason: str | None) -> str:
    """Return the ``[field=...]`` marker from a reason string, or ``""``."""
    match = FIELD_MARKER.search(str(reason or ""))
    return match.group(1) if match else ""


def extract_provider(reason: str | None) -> str:
    """Return the ``[provider=...]`` marker from a reason string, or ``""``.

    Empty for a SKIPPED_NO_TOKEN that was not blocked by a named provider — a
    check that needed a bearer token when the session never bootstrapped one,
    say. The emitter renders that absence as ``blockedBy: null`` rather than
    inventing a provider that did not fail.
    """
    match = PROVIDER_MARKER.search(str(reason or ""))
    return match.group(1).strip() if match else ""


def extract_measurement(reason: str | None) -> tuple[float | None, float | None]:
    """Return ``(observed, threshold)`` from a WARN reason, or ``(None, None)``.

    A WARN is only actionable with both numbers, so the tier always writes them
    as ``observed=<n>ms threshold=<n>ms``.
    """
    text = str(reason or "")
    observed = MEASUREMENT_OBSERVED.search(text)
    threshold = MEASUREMENT_THRESHOLD.search(text)
    return (
        float(observed.group(1)) if observed else None,
        float(threshold.group(1)) if threshold else None,
    )


def classify(reason: str | None) -> ResultState | None:
    """Recover the state from a reason string, or ``None`` if it carries no state.

    Round-trips with :func:`format_reason` for every state and every detail.
    A reason that was not produced by :func:`format_reason` — an ordinary pytest
    skip message, say — classifies as ``None`` rather than being forced into a
    state it never claimed.
    """
    if not reason:
        return None

    head = str(reason).strip().split(REASON_SEPARATOR.strip(), 1)[0].strip()
    try:
        return ResultState[head]
    except KeyError:
        return None


def split_reason(reason: str | None) -> tuple[ResultState | None, str]:
    """Split a reason string into its state and its remaining detail text."""
    state = classify(reason)
    if state is None:
        return None, str(reason or "").strip()

    remainder = str(reason).strip()[len(state.name) :]
    detail = remainder.lstrip(REASON_SEPARATOR.strip()).strip()
    detail = FIELD_MARKER.sub("", detail)
    return state, PROVIDER_MARKER.sub("", detail).strip()


def counts_toward_pass_rate(state: ResultState) -> bool:
    """Return whether ``state`` belongs in the pass-rate denominator."""
    return state in PASS_RATE_DENOMINATOR_STATES


def classification_rules() -> dict[str, object]:
    """The full classification contract, as publishable data.

    Everything a consumer needs to classify a result correctly without reading
    any engine source. Published into the catalogue so the platform cannot
    re-derive it and get it wrong.

    The trap this closes: ``WARN`` and ``INFORMATIONAL`` are emitted through
    ``pytest.skip`` because that is the only built-in non-failing outcome that
    carries a machine-readable reason. A consumer that reads the pytest verdict
    will record both as "did not execute" — but both mean the check *ran*.
    **Classify on the reason prefix, never on the pytest verdict.**
    """
    return {
        "reasonSeparator": REASON_SEPARATOR,
        "reasonFormat": "<STATE>: <detail>",
        "classifyOn": "reasonPrefix",
        "classifyOnNote": (
            "Split the reason on the first ':' and match the prefix against "
            "states[].name. Never infer state from the pytest verdict: WARN and "
            "INFORMATIONAL are reported as skips but both mean the check ran."
        ),
        "states": [
            {
                "name": state.name,
                "definition": state.description,
                "reasonPrefix": state.name,
                "countsTowardPassRate": counts_toward_pass_rate(state),
                "executed": state in EXECUTED_STATES,
            }
            for state in ResultState
        ],
        "passRateDenominatorStates": sorted(
            s.name for s in PASS_RATE_DENOMINATOR_STATES
        ),
        "passRateExcludedStates": sorted(s.name for s in PASS_RATE_EXCLUDED_STATES),
        "passRateFormula": "PASS / (PASS + FAIL)",
        "passRateNote": (
            "Undefined when PASS + FAIL is zero — report 'not applicable', never "
            "100%. A batch of entirely NOT_ASSERTED APIs has no pass rate."
        ),
        "executedStates": sorted(s.name for s in EXECUTED_STATES),
    }

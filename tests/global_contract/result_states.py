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

from enum import Enum


__all__ = [
    "ResultState",
    "PASS_RATE_DENOMINATOR_STATES",
    "PASS_RATE_EXCLUDED_STATES",
    "REASON_SEPARATOR",
    "classify",
    "counts_toward_pass_rate",
    "format_reason",
    "split_reason",
]


REASON_SEPARATOR = ": "


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


def format_reason(state: ResultState, detail: str = "") -> str:
    """Render ``state`` and ``detail`` as a machine-readable reason string.

    >>> format_reason(ResultState.NOT_APPLICABLE, "no inventory row")
    'NOT_APPLICABLE: no inventory row'
    """
    detail_text = str(detail).strip()
    if not detail_text:
        return state.name
    return f"{state.name}{REASON_SEPARATOR}{detail_text}"


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
    return state, remainder.lstrip(REASON_SEPARATOR.strip()).strip()


def counts_toward_pass_rate(state: ResultState) -> bool:
    """Return whether ``state`` belongs in the pass-rate denominator."""
    return state in PASS_RATE_DENOMINATOR_STATES

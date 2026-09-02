"""The write reports back what it stored (second case on this endpoint)

A write that echoes different values than were submitted is schema-valid and wrong. Nothing in the global tier compares request against response.

Uses the endpoint's own declared request from the inventory, so it exercises
exactly what the contract tier exercises.

This endpoint carries two catalogue rows -- "create custom shift (fixed type)"
and "create new shift" -- so it needs a case scoped to each. caseRef is what
keeps them apart; without this file the second row reported as unasserted.

Emits: FAIL, NOT_ASSERTED, PASS.
"""

from _support import case_json, case_response, reached_handler  # noqa: F401

caseRef = "post|/api/v1/attendance/shift/master|attendance shift master|create new shift"


import json as _json


def _sent():
    from _support import row_for

    raw = row_for(caseRef).get("Request Body") or ""
    try:
        return _json.loads(raw)
    except Exception:
        return None


def _entity(body):
    if not isinstance(body, dict):
        return body
    for wrapper in ("data", "result", "payload"):
        inner = body.get(wrapper)
        if isinstance(inner, dict):
            return inner
    return body


def test_response_echoes_what_was_sent(case_response, case_json):
    """A write must report back the values it stored.

    Not a schema question -- a response that echoes a *different* name than the
    one submitted is schema-valid and wrong. This compares the string fields
    that were sent against the ones that came back.
    """
    reached_handler(case_response)
    import pytest

    if not (200 <= case_response.status_code < 300):
        pytest.skip(
            f"the write returned {case_response.status_code}, so there is no "
            "stored state to compare against what was sent"
        )

    sent = _sent()
    if not isinstance(sent, dict):
        pytest.skip("this endpoint declares no JSON request body to echo")

    entity = _entity(case_json)
    if not isinstance(entity, dict):
        pytest.skip("the response carried no entity to compare")

    mismatched = {
        key: {"sent": value, "returned": entity[key]}
        for key, value in sent.items()
        if isinstance(value, str)
        and key in entity
        and isinstance(entity[key], str)
        and entity[key] != value
        and "{{" not in value  # unresolved template, not a real value
    }
    assert not mismatched, (
        f"the response reported different values than were submitted: {mismatched}"
    )

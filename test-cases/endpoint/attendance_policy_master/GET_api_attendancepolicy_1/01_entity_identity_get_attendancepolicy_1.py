"""Returns the entity that was asked for

Fetching one record by id must return *that* record. A response for a different entity is schema-valid, so only comparing identifiers catches it.

Uses the endpoint's own declared request from the inventory, so it exercises
exactly what the contract tier exercises.

Emits: FAIL, NOT_ASSERTED, PASS.
"""

from _support import case_json, case_response, reached_handler  # noqa: F401

caseRef = "get|/api/attendancepolicy/1|attendance policy master|get policy by id"


IDENTIFIER = "1"

#: Keys an entity might carry its own identifier under. Checked in order.
ID_KEYS = ("id", "attendancepolicyId", "attendancepolicy_id", "code", "templateId", "policyId")


def _entity(body):
    """The record itself, whether the API wraps it in data/result or not."""
    if not isinstance(body, dict):
        return body
    for wrapper in ("data", "result", "payload"):
        inner = body.get(wrapper)
        if isinstance(inner, dict):
            return inner
        if isinstance(inner, list) and len(inner) == 1 and isinstance(inner[0], dict):
            return inner[0]
    return body


def test_returns_the_entity_that_was_asked_for(case_response, case_json):
    """Fetching id N must return entity N -- not the first row, not another one.

    The schema check cannot catch this: a response for the wrong entity is
    perfectly schema-valid. Only comparing the returned identifier against the
    requested one can.
    """
    reached_handler(case_response)
    if case_response.status_code == 404:
        import pytest

        pytest.skip(
            f"entity {IDENTIFIER} does not exist in this environment, so there "
            "is nothing to check the identity of"
        )

    entity = _entity(case_json)
    assert isinstance(entity, dict), "response carried no entity object"

    found = {k: entity[k] for k in ID_KEYS if k in entity}
    if not found:
        import pytest

        pytest.skip(
            f"the returned entity carries none of {ID_KEYS}, so its identity "
            "cannot be compared with the requested one"
        )
    assert any(str(v) == IDENTIFIER for v in found.values()), (
        f"asked for id {IDENTIFIER} but the response identifies as {found}"
    )

"""The collection returns a list of consistently shaped records

A schema marks most fields optional, so ragged records validate cleanly and still break consumers. Comparing records against each other catches it.

Uses the endpoint's own declared request from the inventory, so it exercises
exactly what the contract tier exercises.

Emits: FAIL, NOT_ASSERTED, PASS.
"""

from _support import case_json, case_response, reached_handler  # noqa: F401

caseRef = "get|/api/attendance/status-threshold/getall|attendance status threshold api|get all"


def _items(body):
    """The list this endpoint returns, wherever it is nested."""
    if isinstance(body, list):
        return body
    if not isinstance(body, dict):
        return None
    for value in body.values():
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for inner in value.values():
                if isinstance(inner, list):
                    return inner
    return None


def test_returns_a_list(case_response, case_json):
    reached_handler(case_response)
    items = _items(case_json)
    assert items is not None, (
        "a collection endpoint returned no list anywhere in its payload"
    )


def test_records_share_one_shape(case_response, case_json):
    """Every record in one collection must carry the same keys.

    A schema marks most fields optional, so a response where half the rows are
    missing a field validates cleanly and still breaks any consumer that reads
    it. Comparing the rows against each other is what catches that.
    """
    reached_handler(case_response)
    items = _items(case_json) or []
    records = [i for i in items if isinstance(i, dict)]
    if len(records) < 2:
        import pytest

        pytest.skip(f"{len(records)} record(s) returned; need 2 to compare shapes")

    reference = set(records[0])
    ragged = {
        index: sorted(reference.symmetric_difference(record))
        for index, record in enumerate(records)
        if set(record) != reference
    }
    assert not ragged, (
        f"{len(ragged)} of {len(records)} records differ in shape from the "
        f"first: {dict(list(ragged.items())[:2])}"
    )

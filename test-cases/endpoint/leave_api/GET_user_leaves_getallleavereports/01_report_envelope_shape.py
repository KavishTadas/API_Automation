"""The leave-report envelope carries status, message and a data.count block.

Migrated from `Leave_API.json`, TC01. The global tier validates the response
against the OpenAPI schema; these assertions cover the envelope contract the
collection spot-checked by hand, including that `count` really is integral --
a string "12" satisfies most schemas and breaks arithmetic downstream.

Emits PASS / FAIL. Skips if the request never reached the application.
"""

caseRef = (
    "get|/user/leaves/getallleavereports|leave api|"
    "tc01/tc03 - get all leave reports and validate structure"
)


def _data(body):
    return body.get("data") if isinstance(body, dict) else None


def test_envelope_carries_status_and_message(case_json):
    assert isinstance(case_json, dict), "response body was not a JSON object"
    for field in ("status", "message"):
        assert field in case_json, f"envelope omitted {field!r}"


def test_data_carries_count_and_leave_report(case_json):
    """The list is `leaveReport`, singular -- confirmed against the live response."""
    data = _data(case_json)
    assert isinstance(data, dict), f"data was {type(data).__name__}, expected an object"
    assert "count" in data, "data omitted 'count'"
    assert isinstance(data.get("leaveReport"), list), (
        "data.leaveReport was not a list"
    )


def test_count_fields_are_integers(case_json):
    """`bool` is excluded deliberately -- it is an int subclass in Python."""
    count = (_data(case_json) or {}).get("count")
    if count is None:
        import pytest

        pytest.skip("no count block returned to check")
    values = count if isinstance(count, dict) else {"count": count}
    bad = {
        k: v
        for k, v in values.items()
        if not isinstance(v, int) or isinstance(v, bool)
    }
    assert not bad, f"count fields were not integers: {bad}"

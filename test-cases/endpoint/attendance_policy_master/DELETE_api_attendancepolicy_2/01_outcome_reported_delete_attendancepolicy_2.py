"""The outcome is reported in the body, not only the status

The global tier asserts machine-readable *errors*. Nothing asserts that a successful state change tells the caller what happened.

Uses the endpoint's own declared request from the inventory, so it exercises
exactly what the contract tier exercises.

Emits: FAIL, NOT_ASSERTED, PASS.
"""

from _support import case_json, case_response, reached_handler  # noqa: F401

caseRef = "delete|/api/attendancepolicy/2|attendance policy master|delete policy by id"


def test_reports_the_outcome_in_the_body(case_response, case_json):
    """A caller must be able to tell what happened without reading the status.

    This tier's `error_response_is_machine_readable` covers the failure path.
    This covers the success path, which nothing else asserts: an operation that
    returns 200 and an empty body leaves a client unable to confirm anything.
    """
    reached_handler(case_response)
    assert isinstance(case_json, (dict, list)), (
        f"HTTP {case_response.status_code} carried no JSON body, so the outcome "
        "is not reported anywhere a client can read it"
    )
    if isinstance(case_json, dict):
        assert case_json, "the response body was an empty object"

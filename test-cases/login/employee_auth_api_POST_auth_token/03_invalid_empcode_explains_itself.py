"""A rejected empCode comes back with an explanation, not a bare status.

Migrated from `Employee_Auth_API.json`, TC02. The status code itself is already
asserted by `test_status_code_matches_spec`, and the error shape by
`test_response_matches_full_schema`; neither checks that the body actually tells
the caller anything. That is the endpoint-specific part, so it is what lives here.

Co-located with TC01 and TC03 on the same endpoint -- `caseRef` is what scopes
this file to the invalid-empCode row.

Emits PASS / FAIL. Skips if the request never reached the application.
"""

caseRef = "post|/auth/token|employee auth api|tc02 - invalid empcode returns 400"

MESSAGE_FIELDS = ("message", "error", "errorMessage", "detail", "errorCode")


def test_rejection_carries_a_message(case_json):
    assert isinstance(case_json, dict), "error body was not a JSON object"
    present = [f for f in MESSAGE_FIELDS if str(case_json.get(f) or "").strip()]
    assert present, (
        "error response carried none of "
        f"{MESSAGE_FIELDS}; a client cannot tell the user what went wrong"
    )


def test_rejection_does_not_leak_a_token(case_json):
    """A failed login must not hand back a credential."""
    assert not (isinstance(case_json, dict) and case_json.get("token")), (
        "a rejected login returned a token"
    )

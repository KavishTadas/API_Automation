"""A missing password is rejected with a validation message, and no token.

Migrated from `Employee_Auth_API.json`, TC03. Same reasoning as the TC02 case:
the status and the error schema are already covered globally, so only the
endpoint-specific behaviour is asserted here.

Emits PASS / FAIL. Skips if the request never reached the application.
"""

caseRef = "post|/auth/token|employee auth api|tc03 - missing password returns 400"

MESSAGE_FIELDS = ("message", "error", "errorMessage", "detail", "errorCode")


def test_missing_password_carries_a_validation_message(case_json):
    assert isinstance(case_json, dict), "error body was not a JSON object"
    present = [f for f in MESSAGE_FIELDS if str(case_json.get(f) or "").strip()]
    assert present, (
        f"validation failure carried none of {MESSAGE_FIELDS}"
    )


def test_missing_password_does_not_leak_a_token(case_json):
    assert not (isinstance(case_json, dict) and case_json.get("token")), (
        "a request with no password returned a token"
    )

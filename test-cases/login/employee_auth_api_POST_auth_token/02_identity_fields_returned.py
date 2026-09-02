"""empCode and username are returned, and roles is a non-empty array.

Migrated from `Employee_Auth_API.json`, TC01. Endpoint-specific: the schema
declares these fields, but "roles must not be empty" is a business rule about
what an authenticated identity means here, not a shape the schema can express.

Emits PASS / FAIL. Skips if the request never reached the application.
"""

caseRef = "post|/auth/token|employee auth api|tc01 - valid credentials return jwt token"


def test_empcode_and_username_returned(case_json):
    assert isinstance(case_json, dict), "response body was not a JSON object"
    for field in ("empCode", "username"):
        assert case_json.get(field), f"response omitted {field!r} or returned it empty"


def test_roles_is_a_non_empty_array(case_json):
    roles = case_json.get("roles") if isinstance(case_json, dict) else None
    assert isinstance(roles, list), f"roles was {type(roles).__name__}, expected a list"
    assert roles, "roles was an empty array; an authenticated user must carry a role"

"""Token is a three-part JWT.

Migrated from `Employee_Auth_API.json`, TC01. Endpoint-specific: the global tier
asserts the response matches the OpenAPI `LoginResponse` schema, which says
`token` is a string -- it cannot say that string is a JWT.

Emits PASS / FAIL. Skips if the request never reached the application.
"""

caseRef = "post|/auth/token|employee auth api|tc01 - valid credentials return jwt token"


def test_token_is_three_part_jwt(case_json):
    token = case_json.get("token") if isinstance(case_json, dict) else None
    assert token, "response carried no token"
    parts = str(token).split(".")
    assert len(parts) == 3, (
        f"token has {len(parts)} dot-separated part(s); a JWT has 3 "
        "(header.payload.signature)"
    )
    assert all(parts), "token has an empty JWT segment"

"""The UAT login issues a usable token.

Migrated from `Login_Auth_UAT_API.json`, TC01. This issuer is the one the
Attendance endpoints depend on -- the console's own hint says a token minted by
Employee Auth is rejected there with `INVALID_TOKEN` -- so "did this actually
return something usable" is worth asserting on its own, separately from the
Employee Auth issuer.

Emits PASS / FAIL. Skips if the request never reached the application.
"""

caseRef = "post|/auth/token|login auth uat api|tc01 - valid credentials return token"


def test_returns_a_three_part_token(case_json):
    token = case_json.get("token") if isinstance(case_json, dict) else None
    assert token, "UAT login returned no token"
    parts = str(token).split(".")
    assert len(parts) == 3 and all(parts), (
        f"token has {len(parts)} non-empty part(s); a JWT has 3"
    )


def test_token_is_not_a_placeholder(case_json):
    """Guards the failure mode where a template survives into the response."""
    token = str((case_json or {}).get("token") or "")
    assert "{{" not in token and "<" not in token, (
        f"token looks like an unresolved placeholder: {token[:40]!r}"
    )

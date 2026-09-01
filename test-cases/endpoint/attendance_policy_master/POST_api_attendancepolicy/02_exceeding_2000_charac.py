"""Exceeding 2000-charac

Imported from the attendance repo's `Exceeding 2000-charac` probe (Attendance Policy), payload verbatim.

The payload is invalid on its own, so it needs no set-up to mean something: send
it, and the endpoint owes a refusal. Two assertions because they are different
defects -- accepting it means invalid data was stored, a 5xx means the input
reached something that could not cope.

## Side effect

This is a **POST**. A failure means the API accepted the payload, so a record was written on UAT. That is unavoidable: observing that invalid input is stored requires it to be stored.

Emits: FAIL, NOT_ASSERTED, PASS.
"""

import json

from _support import probe_response, reached_handler

caseRef = "post|/api/attendancepolicy|attendance policy master|create new policy"

PROBE_BODY = json.dumps({'policyName': 'Buffer Limit Verification Alpha', 'policyHeading': 'Length Validation Policy', 'policyDescription': 'This policy description is intentionally constructed to exceed the strict two thousand character limit enforced by the enterprise user interface. When designing robust and secure enterprise REST APIs, server-side data validation must never rely solely on client-side frontend constraints. An API client, automated integration script, or malicious actor can easily bypass frontend form limits and send payloads of arbitrary length directly to the backend endpoint. If the backend fails to validate the string length before executing the database persistence transaction, it can lead to unhandled database exceptions, SQL data truncation errors, or application crash. This paragraph is repeated multiple times to cross the two thousand character boundary cleanly. This policy description is intentionally constructed to exceed the strict two thousand character limit enforced by the enterprise user interface. When designing robust and secure enterprise REST APIs, server-side data validation must never rely solely on client-side frontend constraints. An API client, automated integration script, or malicious actor can easily bypass frontend form limits and send payloads of arbitrary length directly to the backend endpoint. If the backend fails to validate the string length before executing the database persistence transaction, it can lead to unhandled database exceptions, SQL data truncation errors, or application crash. This paragraph is repeated multiple times to cross the two thousand character boundary cleanly. This policy description is intentionally constructed to exceed the strict two thousand character limit enforced by the enterprise user interface. When designing robust and secure enterprise REST APIs, server-side data validation must never rely solely on client-side frontend constraints. An API client, automated integration script, or malicious actor can easily bypass frontend form limits and send payloads of arbitrary length directly to the backend endpoint. If the backend fails to validate the string length before executing the database persistence transaction, it can lead to unhandled database exceptions, SQL data truncation errors, or application crash.'})


def test_exceeding_2000_charac_is_refused():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert not (200 <= response.status_code < 300), (
        f"the endpoint accepted this payload with HTTP {response.status_code}; "
        "invalid input was stored"
    )


def test_exceeding_2000_charac_does_not_crash_the_server():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert response.status_code < 500, (
        f"the endpoint returned {response.status_code}; invalid input is "
        "caller error, not a server failure"
    )

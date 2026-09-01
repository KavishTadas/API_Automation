"""Fuzzing Defecr _Policy name

Imported from the attendance repo's `Fuzzing Defecr _Policy name` probe (Late-Early POLICY), payload verbatim.

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

caseRef = "post|/api/attendance/late-early-policies/create|latearly-policy|create"

PROBE_BODY = json.dumps({'policyCode': None, 'policyName': '""""""', 'description': 'Testing quotes-only policy name fuzzing acceptance', 'templateMode': 'CUSTOM', 'eventCountMinutes': 30, 'graceMinutes': 10, 'graceEvent': 2, 'allowedEvent': 3, 'deductionType': 'LEAVE', 'leaveDeductDays': 0.5, 'leaveTypeId': 1, 'effectiveFrom': '2027-01-01', 'effectiveTo': '2027-12-31', 'isDefault': 'N', 'isActive': 'Y', 'assignments': [{'employeeId': 3503, 'effectiveFrom': '2027-01-01', 'effectiveTo': '2027-12-31', 'isActive': 'Y'}]})


def test_fuzzing_defecr_policy_name_is_refused():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert not (200 <= response.status_code < 300), (
        f"the endpoint accepted this payload with HTTP {response.status_code}; "
        "invalid input was stored"
    )


def test_fuzzing_defecr_policy_name_does_not_crash_the_server():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert response.status_code < 500, (
        f"the endpoint returned {response.status_code}; invalid input is "
        "caller error, not a server failure"
    )

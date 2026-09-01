"""BOLA - ID mistmatch mutation

Imported from the attendance repo's `BOLA - ID mistmatch mutation` probe (Threshold Templates), payload verbatim.

The payload is invalid on its own, so it needs no set-up to mean something: send
it, and the endpoint owes a refusal. Two assertions because they are different
defects -- accepting it means invalid data was stored, a 5xx means the input
reached something that could not cope.

## Side effect

This is a **PUT**. A failure means the API accepted the payload, so a record was written on UAT. That is unavoidable: observing that invalid input is stored requires it to be stored.

Emits: FAIL, NOT_ASSERTED, PASS.
"""

import json

from _support import probe_response, reached_handler

caseRef = "put|/api/attendance/status-threshold/update/1|attendance status threshold api|update threshold"

PROBE_BODY = json.dumps({'thresholdId': 9999, 'thresholdCode': 'TH00079', 'thresholdName': 'BOLA ID Mismatch Test', 'description': 'Testing path parameter thresholdId 80 vs body thresholdId 9999 mismatch', 'templateMode': 'CUSTOM', 'shiftTypeApplicability': 'Fixed', 'absentMaxHours': 3.0, 'halfDayMinHours': 3.01, 'fullDayMinHours': 6.0, 'presentMinHours': 8.0, 'effectiveFrom': '2027-01-01', 'effectiveTo': '2027-12-31', 'isDefault': 'N', 'isActive': 'Y', 'templateStatus': 'DRAFT', 'remarks': 'BOLA security mutation test', 'assignments': [{'employeeId': 34, 'effectiveFrom': '2027-01-01', 'effectiveTo': '2027-12-31', 'isActive': 'Y'}]})


def test_bola_id_mistmatch_mutation_is_refused():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert not (200 <= response.status_code < 300), (
        f"the endpoint accepted this payload with HTTP {response.status_code}; "
        "invalid input was stored"
    )


def test_bola_id_mistmatch_mutation_does_not_crash_the_server():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert response.status_code < 500, (
        f"the endpoint returned {response.status_code}; invalid input is "
        "caller error, not a server failure"
    )

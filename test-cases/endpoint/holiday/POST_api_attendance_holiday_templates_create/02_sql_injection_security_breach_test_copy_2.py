"""SQL_Injection_Security Breach test  copy_2

Imported from the attendance repo's `SQL_Injection_Security Breach test  copy_2` probe (Holiday Templates), payload verbatim.

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

caseRef = "post|/api/attendance/holiday-templates/create|holiday template apis copy|create"

PROBE_BODY = json.dumps({'templateCode': 'HTP_SEC_01', 'templateName': 'Security Audit Template 2031', 'description': "Test description <script>alert('SEC_VULN')</script> and ' OR '1'='1' --", 'effectiveFrom': '2031-01-01', 'effectiveTo': '2031-12-31', 'optionModel': 'ALLOWED', 'templateMode': 'CUSTOM', 'isDefault': 'N', 'isActive': 'Y', 'remarks': "<img src=x onerror=alert('REMARKS_XSS')> -- SQL Test", 'holidays': [{'holidayName': 'Audit Holiday', 'occasion': 'Festival & Celebration <svg onload=alert(1)>', 'holidayDate': '2031-01-26', 'optionModel': 'ALLOWED', 'isHalfDay': 'N', 'isOptional': 'N', 'remarks': 'Special \' quote & double " quote test'}], 'assignments': [{'employeeId': 34, 'effectiveFrom': '2031-01-01', 'effectiveTo': '2031-12-31', 'isActive': 'Y'}]})


def test_sql_injection_security_breach_test_copy_2_is_refused():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert not (200 <= response.status_code < 300), (
        f"the endpoint accepted this payload with HTTP {response.status_code}; "
        "invalid input was stored"
    )


def test_sql_injection_security_breach_test_copy_2_does_not_crash_the_server():
    response = probe_response(caseRef, PROBE_BODY)
    reached_handler(response)
    assert response.status_code < 500, (
        f"the endpoint returned {response.status_code}; invalid input is "
        "caller error, not a server failure"
    )

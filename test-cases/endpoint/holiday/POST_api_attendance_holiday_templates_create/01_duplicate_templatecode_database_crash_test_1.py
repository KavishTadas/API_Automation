"""Duplicate templateCode Database Crash Test (1)

Imported from the attendance repo's `Duplicate templateCode Database Crash Test (1)` probe (Holiday Templates), payload verbatim.

## This case cannot be judged on its own, and says so

The defect it probes only exists relative to a record that is already there --
a name already taken, a default already set, a range already occupied, a leave
type already deactivated. Fired once against an environment that does not have
that record, a `2xx` is a **correct first write**, not the defect.

Their suite established the precondition with a create step immediately before.
Reproducing that needs set-up and teardown this tier does not have yet, so this
reports NOT_ASSERTED rather than a result that looks like a verdict. The payload
is kept so the case is ready the moment the fixture exists.

Emits: NOT_ASSERTED.
"""

import json

import pytest

caseRef = "post|/api/attendance/holiday-templates/create|holiday template apis copy|create"

PROBE_BODY = json.dumps({'templateCode': 'HTP00096', 'templateName': 'Duplicate Code Crash Test', 'effectiveFrom': '2026-01-01', 'effectiveTo': '2026-12-31', 'optionModel': 'ALLOWED', 'templateMode': 'CUSTOM', 'isDefault': 'N', 'isActive': 'Y', 'holidays': [{'holidayName': 'New Year', 'occasion': 'National Holiday', 'holidayDate': '2026-01-01', 'optionModel': 'ALLOWED', 'isHalfDay': 'N', 'isOptional': 'N', 'remarks': 'New Year'}], 'assignments': [{'employeeId': 34, 'effectiveFrom': '2026-01-01', 'effectiveTo': '2026-12-31', 'isActive': 'Y'}]})

#: What must already exist for the probe to mean anything.
REQUIRES = "a record this payload would collide with"


def test_duplicate_templatecode_database_crash_test_1():
    pytest.skip(
        f"NOT_ASSERTED: this probe needs {REQUIRES} to exist first; sending it "
        "standalone cannot distinguish the defect from a correct first write"
    )

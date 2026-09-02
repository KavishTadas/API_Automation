"""Deactivated Leave Type Foreign Key Status Gating Test

Imported from the attendance repo's `Deactivated Leave Type Foreign Key Status Gating Test` probe (Late-Early POLICY), payload verbatim.

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

caseRef = "post|/api/attendance/late-early-policies/create|latearly-policy|create"

PROBE_BODY = json.dumps({'policyCode': None, 'policyName': 'Deactivated Leave Gating Test 2038', 'description': 'Testing foreign active-state gating on leaveTypeId: 7 (OD)', 'templateMode': 'CUSTOM', 'eventCountMinutes': 30, 'graceMinutes': 10, 'graceEvent': 2, 'allowedEvent': 3, 'deductionType': 'LEAVE', 'leaveDeductDays': 0.5, 'leaveTypeId': 7, 'fineAmount': None, 'effectiveFrom': '2038-01-01', 'effectiveTo': '2038-12-31', 'isDefault': 'N', 'isActive': 'Y', 'assignments': [{'employeeId': 4223, 'effectiveFrom': '2038-01-01', 'effectiveTo': '2038-12-31', 'isActive': 'Y'}]})

#: What must already exist for the probe to mean anything.
REQUIRES = "a record this payload would collide with"


def test_deactivated_leave_type_foreign_key_status_gating_t():
    pytest.skip(
        f"NOT_ASSERTED: this probe needs {REQUIRES} to exist first; sending it "
        "standalone cannot distinguish the defect from a correct first write"
    )

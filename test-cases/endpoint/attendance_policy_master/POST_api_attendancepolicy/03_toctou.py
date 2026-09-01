"""TOCTOU

Imported from the attendance repo's `TOCTOU` probe (Attendance Shift Master), payload verbatim.

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

caseRef = "post|/api/attendancepolicy|attendance policy master|create new policy"

PROBE_BODY = json.dumps({'policyName': 'ConcurrentRacePolicyMXIACC', 'policyHeading': 'Concurrency Race Test', 'policyDescription': 'Testing simultaneous creation race condition'})

#: What must already exist for the probe to mean anything.
REQUIRES = "a record this payload would collide with"


def test_toctou():
    pytest.skip(
        f"NOT_ASSERTED: this probe needs {REQUIRES} to exist first; sending it "
        "standalone cannot distinguish the defect from a correct first write"
    )

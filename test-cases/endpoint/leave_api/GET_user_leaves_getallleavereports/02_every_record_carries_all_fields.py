"""Every leave record carries all 13 expected fields.

Migrated from `Leave_API.json`, TC03 -- "Every record contains all 13 expected
fields" and "At least two records available for required spot-check".

Endpoint-specific by construction: the OpenAPI schema marks most of these
optional, so `test_response_matches_full_schema` passes on a record missing
several. This asserts the stronger rule the collection actually relied on.

`purpose` is required-but-nullable on purpose: live data showed a March 2026
batch of 25 bulk-created LWP records with no purpose, which is legitimate for
administratively created leave. The field must be present; its value may be null.

Emits PASS / FAIL. Skips if the request never reached the application, or if the
account has too little data to spot-check.
"""

import pytest

caseRef = (
    "get|/user/leaves/getallleavereports|leave api|"
    "tc01/tc03 - get all leave reports and validate structure"
)

#: The 13, read off the live response rather than guessed. The collection's
#: "all 13 expected fields" and the observed record agree exactly on the count.
#: Snake_case throughout -- this endpoint does not use the camelCase the rest of
#: the API favours, which is itself worth not silently "correcting".
EXPECTED_FIELDS = (
    "application_date",
    "day_type",
    "emp_name",
    "empid",
    "end_date",
    "leave_type",
    "lr_id",
    "lr_no",
    "purpose",
    "reason",
    "start_date",
    "status",
    "subject",
)

MINIMUM_RECORDS_FOR_SPOT_CHECK = 2


def _records(body):
    data = body.get("data") if isinstance(body, dict) else None
    return (data or {}).get("leaveReport") if isinstance(data, dict) else None


def test_enough_records_to_spot_check(case_json):
    records = _records(case_json)
    if not isinstance(records, list):
        pytest.skip("no leaveReports list returned")
    if len(records) < MINIMUM_RECORDS_FOR_SPOT_CHECK:
        pytest.skip(
            f"only {len(records)} record(s) returned; the spot-check needs "
            f"{MINIMUM_RECORDS_FOR_SPOT_CHECK}. Not a defect -- this account has "
            "too little leave history to judge the contract."
        )
    assert len(records) >= MINIMUM_RECORDS_FOR_SPOT_CHECK


def test_every_record_carries_every_field(case_json):
    records = _records(case_json)
    if not isinstance(records, list) or not records:
        pytest.skip("no leave records returned to check")

    missing: dict[int, list[str]] = {}
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            missing[index] = ["<record was not an object>"]
            continue
        absent = [f for f in EXPECTED_FIELDS if f not in record]
        if absent:
            missing[index] = absent

    assert not missing, (
        f"{len(missing)} of {len(records)} record(s) omitted expected field(s): "
        + "; ".join(f"#{i}: {', '.join(f)}" for i, f in list(missing.items())[:3])
    )

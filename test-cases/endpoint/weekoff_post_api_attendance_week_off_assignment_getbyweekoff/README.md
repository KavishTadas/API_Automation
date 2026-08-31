# weekoff_post_api_attendance_week_off_assignment_getbyweekoff

`POST /api/attendance/week-off-assignment/getByWeekOff`

Endpoint-specific test cases go in this directory: **one Python file per case**,
named `<NN>_<case_title>.py`. Written by hand, never by a tool.

## What covers this endpoint today

- **week-off-assignment/getByWeekOffId** — `not-asserted` — currently lives in `collections/Weekoff_Policy_API.json`

Generated contract coverage: `tests/auto_generated/` (disposable — regenerated, never edited).

## Adding a case

Number it after the highest existing file. State in the docstring what it
asserts and which result state it emits on failure. The 22 global checks already
run against this endpoint on every run -- do not restate them here; add a case
only for behaviour specific to this endpoint.

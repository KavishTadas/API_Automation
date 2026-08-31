# leave_api_get_user_leaves_getallleavereports

`GET /user/leaves/getAllLeaveReports`

Endpoint-specific test cases go in this directory: **one Python file per case**,
named `<NN>_<case_title>.py`. Written by hand, never by a tool.

## What covers this endpoint today

- **TC01/TC03 - Get all leave reports and validate structure** — `asserted` — currently lives in `collections/Leave_API.json`
- **TC02 - Invalid token returns observed authorization status** — `asserted` — currently lives in `collections/Leave_API.json`

Generated contract coverage: `tests/auto_generated/` (disposable — regenerated, never edited).

## Adding a case

Number it after the highest existing file. State in the docstring what it
asserts and which result state it emits on failure. The 22 global checks already
run against this endpoint on every run -- do not restate them here; add a case
only for behaviour specific to this endpoint.

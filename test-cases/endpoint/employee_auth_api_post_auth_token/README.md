# employee_auth_api_post_auth_token

`POST /auth/token`

Endpoint-specific test cases go in this directory: **one Python file per case**,
named `<NN>_<case_title>.py`. Written by hand, never by a tool.

## What covers this endpoint today

- **TC01 - Valid credentials return JWT token** — `asserted` — currently lives in `collections/auth/Employee_Auth_API.json`
- **TC02 - Invalid empCode returns 400** — `asserted` — currently lives in `collections/auth/Employee_Auth_API.json`
- **TC03 - Missing password returns 400** — `asserted` — currently lives in `collections/auth/Employee_Auth_API.json`

Generated contract coverage: `tests/auto_generated/` (disposable — regenerated, never edited).

## Adding a case

Number it after the highest existing file. State in the docstring what it
asserts and which result state it emits on failure. The 22 global checks already
run against this endpoint on every run -- do not restate them here; add a case
only for behaviour specific to this endpoint.

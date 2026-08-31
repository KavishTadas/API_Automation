# POST /auth/token

Suite: `employee_auth_api` · endpoint slug: `employee_auth_api_post_auth_token`

Endpoint-specific test cases go here: **one Python file per case**, named
`<NN>_<case_title>.py`. Hand-authored, never written by a tool.

## Scoping a case to one ref with `caseRef`

This endpoint carries **3** case(s), so a file here must say which one it
tests. Declare it at module level:

```python
caseRef = "post|/auth/token|employee auth api|tc01 - valid credentials return jwt token"
```

`caseRef` must be one of the `canonicalRef` values below, byte-identical. Omit it
only where the endpoint has a single case and the file applies to all of it.
Co-located files with different `caseRef` values are independent: each is scoped to
its own ref and runs only when that ref is in the manifest.

## Cases on this endpoint

- **TC01 - Valid credentials return JWT token**
  - `caseRef`: `post|/auth/token|employee auth api|tc01 - valid credentials return jwt token`
  - assertion state: `asserted` — currently in `collections/auth/Employee_Auth_API.json`
- **TC02 - Invalid empCode returns 400**
  - `caseRef`: `post|/auth/token|employee auth api|tc02 - invalid empcode returns 400`
  - assertion state: `asserted` — currently in `collections/auth/Employee_Auth_API.json`
- **TC03 - Missing password returns 400**
  - `caseRef`: `post|/auth/token|employee auth api|tc03 - missing password returns 400`
  - assertion state: `asserted` — currently in `collections/auth/Employee_Auth_API.json`

## Adding a case

Number it after the highest existing file. State in the docstring what it asserts and
which result state it emits on failure. The 22 global checks already run against this
endpoint on every run -- add a case here only for behaviour specific to this endpoint.

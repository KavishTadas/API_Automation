# attendance_policy_master_patch_api_attendancepolicy_4_status

`PATCH /api/attendancepolicy/4/status`

Endpoint-specific test cases go here: **one Python file per case**, named
`<NN>_<case_title>.py`. Hand-authored, never written by a tool.

## Scoping a case to one ref with `caseRef`

This endpoint carries **1** case(s), so a file here must say which one it
tests. Declare it at module level:

```python
caseRef = "patch|/api/attendancepolicy/4/status|attendance policy master|activate deactivate"
```

`caseRef` must be one of the `canonicalRef` values below, byte-identical. Omit it
only where the endpoint has a single case and the file applies to all of it.
Co-located files with different `caseRef` values are independent: each is scoped to
its own ref and runs only when that ref is in the manifest.

## Cases on this endpoint

- **Activate Deactivate**
  - `caseRef`: `patch|/api/attendancepolicy/4/status|attendance policy master|activate deactivate`
  - assertion state: `not-asserted` — currently in `collections/Attendance_Management_API.json`

## Adding a case

Number it after the highest existing file. State in the docstring what it asserts and
which result state it emits on failure. The 22 global checks already run against this
endpoint on every run -- add a case here only for behaviour specific to this endpoint.

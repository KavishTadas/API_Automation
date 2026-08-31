# POST /api/attendance/holiday-templates/create

Suite: `holiday_template` · endpoint slug: `holiday_template_post_api_attendance_holiday_templates_create`

Endpoint-specific test cases go here: **one Python file per case**, named
`<NN>_<case_title>.py`. Hand-authored, never written by a tool.

## Scoping a case to one ref with `caseRef`

This endpoint carries **1** case(s), so a file here must say which one it
tests. Declare it at module level:

```python
caseRef = "post|/api/attendance/holiday-templates/create|holiday template apis copy|create"
```

`caseRef` must be one of the `canonicalRef` values below, byte-identical. Omit it
only where the endpoint has a single case and the file applies to all of it.
Co-located files with different `caseRef` values are independent: each is scoped to
its own ref and runs only when that ref is in the manifest.

## Cases on this endpoint

- **Create**
  - `caseRef`: `post|/api/attendance/holiday-templates/create|holiday template apis copy|create`
  - assertion state: `not-asserted` — currently in `collections/Holiday_Template_API.json`

## Adding a case

Number it after the highest existing file. State in the docstring what it asserts and
which result state it emits on failure. The 22 global checks already run against this
endpoint on every run -- add a case here only for behaviour specific to this endpoint.

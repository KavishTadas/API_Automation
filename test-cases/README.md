# test-cases/ — the authored test tier

Every file here is hand-authored. Nothing writes into this tree except the case-stub
generator, and that only creates directories and their `README.md`.

```
test-cases/
  global/                        the fixed 22 checks, one file each   (Phase 4)
  endpoint/<suite>/<endpoint>/   per-endpoint cases, by suite
  login/<endpoint>/              authentication, flat, no suite level
```

## Two roots, two depths

`endpoint/` is nested one level deeper than `login/`. Anything that enumerates cases
must read **both**, or authored login cases become invisible to it. The generator does
this in `case_files()`; there is a unit test pinning it.

## Suite

The suite directory is the **aliased** module from `api-endpoints/module-aliases.yaml`,
never the raw Postman `info.name`. Four collections carry an internal name that
disagrees with their filename — one misspelled and date-stamped
(`Attenedance-july2026` → `weekoff`), one carrying a Postman "Copy" suffix
(`Holiday Template APIs Copy` → `holiday_template`). Those must not become directory
names anyone navigates by.

| Suite | Endpoints |
|---|---:|
| `attendance_policy_master` | 6 |
| `attendance_shift_master` | 6 |
| `attendance_threshold` | 6 |
| `holiday_template` | 6 |
| `weekoff` | 7 |
| `late_early` | 5 |
| `leave_api` | 1 |
| `auth` | 1 |
| `users` | 1 |

## Endpoint directory

`<METHOD>_<path-slug>` — uppercase method, then the path with `/` → `_` and
`{holidayTemplateId}` → `by_holidaytemplateid`. For example:

```
test-cases/endpoint/holiday_template/DELETE_api_attendance_holiday_templates_delete_by_holidaytemplateid/
```

## Why login/ carries a module prefix

`POST /auth/token` is issued by **three** modules. Two of them — `employee auth api`
and `login auth uat api` — live under `login/`, which is flat. Without a prefix both
would resolve to `POST_auth_token` and one endpoint's cases would silently land under
the other, so the module prefix is restored there:

```
test-cases/login/employee_auth_api_POST_auth_token/     3 refs (tc01, tc02, tc03)
test-cases/login/login_auth_uat_api_POST_auth_token/    1 ref
```

The third, module `auth`, is not a login module and stays at
`test-cases/endpoint/auth/POST_auth_token/`.

Collision resolution is automatic and re-checked: if a prefix still cannot separate
two endpoints, generation **fails** rather than overwriting.

## Slugs are frozen; directories are published

`api-docs/ref-to-slug.json` holds two maps:

- `refToSlug` — **frozen**. Never re-derived, never recomputed by a consumer.
- `slugToDirectory` — where that endpoint's cases live.

The tree can be reshaped again without touching a single slug value. Do not derive one
from the other.

## Scoping a case with `caseRef`

An endpoint directory can hold cases for several refs. A case file says which one it
tests by declaring, at module level:

```python
caseRef = "post|/auth/token|employee auth api|tc02 - invalid empcode returns 400"
```

It must be byte-identical to a `canonicalRef` in the endpoint's YAML —
`python scripts/generate-endpoint-yaml.py` **exits 3** otherwise. Omit it only where
the endpoint has a single case. Co-located files with different `caseRef` values are
independent: each runs only when its ref is in the manifest.

## Adding a case

One Python file per case, `<NN>_<case_title>.py`, numbered after the highest existing
file in that directory. State in the docstring what it asserts and which result state
it emits on failure.

The 22 global checks already run against every endpoint on every run. Add a case here
only for behaviour specific to *this* endpoint.

**The seven-state model is load-bearing.** A request that ran but asserted nothing must
report `NOT_ASSERTED`, never `PASS`.

## Path length

Full paths are checked from the repo root against a 200-character ceiling, budgeting 48
characters for the case filename. The longest today is 192. Generation hard-fails past
the ceiling; the fix is a shorter module alias, never a truncated endpoint name.

## The honest gap

Endpoint-specific **business-rule** tests still live in the Postman collections under
`collections/`, not here. Migrating them is Phase 5, which is out of scope for this
window — it depends on redesigning token-chaining and would break the harness
auth-provider filter in the same change. Each endpoint README names where its Newman
coverage currently lives.

# PHASE2_REPORT — authoring surface materialised

**Branch:** `refactor/authoring-surface` · **Verification:** re-ran the full
45-endpoint suite. **Zero delta** across all seven states, `total`, `passRate`,
`unreachableResults` and `clean`. Nothing in the suite reads the new tree yet.

## What was built

| Path | Contents |
|---|---|
| `api-endpoints/*.yaml` | **41** endpoint definitions |
| `api-endpoints/module-aliases.yaml` | 4 alias entries, committed |
| `api-endpoints/README.md` | what belongs here, what must never write here |
| `test-cases/endpoint/<slug>/README.md` | **41** stub dirs naming current coverage |
| `test-cases/README.md` | the global/endpoint split, and the honest Phase 5 gap |
| `api-docs/ref-to-slug.json` | all 45 refs to slug, auditable and diffable |
| `tests/global_contract/endpoint_slug.py` | the single slug implementation |
| `tests/unit/test_endpoint_slug.py` | 10 unit tests, incl. both hard-fail guards |
| `scripts/generate-endpoint-yaml.py` | the Phase 2 generator, `--check` for CI |

## Two decisions forced by the data

### 41 endpoints, not 45

The slug formula in section 4 keys on `module + method + path` — it drops the ref's
**fourth** component. That component is the test case, and four rows collide without
it:

| Cases | Endpoint |
|---:|---|
| 3 | `POST /auth/token` (employee auth api) — tc01 / tc02 / tc03 |
| 2 | `GET /user/leaves/getallleavereports` |
| 2 | `POST /api/v1/attendance/shift/master` |

Approved resolution: key on `module + method + path`, giving 41 collision-free
endpoints, with the surplus rows becoming `testCases[]` entries on their endpoint.
This is the endpoint/case split the requested tree already implies.

**Knock-on, recorded not fixed:** "45 endpoints" in `TECH_STACK.txt` and elsewhere is
the row count, not the endpoint count. 45 rows, 41 endpoints, 39 distinct
`method + path`.

### 85-character ceiling, not 60

The 60-char limit is unsatisfiable. The four aliases save 10-11 characters each, but
the path dominates: `api_attendance_holiday_templates_delete_by_holidaytemplateid` is
59 characters on its own.

| Variant | Max | Over 60 |
|---|---:|---:|
| Rule as written | 84 | 14 |
| Strip leading `/api/` | 80 | 8 |
| Strip `/api/attendance/` and `/api/v1/attendance/` | 69 | 2 |

Approved: **85, rule as written** — no path stripping, no information loss, and the
ceiling fails on something genuinely new rather than on the existing tree. The longest
real slug is 84.

## Slug rule, as implemented

`module + "__" + method + "_" + path`, lowercased, `/` to `_`, `{param}` to
`by_param`, non-`[a-z0-9_]` to `_`, runs collapsed, edges stripped.

**The `__` module separator does not survive.** Section 4 mandates both the `__`
separator *and* collapsing runs of `_`, and collapse wins — which is what produced the
84-char figures reviewed and approved. Preserving `__` would add a character to every
slug and push the longest to exactly 85. The module boundary stays recoverable from
`api-docs/ref-to-slug.json`, which exists so nobody reconstructs it by eye.

## Alias map — 4 entries, all justified by a real defect

Every aliased module name comes from a Postman collection's internal `info.name`,
which disagrees with its own filename. Renaming inside the collections would fix today
and regress on the next export.

| `info.name` | Alias | Defect |
|---|---|---|
| `Holiday Template APIs Copy` | `holiday-template` | Postman "Copy" artifact |
| `Attenedance-july2026` | `weekoff` | misspelled **and** date-stamped |
| `Latearly-Policy` | `late-early` | lost word boundary |
| `Attendance Status Threshold API` | `attendance-threshold` | redundant suffix |

**`Attenedance-july2026` verified before aliasing**, as instructed: all 7 requests in
`Weekoff_Policy_API.json` are `/api/attendance/week-offs/*` or
`/api/attendance/week-off-assignment/*`. The filename is accurate; the internal name is
simply wrong. There is **no non-"Copy" Holiday Template collection** — only one file
exists, and the "Copy" lives inside its JSON.

## canonicalRef integrity

Verified programmatically: the 45 `canonicalRef` values across the tree are
**byte-identical** to catalogue output, with no additions and no omissions. The
`attenedance` misspelling is preserved in all 7 of its refs while their slugs read
`weekoff_*`. Aliases affect slug derivation only.

## OPEN — ref reminting (recorded, not actioned)

Whether to remint refs to correct `attenedance-july2026` and drop the Postman "Copy"
suffix is **contract-visible**: the harness, run manifest and result document all key
on the ref string. Recorded as an open decision per instruction. Not actioned.

## Field decisions worth knowing

- `metadata` carries only **declared** OpenAPI `x-` extensions. Resolver defaults
  (`DEFAULT_SLA_MS = 700`, `DEFAULT_MAX_PAYLOAD_BYTES = 1 MiB`) are deliberately not
  baked in — writing a global fallback into 41 files would turn one default into 41
  declarations nobody chose, and a later change to the default would silently
  disagree with every file.
- `credentialAlias` is `null` throughout. The catalogue registers aliases globally
  (`ATTENDANCE_SVC_UAT_01`, `LEAVE_SVC_UAT_01`); the run manifest binds one at run
  time. No raw credential value appears anywhere in the tree.
- `version` is `null` — no source in the current tree carries an endpoint version.

## Verification

| | baseline | after Phase 2 | delta |
|---|---:|---:|---:|
| PASS | 408 | 408 | 0 |
| FAIL | 122 | 122 | 0 |
| WARN / SKIPPED_NO_TOKEN | 0 / 0 | 0 / 0 | 0 |
| NOT_APPLICABLE | 381 | 381 | 0 |
| NOT_ASSERTED | 36 | 36 | 0 |
| INFORMATIONAL | 6 | 6 | 0 |
| total / passRate / clean | 953 / 0.7698 / false | identical | — |

Plus `python -m pytest tests/unit -q` — 10 passed. Those live in `tests/unit/`, not
`tests/global_contract/`, precisely because the runner collects that whole directory
and unit tests there would have changed the counts above.

## Read-only finding: the five failing checks all predate the 495/53 measurement

| Check | Introduced | Date | vs `33ecada` (2026-08-31) |
|---|---|---|---|
| `test_no_server_version_disclosure` | `75bbf06` | 2026-08-27 | ancestor, predates the 25 |
| `test_error_response_is_machine_readable` | `75bbf06` | 2026-08-27 | ancestor, predates the 25 |
| `test_no_credential_leakage_in_response` | `7f54411` | 2026-08-05 | ancestor, predates the 25 |
| `test_idempotent_get_returns_stable_result` | `7f54411` | 2026-08-05 | ancestor, predates the 25 |
| `test_401_without_valid_token` | `f328a8d` | 2026-08-04 | ancestor, predates the 25 |
| `test_status_code_matches_spec` | `f328a8d` | 2026-08-04 | ancestor, predates the 25 |

**None postdates the commit quoting 495/53.** `75bbf06` — the commit that took the tier
from 12 to 22 checks — alone introduced the two checks responsible for 65 of the 122
failures, and it landed four days before that measurement. Check-set drift cannot
explain the gap between the observed 0.7698 and the quoted 0.903; the cause is
environmental or methodological. Reported only, not investigated.

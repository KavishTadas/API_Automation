# Manual scenario manifests

Inputs for the manual walkthrough. Every ref comes from the reminted
`method|path|module|sub-module` format and from the confirmed-runnable list in
[`../../runnable-apis.json`](../../runnable-apis.json), so none of these
scenarios is waiting on a host that cannot answer.

## Why the scenario header is here and not in each file

The engine **rejects unknown manifest fields** — deliberately, so a typo'd
`authProviderApiID` cannot produce a run that looks fine and quietly skipped its
auth. Top-level keys are limited to `runId`, `environment`, `requestedTiers` and
`apis`, and JSON has no comment syntax. A `$comment` key was tried against
`validate_manifest` and rejected, along with `_comment`, `//`, `comment` and
`description`.

So a header comment inside each `.json` would make every scenario invalid — it
would break the thing it documents. Instead:

- **`runId` carries the scenario id** (`"runId": "s04-batch-shared-provider"`).
  It validates, and it lands in the result document, so a run is identifiable
  from its output rather than only from the file it came from.
- **This table carries the expected outcome.**
- `s09-curl.txt` is a text file, so it has a real `#` header comment.

## Scenarios

Outcomes below were **observed**, not predicted — each manifest was run against
UAT on 2026-08-26, with `s01`, `s08`, `s09` and `s09b` re-run and confirmed on
2026-08-27. Counts drift with live endpoint behaviour; `status`, exit code and
`cleanBlockers` are the stable parts.

| File | Exercises | Observed outcome |
|---|---|---|
| `s01-leave-single.json` | Leave API, `leave-svc-uat-01`, provider Employee_Auth_API | exit 0, `COMPLETED`, 10 PASS / 0 FAIL / 3 N/A, passRate 1.0, **clean**, `cleanBlockers: []`. **The baseline** — what a run with nothing wrong looks like. Re-run 2026-08-27 after the provider correction; see *s01's original provider* below. |
| `s02-attendance-single.json` | Attendance API, `attendance-svc-uat-01`, provider Login_Auth_UAT_API | exit 0, `COMPLETED`, 7 PASS / 6 N/A, passRate 1.0, **clean** |
| `s03-attendance-wrong-provider.json` | As s02 but provider Employee_Auth_API | exit 0, `COMPLETED`, 6 PASS / 1 FAIL / 6 N/A. **The wrong provider still bootstraps successfully** — no `SKIPPED_NO_TOKEN`, empty `statusReason`. The token is minted and then rejected in use, surfacing as one FAIL (`test_response_matches_full_schema`: *did not inspect a success response*). A mis-pointed provider looks like a broken API, not a broken credential — which is the point of the scenario. |
| `s04-batch-shared-provider.json` | 3 APIs, one provider + alias | exit 0, `COMPLETED`, 18 PASS / 3 FAIL / 14 N/A. One bootstrap serves all three. |
| `s05-batch-mixed-providers.json` | Leave + Attendance, different providers | exit 0, `COMPLETED`, 17 PASS / 9 N/A, passRate 1.0, **clean**. Two bootstraps in one run. |
| `s06-unregistered-alias.json` | Any API, alias that is registered nowhere | exit **0**, `COMPLETED_WITH_ERRORS`, 9 `SKIPPED_NO_TOKEN` / 4 N/A, passRate `null`, `cleanBlockers: ["SKIPPED_NO_TOKEN"]`. **Exit 0 is correct** — the run happened; the APIs were blocked. Check `blockedBy` on the results for the provider that failed. |
| `s07-bad-environment.json` | Valid API, `"environment": "PROD"` | exit **2**, `ABORTED`, no tests run. Rejected at validation: *'PROD' is not registered; known environments are ['UAT']*. A result document is still written. |
| `s08-incomplete-definition.json` | **Two** APIs: an inline definition with no error sample and no declared status, beside a fully-specified sibling | exit 0, `COMPLETED`, 13 PASS / 11 N/A, passRate 1.0, **clean** (2026-08-27). Split **7 PASS / 6 N/A** for the incomplete `UPLOAD-S08` and **6 PASS / 5 N/A, 0 FAIL, 0 `SKIPPED_NO_TOKEN`** for the sibling. Missing metadata shows up as `NOT_APPLICABLE`, not as failures, and 5 of `UPLOAD-S08`'s 6 name the gap in `missingField` (`documented_status_codes`, `documented_content_types`, `path_variables`, `request_body_sample` ×2). The sixth is the opt-in CORS check, where `missingField` is `null` because nothing is missing. **Nothing propagates to the sibling** — see below. |
| `s09-curl.txt` | cURL upload carrying an `Authorization` header | exit 0 (confirmed 2026-08-27). Parses; the token is discarded. No `Authorization` key on the emitted `definition` at all; the stored `"cURL"` value reads `Authorization: <redacted>`; `"Auth Type": "Bearer Token"` survives. **The endpoint's need for auth outlives the credential.** Token absent from stdout and stderr. See below. |
| `s09b-curl-malformed.txt` | cURL whose `Authorization` header is missing its colon | exit **2**, `error: header 'Authorization' is not in 'Name: value' form (value withheld)`. Token absent from stdout and stderr; stdout is empty. Before 598227b this message quoted the token verbatim. Re-confirmed 2026-08-27. |
| `s11-batch-multi-host.json` | 12 runnable APIs, 7 UAT + 5 DEV host | exit 0, `COMPLETED`, 73 PASS / 12 FAIL / 1 WARN / 50 N/A, passRate 0.8588, `cleanBlockers: ["FAIL","WARN"]`. Host-level probes run once per host — check `measuredBy`. |
| `s13-ref-vs-inline.json` | Same Attendance API twice: once by `ref`, once inline | exit 0, `COMPLETED`, 13 PASS / 2 WARN / 9 N/A. **passRate 1.0 with `clean: false`** — `cleanBlockers: ["WARN"]` says why. This is the case that reads as an engine bug without that field. |

## s01's original provider, and why it was changed

**As first written, s01 paired the Leave API with `Login_Auth_UAT_API` and
returned 8 PASS / 2 FAIL / 3 N/A** — an accidental reproduction of s03's
phenomenon. Leave lives on the DEV host; that provider mints UAT tokens. The
bootstrap succeeded, the DEV host rejected the token with `401`, and both FAILs
were downstream of it, under `gatewayClassification: AUTH_FAILURE_401`.

It was changed to `Employee_Auth_API` on 2026-08-27, which is what the row above
now records. **s01's job is to establish what a clean run looks like**, so every
other scenario has a reference to read against; a baseline that fails for
configuration reasons cannot do that. No coverage was lost — s03 exercises the
wrong provider deliberately, and on purpose rather than by accident.

**The mistake is worth recording because of how easily it was made.**
`Login_Auth_UAT_API` *looked* right by name — the environment is UAT, and the
name says so. The name describes the provider, not the host its tokens are good
for. Nothing in the manifest, the validation, or the run status flagged the
pairing; it surfaced only as two FAILs that read like a broken Leave endpoint.
That is the same trap §8 of the handoff README describes, arrived at by
accident instead of by design.

## s08 — the fail-soft invariant

The point of s08 is **containment**, not the `NOT_APPLICABLE` classification
itself — s02 and others already show that. The claim is that an under-specified
definition degrades to `NOT_APPLICABLE`, **and stops there**: it never becomes a
FAIL, and it never reaches anything else in the run.

A single-API manifest cannot demonstrate that, so **s08 carries two APIs**: the
inline `UPLOAD-S08` definition, and the fully-specified attendance row s02 uses.
One run, one document, containment visible in it.

| | `UPLOAD-S08` (incomplete) | sibling (fully specified) |
|---|---|---|
| PASS | 7 | 6 |
| NOT_APPLICABLE | 6 | 5 |
| **FAIL** | **0** | **0** |
| **`SKIPPED_NO_TOKEN`** | **0** | **0** |
| passRate | 1.0 | 1.0 |
| `clean` | `true` | `true` |

`missingField` names the gap for **5 of `UPLOAD-S08`'s 6** `NOT_APPLICABLE`
results, so the reader can tell *which* metadata would unlock each check rather
than guessing:

| Test | `missingField` |
|---|---|
| `test_status_code_matches_spec` | `documented_status_codes` |
| `test_content_type_negotiation` | `documented_content_types` |
| `test_404_for_unknown_route` | `path_variables` |
| `test_special_characters_in_input` | `request_body_sample` |
| `test_request_payload_size_enforcement` | `request_body_sample` |
| `test_cors_preflight` | `null` — **correct; nothing is missing** |

The sixth is the opt-in CORS preflight check. It is `NOT_APPLICABLE` because it
is switched off (`GLOBAL_CONTRACT_ENABLE_CORS_PREFLIGHT=1` enables it), not
because the definition lacks anything — so `missingField` is `null`. **A `null`
there means *not a metadata gap*, and must not be rendered as one.**

### The sibling's own `NOT_APPLICABLE`s are not inherited

The sibling reports 5 `NOT_APPLICABLE` of its own, which is easy to misread as
propagation. It is not. Every one of them is a gap in **its own** catalogue row,
and each carries its own `missingField` — `path_variables`,
`documented_content_types`, `request_body_sample`, `documented_status_codes`,
plus the same opt-in CORS `null`.

Running the sibling **alone** (that is `s02`) and diffing the two result sets
confirms it: every result is identical in state and `missingField`, **except the
two host-level probes**, which change for a documented and unrelated reason —

| Test | s02 alone | beside `UPLOAD-S08` |
|---|---|---|
| `test_request_payload_size_enforcement` | `NOT_APPLICABLE`, `referencesHostResult: false` | `NOT_APPLICABLE`, **`referencesHostResult: true`** |
| `test_small_burst_does_not_trigger_immediate_blocking` | `PASS`, `referencesHostResult: false` | `NOT_APPLICABLE`, **`referencesHostResult: true`** |

Both APIs are on the same host, so the host-level probes **run once and are
referenced by the second API** rather than repeated — `referencedHostResults: 2`
on the sibling's summary, and `measuredBy` names the API that actually measured.
That is §6 of the handoff README, not fail-soft. **Follow `measuredBy` before
reading a host-level `NOT_APPLICABLE` as a gap.** It is also why the sibling
totals 11 results here against 13 when run alone.

### A prior observation worth keeping

Before the second API was added, the 2026-08-27 single-API run scored **6 PASS /
1 WARN / 6 N/A**, `cleanBlockers: ["WARN"]`. The WARN was
`test_response_time_within_sla` at **1022.5ms against a 700ms advisory target**.
The current two-API run does not reproduce it — the same check passed for both
APIs — because response time is live and varies.

**It is recorded rather than tuned away.** It is a real observation of the
advisory SLA doing its job in a scenario not designed to test it, and it shows
the WARN state behaving as specified: it does not touch `passRate` (still 1.0),
but it does block `clean`. If this run WARNs for you, that is latency, not the
missing metadata, and not a regression in the scenario.

## About the FAILs in s11

They are not all the same thing, and none is an engine defect. Triaged
2026-08-26 — see the commit message for the full analysis.

- **s11's 7 DEV FAILs are a provider mismatch, not an endpoint defect** —
  401-driven, `gatewayClassification: AUTH_FAILURE_401`, the same shape s01
  originally hit and s03 reproduces on purpose. See §8 of the handoff README.
- **s11's 4 UAT `404` FAILs are stale fixture IDs.** `/api/attendancepolicy/1`,
  `/2`, `/api/v1/attendance/shift/master/6`, `/7` reference records that do not
  exist. The collection endpoints are clean (s02: passRate 1.0). Reproduced
  identically in s04 and s11. This is a class, not four incidents — see
  *stale fixture IDs* in §8 of the handoff README for the inventory-wide count.
- **One genuine candidate for the API owner:** `PATCH
  /api/attendancepolicy/4/status` returned **500**. Observed once. A 500 where
  a 404 would be expected for a missing record is worth a ruling.

## Running one

```bash
python -m tests.global_contract.run \
  docs/platform-handoff/manual-scenarios/s02-attendance-single.json \
  --out reports/platform/s02.json
```

Exit `0` the run happened (tests may still have failed), `2` it could not start,
`3` the runner broke. Read `status` from the document, never the exit code, to
tell a failing test from a failing run.

## s09 — the cURL scenario

```bash
python -m tests.global_contract.parse_curl \
  docs/platform-handoff/manual-scenarios/s09-curl.txt \
  --api-id UPLOAD-S09 --module Uploaded \
  --entry --credential-alias attendance-svc-uat-01
```

Expected: exit 0, `"Auth Type": "Bearer Token"`, and a `"cURL"` value whose
Authorization reads `<redacted>`. The token in the file must appear in **no**
output, warning or error — stdout and stderr both. The file's `#` header block
is ignored by the parser.

The token there is fake. Never commit a live one; the point of the scenario is
that the engine discards it, not that it is safe to store.

## Credentials

`s01`–`s05`, `s11` and `s13` need `CRED_LEAVE_SVC_UAT_01_*` and
`CRED_ATTENDANCE_SVC_UAT_01_*` registered in `.env` (gitignored). `s06` needs
nothing — an unregistered alias is what it tests. Aliases are labels; no
credential value appears in any manifest here.

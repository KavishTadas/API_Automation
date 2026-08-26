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
UAT on 2026-08-26. Counts drift with live endpoint behaviour; `status`, exit
code and `cleanBlockers` are the stable parts.

| File | Exercises | Observed outcome |
|---|---|---|
| `s01-leave-single.json` | Leave API, `leave-svc-uat-01`, provider Login_Auth_UAT_API | exit 0, `COMPLETED`, 8 PASS / 2 FAIL / 3 N/A, passRate 0.8, `cleanBlockers: ["FAIL"]` |
| `s02-attendance-single.json` | Attendance API, `attendance-svc-uat-01`, provider Login_Auth_UAT_API | exit 0, `COMPLETED`, 7 PASS / 6 N/A, passRate 1.0, **clean** |
| `s03-attendance-wrong-provider.json` | As s02 but provider Employee_Auth_API | exit 0, `COMPLETED`, 6 PASS / 1 FAIL / 6 N/A. **The wrong provider still bootstraps successfully** — no `SKIPPED_NO_TOKEN`, empty `statusReason`. The token is minted and then rejected in use, surfacing as one FAIL (`test_response_matches_full_schema`: *did not inspect a success response*). A mis-pointed provider looks like a broken API, not a broken credential — which is the point of the scenario. |
| `s04-batch-shared-provider.json` | 3 APIs, one provider + alias | exit 0, `COMPLETED`, 18 PASS / 3 FAIL / 14 N/A. One bootstrap serves all three. |
| `s05-batch-mixed-providers.json` | Leave + Attendance, different providers | exit 0, `COMPLETED`, 17 PASS / 9 N/A, passRate 1.0, **clean**. Two bootstraps in one run. |
| `s06-unregistered-alias.json` | Any API, alias that is registered nowhere | exit **0**, `COMPLETED_WITH_ERRORS`, 9 `SKIPPED_NO_TOKEN` / 4 N/A, passRate `null`, `cleanBlockers: ["SKIPPED_NO_TOKEN"]`. **Exit 0 is correct** — the run happened; the APIs were blocked. Check `blockedBy` on the results for the provider that failed. |
| `s07-bad-environment.json` | Valid API, `"environment": "PROD"` | exit **2**, `ABORTED`, no tests run. Rejected at validation: *'PROD' is not registered; known environments are ['UAT']*. A result document is still written. |
| `s08-incomplete-definition.json` | Inline definition, no error sample, no declared status | exit 0, `COMPLETED`, 7 PASS / 6 N/A. Missing metadata shows up as `NOT_APPLICABLE`, not as failures, and 5 of the 6 name the gap in `missingField` (`documented_status_codes`, `documented_content_types`, `path_variables`, `request_body_sample` ×2). The sixth is the opt-in CORS check, where `missingField` is `null` because nothing is missing. |
| `s09-curl.txt` | cURL upload carrying an `Authorization` header | Parses; the token is discarded. See below. |
| `s11-batch-multi-host.json` | 12 runnable APIs, 7 UAT + 5 DEV host | exit 0, `COMPLETED`, 73 PASS / 12 FAIL / 1 WARN / 50 N/A, passRate 0.8588, `cleanBlockers: ["FAIL","WARN"]`. Host-level probes run once per host — check `measuredBy`. |
| `s13-ref-vs-inline.json` | Same Attendance API twice: once by `ref`, once inline | exit 0, `COMPLETED`, 13 PASS / 2 WARN / 9 N/A. **passRate 1.0 with `clean: false`** — `cleanBlockers: ["WARN"]` says why. This is the case that reads as an engine bug without that field. |

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

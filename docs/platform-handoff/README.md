# Platform Integration Guide

How the Omfys Java QA Platform drives this test engine and renders what comes
back. Everything here is reproducible from the four sample artifacts in this
directory — you do not need repo access to build a renderer.

> **The output schema is work-in-progress by design.** It is expected to change
> once you start building against it. Say what you need and it will change.

---

## 1. The shape of an integration

```
                 run manifest (you send)
platform  ─────────────────────────────────────►  engine
          ◄─────────────────────────────────────
                 result document (you render)

          ◄─────────────────────────────────────
                 catalogue (you fetch, ahead of any run)
```

Three documents, three jobs:

| Artifact | Direction | Answers |
|---|---|---|
| [`sample-catalogue.json`](sample-catalogue.json) | engine → platform | What APIs and test cases exist? What will run for this API? |
| [`sample-run-manifest.json`](sample-run-manifest.json) | platform → engine | Which APIs should I test, in which environment, with which credentials? |
| [`sample-result-single-api.json`](sample-result-single-api.json) | engine → platform | What happened for one API? |
| [`sample-result-batch.json`](sample-result-batch.json) | engine → platform | What happened across the batch? Contains **all seven states**. |

---

## 2. What you send: the run manifest

```json
{
  "runId": "run-2026-08-25-001",
  "environment": "UAT",
  "requestedTiers": ["global_contract"],
  "apis": [
    { "ref": "get|{{leavebaseurl}}|/user/leaves/getallleavereports|leave api|tc01/tc03 - ...",
      "credentialAlias": "leave-svc-uat-01",
      "authProviderApiId": "post|{{authbaseurl}}|/auth/token|employee auth api|tc01 - ..." },

    { "definition": { "API ID": "API-001", "HTTP Method": "GET", "...": "..." },
      "credentialAlias": "attendance-svc-uat-01",
      "authProviderApiId": "post|{{authbaseurl}}|/auth/token|employee auth api|tc01 - ..." }
  ]
}
```

**Each entry carries either `ref` or `definition`, never both.**

- `ref` — an API already in the repo. The value is the catalogue's `apis[].ref`,
  which is the inventory's `API Identifier`. There is **no fallback matching**:
  an unrecognised `ref` degrades that one API to `NOT_APPLICABLE` and the rest of
  the batch runs normally.
- `definition` — an uploaded API, travelling **by value**. Parse the user's Excel
  or cURL upload into the 15-column shape and inline it. The engine stores
  nothing.

**Unknown fields are rejected**, not ignored — a typo'd `authProviderApiID`
would otherwise produce a run that looks fine and quietly skipped its auth.

### Credentials never travel in a manifest

`credentialAlias` is a **label**. The engine resolves it at run time from
`CRED_<ALIAS>_EMP_CODE` / `CRED_<ALIAS>_EMP_PASSWORD` in the environment or CI
secrets, with the alias uppercased and non-alphanumerics collapsed to
underscores (`attendance-svc-uat-01` → `CRED_ATTENDANCE_SVC_UAT_01_EMP_CODE`).

A manifest is rejected if a control field looks like it carries a secret — a
credential-shaped key anywhere in the control region, or a `credentialAlias`
holding a JWT or a `password=…` string. **Rejections name the JSON path and
never echo the value.** Sample payload *content* is exempt: an auth API's
`Success Response` legitimately documents a `token` field, and that is a
description of the API, not a credential for it.

### Environments

Normalised to uppercase with non-alphanumerics collapsed, so `uat`, `UAT` and
`Uat` are one environment. The **valid set is whatever is registered** — read it
from the catalogue's `environments`. Naming an unregistered environment fails
the run and lists what is registered.

### Auth

`authProviderApiId` names an API used as a **token provider, not a test
subject**. It is called directly and its own collection is never run — otherwise
a failing auth assertion would surface as a failure of the API the user actually
selected.

One login per distinct `(authProviderApiId, credentialAlias)` pair per run.
Eight APIs sharing a pair perform one login between them. An API with no auth
requirement attempts none.

### Why the provider is per-API and not one global setting

This looks like over-engineering until you hit it. It is load-bearing today:

| API | Platform | Working provider |
|---|---|---|
| Leave | `devmcdphcmplatform` | `Employee_Auth_API` (dev host) |
| Attendance | `uatmcdphcmplatform` | **`Login_Auth_UAT_API`** (UAT host) |

A token minted by `Employee_Auth_API` is **rejected by the UAT Attendance
platform** with `INVALID_TOKEN`. The token from `Login_Auth_UAT_API` returns 200
against the same endpoint. Verified directly, not inferred.

So a single global auth setting cannot drive a batch spanning both platforms —
which is exactly what an integration run does. The shipped
`sample-run-manifest.json` shows both providers side by side for this reason.

This is also why `Login_Auth_UAT_API` must not be merged into
`Employee_Auth_API` until the dev/UAT auth consolidation is settled. The two
collections look near-duplicate and reviewing them invites exactly that merge;
they issue tokens that different platforms accept.

---

## 3. What you get back: the result document

```json
{
  "runId": "run-2026-08-25-001",
  "status": "COMPLETED_WITH_ERRORS",
  "statusReason": "auth bootstrap failed for: …",
  "summary": { "counts": {…}, "passRate": 0.6667, "passRateApplicable": true,
                "clean": false, "cleanBlockers": ["FAIL", "WARN"] },
  "apis": [ { "apiRef": "…", "gatewayClassification": null, "summary": {…}, "results": [ … ] } ]
}
```

### Run status is orthogonal to test outcomes

| Status | Meaning |
|---|---|
| `COMPLETED` | Every requested tier executed. **Individual tests may have failed.** |
| `COMPLETED_WITH_ERRORS` | A tier ran only partially — e.g. auth bootstrap failed for some APIs. |
| `ABORTED` | A tier could not start — manifest invalid, environment unresolvable. |

**A test `FAIL` is not a run failure.** A run in which every single test fails
still reports `COMPLETED`. Conflating the two makes one failing assertion look
like an engine outage.

### Per-result fields

| Field | Notes |
|---|---|
| `testId` | Joins to the catalogue. See §4. |
| `apiRef` | The inventory `API Identifier`. |
| `state` | One of seven. See §5. |
| `reason` | Human-readable detail. Always present for non-`PASS`. |
| `missingField` | **Present for `NOT_APPLICABLE`** — names the metadata to declare. |
| `observed`, `threshold` | **Present for `WARN`** — both, always. |
| `durationMs` | Wall-clock. |
| `executed` | Whether the check actually ran. See the `WARN`/`INFORMATIONAL` trap in §5. |
| `provenance` | `sourceType`, `sourceCollection`, `sourceModule`, `owner`. |
| `blockedBy` | **Present for `SKIPPED_NO_TOKEN`** — the `authProviderApiId` whose bootstrap failed. `null` when the block had no named provider. |
| `hostLevel`, `host`, `referencesHostResult` | See §6. |
| `measuredBy` | **Present for every `hostLevel: true` result** — the `apiRef` that carried the measurement. See §6. |
| `gatewayClassification` | See §7. |

---

## 4. Joining catalogue to results

Do **not** match positionally. The prototype's
`assertions[index % assertions.length]` mismatches the moment anyone reorders a
collection.

| Scope | Catalogue id | Result join |
|---|---|---|
| Global | `global_contract::test_status_code_matches_spec` | `(testId, apiRef)` — the global set is published **once** and runs once per API |
| Newman | `newman::{apiRef}::{slug}` | `testId` |
| Generated | `generated::{apiRef}::status_code` | `testId` |

Global tests appear once in `testCases.global`, not duplicated under all 45
APIs — render them as a shared section.

### Showing what will run, before a run

`catalogue.applicability[apiRef][testId]` gives `PLANNED` or
`NOT_APPLICABLE` with a reason, for every API in the catalogue, computed with
**zero HTTP requests**.

An *uploaded* API is not in the catalogue (see §8). You hold its definition, so
call the engine's applicability resolver with it.

---

## 5. The seven states, and the pass-rate rule

Read `catalogue.resultStates` — the definitions, the denominator set, and the
classification rule are all published there. Do not re-derive them.

| State | Meaning | In pass rate? | Executed? |
|---|---|---|---|
| `PASS` | Assertion ran and succeeded | ✅ | ✅ |
| `FAIL` | Assertion ran and failed | ✅ | ✅ |
| `WARN` | Ran; an advisory threshold was exceeded; run not failed | ❌ | ✅ |
| `SKIPPED_NO_TOKEN` | Auth bootstrap failed; API never executed | ❌ | ❌ |
| `NOT_APPLICABLE` | Cannot apply — required metadata absent | ❌ | ❌ |
| `NOT_ASSERTED` | Request executed, but no assertion exists | ❌ | ❌ |
| `INFORMATIONAL` | Observes and records; asserts nothing | ❌ | ✅ |

### Pass rate is `PASS / (PASS + FAIL)`. Nothing else.

37 of 43 Newman requests in this repo carry **no assertions at all**. If
`NOT_ASSERTED` counts as a pass, your headline number is wrong on day one.

- When `PASS + FAIL == 0`, `passRate` is `null` and `passRateApplicable` is
  `false`. **Render that as "not applicable" — never as 100%.**
- The other five states stay individually countable in `summary.counts`.
- `summary.clean` is `false` if anything needs a human: any `FAIL`, any `WARN`,
  any `SKIPPED_NO_TOKEN`. A batch with one `WARN` is not a clean pass.
- `summary.cleanBlockers` names which of those are actually present, worst
  first — e.g. `["WARN"]`. **Render it whenever you render `clean: false`.**
  `passRate: 1.0` beside `clean: false` reads as an engine bug otherwise; it
  is not one, and this field is the sentence that says so. There is no separate
  warnings count — `summary.counts` already carries the per-state numbers.
- `cleanBlockers` is a list of *states*, so it is empty in exactly one
  non-clean case: nothing landed in `PASS + FAIL` at all, which
  `passRateApplicable: false` already tells you.

### The classification trap

`WARN` and `INFORMATIONAL` are emitted through `pytest.skip`, because that is
the only built-in non-failing outcome carrying a machine-readable reason.
**Both mean the check ran.** Classify on the `state` field (or, if you ever read
raw pytest output, on the reason prefix) — never on a pytest verdict. The
`executed` boolean on each result is there so you never have to decide.

---

## 6. Host-level results are referenced, not repeated

Two checks — `test_small_burst_does_not_trigger_immediate_blocking` and
`test_request_payload_size_enforcement` — measure **gateway** behaviour, not
endpoint behaviour. Running them per API meant a 45-API batch across three hosts
issued 450 burst requests and ~45 MB of uploads to test three hosts forty-five
times.

So the probe runs once per host and the other APIs on that host carry a result
that points at it. **`measuredBy` names which `apiRef` did the measuring**, and
it is present on every `hostLevel: true` result — including the one that did the
measuring, where it equals the result's own `apiRef`:

```json
"hostLevel": true,
"host": "https://devmcdphcmplatform.omfysgroup.com",
"referencesHostResult": true,
"measuredBy": "get|{{baseurl}}|/api/v1/attendance/shift/master|…"
```

Render "measured by X" straight from that one field. It is populated even when
it points at the row itself, so there is no self-case to special-case, and no
reason string to parse.

**Referencing records are excluded from `summary.total` and from all counts**
(`summary.referencedHostResults` reports how many were excluded). Counting a
shared host probe 45 times would distort the batch.

`referencesHostResult` answers a narrower question than `measuredBy != apiRef`:
it means *this row was dropped from the tally*. The two agree except for a
host-level row whose API was blocked by auth before the deduplication check ran
— that row is a genuine `SKIPPED_NO_TOKEN` and stays counted, while `measuredBy`
still correctly names the API that carries the host's measurement. **Use
`referencesHostResult` to decide what to count, `measuredBy` to decide what to
display.**

---

## 7. Gateway blocks are not application failures

`gatewayClassification` distinguishes three auth-shaped failures:

| Value | Meaning |
|---|---|
| `AUTH_FAILURE_401` | The application rejected the token. |
| `APPLICATION_AUTH_FAILURE_403` | The application refused the request. |
| `GATEWAY_WAF_EMPTY_BODY_403` | **The request never reached the application.** |

An empty-bodied 403 with `content-length: 0` and a non-JSON content type is a
WAF/gateway block. The Attendance host currently returns exactly this from the
CI runner pending an allowlisting request. Rendering it as "your API failed"
would be wrong for an entire module — say "blocked by gateway" instead.

---

## 8. Known limitations — read these before filing bugs

**Renaming a `pm.test()` string retires one test case and introduces another.**
Newman IDs are title-derived because a Postman assertion has no id and no stable
position, and Newman reports results by assertion *name* — the name is the only
thing that can join. History does not follow a rename. **Reordering assertions
is safe**, which is the more common edit. Global and generated-tier IDs are
derived from code identifiers and survive any title change.

**Uploaded APIs never appear in the catalogue.** The engine is stateless: an
upload travels by value inside the manifest and nothing is persisted. You hold
the definition; use the applicability resolver to show which tests will run.
Every run is reproducible from its manifest alone — preserve that.

**`PLANNED` → `NOT_APPLICABLE` is expected; the reverse is not.** A test the
catalogue predicted would run can still report `NOT_APPLICABLE` at run time —
`test_content_type_negotiation` does this when an API returns a status nothing
declared. This is not an inconsistency and the result document says so in
`applicabilityNote`. A test predicted `NOT_APPLICABLE` will never suddenly run.

**Credential handling after entry is yours.** The engine guarantees redaction of
its own reports and logs — no credential value, length, or masked form appears
in any output, verified by scan rather than inspection. Masking, storage, access
control, and platform-side logging of a raw value the user typed into your UI
are the platform's responsibility.

**`api-docs/API_File.json` is generated.** Regenerating it reshuffles rows and
renumbers `Sr. No`. All IDs in the catalogue are derived from content, not
position, so they survive that — but do not build anything on `Sr. No`.

---

## 9. Running it

### Start here — one working run, from a clean checkout

```bash
# 1. Register the credential alias the sample manifest names.
#    .env is gitignored; these values are never committed.
cat >> .env <<'EOF'
CRED_LEAVE_SVC_UAT_01_EMP_CODE=<your employee code>
CRED_LEAVE_SVC_UAT_01_EMP_PASSWORD=<your password>
EOF

# 2. Run the shipped sample.
python -m tests.global_contract.run docs/platform-handoff/sample-run-manifest.json \
       --out reports/platform/results.json
```

Expected on a working setup: `status: COMPLETED`, `passRate: 1.0`, **exit 0**.

If the alias is not registered, the run still completes and every API reports
`SKIPPED_NO_TOKEN` naming the alias it looked for — a good first look at how the
engine reports blocked work rather than pretending it passed.

### The CLI is what you should call

```
python -m tests.global_contract.run <manifest> [--out <path>] [--quiet]
```

| Exit | Meaning |
|---|---|
| `0` | `COMPLETED` or `COMPLETED_WITH_ERRORS` — the run did what it was asked |
| `2` | `ABORTED` — invalid manifest, unregistered environment, nothing collected |
| `3` | The runner itself broke |

**A failing test exits 0.** That is the point of the CLI: pytest's own exit code
is non-zero whenever any assertion fails, which would report an engine outage
every time an API misbehaved. Read `status` from the result document; use the
exit code only to tell "the run happened" from "the run could not start".

A result document is written on **every** path, ABORTED included, so you never
have to special-case an empty response.

`GLOBAL_CONTRACT_RUN_MANIFEST` and a direct `pytest tests/global_contract`
invocation both still work unchanged — but they expose you to pytest's exit
code, so prefer the CLI.

### Other commands

```bash
# catalogue — zero HTTP requests, byte-stable output
python -m tests.global_contract.catalogue docs/platform-handoff/sample-catalogue.json

# redaction regression
python scripts/regression/verify-result-emitter-redaction.py
```

### About the samples

`sample-run-manifest.json` runs green as shipped, once the alias above is
registered. `sample-result-batch.json` is assembled deliberately so that **all
seven states** appear — a live run only produces the states its APIs happen to
reach, and you need every render path.

# PHASE3_REPORT — complete, authority flipped

**Branch:** `refactor/authoring-surface`

Phase 3 has two halves. Both are now complete.

The structural half landed first (`f714bd7`). The authority flip was **blocked** at
that point on a data gap in the Phase 2 YAML, and was unblocked by reshaping the
authoring surface to carry all 18 inventory columns per case. `api-endpoints/*.yaml`
is now the source of truth; `build/API_File.json` is derived from it.

**Superseded below:** the "BLOCKED" section records why the flip could not proceed on
the original YAML shape. It is kept because the reasoning is the reason the reshape
took the form it did, not because the block still stands.

## Verification summary

| Check | Result |
|---|---|
| Seven-state delta vs baseline | **ZERO** |
| `build/auto_generated/` file count before running | **45** |
| Round-trip, ref-level | catalogue = inventory = YAML tree = **same 45 refs** |
| UI 1 — `sourceCollection` prefix unchanged | **PASS** — 4 entries under `collections/auth/` |
| UI 2 — dropdown resolves two providers on :8765 | **PASS** |
| UI 3 — per-entry `authProviderApiId` round-trips | **PASS** |
| Unit tests | 10 passed |

## RESOLVED (was blocking): the flip could not proceed on the original YAML

`api-endpoints/*.yaml` captures **15 of the inventory's 18 columns**. The three it
drops are all read by the contract tier:

| Missing column | Read by |
|---|---|
| `Request Parameters` | `metadata_resolver.py`, `curl_adapter.py`, **`test_global_api_contract.py`** |
| `Request Body Schema` | `metadata_resolver.py` |
| `Response (example/200)` | `metadata_resolver.py` |

`Request Parameters` is the most consequential: the anonymous-access check clears it
when building its unauthenticated request — that is the mechanism `33ecada` repaired.
Flipping authority to a source that does not carry it would silently change results,
which Rule 2 makes a defect regardless of how the tree looks afterwards.

There is a second, independent gap. Phase 2 stored `purpose`, `samplePayloads` and
`rules` at **endpoint** level, taking them from the primary case. For the three
endpoints carrying multiple cases those genuinely differ:

| Endpoint | `Sub-Module` | `Functional Purpose` | `Example Request Payload` | `Response (200)` |
|---|:--:|:--:|:--:|:--:|
| `POST /auth/token` (3 cases) | 3 distinct | 3 distinct | 3 distinct | 2 distinct |
| `GET /user/leaves/getallleavereports` (2 cases) | 2 distinct | 2 distinct | same | 2 distinct |

So regenerating from the YAML today would emit the primary case's content for four of
the 45 generated tests. The YAML is lossy in two independent ways, and a lossy source
of truth is not a source of truth.

**Fixing this means reshaping the Phase 2 deliverable** — carrying the full 18-column
row per test case rather than 15 columns per endpoint — and regenerating all 41 files.
That is a change to a tree already walked and approved, so it is left for a decision
rather than taken unilaterally.

**What was done instead:** the generator's *output* moved to `build/`; its *input*
still reads `api-docs/API_File.json`. The comment at the top of
`scripts/generate-generic-tests.py` records why, so the flip is blocked rather than
forgotten.

## What did change

### `tests/auto_generated/` was never purely disposable

Three authored modules import from it, one at **module level**:

| Consumer | Symbol | Kind |
|---|---|---|
| `tests/global_contract/auth_bootstrap.py:33` | `perform_api_request` | **module-level** |
| `tests/global_contract/test_global_api_contract.py:36` | several | module-level |
| `tests/global_contract/run.py:97` | `load_runtime_config` | lazy |
| `tests/global_contract/catalogue.py` | `load_runtime_config`, `_resolve_templates` | lazy |
| `harness/service.py:102` | `load_runtime_config` | lazy |

`_api_test_helpers.py` (790 lines) holds `perform_api_request` — the pooled
`httpx.Client` from `b5ee0d3`. A library the authored tier cannot import without is
not disposable output, whatever directory it sat in. Gitignoring it would have made a
fresh clone unable to import `tests.global_contract` at all.

**Approved resolution — split library from output:**

```
tests/api_runtime/_api_test_helpers.py   TRACKED, authored  (moved via git mv)
build/auto_generated/                    GITIGNORED, 45 generated tests + conftest + __init__
```

The generator **no longer writes** `_api_test_helpers.py`. Its `HELPER_CONTENT`
constant — a 791-line second copy of the library — was deleted: keeping it is exactly
how two copies drift, and the generator would have overwritten the real one on every
run.

### Paths updated

| File | Change |
|---|---|
| `tests/global_contract/{auth_bootstrap,catalogue,run,test_global_api_contract}.py` | import from `tests.api_runtime` |
| `harness/service.py` | import from `tests.api_runtime` |
| `tests/global_contract/catalogue.py` | `GENERATED_TESTS_DIR` to `build/auto_generated` |
| `.github/workflows/api-tests.yml` | two `pytest` paths to `build/auto_generated` |
| `scripts/generate-allure.js`, `generate-html-index.js` | node-ID prefix and path regex to `build.auto_generated` |
| `.gitignore` | `build/` added, with a note on where the runtime went |

`pyproject.toml`'s `testpaths = ["tests"]` was left alone deliberately: adding a
gitignored directory that may not exist would make bare `pytest` error on a fresh
clone. CI invokes the generated tier by explicit path.

## The 6-WARN scare, and why it was not a defect

The first Phase 3 run showed `PASS 408 -> 402`, `WARN 0 -> 6`. Every one of the six was
`test_response_time_within_sla`; five were the same `POST /auth/token` measurement
(1134.1 ms against a 1000 ms threshold) counted across its five refs, the sixth a
`DELETE` at 967.9 ms against 700 ms.

Two re-runs of the **same** Phase 3 code returned `PASS 408 / WARN 0` — the baseline
exactly. The check issues no request of its own; it reads bootstrap timings, so it
tracks live UAT latency. An earlier provider-split run had already produced one WARN
at 860 ms with no code change at all.

Worth naming: the suite's headline numbers are **not fully deterministic** across
runs. One advisory check is latency-dependent, so a zero-delta comparison can fail for
reasons that have nothing to do with the change under test. Re-running is the way to
tell them apart.

## Recorded, not fixed (Rule 3)

- **CI never runs the global-contract tier.** `pytest tests/global_contract` appears
  nowhere in the workflow or the `Jenkinsfile`; CI runs only the generated tier. The
  tier producing all 953 results and the entire 0.7698 figure is unverified by CI.
  This also means CI would not have caught the import breakage this phase avoided.
- `scripts/generate-api-file.js` still writes `api-docs/API_File.json` from the
  collections. Once authority flips to the YAML, that becomes a second description of
  the same thing. Reconciling or retiring it is a follow-on decision.
- `scripts/build_unified_console.py:119` reads `api-docs/API_File.json`. It keeps
  working because that file was deliberately not moved.

## Collapse list

**Refs sharing a slug** — 7 refs into 3 endpoints:

| Slug | Refs |
|---|---|
| `employee_auth_api_post_auth_token` | `tc01 - valid credentials return jwt token`<br>`tc02 - invalid empcode returns 400`<br>`tc03 - missing password returns 400` |
| `leave_api_get_user_leaves_getallleavereports` | `tc01/tc03 - get all leave reports and validate structure`<br>`tc02 - invalid token returns observed authorization status` |
| `attendance_shift_master_post_api_v1_attendance_shift_master` | `create custom shift (fixed type)`<br>`create new shift` |

**Method+path shared across modules** — one path, not two endpoints:

`POST /auth/token` spans `auth`, `employee auth api` and `login auth uat api`. Those
three module-scoped endpoints collapse to one `method+path`, which accounts for both
entries lost between 41 and 39. It is also why keying on `method+path` alone was the
wrong option: it would have merged the Employee Auth and Login Auth UAT providers,
which are precisely the two the harness dropdown must keep apart.

---

# Addendum — the flip, and what unblocked it

## The reshape

`api-endpoints/*.yaml` now carries `cases[]`: **41 files, 45 cases**, one case per
inventory row. Content that can differ between cases lives per case; only
`module`, `method` and `endpointPath` stay at endpoint level, because a difference in
those would make it a different endpoint by definition (the slug is derived from
exactly those three).

The column mapping is **bijective** — 13 scalar fields, 3 `samplePayloads[]` entries
keyed by `payloadType`, 2 `rules[]` entries keyed by `category`, totalling 18 — so
`case_to_row` is a true inverse of `row_to_case`. No dedup, no merging, no column
written by two rules.

## Losslessness is tested, not asserted

`tests/unit/test_endpoint_yaml_roundtrip.py` compares every one of the 45 rows
**column by column** against `api-docs/API_File.json`. It also pins the two failures
the first shape had:

- `test_mapping_covers_exactly_eighteen_columns` — catches a dropped column
- `test_multi_case_endpoints_keep_their_differences` — catches per-case content being
  folded up to the endpoint

Round-trip verification: `build/API_File.json` vs `api-docs/API_File.json` —
**45 refs identical, 0 column mismatches, row order identical**, and the parsed
structures compare equal including types.

## Readers repointed to the derived artifact

| Reader | Now reads |
|---|---|
| `tests/global_contract/metadata_resolver.py:72` | `build/API_File.json` |
| generated `conftest.py` (runtime) | `build/API_File.json` |
| `scripts/build_unified_console.py` | `build/API_File.json` |

Without these, editing a YAML file would not have reached the resolver until the Node
generator rewrote `api-docs/`, which would have made the flip cosmetic.

## `build/` is tracked

The gitignore added in `f714bd7` was withdrawn. `build/` is committed, so a fresh
clone can run the suite with no generation step — which matters because
`tests/global_contract/auth_bootstrap.py` imports the runtime at module level.

## caseRef

Endpoint directories can hold cases for several refs. A case file scopes itself by
declaring `caseRef = "<canonicalRef>"` at module level; it must be byte-identical to a
known ref, and `scripts/generate-endpoint-yaml.py` **exits 3** if it is not. Omitting
it is permitted where the endpoint has a single case. All 41 case READMEs document it
with that endpoint's real refs. Three unit tests cover accept / reject / omit.

## Verification against the Phase 4 gate

| State | Baseline | Now | Delta | Gate |
|---|---:|---:|---:|---|
| FAIL | 122 | 122 | 0 | hard |
| SKIPPED_NO_TOKEN | 0 | 0 | 0 | hard |
| NOT_APPLICABLE | 381 | 381 | 0 | hard |
| NOT_ASSERTED | 36 | 36 | 0 | hard |
| INFORMATIONAL | 6 | 6 | 0 | hard |
| total | 953 | 953 | 0 | hard |
| PASS | 408 | 408 | 0 | soft |
| WARN | 0 | 0 | 0 | soft |

**Hard gate: PASS. No PASS/WARN movement, so no SLA justification needed.**
Observed latency WARNs on the final run: **0**. Unit tests: 21 passed.
All three UI checks re-run against the flipped code: `sourceCollection` prefix intact
(4 entries), dropdown resolves 2 providers on :8765, per-entry `authProviderApiId`
round-trips with `SKIPPED_NO_TOKEN: 0`.

## The 291-PASS scare

One run during the flip showed `PASS 408 -> 291`, `NOT_APPLICABLE +122`, `FAIL -5` —
a hard-gate failure. It was **not** the flip. The result document named the cause:

| Count | Reason |
|---:|---|
| 64 | `host https://uat-mcdp-be.omfysgroup.com is unreachable (ConnectTimeout)` |
| 52 | `host https://uatmcdphcmplatform.omfysgroup.com is unreachable (ConnectTimeout)` |
| 12 | `socket.gaierror: getaddrinfo failed` |

A transient network outage. Four subsequent runs — two with the resolver on
`api-docs/`, two on `build/` — all returned exactly `408/122/381/36/6`, and the two
inventory files parse to equal structures.

Worth keeping: the seven-state model turned an outage into `NOT_APPLICABLE` with a
named reason rather than a false pass. That is `60cd25f` doing its job, and it is what
made the anomaly diagnosable in one pass instead of a bisect.

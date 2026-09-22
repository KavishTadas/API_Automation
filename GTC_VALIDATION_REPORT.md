# Global Test Case (GTC) Validation Report

**Scope of evidence:** repo HEAD `4ac7a26`, clean working tree, branch `main`.
**Method:** offline static analysis + the recorded live run `baseline/44-endpoint-run.json`
+ simulated console runs. **No live UAT request was issued.**

---

## Executive summary

Three questions were asked. The short answers:

| # | Question | Answer |
|---|---|---|
| 1 | Are the GTCs universally applicable to every API? | **No — 6 of 28 are.** The tier is universally *executed* but not universally *applicable*. 12 checks are conditional, 2 are dormant, 5 are host-scoped. |
| 2 | Do all GTCs run for every endpoint selected in the UI, regardless of its own test cases? | **Yes, and more strongly than asked.** A check filter cannot even be expressed — the manifest schema *rejects* one. But the premise contains a false assumption; see §3.3. |
| 3 | Are each GTC's prerequisites documented with fallbacks? | **Partially.** 76 (check, prerequisite) pairs are now documented here for the first time. Three prerequisite markers are silently discarded by a regex (D-7). |

**The headline number:** the tier runs **1,276 result rows across 44 endpoints — exactly 29 per
endpoint, without exception**. Mandatory execution is not merely implemented, it is
structurally enforced. What is *not* sound is applicability accounting: **44 of the run's 54
failures are a single gateway misconfiguration counted 44 times**, and the static applicability
map that feeds the console covers only 15 of 28 checks.

**Seven defects** are reported in §5, three of them High. No code was changed.

---

## 1. What the tier actually is

28 checks in `test-cases/global/01_*.py` … `28_*.py`, one assertion each. The harness lives in
`tests/global_contract/`. Discovery is a directory glob (`catalogue.py:242`), so a check cannot
exist without being registered.

Three independent paths agree on the count: file glob = 28, `_registry.CHECK_COUNT` = 28,
AST discovery = 28. **Five places in the repo still say 12 or 22** (D-3).

Categories are **five**, not the three the docs imply:
security 11, functional 6, schema 5, resilience 5, performance 1.

The corpus is **44 inventory rows collapsing to 39 distinct `method + path` operations** — all
REST/JSON with bearer auth. Zero SOAP, GraphQL, gRPC or WebSocket endpoints exist.

---

## 2. Requirement 1 — Universal applicability

### 2.1 Method

Two independent legs, then reconciled:

- **Static** — `resolve_applicability()` over all 39 operations, run twice (`cors_enabled` on
  and off). Issues no HTTP.
- **Empirical** — the 1,276 recorded rows. A check *applied* if its row is
  `PASS/FAIL/WARN/INFORMATIONAL/NOT_ASSERTED` (the request went out); it did *not* apply if
  `NOT_APPLICABLE/SKIPPED_NO_TOKEN`. Host-suppressed rows are a separate bucket, not NA.

**Reconciliation identity — all four numbers, so the document does not look inconsistent:**

```
raw rows                    1276
referencedHostResults         80   (excluded from the summary by result_emitter.py:346)
1276 - 80 = computed total  1196   == summary.total          ✔
raw NOT_APPLICABLE           586
summary.counts NA            506   (= 586 - 80)              ✔
```

### 2.2 The verdict — 6 of 28 are universally applicable

| Bucket | n | Checks |
|---|---|---|
| **UNIVERSAL** (≥95% applied) | **5** | 02 full-schema, 03 credential-leakage, 04 SLA, 11 CORS preflight, 13 HTTPS transport |
| **BROADLY_APPLICABLE** (60–95%) | 4 | 08 401-without-token (0.89), 14 private-endpoint (0.91), 15 error-machine-readable (0.84), 16 error-hides-internals (0.84) |
| **CONDITIONAL** (5–60%) | **12** | 01 (0.16), 05 (0.34), 09 (0.43), 10 (0.14), 12 (0.48), 17 (0.50), 23–26 (0.14), 27 (0.32), 28 (0.25) |
| **DORMANT** (<5%) | **2** | 18 declared-idempotency (0.05), 19 paginated-metadata (**0.00**) |
| **HOST_SCOPED — enforced** | 2 | 06 burst, 07 payload-size (deduped 40/44 correctly) |
| **HOST_SCOPED — declared only** | 3 | 20, 21, 22 — flagged host-level but **measured 44× each** (D-1) |

**Answer, stated plainly: the Global Test Cases are universally *executed* but not universally
*applicable*.** Only 5 checks assert against ≥95% of the corpus. The tier's own seven-state model
is what makes this visible and honest — `NOT_APPLICABLE` is 46% of all rows, and every one of
them names why.

### 2.3 Why the conditional ones are conditional — it is metadata, not protocol

Applicability is gated on **declared metadata presence**, and the inventory does not carry it:

| Metadata field | Provenance across 44 rows | Consequence |
|---|---|---|
| `paginated` | **none 44/44** | Dormantises checks 19, 23, 24, 25 — **one missing `x-paginated` disables four checks** |
| `documented_status_codes` | none 37, openapi 6, inventory 1 | Check 01 falls to 0.16 |
| `required_role` | none 38, openapi 6 | No check consumes it |
| `sla_ms` | **default 38**, openapi 6 | Check 04 reads 100% applicable only because a default is injected |
| `max_payload_bytes` | **default 44/44** | Same — applicability is manufactured by the default |

Checks 04 and 07 are "applicable" only because `metadata_resolver` supplies a default. That is a
defensible design, but it means their applicability rate measures *the default*, not the corpus.

### 2.4 Catalogue/runtime divergence on CORS

`_cors_preflight_enabled()` defaults to **enabled**; `resolve_applicability(cors_enabled=…)` and
`build_catalogue` default to **disabled**. The published catalogue therefore declares check 11
`NOT_APPLICABLE` for **all 39 operations**, while the runtime ran it and it passed **44/44**.
The console shows a check as inapplicable that in fact always runs.

### 2.5 Reconciliation outcome — the invariant holds

| Class | n | Meaning |
|---|---|---|
| AGREE_APPLICABLE | 459 | static PLANNED, empirically executed |
| UNPREDICTED | 572 | **static made no prediction at all** (D-6) |
| AGREE_NA | 144 | both say not applicable |
| HOST_DEDUP | 80 | by design; matches `referencedHostResults` exactly |
| LEGAL_DOWNGRADE | 21 | PLANNED → NOT_APPLICABLE, explicitly permitted |
| **CONTRACT_BREACH** | **0** | **NOT_APPLICABLE → executed. The forbidden transition never occurs.** |

Classes sum to 1,276. Zero unmatched joins. **The one invariant the contract says must never
break, does not break.**

### 2.6 Non-REST portability — a design audit, not a measurement

No non-REST endpoint exists in this repo, so this is **predicted**, not tested.

| Verdict | n | Meaning |
|---|---|---|
| INAPPLICABLE | 10 | the probe cannot be constructed (CORS, TRACE, unknown-route, pagination probes) |
| **SEMANTICS_LOST** | **7** | the check still runs and still reports PASS while asserting nothing meaningful |
| PORTABLE_WITH_ADAPTER | 6 | assumptions map 1:1 onto the other protocol |
| PORTABLE | 5 | transport/header-level only |

Verdicts are **identical for SOAP, GraphQL and gRPC** — not an artefact. All three break the same
three assumptions: HTTP status is constant, the URL path is not the resource identifier, and the
HTTP verb carries no semantics.

**The dangerous bucket is SEMANTICS_LOST** — 7 checks (01, 03, 05, 06, 08, 14, 19) that would
report green against a GraphQL endpoint that is entirely broken, because a GraphQL error still
returns HTTP 200. `A-STATUS` is the single most pervasive assumption: **23 of 28 checks** compare
an HTTP status code.

**Remediation is one change, not 28.** All 23 request-issuing checks funnel through
`perform_api_request(api_row, runtime_config)` and the same 18-column row shape. That is the
architectural chokepoint where a protocol adapter belongs.

---

## 3. Requirement 2 — Mandatory execution

### 3.1 Backend orchestration — 15/15 invariants hold

The decisive finding is stronger than "there is no filter": **a check filter cannot be
expressed.** Injecting one into the baseline manifest is rejected with an explicit error:

```
$.tests: unknown field (allowed: apis, environment, requestedTiers, runId)
$.apis[0].tests: unknown field (allowed: authProviderApiId, credentialAlias, definition, ref)
```

Supporting invariants: `KNOWN_TIERS` has one member; pytest is invoked as
`[test-cases/global, -p, no:cacheprovider]` with **no `-k`, `-m`, `--deselect` or `--ignore``;
`build_contract_params` applies no predicate; every gate calls
`_skip_with_state → pytest.skip(_record_state(...))`, so suppression removes the *assertion*,
never the *row*.

**Live confirmation:** across all 44 endpoints the row-count distribution is `{29: 44}` and the
distinct-check distribution is `{28: 44}`. One check-set, no exceptions. This closes D-5 for the
real engine.

### 3.2 UI, scheduling and isolation — 15/15 invariants hold

Driven against the built console in a `vm` sandbox across four batch shapes (44, 1, 20, one
module). Cardinality is exactly `refs × 28` in every shape.

**Isolation, proven by determinism:** for each of the 44 refs, the result vector produced
*alone* is **byte-identical** to the vector produced *inside the 44-endpoint batch* — for the 23
non-host-level checks, including `durationMs`, `reason` and evidence. No endpoint's presence,
selection state, or test-case inventory alters another's outcome.

**The honest boundary:** for the 5 host-level checks the vectors *do* differ, and must — probe
ownership depends on batch composition. Verified that the difference is confined to
`state`/`reason`/`referencesHostResult`/`measuredBy`/`durationMs`/`executed`, and that **row
count is identical either way**. The correct claim is *batch-dependent in outcome,
batch-independent in cardinality*. A blanket "no cross-contamination" would be false.

Two different salts produce identical cardinality and identical check ids, so the property is
not an artefact of one seed.

### 3.3 The premise correction — an important one

The requirement says GTCs must run *"regardless of whether its individually accompanying test
cases are selected."* **There is no such toggle, so there is nothing to be independent of.**

- The `TC_001/TC_002/TC_003` sub-rows in the multi-select look like an endpoint's own cases.
  They are not. Each carries `data-chk="${esc(a.ref)}"` — **unticking one removes an entire
  independent catalogue ref from the batch**, along with all 28 of *that ref's* global results.
- The genuinely per-endpoint tier is `SEED.apiTestCases` — **188 declared cases across 44
  endpoints**. It appears on exactly **one line** of the 8,670-line template (line 3884), inside
  a render function. It has no checkbox, is never read by `runBatch`, and is never sent by
  `manifestFor`. Verified: a full 44-endpoint run contains **zero `endpoint::` ids**.

So: independence from *per-endpoint test-case* selection is **vacuously true** — those 188 cases
cannot be selected and never execute. Independence from *endpoint* selection is **substantively
true** and is proven above.

**This is worth acting on.** The UI displays 188 test cases that will never run, beside a control
that appears to select them but actually removes whole APIs from the batch.

---

## 4. Requirement 3 — Prerequisites

**76 (check, prerequisite) pairs** are documented in `07-prereq-matrix.csv`, by kind:
inventory-row 25, auth-token 25, metadata-field 14, inventory-column 4, body-sample 3,
path-variable 3, host-resolution 2.

Every check begins with `_require_runnable`, which is why *inventory-row* and *auth-token* each
appear 25 times — those are the two universal preconditions. Mandatory prerequisites are
identified from the gate that fires when they are absent; optional ones are resolved through
`metadata_resolver` provenance, which names the fallback mechanically (`openapi` → `definition`
→ `inventory` → `default` → `none`).

**Highest-value finding:** `paginated` resolves to `none` for **44/44** rows. A single absent
OpenAPI extension (`x-paginated`) is the sole reason four checks (19, 23, 24, 25) are dormant.
Adding it to the spec would activate ~4 checks × 44 endpoints of coverage — the cheapest
coverage win available.

---

## 4b. Prerequisites per endpoint — what each API must carry

§4 answers *"what does each check need?"* This section answers the operational question:
**"for this endpoint, what API details are missing, and what would filling them in buy me?"**

Every one of the 1,232 non-host (endpoint × check) pairs in the recorded run is classified into
exactly one of three kinds. The distinction is the whole point — a create-only check skipped on a
GET is **not** a missing API detail:

| Kind | Pairs | Meaning |
|---|---:|---|
| **Asserted** | 634 | the check ran and asserted |
| **SCOPE** | 268 | out of scope for this method/path shape — by design, nothing to fill in |
| **DETAIL** | **220** | **an API detail is absent and could be supplied — actionable** |
| **RUNTIME** | 69 | the environment blocked it (auth rejected, no 2xx observed) |

### The readiness numbers

```
asserting today          mean 14.4 of 28   (min 11, max 22)
ceiling                  mean 21.9 of 28   (28 minus the out-of-scope checks)
recoverable via metadata mean  5.0 per endpoint  (220 pairs total)

supplying every missing API detail:  14.4  ->  19.4 of 28
```

**No endpoint reaches more than 22 of 28 today, and the mean is 14.4.** Roughly a quarter of the
shortfall is recoverable by filling in metadata; the rest is legitimate scoping.

### Ranked: which missing API detail unlocks the most

| Missing API detail | Pairs unlocked | Where it is declared |
|---|---:|---|
| **`x-idempotent`** (declared, not inferred) | **71** | OpenAPI extension — 42 need it *declared* rather than method-inferred, 29 have none |
| `x-paginated` | 44 | OpenAPI extension |
| documented content type | 38 | `Content-Type` in Request Parameters, or OpenAPI |
| `Response (example/200)` | 37 | inventory column — the documented status codes |
| `Example Request Payload` | 27 | inventory column — needed to mutate a body |
| `Request Body` | 3 | inventory column |

### Root cause: only 2 of 39 operations have an OpenAPI entry

`openapi/openapi.yaml` documents exactly two operations — `POST /auth/token` and
`GET /user/leaves/getAllLeaveReports`. Everything else falls back to inventory inference or an
injected default. The effect is measurable:

| Group | Endpoints | Mean asserting | Mean missing details |
|---|---:|---:|---:|
| Documented in `openapi.yaml` | 6 | **16.0 / 28** | **2.8** |
| Not documented | 38 | 14.2 / 28 | 5.3 |

Being in the spec nearly **halves** the missing-detail count. Four of the six ranked details above
are OpenAPI-only fields, so extending the spec is the single highest-leverage action — not
editing 44 inventory rows.

### Worked example — the two extremes

| | **Best: `GET /user/leaves/getallleavereports`** | **Worst: `PUT /api/attendance/holiday-templates/update/{id}`** |
|---|---|---|
| Asserts | **22** / ceiling 24 | **11** / ceiling 19 |
| Missing details | 3 | 6 |
| Out of scope | 4 | 9 |
| Runtime-blocked | 0 | 1 |
| `documented_status_codes` | `openapi` | **`none`** |
| `documented_content_types` | `openapi` | `inventory` |
| `idempotent` | `openapi` | `inventory` (inferred — rejected by check 18) |
| `sla_ms` | `openapi` | `default` (injected) |
| `paginated` | `none` | `none` |
| To fix | add `Example Request Payload`, `x-paginated` | add an OpenAPI entry: status codes, content type, `x-idempotent`, `x-paginated`, plus `Example Request Payload` |

The difference between the two is almost entirely **provenance**: the best endpoint resolves five
of seven fields from `openapi`; the worst resolves none from it.

### Universal prerequisites — required by every endpoint, for every check

These gate `_require_runnable`, which every one of the 28 checks calls first:

| Prerequisite | Source | Absent ⇒ |
|---|---|---|
| Inventory row (`method` + `path` resolvable) | `build/API_File.json` | `NOT_APPLICABLE` on all 28 |
| Resolvable `Base URL` (no unexpanded `{{…}}`) | inventory + env | `NOT_APPLICABLE`; also disables host bucketing |
| `credentialAlias` registered as `CRED_<ALIAS>_EMP_CODE` / `_EMP_PASSWORD` | `.env` | `SKIPPED_NO_TOKEN` on all 28 — never `FAIL` |
| `authProviderApiId` bound in the manifest | run manifest | as above |

Per-endpoint detail for all 44 is in `14-per-endpoint-prereq.csv` (one row per endpoint) and
`14-per-endpoint-prereq.json` (adds the per-check verdict for every endpoint).

---

## 5. Defects

| ID | Sev | Finding | Evidence | Remediation |
|---|---|---|---|---|
| **D-1** | High | `HOST_LEVEL_TESTS` names 5 checks but only 06 and 07 call `_require_host_representative`. Checks 20/21/22 are flagged `hostLevel` yet dedup **0 of 44**. **44 of the run's 54 FAILs are one gateway misconfiguration counted 44×** (`test_no_server_version_disclosure`). | 06/07 → `referencesHostResult` 40/44; 20/21/22 → 0/44 | Add `_require_host_representative` to 20/21/22, or dedup on `measuredBy` before counting. Expect FAIL to drop 54 → ~11. |
| **D-4** | High | `build/API_File.json` carries **0** `attendanceBaseUrl`; `api-endpoints/` (declared source of truth) carries it in **36 files**. The derived artifact reverted its source. | `cf7cb32`: build 37 / yaml 36 (in sync) → `5622af5`: build **0** / yaml 36 → HEAD unchanged | Regenerate `build/` from `api-endpoints/`, and add a CI check that the derived artifact matches its source. |
| **D-6** | High | `resolve_applicability()` predicts only **15 of 28** checks. Checks 13–19 and 23–28 were added without wiring in. The console shows PLANNED for 13 checks it cannot predict; e.g. check 19 is advertised PLANNED and is `NOT_APPLICABLE` 44/44. | 572 of 1,276 pairs classify as UNPREDICTED | Extend `resolve_applicability` to the 13 unwired checks. Does not breach the PLANNED→NA invariant, so this is a coverage defect, not a correctness one. |
| **D-2** | Med | `referencesHostResult` is derived by sniffing the literal prose `"is reported against"` (`conftest.py:137`) — one producer, one consumer, no marker token. Rewording `_support.py:700` silently zeroes `referencedHostResults`. | The codebase already has the right pattern: `PROVIDER_MARKER = [^\]]+` | Emit a bracket marker (`[hostref=…]`) as every other signal does. |
| **D-5** | Med | No test anywhere asserts run **cardinality**. A regression skipping globals for some endpoints would pass the entire suite. | Closed here for both engine and simulator; not guarded in-repo | Add `results per api == CHECK_COUNT` to `test-unified-console.js` and a pytest equivalent. |
| **D-7** | Med | `FIELD_MARKER = \[field=([A-Za-z0-9_.]+)\]` rejects spaces, silently discarding `field="Base URL"` (13), `field="HTTP Method"` and `field="Request Body"` (17). | Check 17: **22 NOT_APPLICABLE rows, all with `missingField: null`**. Control: check 14's single-word `field="Access"` survives on 4 rows. Repo-wide only **62.5%** of NA rows are actionable. | Widen to `[^\]]+`, matching its sibling `PROVIDER_MARKER`. |
| **D-3** | Low | Five stale counts. Actual is 28. | `build_unified_console.py:54` (12), `catalogue.py:235` (twelve), `platform-ui/README.md:135,138,170` (22), `test-dom.js:77` (12), `_registry.py:1` (22), `test-cases/README.md:8` (22) | Text-only. Note `test-dom.js:77` is a `>= 12` floor that would pass even if the tier collapsed to 12. |

**Bonus observation (Low).** 26 of 28 module docstrings omit `SKIPPED_NO_TOKEN` from their
`Emits:` line although the 2-arg `_require_runnable` makes it reachable. It never fired in this
baseline because auth succeeded, so it is latent documentation drift, not a live bug.

---

## 6. Limitations

1. **No live request was issued.** Every empirical number is one observation of one environment
   on one date, from a committed baseline.
2. **Host bucketing is simulated** from the console builder's host table — all 44 `Base URL`
   values are unresolved templates offline.
3. **Only the simulator supports a true alone-vs-batch experiment.** The live twin would span
   two runs separated in time and cannot separate contamination from drift, so it is not claimed.
4. **Timing-sensitive checks** (04 SLA, 06 burst) have unstable rates by nature; theirs are not
   presented as stable.
5. **All non-REST verdicts are predictions.** Zero non-REST endpoints exist to test against.
6. **`emitsDrift` is a docstring audit, not a reachability proof** — states reachable only via
   exception paths may be missed.

## 7. Reproducing this

Analysis scripts were written to a scratchpad, not the repo, and are read-only. They import
neither `_support.py` (which pulls `httpx`/`pytest`) nor `build_catalogue()`. Artifacts:
`01-check-spec.json`, `02-static-applicability.json`, `03-empirical.json`,
`04-disagreements.csv`, `05-orchestration.md`, `06-nonrest.json`, `07-prereq-matrix.csv`,
`08-ui-proof.md`, `10-defect-evidence.txt`, `99-gtc-master.json`.

This report and the published matrix are the only files added to the repo.

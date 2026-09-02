# Handover — open items recorded, not fixed

Raised during the authoring-surface work order. Each was deliberately left alone
under Rule 3 (do not fix unrelated things). Ordered by consequence.

## 1. CI runs no global-contract tier — RECOMMENDED AS A STANDALONE WORK ORDER

`pytest tests/global_contract` appears nowhere in `.github/workflows/api-tests.yml`
or the `Jenkinsfile`. CI runs only the generated tier (`build/auto_generated`).

The global-contract tier is the one that produces all 953 results, all 22 checks per
endpoint, the seven-state model and the entire pass-rate figure. **None of it is
verified by CI.** Every number quoted in any report in this repo comes from a local
run against live UAT.

Two concrete consequences already observed during this work:

- Phase 3 nearly gitignored a package that `tests/global_contract/auth_bootstrap.py`
  imports at module level. CI would have stayed green throughout, because CI never
  imports that module.
- The suite's own correctness commits (`60cd25f`, `abe15bf`, `f1fd014`, `2a3767e`,
  `33ecada`) all changed global-contract behaviour, and CI could not have caught a
  regression in any of them.

**Recommendation: a standalone work order after Phase 4.** It is not a one-line
addition — the tier needs live UAT credentials, a run manifest, and a decision about
whether a `FAIL` should break the build given the suite currently reports 122 of
them. Folding that into a restructure phase would conflate two unrelated risks.

## 2. The suite is not deterministic against live UAT

Two distinct sources of run-to-run movement were observed:

- **Latency.** `test_response_time_within_sla` reads bootstrap timings and emits
  `WARN` past an advisory threshold (`DEFAULT_SLA_MS = 700`, overridden to 1000 and
  3000 for two operations). One run showed 6 `PASS -> WARN` purely from a latency
  spike; two immediate re-runs of identical code returned the baseline.
- **Reachability.** One run showed `PASS 408 -> 291` with `NOT_APPLICABLE +122`. The
  reasons named it: 64 results on `uat-mcdp-be.omfysgroup.com` and 52 on
  `uatmcdphcmplatform.omfysgroup.com` recorded `ConnectTimeout`, plus 12
  `getaddrinfo failed`. The seven-state model handled it correctly — unreachable work
  became `NOT_APPLICABLE` with a named reason rather than a false pass, which is
  exactly what `60cd25f` built.

**Consequence for any phase gate:** a single-run comparison can fail for reasons
unrelated to the change under test. The two failure modes are distinguishable by
shape — latency touches only `test_response_time_within_sla` and moves PASS/WARN;
unreachability takes whole hosts at once, names `ConnectTimeout` in the reason
string, and moves `NOT_APPLICABLE` and `FAIL`, which are hard-gate fields.

**Gate rule in force from the tree amendment onward:**

- `unreachableResults > 0` — the run is **void**. Discard it and re-run. Do not
  compute a delta; a void run says nothing about the change under test.
- PASS/WARN movement clears only if every moved result is
  `test_response_time_within_sla`, confirmed by two consecutive matching re-runs.
- Movement in `FAIL`, `SKIPPED_NO_TOKEN`, `NOT_APPLICABLE`, `NOT_ASSERTED`,
  `INFORMATIONAL` or `total` on a non-void run is a defect.

## 3. Two descriptions of the same inventory

`scripts/generate-api-file.js` still derives `api-docs/API_File.json` from the Postman
collections. Since Phase 3, `api-endpoints/*.yaml` is the source of truth and
`build/API_File.json` is derived from it. The two now describe the same 45 rows by
different routes and are currently identical, but nothing enforces that.

Reconciling or retiring the Node generator is a follow-on decision. Until then,
`api-docs/API_File.json` is a cross-check, not an input: nothing in the test tiers
reads it.

## 4. Ref reminting is contract-visible and still open

`attenedance-july2026` (misspelled, date-stamped) appears in 7 canonical refs, and
`Holiday Template APIs Copy` carries a Postman export artifact in 6 more. Module
aliases fix the **slugs**; the refs are untouched by design.

Reminting them would change strings the harness, run manifest and result document all
key on. Recorded as open, unactioned.

## 5. Documentation drift

- `TECH_STACK.txt` says "45 API endpoints". That is the **row count**. It is 45 rows,
  41 endpoints, 39 distinct `method + path`.
- `KT_Report_and_Current_status.txt` is 72+ commits stale and has already produced
  several false "open item" claims. Work order section 8 says regenerate, not patch.

## 6. Baseline superseded, and a manifest that does not reject unknown refs

`baseline/33ecada-run.json` (45 refs) is superseded by `baseline/44-endpoint-run.json`
after the bruno `auth` duplicate was removed. Diff future phases against the 44-ref
baseline; the 45-ref one is kept only as the pre-removal record.

Observed while re-cutting it: a manifest naming a ref the catalogue no longer knows is
**not rejected**. The run completed and produced NOT_APPLICABLE results for the unknown
ref, inflating `total` to 955. That is arguably the right graceful behaviour, but it
means a stale manifest fails quietly rather than loudly.

### Proposed: `unknownRefs[]` in `schema-result.json` (NOT actioned)

Add a top-level `unknownRefs[]` to the result document listing every manifest ref the
catalogue does not know. Semantics:

- Unknown refs are **excluded from `total` and from all seven state counts.** They
  produced no measurement, so counting them restates the failure the seven-state model
  exists to prevent -- a result that reads as measured when nothing was.
- The **exit code is unaffected.** A stale ref is a caller-side mistake, not a contract
  failure of the APIs under test, and failing the run would make every endpoint
  removal look like a regression.
- The list makes the condition legible without parsing prose out of a reason string,
  which is the same argument that gave `unreachableResults` its own field in `60cd25f`.

Contract-visible, so it needs the platform team's agreement before implementation.

## 7. Follow-up decision list: things retained without a live consumer

Grouped because they want one decision, not four:

| Item | State |
|---|---|
| `scripts/postman-cli-run.sh` | never invoked; its CI key injection was removed in Phase 1 |
| `bruno/` | not run by CI or any npm script; `bruno/auth/login.bru` is the source of the endpoint removed as a duplicate, and `bruno/unverified-endpoints/` is deliberately quarantined |

Both are "retained artifacts with no live consumer". Retiring either is a product call,
not a redundancy cleanup, and neither is blocking.

### `bruno/auth/login.bru` specifically

The endpoint was removed from the authoring surface, not from Bruno. Nothing runs
Bruno in CI or npm scripts, and `scripts/generate-api-file.js` would still list it in
the now non-authoritative `api-docs/API_File.json`. Deleting the `.bru` is a separate
call; the KT report claims it is intentionally retained, though that document is 70+
commits stale and its `BASE_URL` rationale survives regardless, since the quarantined
profile-investigation request also uses `{{baseUrl}}`.

## 8. `ALLOWED_ORIGINS` is pinned to port 8765

`harness/service.py:59` builds `ALLOWED_ORIGINS` from the module-level `PORT`, but
`harness/serve.py` accepts `--port`. Start the harness anywhere else and its CORS
allowlist no longer matches its own address, so a browser-served console on that port
would have its fetches blocked. Server-to-server checks are unaffected, which is why
`scripts/verify-harness-ui.py` runs green on an ephemeral port. Found during Phase 4;
recorded, not fixed.

## 9. The attendance endpoints are pointed at a WAF-blocked host

**Evidence, unauthenticated GET to `/api/attendance/holiday-templates/getAll`:**

| Host | Response |
|---|---|
| `uat-mcdp-be.omfysgroup.com` (**in use**) | `403`, 0 bytes, no content-type - gateway block |
| `uatmcdphcmplatform.omfysgroup.com` | `401` `application/json` `{"errorCode":"INVALID_TOKEN"}` |
| `devmcdphcmplatform.omfysgroup.com` | `401` `application/json` - same |

The second and third are the application answering. The first never reaches it.

All 31 attendance cases use `basePath: {{baseURL}}` -> `uat-mcdp-be`. Meanwhile
`ATTENDANCE_BASE_URL=https://uatmcdphcmplatform.omfysgroup.com` is defined in `.env`,
in `environments/uat.json`, in CI (line 126, as a *third* spelling
`uat_mcdp_hcm.omfysgroup.com`), and read by `scripts/run-newman.js:296` - but **no
endpoint uses it**. `7620b4b` claimed to point every collection at the host that
serves it; attendance appears to have been missed.

**This plausibly accounts for a large share of the 120 baseline failures**, since 31
of 44 cases sit on that host. Nearly every failure on them has one root cause rather
than many: `401_without_valid_token` seeing 403, `no_credential_leakage_in_response`
and `error_response_is_machine_readable` seeing "non-JSON content for HTTP 403" (the
empty WAF body), `response_matches_full_schema` NOT_ASSERTED because no success
response is ever observed, and `small_burst_...` naming the WAF fingerprint outright.

Genuinely independent of it: `no_server_version_disclosure` - `nginx/1.18.0 (Ubuntu)`
really is advertised, on both hosts.

Changing `basePath` would move the baseline substantially, so it is recorded, not
actioned. Verify with a tokened request against `uatmcdphcmplatform` first.

## 10. Path parameter values belong in runtime config, never in the YAML

`{holidayTemplateId}` is resolved by `_resolve_path_parameters` from the runtime
config via `_canonical_env_key` -> `HOLIDAY_TEMPLATE_ID`. Hardcoding the value into
`endpointPath` in `api-endpoints/*.yaml` instead breaks three things at once:

1. the round-trip test fails - `Endpoint / Path` no longer matches the inventory;
2. the slug changes (`..._delete_by_holidaytemplateid` -> `..._delete_134`), so the
   filename and the frozen `refToSlug` value both stop matching;
3. it is inert until `generate-generic-tests.py` re-runs, because the engine reads
   `build/API_File.json`, not the YAML.

The manifest cannot carry one either: `_ENTRY_FIELDS` admits only `ref`,
`definition`, `credentialAlias` and `authProviderApiId`, and unknown fields are
rejected outright. Runtime config is the only supported channel.

## 11. DEFECT FOUND: policy status toggle returns 500 for a missing entity

`PATCH /api/attendancepolicy/{id}/status` answers **HTTP 500** when the policy
does not exist. The handler has already detected the absence -- the body reads
`"Failed to toggle policy status: Attendance policy not found with ID: 999999"`
-- and then maps it to a server error instead of `404`.

Reproduced directly with a valid Login Auth UAT token, on both a non-existent id
(999999) and an existing one (4). Any client retry policy that treats 5xx as
transient will retry this forever.

Found by `test_unknown_entity_mutation_returns_404`, ported from the attendance
repo's `TC-GLOB-14`. Their matrix records 404 across all six masters for `PUT`;
this is `PATCH` on the `/status` sub-route, which their suite did not probe.

## 12. Two attendance families accept neither available token

Measured directly, same request, both issuers:

| Family | Employee Auth | Login Auth UAT |
|---|---|---|
| `holiday-templates` | 401 | **200** |
| `status-threshold` | 401 | **200** |
| `attendancepolicy` | 401 | **200** |
| `v1/attendance/shift/master` | 401 | 404 (reached the handler) |
| `late-early-policies` | 401 | **401** |
| `week-offs` | 401 | **401** |

Employee Auth is rejected across the board, which is why the run manifest now
assigns Login Auth UAT to attendance. But `late-early-policies` and `week-offs`
refuse that token too, with `INVALID_TOKEN`. Either they need a third issuer we
do not have, or the account behind Login Auth UAT lacks a role for them.

Until that is resolved those two families cannot be exercised at all, and the
imported probes on them correctly report NOT_ASSERTED rather than a verdict.
That is 12 of the 44 endpoints.

## 13. Junk record created on UAT during this work

`POST /api/attendancepolicy` was called once while diagnosing the auth split and
succeeded, creating **policyId 28, policyName "zz"**. It should be deleted. The
imported probes create nothing while they report NOT_ASSERTED, but any that
start passing through to a real handler can create records by design -- that is
how "invalid input is stored" is observed.

## 14. Smaller items

- `.env` still carries `USERNAME` and `PASSWORD` with no consumer in current code.
  Untracked, so out of scope for a tracked-file cleanup.
- `scripts/postman-cli-run.sh` is never invoked. Its CI key injection was removed in
  Phase 1; retiring the script itself is a product decision.
- `attendance-management/API_Documentation_Template.xlsx` is quarantined on purpose
  (`excel_adapter.py:19` — "must not be read from"). Kept deliberately.
- `scripts/project-audit.js` is named in `.gitignore` but does not exist.

## 15. Every host discloses its nginx build -- OPS ACTION REQUIRED

`Server: nginx/1.18.0 (Ubuntu)` is returned by all four origins, to any client,
on any path, with or without credentials. `test_no_server_version_disclosure`
fails on it 44 times, which is 4 real findings fanned out by host-level
attribution -- not 44 defects.

It is **not** a UI-specific failure, though it was reported as one. The CLI
baselines already carry it (43 and 44 FAIL) and a plain `curl` reproduces it.

The fix is `server_tokens off;` in the `http` block of each host's nginx.conf.
That is infrastructure this repository does not contain, so it cannot be
committed here -- only verified from here:

    python scripts/regression/verify-response-header-hygiene.py

Full analysis, the nginx config, UI-path verification steps and the hardening
list: `docs/rca/RCA-001-server-version-disclosure.md`.

**When ops applies the fix**, delete `continue-on-error: true` from the *Check
response header hygiene* step in `.github/workflows/api-tests.yml`. It reports
rather than blocks today only because every host currently fails it.

Related and still open: no host sends `Strict-Transport-Security`.

## 16. The TLS pin now guards a host that no longer exists

`scripts/pinned-tls-agent.js` and `scripts/pinned_tls.py` pin
`dev_mcdp_be.omfysgroup.com`. That host stopped resolving, and the estate moved
to `uat-mcdp-be`, which has no underscore -- so ordinary RFC 6125 hostname
validation applies to it and the pin has nothing left to do.

Both call sites gate on the resolved hostname matching `PINNED_HOST`, so with
`AUTH_BASE_URL` set the pin is simply skipped and standard TLS is used. Nothing
is weakened. But two things still point at the dead host:

- `tests/security/test_pinned_tls_pin.py::test_live_request_succeeds_through_current_certificate_pin`
  makes a live call to it and fails on DNS. It is the one failure in that suite.
- `README.md` and `KT_Report_and_Current_status.txt` still document
  `dev_mcdp_be` as the active auth target, including the rationale for pinning it.

The decision is whether to retire the pinning module or re-point it. Retiring it
is the honest reading -- it exists solely to work around an underscore in a
hostname that is no longer used -- but it is a security-relevant change and the
certificate fingerprint for any replacement host would have to be captured
first. Recorded rather than actioned.

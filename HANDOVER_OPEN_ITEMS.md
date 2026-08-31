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
means a stale manifest fails quietly rather than loudly. Worth a decision.

## 7. `bruno/auth/login.bru` still exists

The endpoint was removed from the authoring surface, not from Bruno. Nothing runs
Bruno in CI or npm scripts, and `scripts/generate-api-file.js` would still list it in
the now non-authoritative `api-docs/API_File.json`. Deleting the `.bru` is a separate
call; the KT report claims it is intentionally retained, though that document is 70+
commits stale and its `BASE_URL` rationale survives regardless, since the quarantined
profile-investigation request also uses `{{baseUrl}}`.

## 8. Smaller items

- `.env` still carries `USERNAME` and `PASSWORD` with no consumer in current code.
  Untracked, so out of scope for a tracked-file cleanup.
- `scripts/postman-cli-run.sh` is never invoked. Its CI key injection was removed in
  Phase 1; retiring the script itself is a product decision.
- `attendance-management/API_Documentation_Template.xlsx` is quarantined on purpose
  (`excel_adapter.py:19` — "must not be read from"). Kept deliberately.
- `scripts/project-audit.js` is named in `.gitignore` but does not exist.

# baseline/ — the reference every later phase is diffed against

`33ecada-run.json` is a full 45-endpoint global-contract run against live UAT,
captured before any restructuring work. Phases 1–4 must reproduce its seven state
counts exactly; any delta is a defect in the phase that introduced it.

`33ecada-manifest.json` is the manifest that produced it, committed so the baseline
is reproducible rather than merely recorded. Reproduce with:

    python -m tests.global_contract.run baseline/33ecada-manifest.json --out /tmp/check.json

The manifest is `full.json`'s 45 APIs with one field added: `authProviderApiId`,
set to the Employee Auth `tc01` provider for all 44 non-provider entries. `full.json`
omits that field entirely, which forces every credential-needing check to
`SKIPPED_NO_TOKEN` and makes it useless as a baseline. One provider for the whole run
matches what the harness UI does — its dropdown selects a single provider per run.

Credential aliases only. No raw credential value appears in either file.

---

## Two baselines are committed, deliberately

| File | Refs | total | Status |
|---|---:|---:|---|
| `33ecada-run.json` + `33ecada-manifest.json` | 45 | 953 | **superseded** — pre-removal record |
| `44-endpoint-run.json` + `44-endpoint-manifest.json` | 44 | 932 | **current** — diff against this |

### Why they differ

The bruno `auth` entry was removed as a verified duplicate. It and
`Login Auth UAT API` both resolved `{{baseUrl}}/auth/token` to
`https://uat-mcdp-be.omfysgroup.com/auth/token` with the same
`{empCode, password}` schema; the Newman one is data-driven, declares
`Content-Type`, and carries a full response example, so nothing was lost.
(`Employee Auth API` is **not** a duplicate — it uses `{{authBaseUrl}}`, a
different host, and stays.)

`total` 953 → 932 is one endpoint's 22 checks less one host-representative
dedup. Every count moved because the contract changed, so this is a **re-cut
baseline, not a regression**. The 44-ref baseline was confirmed stable across
two consecutive re-runs with `unreachableResults: 0`.

The 45-ref pair is kept so the pre-removal numbers stay reproducible. Do not
diff new work against it.

### Gate rules in force

- `unreachableResults > 0` — the run is **void**. Discard, re-run, compute no
  delta.
- Zero delta required on `FAIL`, `SKIPPED_NO_TOKEN`, `NOT_APPLICABLE`,
  `NOT_ASSERTED`, `INFORMATIONAL`, `total`.
- PASS/WARN movement is a defect **unless** every moved result is
  `test_response_time_within_sla`, cleared by two consecutive matching re-runs.

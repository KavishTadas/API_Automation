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

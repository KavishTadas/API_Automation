# Unified console — UI mock

A single self-contained page that merges the two standalone mock artifacts
(`hcm-platform-console.html` and `enterprise-dashboard.html`, preserved in
`docs/ui-mock-source/`) into one console + analytics view.

**This is a UI mock, not the platform plugin.** No engine is attached. The
platform team still builds against `docs/platform-handoff/`. What this page is
for is settling the *shape* of the UI — what a QA engineer selects, what they
see afterwards, and how the seven result states read on screen — before anyone
writes Java against it.

## Build and test

```bash
python scripts/build_unified_console.py     # -> unified-console.html
node docs/platform-ui/test-unified-console.js
```

The build inlines the real catalogue; the test replays the shipped result
documents through the page's own arithmetic and fails if they diverge.
Open `unified-console.html` directly in a browser — `file://` is enough,
there is no server and no network call.

## Why it is generated rather than hand-written

`unified-console.html` is **generated output — do not hand-edit it.** Edit
`unified-console.template.html` and rebuild.

Every API row, state name, host, credential alias and denominator rule is read
out of `docs/platform-handoff/sample-catalogue.json` at build time. The two
source mocks were hand-typed against a stale checkout and drifted badly: they
invented a Payroll module, `API-001`-style identifiers, a 400ms SLA, a
`Staging-US-East` environment, and a binary pass/fail donut. Generating the
page removes the class of defect rather than the instances.

## What the mock gets right that the sources did not

| | Source mocks | This page |
|---|---|---|
| APIs | 8 invented | 45, from the catalogue |
| Modules | included a Payroll module that does not exist | the real four |
| Attendance host | `uat_mcdp_hcm…` — the **resolved misroute** | `uatmcdphcmplatform…` — verified working |
| Credential aliases | 3, one invented | `ATTENDANCE_SVC_UAT_01`, `LEAVE_SVC_UAT_01` |
| Result states | 2 (pass/fail) | 7, plus `PLANNED` pre-run |
| Pass rate | `passed / total executed` | `PASS / (PASS + FAIL)`, **null** when the denominator is zero |
| SLA | 400ms / 1000ms, rendered as failure | 700ms advisory, emits `WARN` |
| Dependencies | Tailwind + Chart.js + Lucide from three CDNs | none — inline CSS and hand-rolled SVG |

## Invariants the page holds

Enforced in code and asserted by `test-unified-console.js` (22 checks):

- Pass rate is `PASS / (PASS + FAIL)`, reported as `n/a` — never `0%` — when
  nothing asserted.
- `clean` is blocked by exactly `FAIL`, `WARN`, `SKIPPED_NO_TOKEN`.
  `NOT_APPLICABLE`, `NOT_ASSERTED` and `INFORMATIONAL` are counted and shown but
  never block. A run can read **100% pass and not clean**, so the two are always
  displayed together.
- A result that references another API's host measurement is tallied in
  `referencedHostResults` and excluded from `total` and `counts`.
- Host-level probes are measured once per host, and ownership is resolved per
  *(host, check)* — if the first API on a host is pre-empted for that check, the
  probe falls through to the next eligible one rather than leaving the host
  unmeasured.
- An unregistered credential alias yields `SKIPPED_NO_TOKEN`, never `FAIL`, and
  degrades the run to `COMPLETED_WITH_ERRORS` (K1b).
- An unasserted request is `NOT_ASSERTED` and never renders as a pass (D7).
- SLA breaches emit `WARN` and never `FAIL` (D11).
- `ref` is an opaque join key and is never rendered as a label — every row shows
  method, path and module. The ref appears once, explicitly marked as a key.
- No credential value reaches the browser. Runs carry the alias only; imported
  cURL commands have any `Authorization` header stripped.

## Simulated runs

The run button executes a deterministic in-browser simulation seeded on
`(ref, testId)`, so re-rendering never reshuffles a verdict. It emits documents
with exactly the real result-contract shape. To make it live, replace the body
of `runBatch()` with a `POST` to the harness's `/run` and keep the rest.

Selection, persona, theme and the last result persist in `localStorage`, and a
`BroadcastChannel` mirrors results to a second tab — run in one, watch in
another.

## Known gaps

- `INFORMATIONAL` is reachable only on the API that carries a host-level payload
  probe, so most small selections will not show it.
- Applicability predictions come from the sample catalogue. Regenerate it
  (`python -m tests.global_contract.catalogue`) and rebuild to refresh them.
- `docs/platform-handoff/sample-result-single-api.json` has a **run-level summary
  that does not describe its own contents** (declares `total: 61` and
  `referencedHostResults: 4`; the document holds 13 results and zero
  referencing ones). Its per-API summary is self-consistent. The conformance
  test skips that one comparison and says so rather than passing quietly.

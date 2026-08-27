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
npm run ui:build      # python scripts/build_unified_console.py -> unified-console.html
npm run ui:test       # invariants + DOM + export + OOXML + history/share
npm run ui:serve      # http://127.0.0.1:8910/unified-console.html
```

The page is fully self-contained, so `npm run ui:serve` is a convenience, not a
requirement — opening `unified-console.html` from disk behaves identically.

`ui:test` needs `jsdom` (`npm i`). The first suite replays the shipped result
documents through the page's own arithmetic and fails if they diverge; the
second loads the built page in a real DOM and drives it — select, run, View
Report, every report tab, theme toggle, navigator, persistence.


## Screens

Three views, matching the flow the source mocks laid out:

1. **Home** — status strip, quick-run multi-select, search, and a grid of suite
   cards (one per module) listing every endpoint. Clicking an endpoint opens it.
2. **Detail** — `Configure Run` on the left (API, method, module, endpoint,
   credential alias, auth provider, read-only payload) and `Test Cases for this
   Endpoint` on the right, each carrying its own state chip. `View Report`
   opens the report for that API.
3. **Report** — the enterprise dashboard: KPI cards, state donut, per-module
   stacked bars, defect triage with Jira ticket generation, BDD behaviours,
   timeline, payload inspection, SLA percentiles, contract compliance, raw JSON.

Finishing a run moves to the Report automatically. `View Report` is disabled
until a run exists, so it can never open an empty or stale dashboard.

The **auth provider** selector is on the Detail screen because Attendance
requires `Login_Auth_UAT_API` — a token minted by Employee Auth is rejected with
`INVALID_TOKEN`. It travels in the manifest per API (K1c); the engine persists
nothing.

## Export

Every export downloads a real file; nothing goes to the clipboard.

| Format | What it is |
|---|---|
| `.xlsx` | Six sheets — `Run_Summary`, `API_Overview`, `Test_Results`, `Defects`, `Assertion_Gaps`, `Contract_Rules`. Styled header row, frozen panes, autofilter, sized columns, and state cells filled by verdict. Column layout follows `api-docs/API_Documentation_Template.xlsx`, including its `inlineStr` convention. |
| `.docx` | A circulatable report: title, quality gate, summary, endpoint table, defects, assertion gaps, contract rules, full result matrix. Repeating table headers and shaded state cells. |
| `.txt` | Fixed-width, for a terminal or an email body. |
| `.csv` | The result matrix only, BOM-led so Excel reads UTF-8. |
| `.json` | The raw result document, exactly as the engine emits it. |

**Both OOXML formats are built in the page.** There is no library here, so
`zipStore()` writes a ZIP with stored (uncompressed) entries — larger than a
deflated archive, but a valid package that Excel and Word open without a repair
prompt. `test-export.js` captures the bytes and `check-export.py` opens them and
checks the required parts, the tab names, the frozen panes, the autofilter and
the style fills. `openpyxl` reads the workbook without warnings.

Because entries are stored, the XML inside is readable in the raw bytes — the
credential-leak assertion greps the whole archive, not just the text export.

## Report history

Every finished run archives itself into `localStorage['HCM_RUN_SNAPSHOTS']` —
the whole result document, not a summary — keeping the most recent 8. Snapshots
are large, so a write that exceeds quota evicts the oldest entry and retries
rather than failing the run.

**Report History** (masthead clock icon, or the sidebar) lists every archived
run newest-first with its gate, pass rate, totals, duration and timestamp.
Opening one restores that exact run: KPI cards, gate banner, charts, matrix,
defects and persona filtering all re-render from it. A banner marks the report
as archived and offers a way back to the latest.

`STATE.history` remains a separate lightweight list — it only feeds the trend
chart, and it carries the sample points, which are never archived.

## Share — standalone HTML

**Share** downloads the whole report as one self-contained file, named
`HCM-API-Report-<runId>-<date>.html`. Open it by double-clicking, or send it as
an email attachment: it renders the full interactive dashboard with no server,
no network and no browser storage.

It works by capturing `PRISTINE` — the document exactly as parsed, before any
rendering — and re-emitting it with the run embedded in `<head>`. The shared
file is therefore byte-for-byte this page plus its data, with no second
template to drift out of step. On boot it detects the payload, loads it, and
replaces `persist()` with a no-op so nothing is read from or written to the
viewer's browser.

> **A trap worth knowing.** `PRISTINE` contains this code's own source, so any
> literal marker written in `buildStandalone` — *including in a comment* — also
> appears in the haystack it searches. The first version spelled the tag out in
> the strip-regex and deleted itself out of the file it was building. The fix
> then spelled it out again in the comment explaining the fix, which truncated
> the file from that line on. Markers are now assembled at run time from
> `SNAP_ID` and `LT`, and nothing in that function — prose included — may
> contain the tag it looks for.

`test-history.js` opens the produced file in a fresh DOM with `localStorage`
denied outright, and asserts the masthead, KPI cards, donut, module bars, gate,
every tab, persona filtering and the theme toggle all work from the embedded
payload alone.

## Global checks — 22

Ten cross-cutting checks were added to `tests/global_contract/`, taking the
tier from 12 to 22. They are real pytest functions in the engine, not UI-only
entries: `catalogue.py` discovers checks by AST-parsing the test module, so
adding a `def test_*` with an `@allure.title` registers it everywhere.

| Check | Category | Gated on |
|---|---|---|
| Transport is HTTPS | security | resolved base URL — metadata only, issues no request |
| Private endpoint refuses an anonymous caller | security | `Access == private` (40/45) |
| Error responses are machine readable | schema | a provokable 4xx; same path-variable guard as the 404 check |
| Error responses hide internal detail | security | as above |
| Write endpoints refuse an unsupported media type | schema | POST/PUT/PATCH with a documented body (24/45) |
| Declared idempotency matches the method | functional | `idempotent` metadata — declaration only |
| Paginated list declares its page metadata | schema | `paginated` metadata |
| Host sets the baseline security headers | security | **host-level** |
| Host discloses no product version | security | **host-level** |
| Host refuses TRACE | security | **host-level** |

Host-level checks are measured once per host and referenced from the other
APIs on it, so a 45-API batch across 3 hosts issues 3 TRACE requests, not 45.

**Nothing here assumes a field the inventory does not carry.** Each check is
gated on data this repo actually holds — the declared method, the `Access`
column, `Request Parameters`, `Request Body`, or the resolved host — and
reports `NOT_APPLICABLE` naming the field when it is absent, exactly as the
original twelve do.

**Safety.** No check sends a destructive method the endpoint did not declare.
TRACE is the one undeclared method sent, and is safe by construction: it
echoes, it mutates nothing, and the check exists because it should be refused.
Idempotency is checked as a *declaration* rather than by repeating a write,
which would mutate a real environment twice.

**What is verified, and what is not.** All 22 collect under pytest (46
parametrised cases) and the tier emits a well-formed result document with
every result inside the seven states. The new assertions have **not** been
exercised against a live endpoint from this clone — there is no `.env` here,
so every case reports `NOT_APPLICABLE` and nothing executes. Running them for
real needs registered base URLs and credentials.

## Theme

A labelled switch in the top bar toggles light/dark, with the sun/moon pair
showing which is active. It is a real `role="switch"` with `aria-checked` and
keyboard support, and it persists. Charts read their colours from CSS custom
properties at draw time, so a flip redraws them rather than leaving stale fills.
With no explicit choice the page follows `prefers-color-scheme`.

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

Enforced in code and asserted by `test-unified-console.js` (22 checks) and
`test-dom.js` (229 checks against the built page), plus `test-export.js` and
`check-export.py` for the exported files:

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

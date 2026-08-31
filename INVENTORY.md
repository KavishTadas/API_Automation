# INVENTORY — Phase 0 file classification

**Base commit:** `33ecada` (main), executed on branch `refactor/authoring-surface`
**Produced:** 31 August 2026
**Scope:** all 230 git-tracked files. Untracked and ignored paths (`node_modules/`,
`.venv/`, `reports/`) are out of scope.

Nothing in this phase was deleted, moved, or edited. This document classifies only.

## Classification rules

| Bucket | Definition |
|---|---|
| `generated` | Reproducible by running a committed script. Safe to delete iff regeneration reproduces it. |
| `authored` | Written by a human, not reproducible. Never auto-written. |
| `config` | Tooling, CI, environment, dependency manifests. |
| `unknown` | No inbound reference found, or provenance unclear. **This bucket is Phase 1's input.** |

Evidence for every classification is a `grep` over tracked files excluding
`node_modules/`, `.git/`, `.venv/`, `__pycache__/`, plus the CI workflow and
`package.json` / `pyproject.toml`.

## Summary

| Bucket | Files |
|---|---:|
| generated | 80 |
| authored | 96 |
| config | 44 |
| unknown | 10 |
| **total** | **230** |

## generated (80)

| Path | Produced by | Evidence |
|---|---|---|
| `tests/auto_generated/test_*.py` (45) | `scripts/generate-generic-tests.py` | CI step "Generate generic pytest tests"; README states the tier is disposable |
| `tests/auto_generated/{__init__,_api_test_helpers,conftest}.py` | same generator | emitted alongside the 45 |
| `api-docs/API_File.json`, `API_File.csv` | `scripts/generate-api-file.js` | CI step "Generate API File" |
| `api-docs/history/**` (25) | `scripts/generate-api-file.js` | timestamped snapshots of the two files above |
| `docs/platform-ui/unified-console.html` | `scripts/build_unified_console.py` | built from `unified-console.template.html` |

Exactly 45 generated test files for 45 catalogue endpoints — **no orphans detected**.
The ~20 renames in the last pull left nothing stale behind.

## authored (96)

Postman collections (9), Bruno requests (7), `openapi/openapi.yaml`, the 13 modules
under `tests/global_contract/`, `tests/security/` (2), `tests/unverified_endpoints/` (2),
`scripts/` (23 minus generated), `harness/` (5), `docs/platform-handoff/` (9),
`docs/platform-ui/` support files, `test-data/` (4), and root documentation
(`README.md`, `SECURITY.md`, `TECH_STACK.txt`, `KT_Report_and_Current_status.txt`).

`docs/platform-ui/unified-console.template.html` is authored; the non-template
sibling is its build output.

## config (44)

`.github/workflows/api-tests.yml`, `Jenkinsfile`, `.devcontainer/`, `.vscode/`,
`.agents/`, `.claude/settings.json`, `environments/` (2), `package.json`,
`package-lock.json`, `pyproject.toml`, `requirements.txt`, `dev-requirements.txt`,
`allure.properties`, `.gitignore`, `.gitattributes`, `.env.example`.

## unknown (10) — Phase 1 input

| # | Path | Finding | Inbound refs |
|---|---|---|---|
| 1 | `full.json` | 6.2 KB run manifest, `runId: "full-audit"`, 45 APIs, added by `2a3767e` (a token-naming commit). Not gitignored. | **zero** |
| 2 | `scratch/fix_tokens.js` | Sole occupant of `scratch/`. | **zero** |
| 3 | `__pycache__/main.cpython-313.pyc` | Tracked despite `__pycache__/` being gitignored. Bytecode for Python 3.13; the venv is 3.14. | n/a |
| 4 | `__pycache__/models.cpython-313.pyc` | as above | n/a |
| 5 | `tests/__pycache__/test_main.cpython-313-pytest-9.0.3.pyc` | as above | n/a |
| 6 | `scripts/diagnose.js` | Listed in `.gitignore` yet tracked. | `.gitignore` only |
| 7 | `scripts/url-check.js` | Listed in `.gitignore` yet tracked. | `.gitignore` only |
| 8 | `attendance-management/~$Attendance_Management_API_Spec.xlsx` | Excel lock file (`~$` prefix) committed by accident. | **zero** |
| 9 | `attendance-management/API_Documentation_Template.xlsx` | **Stale duplicate.** `excel_adapter.py:19` names this copy as carrying the *older* format; the authoritative template is `api-docs/API_Documentation_Template.xlsx` (`excel_adapter.py:55`, `TEMPLATE_PATH`). | referenced only as a counter-example |
| 10 | `scripts/postman-cli-run.sh` | Never invoked by CI or any script. `POSTMAN_API_KEY` is still injected into the workflow (line 127). | `.env.example`, `diagnose.js`, KT report |

Items 3–7 are **tracked-before-ignored**: adding a path to `.gitignore` does not untrack
it. `git rm --cached` is the remedy, and it is a metadata-only change.

## Corrections to the work order's stated hypotheses

The work order (§6, Phase 1) was written without repo access and asked for its
candidates to be verified. Three do not survive contact:

1. **`attendance-management/` is NOT unreferenced.** `scripts/build_attendance_excel.py`
   (lines 16–17) writes its collection path into generated rows, and it carries its own
   README. It cannot be deleted wholesale. Only two files inside it are genuinely
   redundant — the Excel lock file and the stale template duplicate.
2. **CI secrets `USERNAME` / `PASSWORD` are already gone.** The workflow injects
   `EMP_PASSWORD` (lines 31, 122) and `POSTMAN_API_KEY` (line 127) only. The KT report's
   claim is stale. Both names do still exist in the local `.env`.
3. **`tests/auto_generated/` has no orphans.** 45 test files for 45 endpoints, exactly.

## Out of scope, recorded per Rule 3

- `.env` (untracked, correctly ignored) still holds `USERNAME` and `PASSWORD` keys with
  no consumer in current code.
- `scripts/project-audit.js` appears in `.gitignore` but does not exist in the tree.

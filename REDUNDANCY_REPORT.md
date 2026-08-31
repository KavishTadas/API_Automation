# REDUNDANCY_REPORT — Phase 1

**Branch:** `refactor/authoring-surface` · **Baseline:** `baseline/33ecada-run.json`
**Verification:** re-ran the full 45-endpoint suite after removal. **Zero delta** in all
seven state counts, `total`, `passRate`, `unreachableResults` and `clean`.

## Removed (7 files, 1 workflow line)

| Path | Evidence | Action |
|---|---|---|
| `full.json` | 6.2 KB run manifest, added by `2a3767e` (a token-naming commit). Zero inbound references in code, CI, `package.json` or `pyproject.toml`. Not gitignored. | deleted |
| `scratch/fix_tokens.js` | One-shot migration that replaced 34 hardcoded expired bearer tokens with `{{authToken}}`. Already ran, in `aee7a1a`. Zero references. | deleted |
| `attendance-management/~$Attendance_Management_API_Spec.xlsx` | Excel lock file — the `~$` prefix is the temp file Excel writes while a workbook is open. Committed by accident. | deleted |
| `__pycache__/main.cpython-313.pyc` | Tracked despite `__pycache__/` being gitignored. Python 3.13 bytecode; the venv runs 3.14, so it cannot even be loaded. | untracked |
| `__pycache__/models.cpython-313.pyc` | as above | untracked |
| `tests/__pycache__/test_main.cpython-313-pytest-9.0.3.pyc` | as above | untracked |
| `scripts/diagnose.js` | Named in `.gitignore` yet tracked. Not invoked by CI, `package.json`, or any script. | untracked |
| `scripts/url-check.js` | as above | untracked |
| `POSTMAN_API_KEY` injection (`.github/workflows/api-tests.yml:127`) | Its only consumer, `scripts/postman-cli-run.sh`, is never invoked by any workflow or script. | removed |

Untracked files remain on disk. `git rm --cached` is metadata-only; `.gitignore`
now actually takes effect for them. `scratch/` is empty and therefore gone.

The **stored** `POSTMAN_API_KEY` secret was deliberately left in place — deleting a
GitHub secret is the owner's action, not this work order's.

## Kept, against the work order's default

| Path | Why it was not removed |
|---|---|
| `attendance-management/API_Documentation_Template.xlsx` | **Deliberately quarantined.** `excel_adapter.py:19-20`: "Only `attendance-management/API_Documentation_Template.xlsx` has the older 14-column shape; that path is quarantined and must not be read from." It is retained on purpose, and the docstring would dangle if it were deleted. Same quarantine policy that keeps `tests/unverified_endpoints/` and `bruno/unverified-endpoints/`. |
| rest of `attendance-management/` | Referenced by `scripts/build_attendance_excel.py:16-17`, which writes its collection path into generated rows, and by its own README. Not unreferenced. |
| `scripts/postman-cli-run.sh` | Retiring it is a product decision, not a redundancy cleanup. The CI injection it justified is gone; the script itself awaits an owner call. |
| `KT_Report_and_Current_status.txt` | Per work order §8 — regenerate, do not patch or delete. Separate work order. |
| `main.py`, `models.py`, `tests/test_main.py` | Documented as an intentional out-of-scope FastAPI sample in `README.md:99` and quarantined. |

## Verification

| | baseline | after Phase 1 | delta |
|---|---:|---:|---:|
| PASS | 408 | 408 | 0 |
| FAIL | 122 | 122 | 0 |
| WARN | 0 | 0 | 0 |
| SKIPPED_NO_TOKEN | 0 | 0 | 0 |
| NOT_APPLICABLE | 381 | 381 | 0 |
| NOT_ASSERTED | 36 | 36 | 0 |
| INFORMATIONAL | 6 | 6 | 0 |
| total / passRate / clean | 953 / 0.7698 / false | 953 / 0.7698 / false | same |

Wall clock moved 24 s → 79 s between the two runs. That is network variance against
live UAT, not a code effect — every state count is identical.

## Recorded, not fixed (Rule 3)

- `.env` still carries `USERNAME` and `PASSWORD` keys with no consumer in current code.
  Untracked, so out of scope for a tracked-file cleanup.
- `scripts/project-audit.js` is named in `.gitignore` but does not exist in the tree.
- The baseline does not reproduce `33ecada`'s commit-message figures (0.7698 vs 0.903).
  See `baseline/README.md`. Not investigated — out of scope for this phase.

# api-endpoints/ — one YAML per endpoint

**41 endpoint definitions.** This is an authoring surface: from Phase 3 these files
are the source of truth and are edited by hand.

## What belongs here

One `<slug>.yaml` per endpoint, plus `module-aliases.yaml`. Nothing else.

## What must never write here

No tool writes into this directory after Phase 2. `scripts/generate-endpoint-yaml.py`
seeded it once from the catalogue and the inventory; from Phase 3 the data flows the
other way and `build/API_File.json` is derived *from* these files. If you find yourself
adding a writer, you are re-creating the problem this split exists to prevent — a
regeneration that destroys hand-authored content.

Generated output lives in `tests/auto_generated/` (and, from Phase 3, `build/`).

## Why 41 files and not 45

The catalogue has 45 rows, but a row is a **test case**, not an endpoint. Three rows
are cases on `POST /auth/token`; two on `GET /user/leaves/getallleavereports`; two on
`POST /api/v1/attendance/shift/master`. Those collapse into one file each, with the
cases listed under `testCases[]`.

"45 endpoints" is the figure quoted in `TECH_STACK.txt` and elsewhere. It is the row
count, not the endpoint count.

## canonicalRef is contract-visible — do not touch it

Every `canonicalRef` is byte-identical to catalogue output, **including misspellings**.
`attenedance-july2026` appears in seven refs and is preserved exactly. The harness, the
run manifest and the result document all key on this string; changing it is a
contract-visible change, recorded as an open decision in `PHASE2_REPORT.md`.

Module aliases in `module-aliases.yaml` affect **slug derivation only** — never refs.

## Adding an endpoint

1. Copy the closest existing file and edit it.
2. Derive the slug with `tests/global_contract/endpoint_slug.py` — never by hand.
3. Run `python scripts/generate-endpoint-yaml.py --check`. It hard-fails on a slug
   collision or on any slug over 85 characters.
4. If it fails on length, add a `module-aliases.yaml` entry. **Never truncate, never
   hash** — both produce names that cannot be read back to an endpoint, and truncated
   forms collide with each other.

## Field notes

- `metadata` carries only OpenAPI `x-` extensions that are **actually declared**.
  Resolver defaults (`DEFAULT_SLA_MS = 700`, `DEFAULT_MAX_PAYLOAD_BYTES = 1 MiB`) are
  deliberately absent: baking a global fallback into 41 files would turn one default
  into 41 declarations nobody chose.
- `credentialAlias` is null throughout. The catalogue registers aliases globally
  (`ATTENDANCE_SVC_UAT_01`, `LEAVE_SVC_UAT_01`) and the run manifest binds one at run
  time. **Aliases only — a raw credential value must never appear in this tree.**

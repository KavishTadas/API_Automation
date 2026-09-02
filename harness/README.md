# Local Validation Harness — DISPOSABLE

**This is not the platform plugin.** It is a throwaway local rig that exercises
the Sprint 1–4 input/output contracts end to end against real UAT endpoints,
through the same path the platform will use — so the contracts are proven before
the handoff rather than after.

The platform team builds the real thing against `docs/platform-handoff/`, not
against this. Nothing here is designed, tested, or supported for production:
no auth, no persistence, no multi-user safety, no migration path. If this starts
looking like a product, delete it.

## Run it

```bash
python -m harness.serve          # http://127.0.0.1:8765
```

Localhost only — it refuses to bind anything else. Runs are held in memory and
vanish when the process stops.

## What it proves

- The catalogue can drive a UI with no mock data
- A manifest round-trips: submit -> run -> result document -> render
- All seven result states render distinctly
- Pass rate excludes the five non-denominator states
- Credential aliases resolve **server-side**; no raw value ever reaches the browser

## One UI

There is a single page: the unified console, served at both `/` and `/console`.
A second, simpler UI used to live here as `ui.html`. Two pages against one
engine meant two auth-provider dropdowns with two different filters, and the
bug fixed in one of them (d8045e6) still shipped in the other months later.
Rebuild the console with `python scripts/build_unified_console.py`.

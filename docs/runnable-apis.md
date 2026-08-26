# Which APIs are actually runnable

**This is a point-in-time probe, not a generated artifact.** Nothing regenerates
it and no build step checks it. It records what was reachable and runnable on
**2026-08-26**, against UAT, on the `global_contract` tier. Hosts, certificates
and credentials all move — re-probe before relying on it, and update the date
when you do.

The machine-readable list lives in [`runnable-apis.json`](runnable-apis.json):
per-host reachability, the usable refs, and every exclusion with its reason.
This file explains it; that file is the data. Refs are in the post-remint
`method|path|module|sub-module` format and carry no base URL.

## What "runnable" means here

Host reachable **by the path the engine actually uses**, no unresolved
`{{token}}` placeholder, and at least 5 of the 13 contract checks genuinely
executed. The last clause is what separates an API that runs from one that
merely resolves.

## Per host

| Host | Rows | Reachability | Usable |
|---|---|---|---|
| `uatmcdphcmplatform.omfysgroup.com` | 19 | TCP open, TLS 1.3 | **13** |
| `devmcdphcmplatform.omfysgroup.com` | 8 | TCP open, TLS 1.3 | **8** |
| `localhost:9078` | 12 | **connection refused** | 0 |
| `dev_mcdp_be.omfysgroup.com` | 4 | TCP open, **CA verification fails** | 0 |
| `uat-mcdp-be.omfysgroup.com` | 2 | TCP open, TLS 1.3 | 0 — token providers, not targets |

**21 usable APIs across two hosts.**

## Three findings worth carrying forward

### 1. Twelve rows point at `http://localhost:9078`

Holiday Template APIs Copy (6), Latearly-Policy (5), Attenedance-july2026 (1).
The probe gets `ConnectionRefusedError`. These are dead anywhere but the dev
laptop that first captured them — CI, a shared runner, or any other machine will
never reach them. They are a third of the inventory.

### 2. `dev_mcdp_be.omfysgroup.com` fails certificate verification — but is not a dead host

Standard CA verification fails with `SSLCertVerificationError`. The hostname
contains underscores and resolves to `161.118.163.126`, shared with
`devmcdphcmplatform.omfysgroup.com`, whose certificate does not cover it.

**This is distinct from the Employee Auth pinned-agent path, which works.** The
engine reaches this host through `scripts/pinned_tls.py`, where it is
`PINNED_HOST`: the connection is validated against a pinned SHA-256 fingerprint
rather than the CA chain. `scripts/regression/verify-pinned-tls-agent.js` passes
— it mints a real token from this host, and fails closed on a stale pin.

So the four rows are excluded as **test targets**, not written off as
unreachable. Do not "fix" this by disabling verification anywhere else; the
pinned path is the deliberate answer and it is already in place.

### 3. The six Threshold rows never appear as blocked

The six `Attendance Status Threshold API` rows carry `Bearer {{token}}` — a
placeholder nothing resolves. The intuition is that they fail authentication and
surface as `SKIPPED_NO_TOKEN`. **They do not.**

They execute 2–3 of 13 checks and degrade the rest to `NOT_APPLICABLE`, reason
`Header Authorization contains unresolved template`. What passes is
`test_401_without_valid_token`, which deliberately sends no valid token, so the
placeholder is irrelevant to it.

This matters when reading scenario results: these rows inflate the
`NOT_APPLICABLE` count and contribute **nothing** to `SKIPPED_NO_TOKEN`. A
reader scanning for blocked APIs will not see them, and a reader scanning
`NOT_APPLICABLE` will read a credential problem as a metadata gap.

## Regenerating

There is no script. The probe was: resolve every inventory row's host through
the engine's own resolver, probe DNS/TCP/TLS per host, then run the reachable
candidates through `python -m tests.global_contract.run` and count what actually
executed per API. Redo that, and restate the date at the top.

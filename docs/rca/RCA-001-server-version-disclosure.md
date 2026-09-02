# RCA-001 — `Server: nginx/1.18.0 (Ubuntu)` disclosed on every host

**Status:** root cause identified · detection and CI gate shipped · **remediation blocked on infrastructure this repository does not contain**
**Assertion:** `test_no_server_version_disclosure` (`test-cases/global/21_no_server_version_disclosure.py`)
**Failing message:** `uatmcdphcmplatform.omfysgroup.com discloses a product version: {'server': 'nginx/1.18.0 (Ubuntu)'}`

---

## Summary

The assertion is correct and the finding is real. It is **not** a UI defect, and
it is **not** specific to UI-executed calls.

Every host in the estate answers with the nginx build number, to any client, on
any path, with or without credentials. A single `curl` reproduces it. The fix is
one nginx directive applied by whoever operates those hosts.

The one thing that *is* wrong is the premise that this appears only through the
UI. Correcting that premise matters, because chasing a UI-layer cause would have
spent the investigation on the wrong system entirely.

---

## 1. The premise is false — this is not UI-specific

Three independent lines of evidence.

**The committed CLI baselines already contain it.** These are `pytest` runs made
with no browser and no console:

| Baseline | Version-disclosure results |
|---|---|
| `baseline/33ecada-run.json` | **43 FAIL** |
| `baseline/44-endpoint-run.json` | **44 FAIL** |

**A plain `curl` reproduces it** — no harness, no UI, no auth:

```
$ curl -sI https://uatmcdphcmplatform.omfysgroup.com/ | grep -i server
Server: nginx/1.18.0 (Ubuntu)
```

**Every host does it**, not only the one named in the message:

| Host | `Server` |
|---|---|
| `uatmcdphcmplatform.omfysgroup.com` | `nginx/1.18.0 (Ubuntu)` |
| `devmcdphcmplatform.omfysgroup.com` | `nginx/1.18.0 (Ubuntu)` |
| `uat-mcdp-be.omfysgroup.com` | `nginx/1.18.0 (Ubuntu)` |

### So why does it *feel* UI-specific?

Two reasons, both about visibility rather than behaviour.

**The UI shows every row; the CLI showed a delta.** Command-line runs were
compared against a committed baseline that *already contained* these failures. An
expected failure produces no delta, so it never drew attention. The console has
no baseline — it renders the current run, and 37 identical red rows on one host
are impossible to miss.

**One misconfiguration is reported as 37 rows.** This is a host-level check. It
physically runs **once per host** and attributes that verdict to every API on the
host. In `baseline/44-endpoint-run.json` the 44 rows resolve to just **four
measurements**:

| Rows | `measuredBy` — the API that actually made the request |
|---:|---|
| 37 | `delete\|/api/attendance/holiday-templates/…` → `uatmcdphcmplatform` |
| 3 | `post\|/auth/token\|employee auth api` |
| 2 | `get\|/user/leaves/getallleavereports` |
| 2 | `get\|/users/me\|users` |

The true finding count is **four hosts**, not 44 endpoints. The console already
carries this distinction: rows it did not measure are tagged *"measured
elsewhere"*, and the detail pane shows *Measured by*. The fan-out is deliberate —
an API's report should state the security posture of the host serving it — but it
does make one server-config item look like a suite-wide outage.

---

## 2. Why the version is exposed, and why it matters

nginx emits `Server` on **every** response it produces, including its own error
pages. The `server_tokens` directive defaults to `on`, which appends the version.
The `(Ubuntu)` suffix comes from Debian/Ubuntu packaging, so the banner discloses
the distribution as well as the version.

Nothing is misconfigured in the usual sense. **This is stock nginx behaviour that
was never turned off.**

### Why it is flagged

Disclosure is not itself an exploit; it is a targeting aid.

- **It turns reconnaissance into a lookup.** `nginx/1.18.0` maps to a precise CVE
  set. CVE-2021-23017, a resolver off-by-one affecting nginx through 1.20.0 and
  fixed in 1.20.1, covers this build — exploitable only where the `resolver`
  directive is configured, which is exactly the kind of conditional an attacker
  can now check cheaply instead of guessing blind.
- **It dates the platform.** nginx 1.18.0 is the default package of Ubuntu 20.04
  LTS, whose standard support window has closed. The banner therefore hints at
  the OS generation underneath, not only the proxy.
- **It is graded.** Disclosure of this kind maps to CWE-200 and is routinely
  raised in penetration tests and compliance reviews. It is low severity and
  near-zero cost to fix, which is precisely why leaving it open reads badly.

**The header may stay; the version must not.** That is what the assertion
encodes — it matches on a version pattern (`\d+\.\d+`), not on the presence of
`Server`.

---

## 3. Request flow, and where the header is injected

```
  console (127.0.0.1:8765)          same-origin fetch to /run
        |                           harness/service.py, local uvicorn
        v
  pytest global tier                httpx, tests/api_runtime/
        |
        v  HTTPS
  +-----------------------------------------------+
  |  nginx 1.18.0 (Ubuntu)   reverse proxy        |  <-- INJECTS `Server`
  |  terminates TLS, proxies upstream             |
  +-----------------------------------------------+
        |
        v
  +-----------------------------------------------+
  |  Spring Boot / Tomcat + Spring Security       |  sets the X-* headers
  +-----------------------------------------------+
```

The console is **not** in the path as a proxy. It posts a manifest to the local
harness; the harness runs the same pytest tier the CLI runs, through the same
HTTP client. Nothing sits between the console and the remote host that could add
a header — the structural reason a UI-only cause was never plausible.

### Proof that nginx is the injector

Force nginx to answer **without** the application being reached, using an
over-length URI that nginx rejects itself:

```
$ curl -sI "https://uatmcdphcmplatform.omfysgroup.com/aaaa...[9000 chars]"
HTTP/1.1 414 Request-URI Too Large
Server: nginx/1.18.0 (Ubuntu)
Content-Type: text/html
Content-Length: 186
Connection: close
```

A 186-byte `text/html` error page with `Connection: close` is nginx's own,
served before any upstream request is made. The banner is present. **The header
originates at the proxy**, and no application change can remove it.

---

## 4. Which layer sets which header

Measured on `GET /api/attendance/holiday-templates/getall`:

| Header | Set by | Evidence |
|---|---|---|
| `Server: nginx/1.18.0 (Ubuntu)` | **nginx** | Present on nginx's own 414, which never reaches the app |
| `Content-Type: application/json;charset=ISO-8859-1` | **Spring Boot** | `ISO-8859-1` is the Spring/Tomcat default; nginx's own errors are `text/html` |
| `X-Content-Type-Options: nosniff` | **Spring Security** | Part of its default header-writer set |
| `X-Frame-Options: DENY` | **Spring Security** | Default `frameOptions` |
| `X-XSS-Protection: 0` | **Spring Security** | The modern default — deliberately `0`, not `1; mode=block` |
| `Cache-Control` / `Pragma` / `Expires` | **Spring Security** | Its standard no-store triple |
| `Strict-Transport-Security` | **nobody — absent** | Gap; see §7 |

No CDN or WAF fingerprint appears on this host (no `CF-Ray`, no `X-Amz-Cf-Id`,
no `X-Akamai-*`), so the path is a single nginx reverse proxy in front of a
Spring Boot service. `uat-mcdp-be` behaves differently — it returns `403` to
unauthenticated probes, consistent with a filtering layer in front of it — but it
discloses the same banner.

**Consequence for remediation:** the application team cannot fix this. Spring
does not set `Server`, and nginx sets it last and would overwrite an upstream
value anyway. This is an infrastructure change.

---

## 5. The fix (nginx)

### 5.1 Minimum change — suppress the version

In `nginx.conf`, inside the `http` block:

```nginx
http {
    server_tokens off;
    ...
}
```

This reduces the banner to `Server: nginx` and **satisfies this assertion**,
which matches only a version pattern. It also covers nginx's own error pages,
which is why it belongs in `http` rather than in a single `server` block.

Reload without dropping connections:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

### 5.2 Remove the header entirely

`server_tokens off` cannot delete the header — that needs the `headers-more`
module (`libnginx-mod-http-headers-more-filter` on Ubuntu):

```nginx
load_module modules/ngx_http_headers_more_filter_module.so;   # main context

http {
    server_tokens off;
    more_clear_headers 'Server';
    ...
}
```

Removing it outright is marginally better than `Server: nginx`, but the margin is
small: a fingerprinter identifies nginx from error-page HTML and header ordering
regardless. **Do not spoof it** to another product — that misleads your own
operators and monitoring at no cost to an attacker.

### 5.3 If an upstream ever sets its own `Server`

nginx replaces the upstream `Server` on proxied responses, so this is usually
unnecessary. Where an upstream banner must be stripped explicitly:

```nginx
location /api/ {
    proxy_pass http://backend;
    proxy_hide_header Server;
    proxy_hide_header X-Powered-By;
    proxy_hide_header X-AspNet-Version;
}
```

`X-Powered-By` and `X-AspNet-Version` are included because the assertion checks
those too. This estate does not currently send them; this keeps it that way.

### 5.4 Apply to every host

All four origins disclose, so the change is needed on each — `uatmcdphcmplatform`,
`devmcdphcmplatform`, `uat-mcdp-be`, and production. Fixing only the host named in
the failure message leaves three findings open.

---

## 6. Verification

### 6.1 Fastest check — one command, no credentials

```bash
python scripts/regression/verify-response-header-hygiene.py
```

Probes every `*_BASE_URL*` origin and exits `0` clean · `1` disclosure ·
`2` nothing reachable. An unreachable host is deliberately **not** a pass: a dead
DNS entry read as a clean result here once, and exit code `2` exists to stop that
recurring.

Ops can run it against one host with no repository setup:

```bash
python scripts/regression/verify-response-header-hygiene.py https://uatmcdphcmplatform.omfysgroup.com
```

### 6.2 Through the UI path specifically

The UI is not in the network path, so "verify through the UI" means confirming
that the **host-level result the console renders** flips to PASS:

1. `python -m harness.serve --port 8765`, then open `http://127.0.0.1:8765/console`.
2. Select any endpoint on the fixed host and run it.
3. In the results, find **Host discloses no product version in its headers**.
4. Confirm the row is **PASS**, and that its detail pane shows *Measured by* —
   which names the API that actually probed the host.
5. Confirm the sibling rows on that host also turn green. One measurement fans
   out to all of them, so a fix on one host clears ~37 rows at once. **If they do
   not move together, the host-level attribution is wrong**, and that is a
   separate defect worth raising.

### 6.3 The assertion itself

```bash
python -m pytest test-cases/global/21_no_server_version_disclosure.py -q
```

Expect FAIL before the nginx change and PASS after, with no code change in
between. That equivalence is the point: the suite is measuring the server, not
itself.

---

## 7. Further hardening

Ranked by value, not effort. Only the first is currently missing here.

**1. Add HSTS.** No host sends `Strict-Transport-Security`. Without it, a first
plaintext request is downgradeable. Start with a short max-age and raise it once
confident — the directive is hard to walk back once caches hold it:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

The `always` matters: without it the header is skipped on error responses, which
are exactly the ones an attacker provokes.

**2. Keep the headers Spring already sets** — `X-Content-Type-Options`,
`X-Frame-Options`, and the cache triple. They are correct today. Note that adding
*any* `add_header` inside a `location` block silently discards headers inherited
from the parent block; re-declare them there if you add one.

**3. Prefer CSP `frame-ancestors` over `X-Frame-Options`** as the framing
control. `X-Frame-Options` is legacy; CSP is the enforced modern equivalent.

**4. Patch nginx.** Suppressing the banner hides the version; it does not fix it.
1.18.0 is old enough to be worth scheduling an upgrade on its own merits.

**5. Do not spoof.** A fictional banner costs an attacker nothing and misleads
your own incident response.

---

## 8. Catching regressions

**Shipped in this change** — `.github/workflows/api-tests.yml` runs the hygiene
check on every push and writes the result into the job summary. It is
`continue-on-error: true` **on purpose**: every host discloses today, so a
blocking gate would fail from the day it landed, and a gate that always fails
gets switched off rather than fixed.

> **Action on remediation:** once `server_tokens off` is applied, delete the
> `continue-on-error: true` line from the *Check response header hygiene* step.
> That is the moment the gate begins protecting something.

**Also recommended:**

- **Probe post-deploy, not only in CI.** This header comes from infrastructure,
  so it regresses when nginx is reinstalled or a config is reverted — events no
  application pipeline observes. The same script fits a post-deploy smoke step.
- **Monitor synthetically.** Any uptime monitor that can assert on a response
  header catches a reverted config in minutes rather than at the next test run.
- **Treat host-level findings as host-scoped when reporting.** Deduplicate on
  `measuredBy` before counting, or one directive reads as 37 defects — the exact
  confusion that produced the UI-specific premise this RCA had to correct.

---

## Open items

| Item | Owner | Note |
|---|---|---|
| Apply `server_tokens off` on all four origins | **Infrastructure / ops** | Not actionable from this repository — it holds no IaC |
| Add HSTS | Infrastructure / ops | Absent everywhere; start with a low max-age |
| Make the CI gate blocking | This repo | One line, after remediation |
| Schedule an nginx upgrade from 1.18.0 | Infrastructure / ops | Independent of the banner |

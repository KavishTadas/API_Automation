# HCM Leave Management API Test Automation

## What this is

This repository automates API testing for HCM Leave Management using two complementary tiers: hand-written business-rule tests maintained as Postman collections and Bruno requests and run with Newman, plus generic contract tests generated automatically and run with Python/pytest. The current active scope is Employee Auth and Leave Reports against the UAT environment.

## Prerequisites

| Tool | Required version | Installation |
|---|---:|---|
| Node.js | 24.x | With nvm: run `nvm install 24` and `nvm use 24`. Alternatively, install a Node.js 24 release from the Node.js installer. `package.json` has no `engines` field; both GitHub Actions and the Jenkins tool configuration pin Node.js 24. |
| Python | 3.11 or newer | Install Python 3.11 from python.org (or your OS package manager) and enable the option that adds Python to `PATH`. This is a floor, not an exact pin: `pyproject.toml` declares `requires-python = ">=3.11"`. GitHub Actions and the development container select Python 3.11. |
| Java | JDK 17 verified locally; Temurin 21 in GitHub Actions | Install Eclipse Temurin 17 or 21 from Adoptium, set `JAVA_HOME`, and make sure `java -version` works. Allure generation has been verified locally with Temurin 17.0.17, while both GitHub Actions jobs explicitly provision Temurin 21. The Jenkins `tools` block does not configure Java, so Jenkins will use the JDK supplied by its future build agent. |

## Setup from zero

The local Python convention is an isolated `.venv`; do not install the project dependencies globally.

PowerShell:

```powershell
git clone https://github.com/KavishTadas/API_Automation.git
Set-Location API_Automation
npm ci

py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r dev-requirements.txt

Copy-Item .env.example .env
```

macOS/Linux equivalents for the Python environment and file copy are:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r dev-requirements.txt
cp .env.example .env
```

Open `.env` and replace the placeholder values for `EMP_CODE` and `EMP_PASSWORD` with valid UAT credentials. Keep `AUTH_TOKEN`, `API_AUTH_TOKEN`, `authToken`, and `AUTHTOKEN` as placeholders unless you intentionally supply a token, and fill `POSTMAN_*` only when using the related Postman account integrations. The public `BASE_URL`, `AUTH_BASE_URL`, and `LEAVE_BASE_URL` values already ship with the real UAT hosts and should not be changed for normal UAT use. `STAGING_BASE_URL` mirrors the current staging environment file, which is still a placeholder. Never commit `.env`.

## Running the tests

Activate `.venv` first, then run commands from the repository root.

Run the full hand-written Newman suite against UAT (Employee Auth first, then Leave Reports):

```powershell
npm run test:uat
```

Run the Python global contract suite and include its results in Allure:

```powershell
python -m pytest tests/global_contract --alluredir=reports/allure-results
```

Run the auto-generated generic contract suite and include its results in Allure:

```powershell
python -m pytest tests/auto_generated --alluredir=reports/allure-results
```

When collections, Bruno requests, or the API contract change, regenerate the inventory and generic tests before running them:

```powershell
node scripts/generate-api-file.js
python scripts/generate-generic-tests.py
```

To build and open the Allure report:

```powershell
npm run report:generate
npm run report:open
```

Run Newman before the Python suites when building one combined local report because the Newman runner clears old report data at startup. `report:open` now works cross-platform through `scripts/open-allure.js`, including its Windows-safe Java wrapper. The older Windows launch failure is fixed.

## A note on TLS certificate pinning

`dev_mcdp_be.omfysgroup.com` presents a legitimate, CA-trusted, currently valid certificate. The problem is its underscore: strict hostname validation rejects that host name under RFC 6125. The suite handles this narrow exception with certificate pinning in `scripts/pinned_tls.py` and `scripts/pinned-tls-agent.js`. Normal certificate-chain, trusted-root, and validity checks remain enabled; TLS security is not disabled.

**Expiry warning:** the certificate represented by the pinned SHA-256 fingerprint expires on **August 11, 2026**. After that date, requests will correctly fail closed until both pinning helpers are updated with the renewed certificate's fingerprint and the pin regression tests pass.

## Environments

The public hosts in `.env.example` now match the current environment definitions: its UAT `BASE_URL`, `AUTH_BASE_URL`, and `LEAVE_BASE_URL` values are real, while `STAGING_BASE_URL` intentionally mirrors the still-placeholder staging file. The following functional status was verified from those files, with UAT also confirmed by a successful live Newman run on August 5, 2026:

| Environment | Current hosts | Functional status |
|---|---|---|
| `local` | `http://localhost:3000` | **Not a functional HCM target.** It is only a local/sample configuration. |
| `uat` | Auth: `https://dev_mcdp_be.omfysgroup.com`; base: `https://uat-mcdp-be.omfysgroup.com`; Leave: `https://devmcdphcmplatform.omfysgroup.com` | **Functional and active.** This is the current Employee Auth and Leave Reports test target. |
| `staging` | `https://staging-hcm-api.example.com` | **Placeholder/non-functional.** No real staging HCM host is configured. |
| `production` | `https://production-hcm-api.example.com` | **Placeholder/non-functional.** No real production HCM host is configured. |

The FastAPI application in `main.py` is an intentionally out-of-scope sample, not part of HCM testing. Unverified sample checks and requests are quarantined under `tests/unverified_endpoints/` and `bruno/unverified-endpoints/` and are excluded from the active HCM inventory and CI suite.

## CI/CD

GitHub Actions is the active CI path. It runs automatically for every configured push and pull request, so contributors do not need a local VM or build agent; the hosted runner installs Node.js 24, Python 3.11, and Temurin 21 and publishes the generated reports. A Jenkins pipeline also exists, but it is not actively used and is deferred until a Jenkins build agent/VM is allocated.

## Troubleshooting

### Missing or blank credentials

Set both `EMP_CODE` and `EMP_PASSWORD` in `.env` (or as CI secrets). The Newman runner and monitor validate them before starting any collection, fail fast with a clear missing-credential message, and do not continue with a partial auth/leave run.

### Correct committed URL, wrong host in CI

Runtime environment variables and GitHub Actions secrets can take priority over committed environment configuration. This caused a real failure when a stale `LEAVE_BASE_URL` secret silently supplied an old host. If CI reaches a different URL than the repository defines, inspect or remove stale URL secrets and workflow-level overrides before changing the committed UAT files.

### Generated files look wrong

Do not hand-edit files under `tests/auto_generated/`, `api-docs/API_File.csv`, `api-docs/API_File.json`, or generated Allure/HTML report directories. They are regenerated automatically. Fix the source collection/contract or the responsible generator (`scripts/generate-api-file.js`, `scripts/generate-generic-tests.py`, or the report scripts), then regenerate the output.

## Project structure

| Path | Purpose |
|---|---|
| `collections/` | Active hand-written Postman/Newman business-rule suites; `.pending.` collections are skipped. |
| `environments/` | Postman/Newman environment definitions for local, UAT, staging, and production. |
| `openapi/` | Authoritative HCM OpenAPI contract and Spectral rules. |
| `scripts/` | Newman orchestration, TLS pinning, API inventory/test generation, and report wrappers. |
| `tests/auto_generated/` | Regenerated generic endpoint smoke/schema tests; never edit these directly. |
| `tests/global_contract/` | Hand-written cross-endpoint and protocol-level OpenAPI contract checks. |
| `tests/security/` | Certificate-pinning regression and fail-closed security tests. |
| `monitoring/` | Newman-based health checks, schedule configuration, and monitoring output guidance. |

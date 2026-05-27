# HCM API Automation Suite

This repository contains the HCM API test automation workflow for login and leave-management APIs. It runs Postman collections with Newman, keeps Bruno request definitions, lints the OpenAPI contract, generates an API inventory, creates smoke/schema pytest tests from that inventory, and publishes HTML/Allure reports.

The small FastAPI app in `main.py` is retained only as a local sample target for basic Python tests. The primary project is API automation against external HCM environments, with UAT as the current working environment.

## Project Layout

| Path | Purpose |
|---|---|
| `collections/` | Active Postman/Newman collections. Files containing `.pending.` are skipped by runners. |
| `test-data/` | CSV iteration data for collection runs. |
| `environments/` | Newman environment files for `uat`, `local`, `staging`, and `production`. |
| `bruno/` | Bruno collection and environment definitions. |
| `openapi/` | OpenAPI contract and Spectral rules. |
| `scripts/` | Newman runner, report generator, API file generator, and pytest generator. |
| `api-docs/` | Generated API inventory CSV/JSON and history snapshots. |
| `tests/` | FastAPI sample tests and generated API pytest tests. |
| `monitoring/` | Newman-based health check runner and monitoring notes. |

## Setup

Install Node dependencies:

```powershell
npm install
```

Install Python dependencies:

```powershell
python -m pip install -r dev-requirements.txt
```

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Fill `.env` with real credentials or provide them through CI secrets. Do not commit `.env`.

## Common Commands

Run the validated UAT Newman flow:

```powershell
npm run test:uat
```

Run a single collection by filename fragment:

```powershell
$env:ENV="uat"
$env:COLLECTION_FILTER="Login_API"
node scripts/run-newman.js
```

Lint the OpenAPI contract:

```powershell
npm run lint:spec
```

Generate the API inventory and pytest smoke tests:

```powershell
node scripts/generate-api-file.js
python scripts/generate-generic-tests.py
```

Run generated pytest checks:

```powershell
python -m pytest tests\auto_generated
```

Run the monitoring health check:

```powershell
npm run monitor:run
```

## Reports

Newman runs write per-collection HTML reports under `reports/html/` and Allure raw results under `reports/allure-results/`.

Generate the Allure HTML report:

```powershell
npm run report:generate
```

Generate the consolidated HTML index:

```powershell
npm run report:html
```

## CI/CD

GitHub Actions runs API tests on pushes and pull requests, with `workflow_dispatch` inputs for environment and collection selection. Jenkins exposes `ENVIRONMENT`, `COLLECTION`, and `NOTIFY_EMAIL`; `ENVIRONMENT` includes `uat`, `staging`, `production`, and `local`.

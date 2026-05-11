# API Automation

Postman/Newman API automation project structure for the FastAPI sample app.

## Structure

- `collections/` - Postman collections
- `environments/` - Postman environments
- `reports/html/` - HTML test reports
- `reports/allure-results/` - Allure result files
- `test-data/` - CSV and other test data
- `scripts/` - test runner scripts

## Prerequisites

- Node.js and npm
- The FastAPI app running at the `baseUrl` in `environments/QA.postman_environment.json`

## Run

```powershell
npm install
npm test
```

HTML reports are written to `reports/html/`. Allure result files are written to `reports/allure-results/`.

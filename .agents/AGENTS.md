# Allure Reporting Standards for API Test Automation

1. **Hierarchical Grouping**:
   - `@allure.epic`: Module / High-level Service (e.g. `Employee Auth API`, `Leave Module`).
   - `@allure.feature`: Endpoint & Path (e.g. `POST /auth/token — TC01 - Valid credentials return JWT token`).
   - `@allure.story`: Specific test assertion (e.g. `HTTP Status Code Check (200)` or `OpenAPI Schema Validation Check`).

2. **Metadata Parameters**:
   - Every API test case MUST log `HTTP Method`, `Endpoint Path`, and `Expected Status Code` via `allure.dynamic.parameter()`.
   - Every failure MUST attach pretty-printed JSON `Response Headers` and `Response Body Snippet`.

3. **CI Pipeline Step Ordering**:
   - Always install Python reporting packages (`allure-combine`, `dev-requirements.txt`) BEFORE running API test suites so `if: always()` report generation steps do not fail with `ModuleNotFoundError`.

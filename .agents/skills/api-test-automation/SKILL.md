---
name: api-test-automation
description: Guidelines and checklists for configuring Newman, Pytest, OpenAPI schemas, and Allure report hierarchies in HCM API Automation.
---

# API Test Automation Skill

## Newman Collection Execution Checklist
1. Maintain explicit collection ordering in `scripts/run-newman.js` (`RUN_ORDER` array).
2. Ensure data-driven CSV files match collection filenames in `test-data/<CollectionName>.csv`.
3. Verify JWT token extraction (`bru.setVar` or `pm.environment.set`) carries `authToken` forward between collections.
4. Register all 5 Attendance Management collections (`Attendance_Management_API.json`, `Attendance_Threshold_API.json`, `Holiday_Template_API.json`, `Late_Early_Policy_API.json`, `Weekoff_Policy_API.json`) in `RUN_ORDER`.
5. Verify Bruno environment variables match `authBaseUrl` (`https://dev_mcdp_be.omfysgroup.com`) and `attendanceBaseUrl` (`https://uat_mcdp_hcm.omfysgroup.com`).


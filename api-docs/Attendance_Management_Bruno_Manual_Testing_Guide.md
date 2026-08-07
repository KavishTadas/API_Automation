# Attendance Management API — Complete Bruno Manual Testing & Reference Guide

This document provides a comprehensive, field-by-field manual testing guide for the **Attendance Management APIs**. It is compiled from the developer API specifications (`API_File.csv`, `Global_API_Test_Matrix.csv`, `Updated_Attendance_Management_SRS_Jul2026.docx`) and the Postman automation collections.

---

## 🌐 Phase 1: Environment & Authentication Setup

### 1. Bruno Environment Configuration (`UAT`)

Configure your **UAT** environment in Bruno with the following keys:

| Variable Name | Type | Value / URL Description |
| :--- | :--- | :--- |
| **`authBaseUrl`** | String | `https://dev_mcdp_be.omfysgroup.com` *(Employee Auth Host)* |
| **`attendanceBaseUrl`** | String | `https://uat_mcdp_hcm.omfysgroup.com` *(Attendance HCM Host)* |
| **`empCode`** | String | `OMI-0076` *(Your Employee Code)* |
| **`empPassword`** | String | `your_actual_password` |
| **`authToken`** | Dynamic | Populated automatically by Auth post-response script |

---

### 2. Step 1 — Obtain Bearer Token (`POST /auth/token`)

* **Endpoint**: `POST {{authBaseUrl}}/auth/token`
* **Headers**: `Content-Type: application/json`

#### 📥 Request Body Example:
```json
{
  "empCode": "{{empCode}}",
  "password": "{{empPassword}}"
}
```

#### 📤 Expected Response Example (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Authentication successful",
  "data": {
    "empCode": "OMI-0076",
    "empName": "Sachin Khutwad",
    "empId": 34,
    "profileId": 6,
    "roles": [
      "ROLE_ADMIN",
      "ROLE_EMPLOYEE",
      "ROLE_CRM_ADMIN"
    ],
    "email": "sumit.raskar@omfysgroup.com",
    "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJPTUktMDA3NiIsImVtcElkIjozNCwiZW1wQ29kZSI6Ik9NSS0wMDc2IiwicHJvZmlsZUlkIjo2LCJlbXBOYW1lIjoiU2FjaGluIEtodXR3YWQiLCJyb2xlcyI6WyJST0xFX0FETUlOIiwiUk9MRV9FTVBMT1lFRSIsIlJPTEVfQ1JNM19BRE1JTiJdLCJlbWFpbCI6InN1bWl0LnJhc2thckBvbWZ5c2dyb3VwLmNvbSIsImlhdCI6MTc4NTkwOTY5NywiZXhwIjoxNzg1OTM4NDk3fQ.V9rtFbyNHncvRxusjbKx9jrjzkpv_VXtMDkxJSm9PP8"
  }
}
```

#### 📜 Bruno Post-Response Script *(Script Tab)*:
```javascript
if (res.status === 200 && res.body && res.body.data && res.body.data.token) {
  bru.setVar("authToken", res.body.data.token);
  console.log("Token dynamic inheritance active:", res.body.data.token);
}
```

---

## 🧪 Phase 2: Attendance Sub-Module Testing & Response Examples

For all requests below, set **Auth** in Bruno to **Bearer Token** $\rightarrow$ `{{authToken}}`.

---

### 1️⃣ Attendance Policy Master (`Attendance_Management_API.json`)

#### A. Create New Policy (`POST /api/attendancepolicy`)

* **URL**: `POST {{attendanceBaseUrl}}/api/attendancepolicy`
* **Headers**:
  - `Content-Type: application/json`
  - `Authorization: Bearer {{authToken}}`

##### 📥 Request Body Example:
```json
{
  "policyName": "Late Coming Policy",
  "policyHeading": "Late Coming Policy Heading",
  "policyDescription": "Policy for tracking late employee arrivals and penalties"
}
```

##### 📤 Expected Success Response (`200 OK` / `201 Created`):
```json
{
  "status": "SUCCESS",
  "message": "Attendance policy created successfully",
  "data": {
    "policyId": 101,
    "policyName": "Late Coming Policy",
    "policyHeading": "Late Coming Policy Heading",
    "policyDescription": "Policy for tracking late employee arrivals and penalties",
    "isActive": true,
    "createdBy": "OMI-0076",
    "createdDate": "2026-08-07T16:20:00Z"
  }
}
```

##### 📤 Error Response Example (`400 Bad Request` — Missing Field):
```json
{
  "status": "ERROR",
  "message": "Validation failed: policyName is required",
  "errorCode": "INVALID_INPUT_PARAMS"
}
```

---

#### B. Get All Policies (`GET /api/attendancepolicy`)

* **URL**: `GET {{attendanceBaseUrl}}/api/attendancepolicy`
* **Headers**: `Authorization: Bearer {{authToken}}`

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Policies retrieved successfully",
  "data": [
    {
      "policyId": 101,
      "policyName": "Late Coming Policy",
      "policyHeading": "Late Coming Policy Heading",
      "policyDescription": "Policy for tracking late employee arrivals and penalties",
      "isActive": true
    },
    {
      "policyId": 102,
      "policyName": "Early Departure Policy",
      "policyHeading": "Early Departure Heading",
      "policyDescription": "Policy for early clock-out tracking",
      "isActive": true
    }
  ]
}
```

---

#### C. Get Policy by ID (`GET /api/attendancepolicy/{id}`)

* **URL**: `GET {{attendanceBaseUrl}}/api/attendancepolicy/101`

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "data": {
    "policyId": 101,
    "policyName": "Late Coming Policy",
    "policyHeading": "Late Coming Policy Heading",
    "policyDescription": "Policy for tracking late employee arrivals and penalties",
    "isActive": true
  }
}
```

---

#### D. Update Policy (`PUT /api/attendancepolicy/{id}`)

* **URL**: `PUT {{attendanceBaseUrl}}/api/attendancepolicy/101`

##### 📥 Request Body Example:
```json
{
  "policyName": "Updated Late Coming Policy",
  "policyHeading": "Revised Heading 2026",
  "policyDescription": "Updated grace period and penalty rules"
}
```

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Policy 101 updated successfully",
  "data": {
    "policyId": 101,
    "policyName": "Updated Late Coming Policy",
    "policyHeading": "Revised Heading 2026",
    "policyDescription": "Updated grace period and penalty rules",
    "updatedDate": "2026-08-07T16:21:00Z"
  }
}
```

---

#### E. Delete Policy (`DELETE /api/attendancepolicy/{id}`)

* **URL**: `DELETE {{attendanceBaseUrl}}/api/attendancepolicy/101`

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Policy 101 deleted successfully"
}
```

---

### 2️⃣ Attendance Status Threshold API (`Attendance_Threshold_API.json`)

#### A. Configure Threshold Rules (`POST /api/attendancethreshold`)

* **URL**: `POST {{attendanceBaseUrl}}/api/attendancethreshold`

##### 📥 Request Body Example:
```json
{
  "policyId": 101,
  "presentMinHours": 8.0,
  "halfDayMinHours": 4.0,
  "lateGracePeriodMinutes": 15,
  "earlyExitGracePeriodMinutes": 15
}
```

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Attendance threshold configuration saved",
  "data": {
    "thresholdId": 501,
    "policyId": 101,
    "presentMinHours": 8.0,
    "halfDayMinHours": 4.0,
    "lateGracePeriodMinutes": 15,
    "earlyExitGracePeriodMinutes": 15
  }
}
```

---

### 3️⃣ Holiday Template API (`Holiday_Template_API.json`)

#### A. Create Holiday Template (`POST /api/holidaytemplate`)

* **URL**: `POST {{attendanceBaseUrl}}/api/holidaytemplate`

##### 📥 Request Body Example:
```json
{
  "templateName": "General National Holiday Calendar 2026",
  "year": 2026,
  "isApplicableToAll": true,
  "holidays": [
    {
      "holidayName": "Independence Day",
      "holidayDate": "2026-08-15",
      "isMandatory": true
    },
    {
      "holidayName": "Republic Day",
      "holidayDate": "2026-01-26",
      "isMandatory": true
    }
  ]
}
```

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Holiday template created successfully",
  "data": {
    "templateId": 301,
    "templateName": "General National Holiday Calendar 2026",
    "year": 2026,
    "totalHolidays": 2
  }
}
```

---

### 4️⃣ Late/Early Policy API (`Late_Early_Policy_API.json`)

#### A. Configure Late / Early Penalty Rules (`POST /api/lateearlypolicy`)

* **URL**: `POST {{attendanceBaseUrl}}/api/lateearlypolicy`

##### 📥 Request Body Example:
```json
{
  "gracePeriodMinutes": 15,
  "maxLateOccurrencesAllowed": 3,
  "penaltyDeductionType": "HALF_DAY",
  "applyDeductionOnOccurrence": 4
}
```

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Late/Early policy configuration saved",
  "data": {
    "lateEarlyPolicyId": 401,
    "gracePeriodMinutes": 15,
    "maxLateOccurrencesAllowed": 3,
    "penaltyDeductionType": "HALF_DAY"
  }
}
```

---

### 5️⃣ Weekoff Policy API (`Weekoff_Policy_API.json`)

#### A. Activate / Deactivate Weekoff Rule (`POST /api/weekoff/actdeact`)

* **URL**: `POST {{attendanceBaseUrl}}/api/weekoff/actdeact`

##### 📥 Request Body Example:
```json
{
  "weekOffId": 1,
  "isActive": true,
  "remarks": "Activated Saturday/Sunday alternate weekoff policy"
}
```

##### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "WeekOff status updated successfully",
  "data": {
    "weekOffId": 1,
    "isActive": true,
    "updatedBy": "OMI-0076"
  }
}
```

---

## 🛡️ Phase 3: Global Negative & Edge Case Test Matrix

As defined in `Global_API_Test_Matrix.csv`, execute the following negative test scenarios in Bruno for every Attendance endpoint:

| Test ID | Scenario Name | Request Modification | Expected Status | Response Assertion |
| :--- | :--- | :--- | :--- | :--- |
| **GLOB-AUTH-01** | Missing Auth Header | Remove `Authorization` header | `401 Unauthorized` | Verify status is 401 |
| **GLOB-AUTH-02** | Invalid Bearer Token | `Authorization: Bearer invalid_xyz` | `401 Unauthorized` | Verify token invalid error |
| **GLOB-VAL-01** | Empty JSON Body | Send `{}` payload | `400 Bad Request` | Verify validation message |
| **GLOB-VAL-02** | Missing Required Field | Omit `policyName` or `templateName` | `400 Bad Request` | Verify missing field listed |
| **GLOB-VAL-03** | Invalid Data Types | Send string `"abc"` for integer `year` | `400 Bad Request` | AJV Schema mismatch |
| **GLOB-ERR-01** | Non-Existent Endpoint | Request `/api/unknown_attendance` | `404 Not Found` | Verify 404 error payload |

# Attendance Management Master APIs — Complete Bruno Manual Testing & Reference Guide

This document provides a comprehensive, request-by-request manual testing reference for all **Attendance Master APIs** (Attendance Policy Master, Attendance Shift Master, Thresholds, Holidays, Late/Early & Weekoff Policies).

---

## 🌐 Phase 1: Environment & Token Setup in Bruno

### 1. Bruno Environment Configuration (`UAT`)

Configure your **`UAT`** environment in Bruno with these keys:

| Variable Name | Type | Value / URL Description |
| :--- | :--- | :--- |
| **`authBaseUrl`** | String | `https://dev_mcdp_be.omfysgroup.com` *(Employee Auth Host)* |
| **`attendanceBaseUrl`** | String | `https://uat_mcdp_hcm.omfysgroup.com` *(Attendance HCM Host)* |
| **`empCode`** | String | `OMI-0076` *(Employee Code)* |
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

#### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "message": "Authentication successful",
  "data": {
    "empCode": "OMI-0076",
    "empName": "Sachin Khutwad",
    "token": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJPTUktMDA3NiIsImVtcElkIjozNCwiZW1wQ29kZSI6Ik9NSS0wMDc2IiwicHJvZmlsZUlkIjo6Niwicm9sZXMiOlsiUk9MRV9BRE1JTiIsIlJPTEVfRU1QTE9ZRUUiXX0.V9rtFbyNHncvRxusjbKx9jrjzkpv_VXtMDkxJSm9PP8"
  }
}
```

#### 📜 Bruno Post-Response Script *(Script Tab)*:
```javascript
if (res.status === 200 && res.body && res.body.data && res.body.data.token) {
  bru.setVar("authToken", res.body.data.token);
  console.log("authToken dynamically captured:", res.body.data.token);
}
```

---

## 🏛️ Phase 2: Attendance Policy Master APIs (`/api/attendancepolicy`)

For all requests below, set **Auth** in Bruno to **Bearer Token** $\rightarrow$ `{{authToken}}`.

---

### 1. Create New Policy (`POST /api/attendancepolicy`)
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy`

#### 📥 Request Body Example:
```json
{
  "policyName": "Late Coming",
  "policyHeading": "Late Coming Policy Heading",
  "policyDescription": "Late Coming Policy Description"
}
```

#### 📤 Expected Success Response (`200 OK` / `201 Created`):
```json
{
  "status": "SUCCESS",
  "message": "Attendance policy created successfully",
  "data": {
    "policyId": 1,
    "policyName": "Late Coming",
    "policyHeading": "Late Coming Policy Heading",
    "policyDescription": "Late Coming Policy Description",
    "isActive": true
  }
}
```

---

### 2. Get All Policies (`GET /api/attendancepolicy`)
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy`

#### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "data": [
    {
      "policyId": 1,
      "policyName": "Late Coming",
      "policyHeading": "Late Coming Policy Heading",
      "policyDescription": "Late Coming Policy Description",
      "isActive": true
    }
  ]
}
```

---

### 3. Get Policy by ID (`GET /api/attendancepolicy/{id}`)
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/1`

#### 📤 Expected Success Response (`200 OK`):
```json
{
  "status": "SUCCESS",
  "data": {
    "policyId": 1,
    "policyName": "Late Coming",
    "policyHeading": "Late Coming Policy Heading",
    "policyDescription": "Late Coming Policy Description"
  }
}
```

---

### 4. Update Policy by ID (`PUT /api/attendancepolicy/{id}`)
* **Method**: `PUT`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/2`

#### 📥 Request Body Example:
```json
{
  "policyName": "Late Coming Policy",
  "policyHeading": "Late Coming Policy Heading",
  "policyDescription": "Late Coming Policy Description"
}
```

---

### 5. Delete Policy by ID (`DELETE /api/attendancepolicy/{id}`)
* **Method**: `DELETE`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/2`

---

### 6. Activate / Deactivate Policy (`PATCH /api/attendancepolicy/{id}/status?action=ACTIVATE`)
* **Method**: `PATCH`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/4/status?action=ACTIVATE`
* **Query Parameters**:
  - `action`: `ACTIVATE` or `DEACTIVATE`

---

## ⏱️ Phase 3: Attendance Shift Master APIs (`/api/v1/attendance/shift/master`)

---

### 1. Create New Standard Shift (`POST /api/v1/attendance/shift/master`)
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master`

#### 📥 Request Body Example (Standard Morning Shift):
```json
{
  "shiftCode": "SHF-MIDNIGHT-001",
  "shiftName": "MidNight Shift - Standard",
  "shiftType": "FIXED",
  "applicabilityType": "DEFAULT",
  "startTime": "09:00:00",
  "endTime": "18:00:00",
  "graceMinutes": 15,
  "requiredDurationHours": null,
  "effectiveFrom": "01-Aug-2026",
  "effectiveTo": "31-Dec-2026",
  "isDeleted": "N",
  "description": "Standard shift configuration",
  "remarks": "Standard morning shift for all employees",
  "breakConfigs": [
    {
      "breakName": "Lunch Break",
      "breakDurationMinutes": 60,
      "paidFlag": false
    },
    {
      "breakName": "Tea Break",
      "breakDurationMinutes": 15,
      "paidFlag": true
    },
    {
      "breakName": "Evening Tea",
      "breakDurationMinutes": 15,
      "paidFlag": true
    }
  ],
  "applicableEmpIds": null
}
```

---

### 2. Create CUSTOM Shift for Specific Employees (`POST /api/v1/attendance/shift/master`)
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master`

#### 📥 Request Body Example (Night Cross-Midnight Shift for Custom Employee List):
```json
{
  "shiftCode": "SHF-NIGHT-005",
  "shiftName": "Night Shift - Tech Support Team",
  "shiftType": "FIXED",
  "applicabilityType": "CUSTOM",
  "startTime": "22:00:00",
  "endTime": "06:00:00",
  "graceMinutes": 10,
  "requiredDurationHours": null,
  "effectiveFrom": "01-Aug-2026",
  "effectiveTo": "31-Mar-2027",
  "activeFlag": true,
  "remarks": "Night shift for global support team (cross-midnight)",
  "breakConfigs": [
    {
      "breakName": "Dinner Break",
      "breakDurationMinutes": 45,
      "paidFlag": false
    },
    {
      "breakName": "Tea Break",
      "breakDurationMinutes": 15,
      "paidFlag": true
    },
    {
      "breakName": "Refreshment Break",
      "breakDurationMinutes": 10,
      "paidFlag": true
    }
  ],
  "applicableEmpIds": [3496, 3500]
}
```

---

### 3. Update Shift Master (`PUT /api/v1/attendance/shift/master/{id}`)
* **Method**: `PUT`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master/2`

#### 📥 Request Body Example:
```json
{
  "shiftName": "Night Shift - Techno Support Team",
  "shiftType": "FIXED",
  "applicabilityType": "DEFAULT",
  "startTime": "22:00:00",
  "endTime": "06:00:00",
  "graceMinutes": 10,
  "requiredDurationHours": null,
  "effectiveFrom": "01-Aug-2026",
  "effectiveTo": "31-Mar-2027",
  "activeFlag": true,
  "description": "Updated shift schedule",
  "remarks": "Night shift for global support team (cross-midnight)",
  "breakConfigs": [
    {
      "breakName": "Dinner Break",
      "breakDurationMinutes": 45,
      "paidFlag": false
    },
    {
      "breakName": "Shortscut Break",
      "breakDurationMinutes": 15,
      "paidFlag": true
    },
    {
      "breakName": "Refreshment Break",
      "breakDurationMinutes": 10,
      "paidFlag": true
    }
  ],
  "applicableEmpIds": [3496, 3500]
}
```

---

### 4. Get Shift by ID (`GET /api/v1/attendance/shift/master/{id}`)
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master/7`

---

### 5. Delete Shift Master (`DELETE /api/v1/attendance/shift/master/{id}`)
* **Method**: `DELETE`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master/6`

---

### 6. Toggle Delete / Deactivate Shift (`PATCH /api/v1/attendance/shift/master/status/{id}?action=DEACTIVATE`)
* **Method**: `PATCH`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master/status/7?action=DEACTIVATE`
* **Query Parameters**:
  - `action`: `DEACTIVATE` or `ACTIVATE`

---

### 7. Get All Shifts (`GET /api/v1/attendance/shift/master`)
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/v1/attendance/shift/master?page=0&includeDeleted=true`
* **Query Parameters**:
  - `page`: `0`
  - `includeDeleted`: `true`
  - `searchText` *(optional)*
  - `shiftType` *(optional)*
  - `applicabilityType` *(optional)*
  - `activeFlag` *(optional)*

---

## 🛡️ Phase 4: Negative & Validation Test Matrix

| Test Case | Scenario Name | Endpoint Path | Method | Expected Status |
| :--- | :--- | :--- | :--- | :--- |
| **SHIFT-ERR-01** | Missing Auth Token | `/api/v1/attendance/shift/master` | `POST` | `401 Unauthorized` |
| **SHIFT-ERR-02** | Invalid Shift Time (End < Start) | `/api/v1/attendance/shift/master` | `POST` | `400 Bad Request` |
| **SHIFT-ERR-03** | Duplicate Shift Code | `/api/v1/attendance/shift/master` | `POST` | `400 Bad Request` |
| **SHIFT-ERR-04** | Non-Existent Shift ID | `/api/v1/attendance/shift/master/9999` | `GET` | `404 Not Found` |

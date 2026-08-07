# Attendance Management API — Bruno Manual Testing Guide

This document provides step-by-step instructions for manually testing the **Attendance Management APIs** using **Bruno GUI** or **Bruno CLI**, including environment setup, authentication token inheritance, and module-by-module execution workflows.

---

## 🌐 Phase 1: Environment & Token Setup in Bruno

### 1. Environment Configuration (`UAT`)
Create or select the **`UAT`** environment in Bruno with the following variables:

| Variable Name | Description & URL |
| :--- | :--- |
| **`authBaseUrl`** | `https://dev_mcdp_be.omfysgroup.com` *(Employee Auth API)* |
| **`attendanceBaseUrl`** | `https://uat_mcdp_hcm.omfysgroup.com` *(Attendance HCM API)* |
| **`empCode`** | Your Employee Code |
| **`empPassword`** | Your Employee Password |
| **`authToken`** | Dynamically populated by Auth request |

---

### 2. Step 1 — Obtain Bearer Token (`POST /auth/token`)

* **Method**: `POST`
* **URL**: `{{authBaseUrl}}/auth/token`
* **Headers**: `Content-Type: application/json`
* **Body (JSON)**:
  ```json
  {
    "empCode": "{{empCode}}",
    "password": "{{empPassword}}"
  }
  ```

* **Bruno Post-Response Script** *(Script Tab)*:
  ```javascript
  if (res.status === 200 && res.body && res.body.data && res.body.data.token) {
    bru.setVar("authToken", res.body.data.token);
    console.log("authToken set successfully:", res.body.data.token);
  }
  ```

---

## 🧪 Phase 2: Attendance Sub-Module Testing Workflows

For all subsequent requests below, set **Auth** in Bruno to **Bearer Token** $\rightarrow$ `{{authToken}}`.

---

### 1️⃣ Attendance Policy Master (`collections/Attendance_Management_API.json`)

#### A. Create New Policy
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy`
* **Body (JSON)**:
  ```json
  {
    "policyName": "Late Coming Policy",
    "policyHeading": "Late Coming Policy Heading",
    "policyDescription": "Policy for tracking late employee arrivals"
  }
  ```
* **Expected Response**: `200 OK` or `201 Created`

#### B. Get All Policies
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy`
* **Expected Response**: `200 OK` array of policies

#### C. Get Policy by ID
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/{id}`

#### D. Update Policy
* **Method**: `PUT`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/{id}`

#### E. Delete Policy
* **Method**: `DELETE`
* **URL**: `{{attendanceBaseUrl}}/api/attendancepolicy/{id}`

---

### 2️⃣ Attendance Status Threshold API (`collections/Attendance_Threshold_API.json`)

#### A. Configure Threshold Rules
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/attendancethreshold`
* **Body (JSON)**:
  ```json
  {
    "policyId": 1,
    "presentMinHours": 8,
    "halfDayMinHours": 4,
    "lateGracePeriodMinutes": 15
  }
  ```
* **Expected Response**: `200 OK`

#### B. Get Threshold Configurations
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/attendancethreshold`

---

### 3️⃣ Holiday Template API (`collections/Holiday_Template_API.json`)

#### A. Create Holiday Template
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/holidaytemplate`
* **Body (JSON)**:
  ```json
  {
    "templateName": "General Holiday Calendar 2026",
    "year": 2026,
    "isApplicableToAll": true
  }
  ```
* **Expected Response**: `200 OK` template object

#### B. Get Holiday Templates
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/holidaytemplate`

---

### 4️⃣ Late/Early Policy API (`collections/Late_Early_Policy_API.json`)

#### A. Configure Late / Early Departure Rules
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/lateearlypolicy`
* **Body (JSON)**:
  ```json
  {
    "gracePeriodMinutes": 15,
    "maxLateOccurrencesAllowed": 3,
    "penaltyDeductionType": "HALF_DAY"
  }
  ```
* **Expected Response**: `200 OK`

#### B. Get Late/Early Policies
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/lateearlypolicy`

---

### 5️⃣ Weekoff Policy API (`collections/Weekoff_Policy_API.json`)

#### A. Activate / Deactivate Weekoff Rule (`WeekOffActDeact`)
* **Method**: `POST`
* **URL**: `{{attendanceBaseUrl}}/api/weekoff/actdeact`
* **Body (JSON)**:
  ```json
  {
    "weekOffId": 1,
    "isActive": true
  }
  ```
* **Expected Response**: `200 OK` status update

#### B. Get Weekoff Rules
* **Method**: `GET`
* **URL**: `{{attendanceBaseUrl}}/api/weekoff`

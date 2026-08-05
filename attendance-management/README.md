# Attendance Management API Automation

Dedicated module for all **Attendance Management** API collections, Bruno requests, test data, and OpenAPI specifications.

---

## 📁 Directory Structure

```text
attendance-management/
├── collections/                  # Postman / Newman test collections
│   └── Attendance_API.json
├── bruno/                        # Bruno API request definitions
│   └── get-attendance-history.bru
│   └── mark-attendance.bru
├── test-data/                    # CSV & JSON datasets for data-driven testing
│   └── Attendance_API.csv
├── openapi/                      # OpenAPI v3 specifications for Attendance
│   └── attendance-spec.yaml
└── README.md                     # Module documentation
```

---

## 🚀 Execution Commands

### **1. Run via Newman (Postman Collection)**
```bash
npx newman run attendance-management/collections/Attendance_API.json -d attendance-management/test-data/Attendance_API.csv -e environments/uat.json
```

### **2. Run via Bruno CLI**
```bash
npx @usebruno/cli run attendance-management/bruno --env local
```

### **3. Open in Bruno Desktop App**
1. Open Bruno Desktop App.
2. Click **Open Collection**.
3. Select the `attendance-management/bruno` folder.

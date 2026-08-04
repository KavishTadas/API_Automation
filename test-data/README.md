# Test Data — Data-Driven Testing

Each CSV file in this folder maps to a collection in
collections/ by matching filename.

Newman reads the CSV and runs the collection once per row,
substituting CSV column values as environment variables
available inside test scripts as pm.iterationData.get('columnName').

## Leave_API.csv columns
- startDate     → substituted into request body
- endDate       → substituted into request body
- testLabel     → logged to console per iteration
- expectRecords → 'true'/'false' — whether records array
                  should be non-empty

## Adding new test data
Add rows to the CSV. Do not change column headers.
Newman automatically picks up the file on next run.

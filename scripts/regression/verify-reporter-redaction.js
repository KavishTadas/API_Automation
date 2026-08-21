const assert = require('assert');
const fs = require('fs');
const path = require('path');

const reportsDir = path.resolve(__dirname, '..', '..', 'reports');
const probePath = path.join(
  reportsDir,
  `.reporter-redaction-regression-${process.pid}.json`
);
const REDACTED = '***REDACTED***';

// Loading the reporter config installs the report-only fs redaction hooks.
require('../reporter-config');

const sensitiveValues = [
  'Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJyZWRhY3Rpb24tcHJvYmUifQ.signature',
  'lower-case-authorization-value',
  'password-value',
  'employee-password-value',
  'secret-value',
  'employee-code-value'
];

const fixture = {
  Authorization: sensitiveValues[0],
  nested: {
    authorization: sensitiveValues[1],
    password: sensitiveValues[2],
    empPassword: sensitiveValues[3],
    clientSecret: sensitiveValues[4],
    empCode: sensitiveValues[5],
    safe: 'preserved'
  },
  array: [
    {
      AUTHORIZATION: sensitiveValues[0],
      EMP_PASSWORD: sensitiveValues[3],
      SECRET: sensitiveValues[4],
      EMP_CODE: sensitiveValues[5]
    }
  ]
};

try {
  fs.mkdirSync(reportsDir, { recursive: true });
  fs.writeFileSync(probePath, JSON.stringify(fixture), 'utf8');

  const redacted = JSON.parse(fs.readFileSync(probePath, 'utf8'));

  assert.strictEqual(redacted.Authorization, REDACTED);
  assert.strictEqual(redacted.nested.authorization, REDACTED);
  assert.strictEqual(redacted.nested.password, REDACTED);
  assert.strictEqual(redacted.nested.empPassword, REDACTED);
  assert.strictEqual(redacted.nested.clientSecret, REDACTED);
  assert.strictEqual(redacted.nested.empCode, REDACTED);
  assert.strictEqual(redacted.nested.safe, 'preserved');
  assert.strictEqual(redacted.array[0].AUTHORIZATION, REDACTED);
  assert.strictEqual(redacted.array[0].EMP_PASSWORD, REDACTED);
  assert.strictEqual(redacted.array[0].SECRET, REDACTED);
  assert.strictEqual(redacted.array[0].EMP_CODE, REDACTED);

  const serialized = JSON.stringify(redacted);
  sensitiveValues.forEach((value) => {
    assert.strictEqual(serialized.includes(value), false);
  });

  console.log(
    'Structured report JSON redacts authorization, empCode, password, empPassword, and secret keys recursively.'
  );
} finally {
  fs.rmSync(probePath, { force: true });
}

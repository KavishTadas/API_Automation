const assert = require('assert');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

require('dotenv').config({ quiet: true });

const newman = require('newman');
const reporterConfig = require('../reporter-config');
const { pinnedRequest } = require('../pinned-tls-agent');

const projectRoot = path.resolve(__dirname, '..', '..');
const resultsDir = path.join(projectRoot, 'reports', 'allure-results');
const reportDir = path.join(projectRoot, 'reports', 'allure-report');
const REDACTED = '***REDACTED***';
const JWT_BEARER_PATTERN =
  /\bBearer\s+(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b/gi;

function requiredEnvironmentValue(name) {
  const value = process.env[name];
  if (typeof value !== 'string' || value.trim() === '') {
    throw new Error(`Missing required environment variable ${name}`);
  }
  return value;
}

function listFiles(rootPath) {
  if (!fs.existsSync(rootPath)) {
    return [];
  }

  return fs.readdirSync(rootPath, { withFileTypes: true }).flatMap((entry) => {
    const entryPath = path.join(rootPath, entry.name);
    return entry.isDirectory() ? listFiles(entryPath) : [entryPath];
  });
}

function runNewman(options) {
  return new Promise((resolve, reject) => {
    newman.run(options, (error, summary) => {
      if (error) {
        reject(error);
        return;
      }

      const requestErrors = (summary?.run?.failures || []).filter(
        (failure) => failure.source?.name === 'request'
      );
      if (requestErrors.length > 0) {
        reject(new Error('The live Newman Bearer request did not complete'));
        return;
      }

      resolve(summary);
    });
  });
}

function authorizationValues(value, found = []) {
  if (Array.isArray(value)) {
    value.forEach((child) => authorizationValues(child, found));
    return found;
  }

  if (value && typeof value === 'object') {
    Object.entries(value).forEach(([key, child]) => {
      if (key.toLowerCase() === 'authorization') {
        found.push(child);
      } else {
        authorizationValues(child, found);
      }
    });
  }

  return found;
}

async function main() {
  const empCode = requiredEnvironmentValue('EMP_CODE');
  const empPassword = requiredEnvironmentValue('EMP_PASSWORD');
  const leaveBaseUrl = requiredEnvironmentValue('LEAVE_BASE_URL');

  const authResponse = await pinnedRequest('/auth/token', {
    method: 'POST',
    jsonBody: { empCode, password: empPassword }
  });
  assert.strictEqual(authResponse.statusCode, 200, 'Pinned auth must return 200');

  const authPayload = JSON.parse(authResponse.text);
  const token = authPayload.token;
  assert.match(
    token,
    /^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/,
    'Auth response must contain a three-part JWT'
  );

  fs.mkdirSync(resultsDir, { recursive: true });
  const filesBefore = new Set(listFiles(resultsDir));
  const collectionName = 'Bearer_Redaction_Verification';
  const collection = {
    info: {
      name: collectionName,
      schema: 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'
    },
    item: [
      {
        name: 'One real Bearer request',
        request: {
          method: 'GET',
          header: [
            {
              key: 'Authorization',
              value: 'Bearer {{authToken}}',
              type: 'text'
            }
          ],
          url: {
            raw: '{{leaveBaseUrl}}/user/leaves/getAllLeaveReports?month=4&year=2026',
            host: ['{{leaveBaseUrl}}'],
            path: ['user', 'leaves', 'getAllLeaveReports'],
            query: [
              { key: 'month', value: '4' },
              { key: 'year', value: '2026' }
            ]
          }
        },
        event: [
          {
            listen: 'test',
            script: {
              type: 'text/javascript',
              exec: [
                "pm.test('Bearer request completed', function () {",
                '  pm.expect(pm.response).to.exist;',
                '});'
              ]
            }
          }
        ]
      }
    ]
  };

  const summary = await runNewman({
    collection,
    envVar: [
      { key: 'authToken', value: token },
      { key: 'leaveBaseUrl', value: leaveBaseUrl }
    ],
    reporters: ['allure'],
    reporter: {
      allure: {
        export: resultsDir,
        collectionAsParentSuite: true,
        postProcessorForTest: reporterConfig.createAllurePostProcessor({
          collectionName,
          resultsDir
        })
      }
    },
    timeoutRequest: 10000
  });

  assert.strictEqual(summary.run.stats.requests.total, 1);
  assert.strictEqual(summary.run.stats.requests.failed, 0);

  const filesAfter = listFiles(resultsDir);
  const newFiles = filesAfter.filter((filePath) => !filesBefore.has(filePath));
  const newResults = newFiles.filter((filePath) =>
    filePath.endsWith('-result.json')
  );
  const requestHeaderAttachments = [];

  newResults.forEach((resultPath) => {
    const result = JSON.parse(fs.readFileSync(resultPath, 'utf8'));
    (result.attachments || [])
      .filter((attachment) => attachment.name === 'Request Headers')
      .forEach((attachment) => {
        requestHeaderAttachments.push(
          path.join(resultsDir, attachment.source)
        );
      });
  });

  assert.strictEqual(
    requestHeaderAttachments.length,
    1,
    'Expected exactly one Request Headers attachment from the live request'
  );

  const requestHeadersText = fs.readFileSync(
    requestHeaderAttachments[0],
    'utf8'
  );
  const requestHeaders = JSON.parse(requestHeadersText);
  const redactedAuthorizationValues = authorizationValues(requestHeaders);
  assert.ok(
    redactedAuthorizationValues.length > 0,
    'Request Headers attachment must contain Authorization'
  );
  redactedAuthorizationValues.forEach((value) => {
    assert.strictEqual(value, REDACTED);
  });
  assert.strictEqual(requestHeadersText.includes(token), false);

  const generateReport = spawnSync(
    process.execPath,
    [path.join(projectRoot, 'scripts', 'generate-allure.js')],
    {
      cwd: projectRoot,
      encoding: 'utf8',
      shell: false
    }
  );
  if (generateReport.status !== 0) {
    throw new Error(
      `Allure generation failed: ${generateReport.stderr || generateReport.stdout}`
    );
  }

  const reportFiles = [
    ...listFiles(resultsDir),
    ...listFiles(reportDir)
  ];
  const exactTokenMatches = [];
  const jwtBearerMatches = [];

  reportFiles.forEach((filePath) => {
    const content = fs.readFileSync(filePath).toString('utf8');
    if (content.includes(token)) {
      exactTokenMatches.push(filePath);
    }
    JWT_BEARER_PATTERN.lastIndex = 0;
    if (JWT_BEARER_PATTERN.test(content)) {
      jwtBearerMatches.push(filePath);
    }
  });

  assert.deepStrictEqual(exactTokenMatches, []);
  assert.deepStrictEqual(jwtBearerMatches, []);

  const tokenFingerprint = crypto
    .createHash('sha256')
    .update(token)
    .digest('hex')
    .slice(0, 16);
  const responseCode = summary.run.executions[0].response.code;

  console.log(`Live Newman Bearer requests: ${summary.run.stats.requests.total}`);
  console.log(`Live response status: ${responseCode}`);
  console.log(`Token SHA-256 fingerprint: ${tokenFingerprint}`);
  console.log('Actual Request Headers attachment JSON:');
  console.log(requestHeadersText);
  console.log(`Exact-token matches across both Allure trees: ${exactTokenMatches.length}`);
  console.log(`JWT-shaped Bearer files across both Allure trees: ${jwtBearerMatches.length}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});

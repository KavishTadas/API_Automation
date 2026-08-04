require('dotenv').config();
const newman   = require('newman');
const Ajv      = require('ajv');
const fs       = require('fs');
const path     = require('path');
const YAML     = require('yaml');
const reporterConfig = require('./reporter-config');
const { generateIndex } = require('./generate-html-index');
const {
  createPinnedTlsAgent,
  PINNED_HOST
} = require('./pinned-tls-agent');

const PINNED_AUTH_BASE_URL =
  process.env.NEWMAN_RETRY_PROBE_AUTH_BASE_URL || `https://${PINNED_HOST}`;
const LEAVE_REPORT_BASE_URL = 'https://devmcdphcmplatform.omfysgroup.com';
const PINNED_TLS_DEBUG = process.env.PINNED_TLS_DEBUG === '1';
// Tune these two constants if the retry budget or initial backoff ever needs
// to change. Attempts use 500ms then 1000ms delays (three attempts total).
const MAX_TRANSIENT_ATTEMPTS = 3;
const INITIAL_RETRY_DELAY_MS = 500;
const RETRYABLE_NETWORK_ERROR_CODES = new Set([
  'ECONNABORTED',
  'ECONNREFUSED',
  'ECONNRESET',
  'EHOSTUNREACH',
  'EAI_AGAIN',
  'ENETUNREACH',
  'ENOTFOUND',
  'EPIPE',
  'ESOCKETTIMEDOUT',
  'ETIMEDOUT'
]);
const OPENAPI_SCHEMA_BUNDLE_ID =
  'https://hcm-api-automation.local/openapi-schema-bundle.json';
const REQUIRED_RESPONSE_SCHEMAS = [
  'LoginResponse',
  'ErrorResponse',
  'GetAllLeaveReportsResponse',
  'GetAllLeaveReportsErrorResponse',
  'GetAllLeaveReportsItem'
];

function loadOpenApiSchemaBundle() {
  const specPath = path.join(__dirname, '..', 'openapi', 'openapi.yaml');
  const document = YAML.parse(fs.readFileSync(specPath, 'utf8'));
  const schemas = document?.components?.schemas;

  if (!schemas || typeof schemas !== 'object') {
    throw new Error(
      'OpenAPI schema loading failed: components.schemas is missing from openapi/openapi.yaml'
    );
  }

  const missingSchemas = REQUIRED_RESPONSE_SCHEMAS.filter(
    schemaName => !Object.prototype.hasOwnProperty.call(schemas, schemaName)
  );
  if (missingSchemas.length > 0) {
    throw new Error(
      `OpenAPI schema loading failed: missing ${missingSchemas.join(', ')}`
    );
  }

  const schemaBundle = {
    $schema: 'http://json-schema.org/draft-07/schema#',
    $id: OPENAPI_SCHEMA_BUNDLE_ID,
    components: { schemas }
  };

  // Compile every response schema before making network calls. Collection
  // scripts repeat this validation inside Newman's sandbox against real bodies.
  const ajv = new Ajv({ allErrors: true, strict: false });
  ajv.addSchema(schemaBundle);
  REQUIRED_RESPONSE_SCHEMAS.forEach(schemaName => {
    const validator = ajv.getSchema(
      `${OPENAPI_SCHEMA_BUNDLE_ID}#/components/schemas/${schemaName}`
    );
    if (typeof validator !== 'function') {
      throw new Error(
        `OpenAPI schema loading failed: could not compile ${schemaName}`
      );
    }
  });

  return JSON.stringify(schemaBundle);
}

const OPENAPI_SCHEMA_BUNDLE_JSON = loadOpenApiSchemaBundle();

function wait(delayMs) {
  return new Promise(resolve => setTimeout(resolve, delayMs));
}

function cursorKey(cursor) {
  if (!cursor) {
    return undefined;
  }
  return `${cursor.iteration ?? ''}:${cursor.httpRequestId ?? cursor.ref ?? cursor.position ?? ''}`;
}

function isRetryableNetworkError(error) {
  if (!error) {
    return false;
  }

  const code = String(error.code || error.errno || '').toUpperCase();
  if (RETRYABLE_NETWORK_ERROR_CODES.has(code)) {
    return true;
  }

  const message = String(error.message || error);
  return /\b(?:ECONNABORTED|ECONNREFUSED|ECONNRESET|EHOSTUNREACH|EAI_AGAIN|ENETUNREACH|ENOTFOUND|EPIPE|ESOCKETTIMEDOUT|ETIMEDOUT)\b|socket hang up|getaddrinfo\s+(?:ENOTFOUND|EAI_AGAIN)|connect(?:ion)?\s+timed?\s*out|request\s+timed?\s*out/i.test(message);
}

function failureText(failure) {
  return [
    failure?.error?.test,
    failure?.error?.message,
    failure?.error?.stack,
    failure?.error?.name,
    failure?.error?.code,
    failure?.message
  ]
    .filter(Boolean)
    .join(' ');
}

function classifyTransientFailure(err, summary) {
  const executions = Array.isArray(summary?.run?.executions)
    ? summary.run.executions
    : [];
  const failures = Array.isArray(summary?.run?.failures)
    ? summary.run.failures
    : [];
  const reasons = [];
  let sawNonRetryable4xx = false;

  executions.forEach(execution => {
    const requestName = execution.item?.name || 'unnamed request';
    const statusCode = Number(execution.response?.code);

    if (statusCode === 429 || (statusCode >= 500 && statusCode <= 599)) {
      const status = execution.response?.status
        ? ` ${execution.response.status}`
        : '';
      reasons.push(`HTTP ${statusCode}${status} from "${requestName}"`);
      return;
    }

    if (statusCode >= 400 && statusCode < 500) {
      sawNonRetryable4xx = true;
      return;
    }

    if (isRetryableNetworkError(execution.requestError)) {
      reasons.push(
        `${execution.requestError.code || 'network error'} in "${requestName}": ${execution.requestError.message}`
      );
    }
  });

  if (isRetryableNetworkError(err)) {
    reasons.push(`${err.code || 'network error'}: ${err.message}`);
  }

  const failureDetails = failures.map(failure => failureText(failure)).join(' ');
  if (
    /OpenAPI.*schema|schema validation|Ajv|JSON schema/i.test(failureDetails) ||
    /JSONError|Unexpected token|Expected application\/json response|content-type/i.test(failureDetails)
  ) {
    return { retryable: false, reason: '' };
  }

  if (sawNonRetryable4xx) {
    return { retryable: false, reason: 'non-retryable 4xx response' };
  }

  if (reasons.length === 0) {
    return { retryable: false, reason: '' };
  }

  return {
    retryable: true,
    reason: [...new Set(reasons)].join('; ')
  };
}

const ENV     = process.env.ENV || 'local';
const envFile = path.join(__dirname, '..', 'environments', `${ENV}.json`);

if (!fs.existsSync(envFile)) {
  console.error(`ERROR: Environment file not found: environments/${ENV}.json`);
  process.exit(1);
}

for (const [credential, value] of Object.entries({
  empCode: process.env.EMP_CODE,
  empPassword: process.env.EMP_PASSWORD
})) {
  if (typeof value !== 'string' || value.trim() === '') {
    console.error(
      `ERROR: Missing required credential ${credential} — set ${credential === 'empCode' ? 'EMP_CODE' : 'EMP_PASSWORD'} via env var before running`
    );
    process.exit(1);
  }
}

const collectionsDir  = path.join(__dirname, '..', 'collections');
const RUN_ORDER = [
  'Employee_Auth_API.json',
  'Leave_API.json'
];

const discovered = fs.readdirSync(collectionsDir)
  .filter(f =>
    f.endsWith('.json') &&
    !f.includes('.pending.')
  );

const collectionFiles = [
  ...RUN_ORDER.filter(f => discovered.includes(f)),
  ...discovered.filter(f => !RUN_ORDER.includes(f))
];

const COLLECTION_FILTER = process.env.COLLECTION_FILTER;
const requestedCollectionFilters = COLLECTION_FILTER && COLLECTION_FILTER !== 'all'
  ? COLLECTION_FILTER.split(',')
      .map(filter => filter.trim().toLowerCase().replace('.json', ''))
      .filter(Boolean)
  : [];
const filteredFiles = (
  requestedCollectionFilters.length > 0
)
  ? collectionFiles.filter(f =>
      requestedCollectionFilters.some(filter =>
        f.toLowerCase().replace('.json', '').includes(filter)
      )
    )
  : collectionFiles;

if (COLLECTION_FILTER && COLLECTION_FILTER !== 'all') {
  console.log('Collection filter applied:', COLLECTION_FILTER);
  console.log('Running:', filteredFiles.length, 'collection(s)');
}

const collectionFilesFiltered = filteredFiles;

console.log('\nCollection run order:');
filteredFiles.forEach((f, i) =>
  console.log(`  ${i + 1}. ${f}`)
);

if (filteredFiles.length === 0) {
  if (COLLECTION_FILTER && COLLECTION_FILTER !== 'all') {
    console.error(`ERROR: No collections matched filter "${COLLECTION_FILTER}".`);
    process.exit(1);
  }
  console.warn('No collections found in collections/');
  process.exit(0);
}

const results = [];
const sharedEnvVars = {
  authBaseUrl:  PINNED_AUTH_BASE_URL,
  baseUrl:      process.env.BASE_URL      ||
                'https://uat-mcdp-be.omfysgroup.com',
  empCode:      process.env.EMP_CODE      || '',
  empPassword:  process.env.EMP_PASSWORD  || '',
  leaveBaseUrl: process.env.LEAVE_BASE_URL ||
                LEAVE_REPORT_BASE_URL,
  openapiSchemaBundle: OPENAPI_SCHEMA_BUNDLE_JSON
};

function runCollectionAttempt(collectionFile, attempt) {
  return new Promise((resolve) => {
    const collectionName = collectionFile.replace('.json', '');
    const collectionPath = path.join(collectionsDir, collectionFile);
    const timestamp      = Date.now();
    const testDataPath   = path.join(__dirname, '..', 'test-data', `${collectionName}.csv`);
    const htmlReportPath = path.join(
      __dirname, '..', 'reports', 'html',
      `report-${collectionName}-${timestamp}.html`
    );

    const htmlConfig = Object.assign({}, reporterConfig, {
      export: htmlReportPath
    });

    const environment = require(envFile);
    const collectionEnvVars = {
      ...sharedEnvVars,
      ...(collectionFile === 'Employee_Auth_API.json'
        ? { authBaseUrl: PINNED_AUTH_BASE_URL }
        : {}),
      ...(collectionFile === 'Leave_API.json'
        ? { leaveBaseUrl: LEAVE_REPORT_BASE_URL }
        : {})
    };
    const options = {
      collection: require(collectionPath),
      environment: {
        ...environment,
        values: environment.values.map((variable) => (
          Object.prototype.hasOwnProperty.call(collectionEnvVars, variable.key)
            ? { ...variable, value: collectionEnvVars[variable.key] }
            : variable
        ))
      },
      envVar: Object.entries(collectionEnvVars).map(
        ([key, value]) => ({ key, value })
      ),
      reporters: ['htmlextra', 'allure', 'cli'],
      reporter: {
        htmlextra: htmlConfig,
        allure: {
          export: path.join(__dirname, '..', 'reports', 'allure-results')
        }
      },
      // Abort the current attempt on transport errors so the outer retry can
      // classify the real Newman request error; assertions do not abort.
      bail: ['folder'],
      timeoutRequest: 10000,
      delayRequest:   200
    };

    let pinnedAuthAgent;
    if (collectionFile === 'Employee_Auth_API.json') {
      const authBaseUrl = new URL(PINNED_AUTH_BASE_URL);
      const usePinnedTlsAgent = (
        authBaseUrl.protocol === 'https:' &&
        authBaseUrl.hostname === PINNED_HOST
      );

      if (usePinnedTlsAgent) {
        pinnedAuthAgent = createPinnedTlsAgent({
          onPinVerified: PINNED_TLS_DEBUG
            ? ({ hostname, fingerprint }) => console.log(
                `[PINNED TLS VERIFIED] host=${hostname} sha256=${fingerprint}`
              )
            : undefined
        });
        options.requestAgents = { https: pinnedAuthAgent };
        console.log(
          `  Pinned TLS agent attached to Employee_Auth_API for ${PINNED_HOST}`
        );
      } else {
        console.log(
          `  Pinned TLS agent skipped for Employee_Auth_API; using ${PINNED_AUTH_BASE_URL}`
        );
      }
    }

    if (fs.existsSync(testDataPath)) {
      options.iterationData = testDataPath;
    }

    console.log(
      attempt === 1
        ? `\nRunning ${collectionName}`
        : `\nRunning ${collectionName} (attempt ${attempt}/${MAX_TRANSIENT_ATTEMPTS})`
    );

    newman.run(options, (err, summary) => {
      if (pinnedAuthAgent) {
        pinnedAuthAgent.destroy();
      }
      const stats    = summary ? summary.run.stats    : {};
      const failures = Array.isArray(summary?.run?.failures)
        ? summary.run.failures
        : [];
      const timings  = summary ? summary.run.timings  : {};

      const passed = stats.assertions
        ? stats.assertions.total - stats.assertions.failed
        : 0;

      const result = {
        Collection:    collectionName,
        Requests:      stats.requests   ? stats.requests.total   : 0,
        Passed:        passed,
        Failed:        stats.assertions ? stats.assertions.failed : 0,
        Skipped:       stats.requests   ? stats.requests.pending  : 0,
        'Duration(ms)': timings.completed && timings.started
          ? timings.completed - timings.started
          : 0
      };

      if (err) {
        console.error(`Newman run error in ${collectionName}: ${err.message}`);
      }

      if (failures.length > 0) {
        console.log(`Assertion failures in ${collectionName}:`);
        failures.forEach(f => {
          const msg = f.error ? f.error.message : String(f);
          console.log(`  - ${msg}`);
        });
      }

      try {
        const rawValues =
          summary?.environment?.values?.members ||
          summary?.environment?.values ||
          [];
        const members = Array.isArray(rawValues)
          ? rawValues
          : Object.values(rawValues);
        let carried = 0;
        members.forEach(v => {
          if (
            v?.key &&
            ![
              'authBaseUrl',
              'baseUrl',
              'leaveBaseUrl',
              'empCode',
              'empPassword',
              'openapiSchemaBundle'
            ].includes(v.key) &&
            v.value !== undefined &&
            v.value !== null &&
            v.value !== '' &&
            v.value !== 'undefined'
          ) {
            sharedEnvVars[v.key] = v.value;
            carried++;
          }
        });
        if (carried > 0) {
          console.log(
            `  → ${carried} env var(s) carried forward from ${collectionName}`
          );
          if (sharedEnvVars.authToken) {
            console.log(
              `  → authToken present — length: ${sharedEnvVars.authToken.length}`
            );
          }
        }
      } catch (e) {
        console.warn(
          `  ⚠ Could not carry env vars from ${collectionName}: ${e.message}`
        );
      }

      const collectionResult = {
        ...result,
        reportFile: htmlReportPath,
        _failed: result.Failed > 0 || failures.length > 0 || !!err
      };
      resolve({ collectionResult, err, summary });
    });
  });
}

async function runCollection(collectionFile) {
  const collectionName = collectionFile.replace('.json', '');

  let attempt = 1;
  while (attempt <= MAX_TRANSIENT_ATTEMPTS) {
    const attemptResult = await runCollectionAttempt(collectionFile, attempt);
    const retryDecision = classifyTransientFailure(
      attemptResult.err,
      attemptResult.summary
    );

    if (retryDecision.retryable && attempt < MAX_TRANSIENT_ATTEMPTS) {
      const delayMs = INITIAL_RETRY_DELAY_MS * (2 ** (attempt - 1));
      console.log(
        `Retrying ${collectionName}: attempt ${attempt + 1}/${MAX_TRANSIENT_ATTEMPTS}; reason: ${retryDecision.reason}; delay: ${delayMs}ms`
      );
      await wait(delayMs);
      attempt += 1;
      continue;
    }

    const retriesExhausted = retryDecision.retryable &&
      attempt === MAX_TRANSIENT_ATTEMPTS;
    if (retriesExhausted) {
      console.error(
        `Retry limit exhausted for ${collectionName} after ${MAX_TRANSIENT_ATTEMPTS} attempts; last reason: ${retryDecision.reason}`
      );
    }

    const collectionResult = {
      ...attemptResult.collectionResult,
      _failed: retriesExhausted || attemptResult.collectionResult._failed
    };
    results.push(collectionResult);
    return collectionResult;
  }

  throw new Error(`Retry loop ended unexpectedly for ${collectionName}`);
}

function markLeaveApiBlocked() {
  console.log(
    '\nBlocked Leave_API: skipped due to upstream Employee_Auth_API failure.'
  );
  results.push({
    Collection: 'Leave_API (BLOCKED: Employee_Auth_API failed)',
    Requests: 0,
    Passed: 0,
    Failed: 0,
    Skipped: 1,
    'Duration(ms)': 0,
    reportFile: '',
    _failed: false
  });
}

function writeAllureCategories() {
  const categoriesPath = path.join(
    __dirname, '..', 'reports', 'allure-results', 'categories.json'
  );
  const categories = [
    {
      name: 'Authentication and authorization',
      matchedStatuses: ['failed', 'broken'],
      messageRegex: '.*(401|403|Unauthorized|Forbidden|authToken|Bearer|Invalid credentials|missing auth).*',
      traceRegex: '.*(401|403|Unauthorized|Forbidden|authToken|Bearer|Invalid credentials|missing auth).*'
    },
    {
      name: 'JSON parsing and schema',
      matchedStatuses: ['failed', 'broken'],
      messageRegex: '.*(JSONError|Unexpected token|JSON|schema|parse|valid JSON).*',
      traceRegex: '.*(JSONError|Unexpected token|JSON|schema|parse|valid JSON).*'
    },
    {
      name: 'Client/API validation 4xx',
      matchedStatuses: ['failed', 'broken'],
      messageRegex: '.*(400|404|409|422|Bad Request|Not Found|Unprocessable).*',
      traceRegex: '.*(400|404|409|422|Bad Request|Not Found|Unprocessable).*'
    },
    {
      name: 'Server/API availability 5xx',
      matchedStatuses: ['failed', 'broken'],
      messageRegex: '.*(500|502|503|504|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout).*',
      traceRegex: '.*(500|502|503|504|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout).*'
    },
    {
      name: 'Timeouts and network',
      matchedStatuses: ['failed', 'broken'],
      messageRegex: '.*(timeout|ETIMEDOUT|ECONNRESET|ENOTFOUND|ECONNREFUSED|socket hang up).*',
      traceRegex: '.*(timeout|ETIMEDOUT|ECONNRESET|ENOTFOUND|ECONNREFUSED|socket hang up).*'
    },
    {
      name: 'Assertion failures',
      matchedStatuses: ['failed'],
      messageRegex: '.*(expected|assertion|AssertionError|Status code|Response time).*',
      traceRegex: '.*(expected|assertion|AssertionError|Status code|Response time).*'
    },
    {
      name: 'Broken tests',
      matchedStatuses: ['broken']
    }
  ];

  fs.mkdirSync(path.dirname(categoriesPath), { recursive: true });
  fs.writeFileSync(
    categoriesPath,
    `${JSON.stringify(categories, null, 2)}\n`
  );
  console.log('  OK categories.json written to allure-results');
}

async function runAll() {
  const executorPath = path.join(
    __dirname, '..', 'reports', 'allure-results', 'executor.json'
  );
  const executor = {
    name:      'Local',
    type:      'local',
    buildName: `${ENV} run — ${new Date().toISOString().slice(0,19).replace('T',' ')}`,
    buildUrl:  '',
    reportUrl: ''
  };
  fs.mkdirSync(path.dirname(executorPath), { recursive: true });
  fs.writeFileSync(executorPath, JSON.stringify(executor, null, 2));

  const envPropsPath = path.join(
    __dirname, '..', 'reports', 'allure-results',
    'environment.properties'
  );
  const envProps = [
    `ENV=${ENV}`,
    `Base URL=${process.env.BASE_URL || process.env.STAGING_BASE_URL || 'not set'}`,
    `Emp Code=${process.env.EMP_CODE ? '***' + process.env.EMP_CODE.slice(-3) : 'not set'}`,
    `Node Version=${process.version}`,
    `Newman Version=6.2.2`,
    `Platform=${process.platform}`,
    `Run Date=${new Date().toISOString().slice(0, 10)}`,
    `Run Time=${new Date().toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' })}`
  ].join('\n');
  fs.mkdirSync(path.dirname(envPropsPath), { recursive: true });
  fs.writeFileSync(envPropsPath, envProps);
  console.log('  ✓ environment.properties written to allure-results');
  writeAllureCategories();

  let authFailed = false;
  for (const file of collectionFilesFiltered) {
    if (authFailed && file === 'Leave_API.json') {
      markLeaveApiBlocked();
      continue;
    }

    const collectionResult = await runCollection(file);
    if (file === 'Employee_Auth_API.json' && collectionResult._failed) {
      authFailed = true;
    }
  }

  console.log('\nRun summary:');
  console.table(results.map(({ _failed, ...r }) => r));
  generateIndex(
    results.map(({ _failed, reportFile, ...r }) =>
      ({ ...r, reportFile }))
  );

  if (results.some(r => r._failed)) {
    process.exit(1);
  }
}

const reportsDir = path.join(__dirname, '..', 'reports');
const allureHistorySource = path.join(
  reportsDir, 'allure-report', 'history'
);
const allureHistoryDest = path.join(
  reportsDir, 'allure-results', 'history'
);

const dirsToClear = [
  path.join(reportsDir, 'html'),
  path.join(reportsDir, 'allure-results'),
  path.join(reportsDir, 'allure-report')
];

function clearDirectory(dirPath) {
  if (!fs.existsSync(dirPath)) {
    console.log(`✓ ${dirPath} does not exist`);
    return;
  }

  try {
    const files = fs.readdirSync(dirPath);
    files.forEach(file => {
      const filePath = path.join(dirPath, file);
      const stat = fs.statSync(filePath);

      if (stat.isDirectory()) {
        clearDirectory(filePath);
        fs.rmdirSync(filePath);
      } else {
        fs.unlinkSync(filePath);
      }
    });
    console.log(`✓ Cleared ${dirPath}`);
  } catch (err) {
    console.error(`✗ Error clearing ${dirPath}: ${err.message}`);
  }
}

function snapshotDirectory(dirPath, basePath = dirPath) {
  if (!fs.existsSync(dirPath)) {
    return [];
  }

  return fs.readdirSync(dirPath).flatMap(file => {
    const filePath = path.join(dirPath, file);
    const stat = fs.statSync(filePath);

    if (stat.isDirectory()) {
      return snapshotDirectory(filePath, basePath);
    }

    return [{
      relativePath: path.relative(basePath, filePath),
      content: fs.readFileSync(filePath)
    }];
  });
}

function restoreDirectory(dirPath, snapshot) {
  if (snapshot.length === 0) {
    return;
  }

  snapshot.forEach(file => {
    const filePath = path.join(dirPath, file.relativePath);
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, file.content);
  });
  console.log('  Allure history carried forward');
}

const allureHistorySnapshot = snapshotDirectory(allureHistorySource);

console.log('Clearing reports data...\n');
dirsToClear.forEach(dir => clearDirectory(dir));
restoreDirectory(allureHistoryDest, allureHistorySnapshot);
console.log('\n✓ Reports cleared');

const pendingFiles = fs.readdirSync(collectionsDir)
  .filter(f => f.includes('.pending.'));
if (pendingFiles.length > 0) {
  console.log('\nSkipped (pending real endpoints):');
  pendingFiles.forEach(f => console.log(`  ⏸  ${f}`));
}

runAll();

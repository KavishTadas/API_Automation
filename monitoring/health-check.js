require('dotenv').config();

const fs = require('fs');
const path = require('path');
const newman = require('newman');
const Ajv = require('ajv');
const YAML = require('yaml');
const {
  createPinnedTlsAgent,
  PINNED_HOST
} = require('../scripts/pinned-tls-agent');

const stripBom = value => value.replace(/^\uFEFF/, '');

const COLLECTIONS_DIR = 'collections';
const LOGS_DIR = path.join('monitoring', 'logs');
const RESPONSE_TIME_DEGRADED_MS = 2000;
const COLLECTION_RUN_ORDER = [
  'Employee_Auth_API.json',
  'Leave_API.json'
];
const ENV = process.env.ENV || 'uat';
const ENV_FILE = path.join(__dirname, '..', 'environments', `${ENV}.json`);
const LEAVE_TEST_DATA_PATH = path.join(
  __dirname,
  '..',
  'test-data',
  'Leave_API.csv'
);
const OPENAPI_SCHEMA_BUNDLE_ID =
  'https://hcm-api-automation.local/openapi-schema-bundle.json';
const REQUIRED_RESPONSE_SCHEMAS = [
  'LoginResponse',
  'ErrorResponse',
  'GetAllLeaveReportsResponse',
  'GetAllLeaveReportsErrorResponse',
  'GetAllLeaveReportsItem'
];

/**
 * Returns today's date in YYYY-MM-DD format.
 *
 * @returns {string} Current date.
 */
function getDateStamp() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Loads the selected Newman environment file.
 *
 * @returns {object|undefined} Parsed Postman environment.
 */
function loadEnvironmentFile() {
  if (!fs.existsSync(ENV_FILE)) {
    return undefined;
  }

  return JSON.parse(stripBom(fs.readFileSync(ENV_FILE, 'utf8')));
}

/**
 * Returns a defensive copy for Newman, which may mutate environment values.
 *
 * @param {object|undefined} environment Parsed Postman environment.
 * @returns {object|undefined} Cloned environment.
 */
function cloneEnvironment(environment) {
  return environment ? JSON.parse(JSON.stringify(environment)) : undefined;
}

/**
 * Extracts enabled environment values into a plain object.
 *
 * @param {object|undefined} environment Parsed Postman environment.
 * @returns {object} Environment key/value map.
 */
function extractEnvironmentValues(environment) {
  const rawValues =
    environment && environment.values && environment.values.members
      ? environment.values.members
      : environment && environment.values
        ? environment.values
        : [];
  const values = Array.isArray(rawValues) ? rawValues : Object.values(rawValues);

  return values.reduce((vars, value) => {
    if (value && value.key && value.enabled !== false) {
      vars[value.key] = value.value || '';
    }
    return vars;
  }, {});
}

/**
 * Builds the same precompiled OpenAPI schema bundle used by the main runner.
 *
 * @returns {string} Serialized schema bundle for Newman's environment.
 */
function loadOpenApiSchemaBundle() {
  const specPath = path.join(__dirname, '..', 'openapi', 'openapi.yaml');
  const document = YAML.parse(fs.readFileSync(specPath, 'utf8'));
  const schemas = document && document.components && document.components.schemas;

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

const baseEnvironment = loadEnvironmentFile();
const sharedEnvVars = {
  ...extractEnvironmentValues(baseEnvironment)
};

sharedEnvVars.baseUrl = process.env.BASE_URL || sharedEnvVars.baseUrl || '';
sharedEnvVars.authBaseUrl = process.env.AUTH_BASE_URL || sharedEnvVars.authBaseUrl || '';
sharedEnvVars.empCode = process.env.EMP_CODE || sharedEnvVars.empCode || '';
sharedEnvVars.empPassword = process.env.EMP_PASSWORD || sharedEnvVars.empPassword || '';
sharedEnvVars.leaveBaseUrl = process.env.LEAVE_BASE_URL || sharedEnvVars.leaveBaseUrl || '';
sharedEnvVars.openapiSchemaBundle = OPENAPI_SCHEMA_BUNDLE_JSON;

/**
 * Fails before Newman starts if required credentials are unavailable.
 *
 * @returns {void}
 */
function validateRequiredCredentials() {
  for (const [credential, value] of Object.entries({
    empCode: sharedEnvVars.empCode,
    empPassword: sharedEnvVars.empPassword
  })) {
    if (typeof value !== 'string' || value.trim() === '') {
      throw new Error(
        `Missing required credential ${credential} — set ${credential === 'empCode' ? 'EMP_CODE' : 'EMP_PASSWORD'} via env var before running`
      );
    }
  }
}

/**
 * Discovers JSON collection files in the collections directory.
 *
 * @returns {string[]} Collection file paths.
 */
function discoverCollections() {
  const discovered = fs
    .readdirSync(COLLECTIONS_DIR)
    .filter(f => f.endsWith('.json') && !f.includes('.pending.'))
    .sort();

  return [
    ...COLLECTION_RUN_ORDER.filter(fileName => discovered.includes(fileName)),
    ...discovered.filter(fileName => !COLLECTION_RUN_ORDER.includes(fileName))
  ].map((fileName) => path.join(COLLECTIONS_DIR, fileName));
}

/**
 * Carries non-empty environment values from a Newman summary into later runs.
 *
 * @param {object} summary Newman summary.
 * @returns {number} Number of values carried forward.
 */
function carryForwardEnvVars(summary) {
  const rawValues =
    summary && summary.environment && summary.environment.values && summary.environment.values.members
      ? summary.environment.values.members
      : summary && summary.environment && summary.environment.values
        ? summary.environment.values
        : [];
  const values = Array.isArray(rawValues) ? rawValues : Object.values(rawValues);
  let carried = 0;

  values.forEach((value) => {
    if (
      value &&
      value.key &&
      value.value !== undefined &&
      value.value !== null &&
      value.value !== '' &&
      value.value !== 'undefined'
    ) {
      sharedEnvVars[value.key] = value.value;
      carried += 1;
    }
  });

  return carried;
}

/**
 * Runs one collection with Newman.
 *
 * @param {string} collectionPath Collection file path.
 * @returns {Promise<object>} Newman summary.
 */
function runCollection(collectionPath) {
  return new Promise((resolve) => {
    const collectionFile = path.basename(collectionPath);
    const options = {
      collection: collectionPath,
      environment: cloneEnvironment(baseEnvironment),
      envVar: Object.entries(sharedEnvVars)
        .filter(([, value]) => value !== undefined && value !== null)
        .map(([key, value]) => ({ key, value })),
      timeoutRequest: 10000,
      bail: false,
      reporters: ['cli']
    };

    if (collectionFile === 'Leave_API.json') {
      options.iterationData = LEAVE_TEST_DATA_PATH;
    }

    let pinnedAuthAgent;
    if (collectionFile === 'Employee_Auth_API.json') {
      const authBaseUrl = new URL(sharedEnvVars.authBaseUrl);
      const usePinnedTlsAgent = (
        authBaseUrl.protocol === 'https:' &&
        authBaseUrl.hostname === PINNED_HOST
      );

      if (usePinnedTlsAgent) {
        pinnedAuthAgent = createPinnedTlsAgent();
        options.requestAgents = { https: pinnedAuthAgent };
        console.log(
          `Pinned TLS agent attached to Employee_Auth_API for ${PINNED_HOST}`
        );
      }
    }

    newman.run(options, (error, summary) => {
      if (pinnedAuthAgent) {
        pinnedAuthAgent.destroy();
      }

      if (error) {
        resolve({
          collectionPath,
          runError: error,
          run: {
            executions: [],
            failures: [
              {
                error,
                source: {
                  name: path.basename(collectionPath, path.extname(collectionPath))
                }
              }
            ]
          }
        });
        return;
      }

      resolve(summary);
    });
  });
}

/**
 * Finds the Newman execution associated with a failure.
 *
 * @param {object} summary Newman summary.
 * @param {object} failure Newman failure.
 * @returns {object|null} Matching execution.
 */
function findExecution(summary, failure) {
  const executions = summary.run && Array.isArray(summary.run.executions) ? summary.run.executions : [];

  if (!failure.cursor) {
    return null;
  }

  return executions.find((execution) => {
    if (!execution.cursor) {
      return false;
    }

    return execution.cursor.ref === failure.cursor.ref
      && execution.cursor.iteration === failure.cursor.iteration;
  }) || executions[failure.cursor.position] || null;
}

/**
 * Safely converts a Postman SDK URL to a string.
 *
 * @param {object} request Newman request object.
 * @returns {string|null} Request endpoint.
 */
function getEndpoint(request) {
  if (!request || !request.url) {
    return null;
  }

  return typeof request.url.toString === 'function'
    ? request.url.toString()
    : String(request.url);
}

/**
 * Creates a log entry for one Newman failure.
 *
 * @param {object} summary Newman summary.
 * @param {object} failure Newman failure.
 * @returns {object} Health log entry.
 */
function createFailureLogEntry(summary, failure) {
  const execution = findExecution(summary, failure);
  const request = execution && execution.request ? execution.request : null;
  const response = execution && execution.response ? execution.response : null;
  const error = failure.error || {};

  return {
    timestamp: new Date().toISOString(),
    collection: summary.collection && summary.collection.name
      ? summary.collection.name
      : path.basename(summary.collectionPath || 'unknown', path.extname(summary.collectionPath || 'unknown')),
    requestName: execution && execution.item ? execution.item.name : failure.source && failure.source.name || null,
    endpoint: getEndpoint(request),
    method: request && request.method ? request.method : null,
    statusCode: response && typeof response.code !== 'undefined' ? response.code : null,
    responseTimeMs: response && typeof response.responseTime !== 'undefined' ? response.responseTime : null,
    error: error.message || String(error),
    expected: typeof error.expected !== 'undefined' ? error.expected : null,
    actual: typeof error.actual !== 'undefined' ? error.actual : null
  };
}

/**
 * Reads the existing JSON log array from disk.
 *
 * @param {string} logPath Log file path.
 * @returns {object[]} Existing log entries.
 */
function readExistingLog(logPath) {
  if (!fs.existsSync(logPath)) {
    return [];
  }

  try {
    const parsed = JSON.parse(stripBom(fs.readFileSync(logPath, 'utf8')));
    if (!Array.isArray(parsed)) {
      throw new TypeError('Health log root must be a JSON array');
    }
    return parsed;
  } catch (error) {
    throw new Error(
      `Failed to parse existing health log ${logPath}: ${error.message}`,
      { cause: error }
    );
  }
}

/**
 * Appends failure entries to today's health log JSON file.
 *
 * @param {object[]} entries Failure log entries.
 * @returns {void}
 */
function appendFailureLog(entries) {
  if (entries.length === 0) {
    return;
  }

  fs.mkdirSync(LOGS_DIR, { recursive: true });
  const logPath = path.join(LOGS_DIR, `health-${getDateStamp()}.json`);
  const existingEntries = readExistingLog(logPath);
  fs.writeFileSync(logPath, `${JSON.stringify([...existingEntries, ...entries], null, 2)}\n`);
}

/**
 * Determines whether a collection has degraded response times.
 *
 * @param {object} summary Newman summary.
 * @returns {boolean} True when any response time is above the degraded threshold.
 */
function hasDegradedResponse(summary) {
  const executions = summary.run && Array.isArray(summary.run.executions) ? summary.run.executions : [];

  return executions.some((execution) => {
    const responseTime = execution.response && execution.response.responseTime;
    return typeof responseTime === 'number' && responseTime > RESPONSE_TIME_DEGRADED_MS;
  });
}

/**
 * Prints the final health summary.
 *
 * @param {{ healthy: number, degraded: number, failed: number, blocked: number }} counts Health counts.
 * @returns {void}
 */
function printSummary(counts) {
  console.log(
    `✓ HEALTHY: ${counts.healthy}  ⚠ DEGRADED: ${counts.degraded}  ✗ FAILED: ${counts.failed}  ⏸ BLOCKED: ${counts.blocked}`
  );
}

/**
 * Runs all collections and writes monitoring logs for failures.
 *
 * @returns {Promise<void>} Resolves when monitoring completes.
 */
async function main() {
  validateRequiredCredentials();
  if (!fs.existsSync(LEAVE_TEST_DATA_PATH)) {
    throw new Error(
      'Leave monitoring data is missing: test-data/Leave_API.csv'
    );
  }

  const collections = discoverCollections();
  const counts = {
    healthy: 0,
    degraded: 0,
    failed: 0,
    blocked: 0
  };
  let authFailed = false;

  for (const collectionPath of collections) {
    const collectionFile = path.basename(collectionPath);
    if (authFailed && collectionFile === 'Leave_API.json') {
      const blockedMessage =
        'Blocked Leave_API: skipped due to upstream Employee_Auth_API failure.';
      console.log(`\n${blockedMessage}`);
      appendFailureLog([
        {
          timestamp: new Date().toISOString(),
          collection: 'Leave_API',
          requestName: null,
          endpoint: null,
          method: null,
          statusCode: null,
          responseTimeMs: null,
          error: blockedMessage,
          expected: null,
          actual: null
        }
      ]);
      counts.blocked += 1;
      continue;
    }

    const summary = await runCollection(collectionPath);
    carryForwardEnvVars(summary);
    const failures = summary.run && Array.isArray(summary.run.failures) ? summary.run.failures : [];

    appendFailureLog(failures.map((failure) => createFailureLogEntry(summary, failure)));

    if (failures.length > 0) {
      counts.failed += 1;
      if (collectionFile === 'Employee_Auth_API.json') {
        authFailed = true;
      }
    } else if (hasDegradedResponse(summary)) {
      counts.degraded += 1;
    } else {
      counts.healthy += 1;
    }
  }

  printSummary(counts);
  process.exit(counts.failed === 0 && counts.blocked === 0 ? 0 : 1);
}

main().catch((error) => {
  try {
    appendFailureLog([
      {
        timestamp: new Date().toISOString(),
        collection: null,
        requestName: null,
        endpoint: null,
        method: null,
        statusCode: null,
        responseTimeMs: null,
        error: error.message || String(error),
        expected: null,
        actual: null
      }
    ]);
  } catch (logError) {
    console.error(`Could not append monitoring failure log: ${logError.message}`);
  }
  console.error(error.message || error);
  console.log('✓ HEALTHY: 0  ⚠ DEGRADED: 0  ✗ FAILED: 1  ⏸ BLOCKED: 0');
  process.exit(1);
});

require('dotenv').config();

const fs = require('fs');
const path = require('path');
const newman = require('newman');

const COLLECTIONS_DIR = 'collections';
const LOGS_DIR = path.join('monitoring', 'logs');
const RESPONSE_TIME_DEGRADED_MS = 2000;

/**
 * Returns today's date in YYYY-MM-DD format.
 *
 * @returns {string} Current date.
 */
function getDateStamp() {
  return new Date().toISOString().slice(0, 10);
}

/**
 * Discovers JSON collection files in the collections directory.
 *
 * @returns {string[]} Collection file paths.
 */
function discoverCollections() {
  return fs
    .readdirSync(COLLECTIONS_DIR)
    .filter((fileName) => fileName.toLowerCase().endsWith('.json'))
    .sort()
    .map((fileName) => path.join(COLLECTIONS_DIR, fileName));
}

/**
 * Runs one collection with Newman.
 *
 * @param {string} collectionPath Collection file path.
 * @returns {Promise<object>} Newman summary.
 */
function runCollection(collectionPath) {
  return new Promise((resolve) => {
    newman.run(
      {
        collection: collectionPath,
        timeoutRequest: 10000,
        bail: false,
        reporters: ['cli']
      },
      (error, summary) => {
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
      }
    );
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
    const parsed = JSON.parse(fs.readFileSync(logPath, 'utf8'));
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
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
 * @param {{ healthy: number, degraded: number, failed: number }} counts Health counts.
 * @returns {void}
 */
function printSummary(counts) {
  console.log(`✓ HEALTHY: ${counts.healthy}  ⚠ DEGRADED: ${counts.degraded}  ✗ FAILED: ${counts.failed}`);
}

/**
 * Runs all collections and writes monitoring logs for failures.
 *
 * @returns {Promise<void>} Resolves when monitoring completes.
 */
async function main() {
  const collections = discoverCollections();
  const counts = {
    healthy: 0,
    degraded: 0,
    failed: 0
  };

  for (const collectionPath of collections) {
    const summary = await runCollection(collectionPath);
    const failures = summary.run && Array.isArray(summary.run.failures) ? summary.run.failures : [];

    appendFailureLog(failures.map((failure) => createFailureLogEntry(summary, failure)));

    if (failures.length > 0) {
      counts.failed += 1;
    } else if (hasDegradedResponse(summary)) {
      counts.degraded += 1;
    } else {
      counts.healthy += 1;
    }
  }

  printSummary(counts);
  process.exit(counts.failed === 0 ? 0 : 1);
}

main().catch((error) => {
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
  console.error(error.message || error);
  console.log('✓ HEALTHY: 0  ⚠ DEGRADED: 0  ✗ FAILED: 1');
  process.exit(1);
});

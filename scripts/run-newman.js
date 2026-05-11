require('dotenv').config();

const fs = require('fs');
const path = require('path');
const newman = require('newman');
const reporterConfig = require('./reporter-config');

const COLLECTIONS_DIR = 'collections';
const ENVIRONMENTS_DIR = 'environments';
const TEST_DATA_DIR = 'test-data';
const HTML_REPORT_DIR = path.join('reports', 'html');
const ALLURE_RESULTS_DIR = path.join('reports', 'allure-results');

/**
 * Gets the target environment name from process.env.ENV.
 *
 * @returns {string} Environment name to execute against.
 */
function getTargetEnvironment() {
  return process.env.ENV || 'local';
}

/**
 * Builds the Postman/Newman environment file path for a target environment.
 *
 * @param {string} targetEnvironment Environment name.
 * @returns {string} Relative environment file path.
 */
function getEnvironmentPath(targetEnvironment) {
  return path.join(ENVIRONMENTS_DIR, `${targetEnvironment}.json`);
}

/**
 * Exits the process when the target environment file is missing.
 *
 * @param {string} environmentPath Relative environment file path.
 * @returns {void}
 */
function exitIfEnvironmentMissing(environmentPath) {
  if (!fs.existsSync(environmentPath)) {
    console.error(`ERROR: Environment file not found: ${environmentPath} — did you copy .env.example to .env?`);
    process.exit(1);
  }
}

/**
 * Discovers JSON collection files from the collections directory.
 *
 * @returns {string[]} Sorted collection file paths.
 */
function discoverCollections() {
  if (!fs.existsSync(COLLECTIONS_DIR)) {
    console.warn('No collections found in collections/');
    return [];
  }

  return fs
    .readdirSync(COLLECTIONS_DIR)
    .filter((fileName) => fileName.toLowerCase().endsWith('.json'))
    .sort()
    .map((fileName) => path.join(COLLECTIONS_DIR, fileName));
}

/**
 * Ensures all generated report directories exist before a Newman run starts.
 *
 * @returns {void}
 */
function ensureReportDirectories() {
  fs.mkdirSync(HTML_REPORT_DIR, { recursive: true });
  fs.mkdirSync(ALLURE_RESULTS_DIR, { recursive: true });
}

/**
 * Gets the collection name from a collection file path.
 *
 * @param {string} collectionPath Collection file path.
 * @returns {string} Collection file name without extension.
 */
function getCollectionName(collectionPath) {
  return path.basename(collectionPath, path.extname(collectionPath));
}

/**
 * Finds CSV iteration data for a collection when it exists.
 *
 * @param {string} collectionName Collection name without extension.
 * @returns {string|undefined} CSV data file path, if present.
 */
function getIterationDataPath(collectionName) {
  const dataPath = path.join(TEST_DATA_DIR, `${collectionName}.csv`);
  return fs.existsSync(dataPath) ? dataPath : undefined;
}

/**
 * Creates reporter options for a collection run.
 *
 * @param {string} collectionName Collection name without extension.
 * @returns {object} Newman reporter configuration.
 */
function createReporterOptions(collectionName) {
  return {
    htmlextra: {
      ...reporterConfig,
      export: path.join(HTML_REPORT_DIR, `report-${collectionName}-${Date.now()}.html`)
    },
    allure: {
      resultsDir: ALLURE_RESULTS_DIR
    }
  };
}

/**
 * Creates Newman run options for one collection.
 *
 * @param {string} collectionPath Collection file path.
 * @param {string} environmentPath Environment file path.
 * @returns {object} Newman run options.
 */
function createNewmanOptions(collectionPath, environmentPath) {
  const collectionName = getCollectionName(collectionPath);
  const iterationData = getIterationDataPath(collectionName);
  const options = {
    collection: collectionPath,
    environment: environmentPath,
    reporters: ['htmlextra', 'allure'],
    reporter: createReporterOptions(collectionName),
    timeoutRequest: 10000,
    delayRequest: 200
  };

  if (iterationData) {
    options.iterationData = iterationData;
  }

  return options;
}

/**
 * Runs a Newman collection and resolves with its summary.
 *
 * @param {string} collectionPath Collection file path.
 * @param {string} environmentPath Environment file path.
 * @returns {Promise<object>} Newman run summary.
 */
function runCollection(collectionPath, environmentPath) {
  return new Promise((resolve, reject) => {
    newman.run(createNewmanOptions(collectionPath, environmentPath), (error, summary) => {
      if (error) {
        reject({
          type: 'run-error',
          collection: getCollectionName(collectionPath),
          error
        });
        return;
      }

      resolve(summary);
    });
  });
}

/**
 * Gets the elapsed run duration from a Newman summary.
 *
 * @param {object} summary Newman run summary.
 * @returns {number} Run duration in milliseconds.
 */
function getDuration(summary) {
  const started = summary.run && summary.run.timings && summary.run.timings.started;
  const completed = summary.run && summary.run.timings && summary.run.timings.completed;
  return started && completed ? completed - started : 0;
}

/**
 * Converts a Newman summary into one row for the final console table.
 *
 * @param {object} summary Newman run summary.
 * @returns {object} Summary table row.
 */
function createSummaryRow(summary) {
  const collectionName = summary.collection && summary.collection.name
    ? summary.collection.name
    : getCollectionName(summary.collection.id || 'unknown');
  const assertionStats = summary.run.stats.assertions || {};
  const failed = assertionStats.failed || 0;
  const skipped = assertionStats.pending || 0;
  const total = assertionStats.total || 0;

  return {
    Collection: collectionName,
    Requests: (summary.run.stats.requests && summary.run.stats.requests.total) || 0,
    Passed: Math.max(total - failed - skipped, 0),
    Failed: failed,
    Skipped: skipped,
    'Duration(ms)': getDuration(summary)
  };
}

/**
 * Separates Newman assertion failures from non-assertion run failures.
 *
 * @param {object[]} failures Newman failure list.
 * @returns {{ assertionFailures: object[], runFailures: object[] }} Classified failures.
 */
function classifyFailures(failures) {
  return failures.reduce(
    (classified, failure) => {
      if (failure.error && failure.error.name === 'AssertionError') {
        classified.assertionFailures.push(failure);
      } else {
        classified.runFailures.push(failure);
      }

      return classified;
    },
    { assertionFailures: [], runFailures: [] }
  );
}

/**
 * Logs Newman run failures that are not assertion failures.
 *
 * @param {string} collectionName Collection name.
 * @param {object[]} runFailures Non-assertion failures.
 * @returns {void}
 */
function logRunFailures(collectionName, runFailures) {
  if (runFailures.length === 0) {
    return;
  }

  console.error(`\nNewman run failures in ${collectionName}:`);
  runFailures.forEach((failure) => {
    console.error(`- ${failure.error && failure.error.message ? failure.error.message : 'Unknown run failure'}`);
  });
}

/**
 * Logs Newman assertion failures separately from run failures.
 *
 * @param {string} collectionName Collection name.
 * @param {object[]} assertionFailures Assertion failures.
 * @returns {void}
 */
function logAssertionFailures(collectionName, assertionFailures) {
  if (assertionFailures.length === 0) {
    return;
  }

  console.error(`\nAssertion failures in ${collectionName}:`);
  assertionFailures.forEach((failure) => {
    console.error(`- ${failure.error && failure.error.message ? failure.error.message : 'Unknown assertion failure'}`);
  });
}

/**
 * Prints the final collection execution summary table.
 *
 * @param {object[]} rows Summary table rows.
 * @returns {void}
 */
function printSummaryTable(rows) {
  console.log('\nRun summary:');
  console.table(rows);
}

/**
 * Executes all discovered collections sequentially.
 *
 * @returns {Promise<void>} Resolves after all collections have run.
 */
async function main() {
  const targetEnvironment = getTargetEnvironment();
  const environmentPath = getEnvironmentPath(targetEnvironment);
  exitIfEnvironmentMissing(environmentPath);

  const collectionPaths = discoverCollections();
  if (collectionPaths.length === 0) {
    console.warn('No collections found in collections/');
    process.exit(0);
  }

  ensureReportDirectories();

  const summaryRows = [];
  let hasFailures = false;

  for (const collectionPath of collectionPaths) {
    const collectionName = getCollectionName(collectionPath);
    console.log(`Running ${collectionName}`);

    try {
      const summary = await runCollection(collectionPath, environmentPath);
      const failures = summary.run.failures || [];
      const { assertionFailures, runFailures } = classifyFailures(failures);

      summaryRows.push(createSummaryRow(summary));
      logRunFailures(collectionName, runFailures);
      logAssertionFailures(collectionName, assertionFailures);

      if (failures.length > 0) {
        hasFailures = true;
      }
    } catch (errorDetails) {
      hasFailures = true;
      summaryRows.push({
        Collection: errorDetails.collection || collectionName,
        Requests: 0,
        Passed: 0,
        Failed: 1,
        Skipped: 0,
        'Duration(ms)': 0
      });

      if (errorDetails.type === 'run-error') {
        console.error(`\nNewman run error in ${errorDetails.collection}:`);
        console.error(errorDetails.error && errorDetails.error.message ? errorDetails.error.message : errorDetails.error);
      } else {
        console.error(`\nUnexpected runner error in ${collectionName}:`);
        console.error(errorDetails);
      }
    }
  }

  printSummaryTable(summaryRows);

  if (hasFailures) {
    process.exit(1);
  }
}

main();

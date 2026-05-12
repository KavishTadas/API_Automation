require('dotenv').config();
const newman   = require('newman');
const fs       = require('fs');
const path     = require('path');
const reporterConfig = require('./reporter-config');

const ENV     = process.env.ENV || 'local';
const envFile = path.join(__dirname, '..', 'environments', `${ENV}.json`);

if (!fs.existsSync(envFile)) {
  console.error(`ERROR: Environment file not found: environments/${ENV}.json`);
  process.exit(1);
}

const collectionsDir  = path.join(__dirname, '..', 'collections');
const collectionFiles = fs.readdirSync(collectionsDir)
  .filter(f => f.endsWith('.json') && !f.includes('.pending.'));

if (collectionFiles.length === 0) {
  console.warn('No collections found in collections/');
  process.exit(0);
}

const results = [];

function runCollection(collectionFile) {
  return new Promise((resolve) => {
    const collectionName = collectionFile.replace('.json', '');
    const collectionPath = path.join(collectionsDir, collectionFile);
    const timestamp      = Date.now();
    const testDataPath   = path.join(__dirname, '..', 'test-data', `${collectionName}.csv`);

    const htmlConfig = Object.assign({}, reporterConfig, {
      export: path.join(
        __dirname, '..', 'reports', 'html',
        `report-${collectionName}-${timestamp}.html`
      )
    });

    const options = {
      collection:   require(collectionPath),
      environment:  require(envFile),
      envVar: [
        { key: 'empCode',     value: process.env.EMP_CODE     || '' },
        { key: 'empPassword', value: process.env.EMP_PASSWORD || '' }
      ],
      reporters: ['htmlextra', 'allure', 'cli'],
      reporter: {
        htmlextra: htmlConfig,
        allure: {
          export: path.join(__dirname, '..', 'reports', 'allure-results')
        }
      },
      timeoutRequest: 10000,
      delayRequest:   200
    };

    if (fs.existsSync(testDataPath)) {
      options.iterationData = testDataPath;
    }

    console.log(`\nRunning ${collectionName}`);

    newman.run(options, (err, summary) => {
      const stats    = summary ? summary.run.stats    : {};
      const failures = summary ? summary.run.failures : [];
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

      results.push({ ...result, _failed: result.Failed > 0 || !!err });
      resolve();
    });
  });
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

  for (const file of collectionFiles) {
    await runCollection(file);
  }

  console.log('\nRun summary:');
  console.table(results.map(({ _failed, ...r }) => r));

  if (results.some(r => r._failed)) {
    process.exit(1);
  }
}

const reportsDir = path.join(__dirname, '..', 'reports');

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

console.log('Clearing reports data...\n');
dirsToClear.forEach(dir => clearDirectory(dir));
console.log('\n✓ Reports cleared');

const pendingFiles = fs.readdirSync(collectionsDir)
  .filter(f => f.includes('.pending.'));
if (pendingFiles.length > 0) {
  console.log('\nSkipped (pending real endpoints):');
  pendingFiles.forEach(f => console.log(`  ⏸  ${f}`));
}

runAll();

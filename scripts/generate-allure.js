const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const { annotateAuthFailure } = require('./allure-category-classifier');

const projectRoot = path.resolve(__dirname, '..');
const allureResultsDir = path.join(projectRoot, 'reports', 'allure-results');
const generatedSubDir = path.join(allureResultsDir, 'generated-tests');
const DEFAULT_MODULE = 'API Module';
const DEFAULT_FEATURE = 'POST /api/v1/endpoint';
const LEGACY_INFERRED_UMBRELLAS = new Set([
  DEFAULT_MODULE,
  'Employee Auth API',
  'Leave Management API',
  'Attendance Management API'
]);

function labelValue(data, name) {
  const label = (data.labels || []).find((item) => item.name === name);
  return label ? label.value : '';
}

function replaceLabel(data, name, value) {
  if (!value || labelValue(data, name) === value) {
    return;
  }

  data.labels = (data.labels || []).filter((label) => label.name !== name);
  data.labels.push({ name, value });
}

function setLabelIfMissing(data, name, value) {
  if (value && !labelValue(data, name)) {
    data.labels.push({ name, value });
  }
}

function displayIdentity(identity) {
  return path.basename(identity, path.extname(identity))
    .replace(/_/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function isPlaceholder(value) {
  return !value || value === DEFAULT_MODULE || value === DEFAULT_FEATURE;
}

function isTechnicalSuite(value) {
  return !value ||
    /^(tests?(\.|$)|test_)|auto_generated|global_contract/i.test(value);
}

function buildContainerIdentityMap() {
  const identities = new Map();

  fs.readdirSync(allureResultsDir)
    .filter((file) => file.endsWith('-container.json'))
    .forEach((file) => {
      try {
        const container = JSON.parse(
          fs.readFileSync(path.join(allureResultsDir, file), 'utf8')
        );
        (container.children || []).forEach((uuid) => {
          if (container.name && !identities.has(uuid)) {
            identities.set(uuid, container.name);
          }
        });
      } catch (error) {
        console.warn(`Could not read Allure container ${file}:`, error.message);
      }
    });

  return identities;
}

const generatedSourceCache = new Map();

function generatedSourceMetadata(data) {
  const match = (data.fullName || '').match(
    /^build\.auto_generated\.([^#]+)#/
  );
  if (!match) {
    return null;
  }

  const modulePath = match[1];
  if (generatedSourceCache.has(modulePath)) {
    return generatedSourceCache.get(modulePath);
  }

  const sourcePath = path.join(
    projectRoot,
    'tests',
    'auto_generated',
    `${modulePath}.py`
  );
  let metadata = null;

  try {
    const source = fs.readFileSync(sourcePath, 'utf8');
    const apiMatch = source.match(
      /API\s*=\s*json\.loads\(r"""([\s\S]*?)"""\)/
    );
    if (apiMatch) {
      const api = JSON.parse(apiMatch[1]);
      metadata = {
        moduleName: api['Module Name'] || '',
        method: api['HTTP Method'] || '',
        endpoint: api['Endpoint / Path'] || '',
        subModule: api['Sub-Module Name'] || ''
      };
    }
  } catch (error) {
    console.warn(
      `Could not recover generated-test provenance from ${sourcePath}:`,
      error.message
    );
  }

  generatedSourceCache.set(modulePath, metadata);
  return metadata;
}

function requestIdentity(data) {
  let method = '';
  let endpoint = '';
  const parameters = data.parameters || [];
  const operationCase = parameters.find(
    (parameter) => parameter.name === 'operation_case'
  );
  const operationMatch = String(operationCase?.value || '').match(
    /method='([A-Z]+)',\s*path='([^']+)'/
  );

  if (operationMatch) {
    method = operationMatch[1];
    endpoint = operationMatch[2];
  }

  const requestParameter = parameters.find(
    (parameter) =>
      parameter.name === 'Request' || parameter.name === 'HTTP Method'
  );
  const requestValue = String(requestParameter?.value || '');
  const separatorIndex = requestValue.indexOf(' - ');

  if (separatorIndex > 0) {
    method = requestValue.slice(0, separatorIndex).trim();
    const rawUrl = requestValue.slice(separatorIndex + 3).trim();
    try {
      endpoint = new URL(rawUrl).pathname;
    } catch (error) {
      endpoint = rawUrl;
    }
  } else if (/^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)$/.test(requestValue.trim())) {
    method = requestValue.trim();
  }

  const endpointParameter = parameters.find(
    (parameter) => parameter.name === 'Endpoint Path'
  );
  if (endpointParameter?.value) {
    endpoint = String(endpointParameter.value);
  }

  const generatedMetadata = generatedSourceMetadata(data);
  method ||= generatedMetadata?.method || '';
  endpoint ||= generatedMetadata?.endpoint || '';

  const existingFeature = labelValue(data, 'feature');
  const featureMatch = existingFeature.match(
    /^(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\/\S+)/
  );
  if (featureMatch && !endpoint) {
    method = featureMatch[1];
    endpoint = featureMatch[2];
  }

  const nameMatch = (data.name || '').match(
    /\[(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\s+(\/[^\]]+)\]/
  );
  if (nameMatch && !endpoint) {
    method = nameMatch[1];
    endpoint = nameMatch[2];
  }

  if (endpoint === '/api/v1/endpoint') {
    endpoint = '';
  }

  if (data.name === 'test_small_burst_does_not_trigger_immediate_blocking') {
    method = 'GET';
    endpoint = '/user/leaves/getAllLeaveReports';
  } else if (
    data.name === 'test_live_request_succeeds_through_current_certificate_pin'
  ) {
    method = 'POST';
    endpoint = '/auth/token';
  }

  return { method: method || 'POST', endpoint };
}

function inferredModuleName(data, endpoint) {
  const searchable = `${endpoint} ${data.name || ''} ${data.fullName || ''}`;

  if (endpoint.includes('/auth/token') || /auth|token|login/i.test(searchable)) {
    return 'Employee Auth API';
  }
  if (
    endpoint.includes('/user/leaves/') ||
    /leave|getAllLeaveReports|showleavereport/i.test(searchable)
  ) {
    return 'Leave Management API';
  }
  if (/attendance|threshold|holiday|lateearly|weekoff/i.test(searchable)) {
    return 'Attendance Management API';
  }
  return DEFAULT_MODULE;
}

function resolvedFeature(data, request, fallback) {
  if (request.endpoint) {
    return `${request.method} ${request.endpoint}`;
  }
  const existing = labelValue(data, 'feature');
  return !isPlaceholder(existing) ? existing : fallback;
}

function applySourceHierarchy(data, umbrella, feature, options = {}) {
  const { forceUmbrella = false } = options;
  ['epic', 'parentSuite'].forEach((labelName) => {
    const existing = labelValue(data, labelName);
    const inferredConflict = existing !== umbrella &&
      LEGACY_INFERRED_UMBRELLAS.has(existing);

    if (
      forceUmbrella ||
      !existing ||
      isTechnicalSuite(existing) ||
      inferredConflict
    ) {
      replaceLabel(data, labelName, umbrella);
    }
  });
  if (isPlaceholder(labelValue(data, 'feature'))) {
    replaceLabel(data, 'feature', feature);
  }

  const suite = labelValue(data, 'suite');
  if (isTechnicalSuite(suite) || isPlaceholder(suite)) {
    replaceLabel(data, 'suite', feature);
  }

  setLabelIfMissing(data, 'story', data.name || feature);
  setLabelIfMissing(data, 'subSuite', labelValue(data, 'story'));
}

function prepareAllureResults() {
  if (!fs.existsSync(allureResultsDir)) {
    fs.mkdirSync(allureResultsDir, { recursive: true });
  }

  if (fs.existsSync(generatedSubDir)) {
    const files = fs.readdirSync(generatedSubDir);
    files.forEach(file => {
      const src = path.join(generatedSubDir, file);
      const dest = path.join(allureResultsDir, file);
      if (fs.lstatSync(src).isFile()) {
        try {
          fs.renameSync(src, dest);
        } catch (e) {
          fs.copyFileSync(src, dest);
        }
      }
    });
  }

  const resultFiles = fs.readdirSync(allureResultsDir)
    .filter(f => f.endsWith('-result.json'));
  const containerIdentityByUuid = buildContainerIdentityMap();

  let processedCount = 0;
  const authClassifications = {};
  resultFiles.forEach(file => {
    const filePath = path.join(allureResultsDir, file);
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const data = JSON.parse(content);

      const name = data.name || '';
      const fullName = data.fullName || '';

      // Purge skipped/ignored unverified endpoint results per user request
      if (data.status === 'skipped' || name.includes('users_me') || fullName.includes('unverified_endpoints') || name.includes('unverified')) {
        try {
          fs.unlinkSync(filePath);
        } catch (e) {}
        return;
      }

      data.labels = data.labels || [];
      const request = requestIdentity(data);
      const generatedMetadata = generatedSourceMetadata(data);
      const sourceCollection = labelValue(data, 'sourceCollection');
      const sourceModule = labelValue(data, 'sourceModule') ||
        generatedMetadata?.moduleName || '';
      const isGlobalContract = fullName.startsWith('tests.global_contract.');
      const isSecurity = fullName.startsWith('tests.security.');
      const isAutoGenerated = fullName.startsWith('build.auto_generated.');
      const legacyNewmanCollection = !fullName.startsWith('tests.')
        ? containerIdentityByUuid.get(data.uuid) || ''
        : '';
      let moduleName = '';
      let apiFeatureName = '';

      if (isGlobalContract) {
        moduleName = 'Global Contract Checks';
        apiFeatureName = resolvedFeature(
          data,
          request,
          'Cross-cutting API behavior'
        );
        replaceLabel(data, 'sourceType', 'Python global-contract');
        applySourceHierarchy(data, moduleName, apiFeatureName, {
          forceUmbrella: true
        });
      } else if (isSecurity) {
        moduleName = 'Security & TLS Pinning';
        const fallback = name ===
          'test_wrong_certificate_pin_fails_closed_without_network'
          ? 'Offline certificate pin enforcement'
          : 'TLS certificate pinning';
        apiFeatureName = resolvedFeature(data, request, fallback);
        replaceLabel(data, 'sourceType', 'Python security');
        applySourceHierarchy(data, moduleName, apiFeatureName, {
          forceUmbrella: true
        });
      } else if (isAutoGenerated && sourceModule) {
        moduleName = sourceModule;
        const generatedFeature = generatedMetadata
          ? [
              generatedMetadata.method,
              generatedMetadata.endpoint,
              generatedMetadata.subModule
                ? `— ${generatedMetadata.subModule}`
                : ''
            ].filter(Boolean).join(' ')
          : '';
        apiFeatureName = labelValue(data, 'feature') ||
          generatedFeature ||
          resolvedFeature(data, request, name);
        replaceLabel(data, 'sourceModule', sourceModule);
        replaceLabel(data, 'sourceType', 'Python auto-generated');
        applySourceHierarchy(data, moduleName, apiFeatureName);
      } else if (sourceCollection || legacyNewmanCollection) {
        const collectionIdentity = sourceCollection || legacyNewmanCollection;
        moduleName = displayIdentity(collectionIdentity);
        apiFeatureName = labelValue(data, 'feature') ||
          resolvedFeature(data, request, name);
        replaceLabel(data, 'sourceCollection', collectionIdentity);
        replaceLabel(data, 'sourceType', 'Newman');
        applySourceHierarchy(data, moduleName, apiFeatureName);
      } else {
        // Compatibility fallback for results with no source provenance at all.
        moduleName = labelValue(data, 'epic') ||
          labelValue(data, 'parentSuite') ||
          inferredModuleName(data, request.endpoint);
        apiFeatureName = resolvedFeature(data, request, DEFAULT_FEATURE);
        setLabelIfMissing(data, 'epic', moduleName);
        setLabelIfMissing(data, 'feature', apiFeatureName);
        setLabelIfMissing(data, 'story', name);
        setLabelIfMissing(data, 'parentSuite', moduleName);
        setLabelIfMissing(data, 'suite', apiFeatureName);
        setLabelIfMissing(data, 'subSuite', name);
      }

      // Populate statusDetails message so categories.json messageRegex can match passed and failed tests
      data.statusDetails = data.statusDetails || {};
      if (!data.statusDetails.message) {
        data.statusDetails.message = `[${moduleName}] ${apiFeatureName} - ${name}`;
      }

      const authClassification = annotateAuthFailure(data, allureResultsDir);
      if (authClassification) {
        authClassifications[authClassification] =
          (authClassifications[authClassification] || 0) + 1;
      }

      fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
      processedCount++;
    } catch (e) {
      console.warn(`Failed to post-process Allure result ${file}:`, e.message);
    }
  });

  console.log(`Preprocessed ${resultFiles.length} Allure result files (${processedCount} updated with Epic/Feature/Story labels).`);
  if (Object.keys(authClassifications).length > 0) {
    console.log('Auth/infrastructure failure classifications:', authClassifications);
  }
}

prepareAllureResults();

const allureDist = path.join(projectRoot, 'node_modules', 'allure-commandline', 'dist');
const allureBin = process.platform === 'win32'
  ? 'java'
  : path.join(projectRoot, 'node_modules', '.bin', 'allure');
const allureArgs = process.platform === 'win32'
  ? [
      '-classpath',
      `${path.join(allureDist, 'lib', '*')};${path.join(allureDist, 'lib', 'config')}`,
      'io.qameta.allure.CommandLine'
    ]
  : [];

console.log('Generating Allure HTML report...');
const result = spawnSync(
  allureBin,
  [...allureArgs, 'generate', 'reports/allure-results', '--clean',
   '-o', 'reports/allure-report'],
  { stdio: 'inherit', shell: false, cwd: projectRoot }
);

if (result.status === 0) {
  console.log('Allure report generated: reports/allure-report/index.html');
} else {
  console.error('Allure generation failed with status:', result.status);
  process.exit(result.status || 1);
}



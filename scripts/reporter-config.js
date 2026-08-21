const fs = require('fs');
const path = require('path');
const { FileSystemAllureWriter } = require('allure-js-commons');

const REDACTED = '***REDACTED***';
const SENSITIVE_KEY_PATTERN =
  /(authorization|emp[_.-]*code|emp[_.-]*password|password|secret|token)/i;
const SENSITIVE_KEY_SOURCE =
  '[A-Za-z0-9_.-]*' +
  '(?:authorization|emp[_.-]*code|emp[_.-]*password|password|secret|token)' +
  '[A-Za-z0-9_.-]*';
const REPORTS_DIR = path.resolve(__dirname, '..', 'reports');
const PATCH_MARKER = Symbol.for('hcm-api-automation.report-redaction');

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function redactObject(value) {
  if (Array.isArray(value)) {
    return value.map(redactObject);
  }

  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [
        key,
        SENSITIVE_KEY_PATTERN.test(key) ? REDACTED : redactObject(child)
      ])
    );
  }

  return value;
}

function redactStructuredJson(text) {
  const trimmed = text.trim();

  if (
    !trimmed ||
    !(
      (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
      (trimmed.startsWith('[') && trimmed.endsWith(']'))
    )
  ) {
    return null;
  }

  try {
    return JSON.stringify(redactObject(JSON.parse(trimmed)), null, 2);
  } catch (error) {
    return null;
  }
}

function redactKnownValues(text) {
  return Object.entries(process.env)
    .filter(([key, value]) =>
      SENSITIVE_KEY_PATTERN.test(key) &&
      typeof value === 'string' &&
      value.length > 0
    )
    .sort((left, right) => right[1].length - left[1].length)
    .reduce(
      (result, [, value]) =>
        result.replace(new RegExp(escapeRegExp(value), 'g'), REDACTED),
      text
    );
}

function redactText(text) {
  const structured = redactStructuredJson(text);

  if (structured !== null) {
    return redactKnownValues(structured);
  }

  let redacted = redactKnownValues(text);

  redacted = redacted.replace(
    new RegExp(
      `((?:"|')${SENSITIVE_KEY_SOURCE}(?:"|')\\s*:\\s*)` +
      `(?:"(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*'|[^,}\\]\\r\\n<]+)`,
      'gi'
    ),
    `$1"${REDACTED}"`
  );
  redacted = redacted.replace(
    new RegExp(
      `(&quot;${SENSITIVE_KEY_SOURCE}&quot;\\s*:\\s*&quot;)` +
      '[\\s\\S]*?(&quot;)',
      'gi'
    ),
    `$1${REDACTED}$2`
  );
  redacted = redacted.replace(
    new RegExp(
      `(<td[^>]*>\\s*${SENSITIVE_KEY_SOURCE}\\s*</td>\\s*<td[^>]*>)` +
      '[\\s\\S]*?(</td>)',
      'gi'
    ),
    `$1${REDACTED}$2`
  );
  redacted = redacted.replace(
    new RegExp(
      `(\\b${SENSITIVE_KEY_SOURCE}\\b\\s*[:=]\\s*)` +
      `(?:"(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*'|[^\\s,;&<]+)`,
      'gi'
    ),
    `$1${REDACTED}`
  );
  redacted = redacted.replace(
    /\bBearer\s+[A-Za-z0-9._~+/-]+=*/gi,
    `Bearer ${REDACTED}`
  );

  return redacted;
}

function isReportPath(filePath) {
  if (
    typeof filePath !== 'string' &&
    !Buffer.isBuffer(filePath) &&
    !(filePath instanceof URL)
  ) {
    return false;
  }

  const resolved = path.resolve(filePath.toString());
  return resolved === REPORTS_DIR ||
    resolved.startsWith(`${REPORTS_DIR}${path.sep}`);
}

function redactReportContent(filePath, content) {
  if (!isReportPath(filePath)) {
    return content;
  }

  if (typeof content === 'string') {
    return redactText(content);
  }

  if (Buffer.isBuffer(content) || content instanceof Uint8Array) {
    const original = Buffer.from(content);
    const decoded = original.toString('utf8');
    const redacted = redactText(decoded);

    return redacted === decoded ? content : Buffer.from(redacted, 'utf8');
  }

  return content;
}

function installReportRedaction() {
  if (fs[PATCH_MARKER]) {
    return;
  }

  Object.defineProperty(fs, PATCH_MARKER, {
    value: true,
    enumerable: false
  });

  ['writeFileSync', 'appendFileSync'].forEach((methodName) => {
    const original = fs[methodName].bind(fs);

    fs[methodName] = (filePath, content, ...args) =>
      original(filePath, redactReportContent(filePath, content), ...args);
  });

  ['writeFile', 'appendFile'].forEach((methodName) => {
    const original = fs[methodName].bind(fs);

    fs[methodName] = (filePath, content, ...args) =>
      original(filePath, redactReportContent(filePath, content), ...args);
  });

  if (fs.promises && typeof fs.promises.writeFile === 'function') {
    const original = fs.promises.writeFile.bind(fs.promises);

    fs.promises.writeFile = (filePath, content, ...args) =>
      original(filePath, redactReportContent(filePath, content), ...args);
  }

  if (fs.promises && typeof fs.promises.appendFile === 'function') {
    const original = fs.promises.appendFile.bind(fs.promises);

    fs.promises.appendFile = (filePath, content, ...args) =>
      original(filePath, redactReportContent(filePath, content), ...args);
  }
}

installReportRedaction();

function replaceLabel(labels, name, value) {
  return [
    ...(Array.isArray(labels)
      ? labels.filter((label) => label.name !== name)
      : []),
    { name, value }
  ];
}

function createAllurePostProcessor({ collectionName, resultsDir }) {
  if (!collectionName || !resultsDir) {
    throw new Error(
      'Newman Allure provenance requires collectionName and resultsDir'
    );
  }

  return (inMemoryWriter) => {
    const fileWriter = new FileSystemAllureWriter({ resultsDir });

    Object.entries(inMemoryWriter.attachments || {}).forEach(
      ([name, content]) => fileWriter.writeAttachment(name, content)
    );
    (inMemoryWriter.groups || []).forEach(
      (group) => fileWriter.writeGroup(group)
    );
    (inMemoryWriter.tests || []).forEach((testResult) => {
      testResult.labels = replaceLabel(
        testResult.labels,
        'sourceCollection',
        collectionName
      );
      testResult.labels = replaceLabel(
        testResult.labels,
        'sourceType',
        'Newman'
      );
      fileWriter.writeResult(testResult);
    });

    if (inMemoryWriter.categories) {
      fileWriter.writeCategoriesDefinitions(inMemoryWriter.categories);
    }
    if (inMemoryWriter.envInfo) {
      fileWriter.writeEnvironmentInfo(inMemoryWriter.envInfo);
    }
  };
}

const reporterConfig = {
  export: null,
  title: 'API Automation Report',
  browserTitle: 'API Test Results',
  darkTheme: true,
  testPaging: true,
  showMarkdownLinks: true,
  showOnlyFails: false,
  skipSensitiveData: true,
  omitRequestBodies: false,
  omitResponseBodies: false,
  noSyntaxHighlighting: false,
  showEnvironmentData: true,
  showGlobalData: false,
  timezone: 'Asia/Kolkata'
};

// Keep the factory out of Object.assign() calls that build htmlextra options.
Object.defineProperty(reporterConfig, 'createAllurePostProcessor', {
  value: createAllurePostProcessor,
  enumerable: false
});

module.exports = reporterConfig;

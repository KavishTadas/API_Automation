#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { execFileSync } = require('child_process');

const stripBom = s => s.replace(/^\uFEFF/, '');

const ROOT_DIR = path.resolve(__dirname, '..');
const COLLECTIONS_DIR = path.join(ROOT_DIR, 'collections');
const BRUNO_DIR = path.join(ROOT_DIR, 'bruno');
const BRUNO_UNVERIFIED_PREFIX = 'bruno/unverified-endpoints/';
const OUT_DIR = path.join(ROOT_DIR, 'api-docs');
const CSV_OUT = path.join(OUT_DIR, 'API_File.csv');
const JSON_OUT = path.join(OUT_DIR, 'API_File.json');
const HISTORY_DIR = path.join(OUT_DIR, 'history');
const HISTORY_INDEX = path.join(HISTORY_DIR, 'API_File_history.json');

const HEADERS = [
  'Sr. No',
  'Module Name',
  'Sub-Module Name',
  'Access',
  'Functional Purpose',
  'Base URL',
  'Endpoint / Path',
  'HTTP Method',
  'Request Parameters',
  'Request Body',
  'Example Request Payload',
  'Request Body Schema',
  'Response (example/200)',
  'Example Response Payload',
  'Dependent APIs / Services',
  'Owner / Developer',
  'API Identifier',
  'Comments'
];

const HTTP_METHODS = [
  'get',
  'post',
  'put',
  'patch',
  'delete',
  'head',
  'options'
];

let headAuthorCache = null;

function listFiles(dirPath, predicate) {
  if (!fs.existsSync(dirPath)) {
    return [];
  }

  return fs.readdirSync(dirPath, { withFileTypes: true }).flatMap((entry) => {
    const fullPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      return listFiles(fullPath, predicate);
    }

    return predicate(fullPath) ? [fullPath] : [];
  });
}

function toPosixPath(filePath) {
  return path.relative(ROOT_DIR, filePath).split(path.sep).join('/');
}

function cleanText(value) {
  if (value === null || typeof value === 'undefined') {
    return '';
  }

  if (typeof value === 'object') {
    return JSON.stringify(value, null, 2);
  }

  return String(value)
    .replace(/\r\n/g, '\n')
    .replace(/\r/g, '\n')
    .trim();
}

function compactText(value) {
  return cleanText(value).replace(/\s+/g, ' ').trim();
}

function unique(values) {
  return [...new Set(values.filter(Boolean))];
}

function stripOuterQuotes(value) {
  const text = cleanText(value);

  if (
    (text.startsWith('"') && text.endsWith('"')) ||
    (text.startsWith("'") && text.endsWith("'"))
  ) {
    return text.slice(1, -1);
  }

  return text;
}

function readDescription(description) {
  if (!description) {
    return '';
  }

  if (typeof description === 'string') {
    return cleanText(description);
  }

  return cleanText(
    description.content ||
    description.text ||
    description.description ||
    ''
  );
}

function gitAuthorForPath(gitPath) {
  return execFileSync(
    'git',
    ['log', '-1', '--format=%an <%ae>', '--', gitPath],
    {
      cwd: ROOT_DIR,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore']
    }
  ).trim();
}

function stagedRenameSource(gitPath) {
  const nameStatus = execFileSync(
    'git',
    ['diff', '--cached', '--name-status', '--find-renames'],
    {
      cwd: ROOT_DIR,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore']
    }
  );

  for (const line of nameStatus.split(/\r?\n/)) {
    const [status, source, destination] = line.split('\t');
    if (status && status.startsWith('R') && destination === gitPath) {
      return source;
    }
  }

  return '';
}

function getGitAuthor(filePath) {
  try {
    const gitPath = path.relative(ROOT_DIR, filePath).split(path.sep).join('/');
    const author = gitAuthorForPath(gitPath);
    if (author) {
      return author;
    }

    const renameSource = stagedRenameSource(gitPath);
    return renameSource
      ? gitAuthorForPath(renameSource) || getHeadCommitAuthor()
      : getHeadCommitAuthor();
  } catch (error) {
    return getHeadCommitAuthor();
  }
}

function getHeadCommitAuthor() {
  if (headAuthorCache !== null) {
    return headAuthorCache;
  }

  headAuthorCache = '';

  try {
    const gitDir = path.join(ROOT_DIR, '.git');
    const head = fs.readFileSync(path.join(gitDir, 'HEAD'), 'utf8').trim();
    const sha = head.startsWith('ref:')
      ? readGitRef(gitDir, head.replace(/^ref:\s*/, ''))
      : head;

    if (!sha) {
      return headAuthorCache;
    }

    const objectPath = path.join(gitDir, 'objects', sha.slice(0, 2), sha.slice(2));
    const inflated = zlib.inflateSync(fs.readFileSync(objectPath)).toString('utf8');
    const body = inflated.slice(inflated.indexOf('\0') + 1);
    const authorLine = body.split('\n').find((line) => line.startsWith('author '));

    if (authorLine) {
      headAuthorCache = authorLine
        .replace(/^author\s+/, '')
        .replace(/\s+\d+\s+[+-]\d+$/, '')
        .trim();
    }
  } catch (error) {
    headAuthorCache = '';
  }

  return headAuthorCache;
}

function readGitRef(gitDir, refPath) {
  const looseRef = path.join(gitDir, refPath);

  if (fs.existsSync(looseRef)) {
    return fs.readFileSync(looseRef, 'utf8').trim();
  }

  const packedRefs = path.join(gitDir, 'packed-refs');
  if (!fs.existsSync(packedRefs)) {
    return '';
  }

  return fs.readFileSync(packedRefs, 'utf8')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#') && !line.startsWith('^'))
    .map((line) => line.split(/\s+/))
    .find((parts) => parts[1] === refPath)?.[0] || '';
}

function csvEscape(value) {
  const text = cleanText(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function makeCsv(rows) {
  return [
    HEADERS.map(csvEscape).join(','),
    ...rows.map((row) => HEADERS.map((header) => csvEscape(row[header])).join(','))
  ].join('\n') + '\n';
}

function writeCsv(rows) {
  fs.writeFileSync(CSV_OUT, makeCsv(rows), 'utf8');
}

function normalizeRow(row, index) {
  return HEADERS.reduce((normalized, header) => {
    normalized[header] = header === 'Sr. No'
      ? String(index + 1)
      : cleanText(row[header]);
    return normalized;
  }, {});
}

function getEventScriptText(events) {
  return (events || [])
    .flatMap((event) => {
      const exec = event && event.script ? event.script.exec : [];
      return Array.isArray(exec) ? exec : [exec];
    })
    .map(cleanText)
    .filter(Boolean)
    .join('\n');
}

function extractQuotedCalls(scriptText, callName) {
  const found = [];
  const regex = new RegExp(`${callName}\\s*\\(\\s*(['"\`])([^'"\`]+)\\1`, 'g');
  let match;

  while ((match = regex.exec(scriptText)) !== null) {
    found.push(match[2]);
  }

  return found;
}

function extractPostmanTestNames(scriptText) {
  return extractQuotedCalls(scriptText, 'pm\\.test');
}

function extractBruTestNames(scriptText) {
  return extractQuotedCalls(scriptText, 'test');
}

function extractExpectedStatuses(scriptText) {
  const statuses = [];
  const patterns = [
    /to\.have\.status\(\s*(\d{3})\s*\)/g,
    /response\.code\)\.to\.be\.oneOf\(\s*\[([^\]]+)\]/g,
    /getStatus\(\)[\s\S]{0,80}?equal\(\s*(\d{3})\s*\)/g
  ];

  for (const pattern of patterns) {
    let match;
    while ((match = pattern.exec(scriptText)) !== null) {
      if (match[1] && match[1].includes(',')) {
        match[1]
          .split(',')
          .map((status) => status.trim())
          .filter(Boolean)
          .forEach((status) => statuses.push(status));
      } else {
        statuses.push(match[1]);
      }
    }
  }

  return unique(statuses);
}

function extractVariableNames(text) {
  const variables = [];
  const regex = /{{\s*([^}]+?)\s*}}/g;
  let match;

  while ((match = regex.exec(text)) !== null) {
    variables.push(match[1].trim());
  }

  return unique(variables);
}

function getPostmanUrlRaw(url) {
  if (!url) {
    return '';
  }

  if (typeof url === 'string') {
    return url;
  }

  if (url.raw) {
    return url.raw;
  }

  const protocol = url.protocol ? `${url.protocol}://` : '';
  const host = Array.isArray(url.host) ? url.host.join('.') : cleanText(url.host);
  const pathPart = Array.isArray(url.path) ? `/${url.path.join('/')}` : '';
  return `${protocol}${host}${pathPart}`;
}

function splitBaseAndPath(rawUrl, urlObject = {}) {
  const raw = cleanText(rawUrl);
  const noQuery = raw.split('?')[0];

  if (!raw) {
    return { baseUrl: '', endpointPath: '' };
  }

  const variableBase = noQuery.match(/^({{\s*[^}]+?\s*}})(\/.*)?$/);
  if (variableBase) {
    return {
      baseUrl: variableBase[1],
      endpointPath: variableBase[2] || '/'
    };
  }

  try {
    const parsed = new URL(raw);
    return {
      baseUrl: parsed.origin,
      endpointPath: parsed.pathname || '/'
    };
  } catch (error) {
    // Continue with Postman object fallback.
  }

  if (urlObject && Array.isArray(urlObject.host) && urlObject.host.length > 0) {
    const protocol = urlObject.protocol ? `${urlObject.protocol}://` : '';
    const baseUrl = `${protocol}${urlObject.host.join('.')}`;
    const endpointPath = Array.isArray(urlObject.path)
      ? `/${urlObject.path.filter((segment) => segment !== '').join('/')}`
      : '';

    return {
      baseUrl,
      endpointPath: endpointPath || '/'
    };
  }

  if (noQuery.startsWith('/')) {
    return { baseUrl: '', endpointPath: noQuery };
  }

  return { baseUrl: '', endpointPath: noQuery };
}

function getPostmanQueryParams(url, rawUrl) {
  const params = [];

  if (url && Array.isArray(url.query)) {
    url.query
      .filter((query) => query && query.disabled !== true)
      .forEach((query) => {
        params.push(`${query.key || ''}=${query.value || ''}`);
      });
  }

  if (params.length === 0 && cleanText(rawUrl).includes('?')) {
    const queryString = cleanText(rawUrl).split('?').slice(1).join('?');
    queryString.split('&').filter(Boolean).forEach((pair) => params.push(pair));
  }

  return unique(params);
}

function getPostmanHeaders(headers) {
  return (headers || [])
    .filter((header) => header && header.disabled !== true)
    .map((header) => `${header.key || ''}=${header.value || ''}`)
    .filter((header) => header !== '=');
}

function getPostmanAuthorizationHeader(auth) {
  if (!auth || auth.type !== 'bearer' || !Array.isArray(auth.bearer)) {
    return '';
  }

  const tokenEntry = auth.bearer.find(
    (entry) => entry && entry.disabled !== true && entry.key === 'token'
  );
  const token = tokenEntry && cleanText(tokenEntry.value);
  return token ? `Authorization=Bearer ${token}` : '';
}

function getPostmanPathVariables(url, endpointPath) {
  const variables = [];

  if (url && Array.isArray(url.variable)) {
    url.variable.forEach((variable) => {
      if (variable && variable.key) {
        variables.push(`${variable.key}=${variable.value || ''}`);
      }
    });
  }

  extractVariableNames(endpointPath).forEach((variable) => variables.push(variable));

  const colonParams = endpointPath.match(/\/:([A-Za-z0-9_]+)/g) || [];
  colonParams.forEach((param) => variables.push(param.slice(2)));

  const braceParams = endpointPath.match(/{([^}]+)}/g) || [];
  braceParams.forEach((param) => {
    if (!param.startsWith('{{')) {
      variables.push(param.slice(1, -1));
    }
  });

  return unique(variables);
}

function buildRequestParameters({ queryParams, pathVariables, headers }) {
  const sections = [];

  if (pathVariables.length > 0) {
    sections.push(`path variables: ${pathVariables.join('; ')}`);
  }

  if (queryParams.length > 0) {
    sections.push(`query: ${queryParams.join('; ')}`);
  }

  if (headers.length > 0) {
    sections.push(`headers: ${headers.join('; ')}`);
  }

  return sections.join(' | ');
}

function getPostmanBody(body) {
  if (!body || !body.mode) {
    return '';
  }

  if (body.mode === 'raw') {
    return cleanText(body.raw);
  }

  if (body.mode === 'urlencoded' || body.mode === 'formdata') {
    return (body[body.mode] || [])
      .filter((entry) => entry && entry.disabled !== true)
      .map((entry) => `${entry.key || ''}=${entry.value || ''}`)
      .join('&');
  }

  if (body.mode === 'graphql') {
    return cleanText(body.graphql);
  }

  if (body.mode === 'file') {
    return cleanText(body.file);
  }

  return cleanText(body);
}

function inferJsonSchema(value) {
  if (Array.isArray(value)) {
    return value.length > 0 ? [inferJsonSchema(value[0])] : [];
  }

  if (value === null) {
    return 'null';
  }

  if (typeof value === 'object') {
    return Object.keys(value).reduce((schema, key) => {
      schema[key] = inferJsonSchema(value[key]);
      return schema;
    }, {});
  }

  return typeof value;
}

function inferSchemaFromRawBody(rawBody) {
  const raw = cleanText(rawBody);

  if (!raw) {
    return '';
  }

  const templatedAsStrings = raw.replace(/{{\s*[^}]+?\s*}}/g, '__variable__');

  try {
    const parsed = JSON.parse(templatedAsStrings);
    return JSON.stringify(inferJsonSchema(parsed));
  } catch (error) {
    return '';
  }
}

function getPostmanBodySchema(body) {
  if (!body || !body.mode) {
    return '';
  }

  if (body.mode === 'raw') {
    return inferSchemaFromRawBody(body.raw);
  }

  if (body.mode === 'urlencoded' || body.mode === 'formdata') {
    const schema = {};
    (body[body.mode] || [])
      .filter((entry) => entry && entry.disabled !== true)
      .forEach((entry) => {
        schema[entry.key || ''] = 'string';
      });
    return Object.keys(schema).length > 0 ? JSON.stringify(schema) : '';
  }

  if (body.mode === 'graphql') {
    return 'GraphQL payload';
  }

  if (body.mode === 'file') {
    return 'File upload';
  }

  return '';
}

function extractPostmanResponseDetails(item, scriptText, endpointPath) {
  const responses = Array.isArray(item.response) ? item.response : [];
  const preferred = responses.find((response) => Number(response.code) === 200) ||
    responses[0];

  if (preferred) {
    const body = cleanText(preferred.body);
    return {
      responseSummary: [
        `HTTP ${preferred.code || ''} ${preferred.status || ''}`.trim(),
        body
      ].filter(Boolean).join('\n'),
      exampleResponsePayload: body
    };
  }

  const statuses = extractExpectedStatuses(scriptText);
  const inferredPayload = inferExampleResponsePayload(scriptText, endpointPath);
  const effectiveStatuses = statuses.length > 0
    ? statuses
    : inferredPayload
      ? ['200']
      : [];
  return {
    responseSummary: [
      effectiveStatuses.length > 0
        ? `Expected status(es): ${effectiveStatuses.join(', ')}`
        : '',
      inferredPayload
    ].filter(Boolean).join('\n'),
    exampleResponsePayload: inferredPayload
  };
}

function extractPostmanResponse(item, scriptText) {
  return extractPostmanResponseDetails(item, scriptText, '').responseSummary;
}

function inferExampleResponsePayload(scriptText, endpointPath) {
  const text = `${scriptText}\n${endpointPath}`;

  if (!/200|getStatus\(\)|to\.have\.status/i.test(text)) {
    return '';
  }

  if (/pendingleavs/i.test(text)) {
    return JSON.stringify({ pendingleavs: [] }, null, 2);
  }

  if (/leaveReport/i.test(text) && /\bcount\b/i.test(text)) {
    return JSON.stringify({
      status: '<status>',
      message: '<message>',
      data: {
        count: {
          rejected: 0,
          cancelled: 0,
          pending: 0,
          approved: 0
        },
        leaveReport: []
      }
    }, null, 2);
  }

  if (/\brecords\b/i.test(text)) {
    return JSON.stringify({ records: [] }, null, 2);
  }

  if (/\btoken\b/i.test(text) && /\broles\b/i.test(text)) {
    return JSON.stringify({
      empCode: '<empCode>',
      roles: ['<role>'],
      token: '<jwt-token>',
      username: '<username>'
    }, null, 2);
  }

  if (/\btoken\b/i.test(text)) {
    return JSON.stringify({ token: '<jwt-token>' }, null, 2);
  }

  if (/\bemail\b/i.test(text)) {
    return JSON.stringify({ email: '<email>' }, null, 2);
  }

  if (/message/i.test(text)) {
    return JSON.stringify({ message: '<message>' }, null, 2);
  }

  return '';
}

function makeExampleRequestPayload(requestBody, dataFilePath) {
  const body = cleanText(requestBody);

  if (!body) {
    return '';
  }

  const firstRow = readFirstCsvRow(dataFilePath);
  const resolved = body.replace(/{{\s*([^}]+?)\s*}}/g, (match, key) => {
    const variableName = key.trim();
    return safeExampleValue(variableName, firstRow[variableName] || `<${variableName}>`);
  });

  try {
    return JSON.stringify(JSON.parse(resolved), null, 2);
  } catch (error) {
    return resolved;
  }
}

function readFirstCsvRow(filePath) {
  if (!filePath || !fs.existsSync(filePath)) {
    return {};
  }

  const lines = stripBom(fs.readFileSync(filePath, 'utf8'))
    .split(/\r?\n/)
    .filter(Boolean);

  if (lines.length < 2) {
    return {};
  }

  const headers = parseCsvLine(lines[0]);
  const values = parseCsvLine(lines[1]);

  return headers.reduce((row, header, index) => {
    row[header] = values[index] || '';
    return row;
  }, {});
}

function parseCsvLine(line) {
  const cells = [];
  let current = '';
  let inQuotes = false;

  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];

    if (char === '"') {
      if (inQuotes && line[index + 1] === '"') {
        current += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (char === ',' && !inQuotes) {
      cells.push(current);
      current = '';
    } else {
      current += char;
    }
  }

  cells.push(current);
  return cells;
}

function safeExampleValue(key, value) {
  if (/password|token|secret|api[_-]?key|authorization/i.test(key)) {
    return `<${key}>`;
  }

  return value;
}

function detectPostmanAccess(item, request, collection, scriptText) {
  const auth = request.auth || item.auth || collection.auth;
  const headerText = cleanText(request.header);
  const requestText = [
    getPostmanUrlRaw(request.url),
    headerText,
    getPostmanBody(request.body),
    scriptText,
    item.name
  ].join('\n');

  if (auth && auth.type && auth.type !== 'noauth') {
    return 'private';
  }

  if (
    /\{\{\s*authToken\s*}}|pm\.environment\.get\(\s*['"]authToken['"]|Authorization|Bearer|without token|missing auth|401|403/i
      .test(requestText)
  ) {
    return 'private';
  }

  if (auth && auth.type === 'noauth') {
    return 'public';
  }

  return 'public';
}

function extractDependencies(sourceText) {
  const text = cleanText(sourceText);
  const dependencies = [];
  const producesAuthToken =
    /pm\.environment\.set\(\s*['"]authToken['"]/i.test(text) ||
    /bru\.setVar\(\s*['"]authToken['"]/i.test(text);

  const consumesAuthToken =
    /\{\{\s*authToken\s*}}/i.test(text) ||
    /pm\.environment\.get\(\s*['"]authToken['"]/i.test(text) ||
    /Bearer\s+\{\{\s*authToken\s*}}/i.test(text);

  if (producesAuthToken) {
    dependencies.push('Produces authToken for downstream APIs');
  }

  if (consumesAuthToken && !producesAuthToken) {
    dependencies.push('Requires authToken from Employee Auth API');
  }

  const setVars = unique([
    ...[...text.matchAll(/pm\.environment\.set\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1]),
    ...[...text.matchAll(/pm\.variables\.set\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1]),
    ...[...text.matchAll(/bru\.setVar\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1])
  ]).filter((variable) => variable !== 'authToken');

  if (setVars.length > 0) {
    dependencies.push(`Sets variables: ${setVars.join(', ')}`);
  }

  return unique(dependencies).join('; ');
}

function extractProducedVariables(sourceText) {
  const text = cleanText(sourceText);
  return unique([
    ...[...text.matchAll(/pm\.environment\.set\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1]),
    ...[...text.matchAll(/pm\.variables\.set\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1]),
    ...[...text.matchAll(/bru\.setVar\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1])
  ]);
}

function extractConsumedVariables(sourceText) {
  const text = cleanText(sourceText);
  const variables = [
    ...extractVariableNames(text),
    ...[...text.matchAll(/pm\.environment\.get\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1]),
    ...[...text.matchAll(/pm\.variables\.get\(\s*['"]([^'"]+)['"]/g)].map((match) => match[1])
  ];

  return unique(variables)
    .filter((variable) => !/baseUrl|leaveBaseUrl|BASE_URL|USERNAME|PASSWORD|empCode|empPassword|startDate|endDate/i
      .test(variable));
}

function enrichDependencies(rows) {
  const producers = new Map();

  rows.forEach((row) => {
    (row.__produces || []).forEach((variable) => {
      if (!producers.has(variable)) {
        producers.set(variable, row);
      }
    });
  });

  rows.forEach((row) => {
    const dependencies = cleanText(row['Dependent APIs / Services'])
      .split(';')
      .map((item) => item.trim())
      .filter(Boolean);

    (row.__consumes || []).forEach((variable) => {
      const producer = producers.get(variable);
      if (!producer || producer === row) {
        return;
      }

      dependencies.push(
        `Depends on ${producer['Module Name']} ${producer['HTTP Method']} ${producer['Endpoint / Path']} for ${variable}`
      );
    });

    row['Dependent APIs / Services'] = unique(dependencies).join('; ');
  });

  return rows;
}

function makeFunctionalPurpose({ itemName, description, scriptText, bru }) {
  const testNames = bru
    ? extractBruTestNames(scriptText)
    : extractPostmanTestNames(scriptText);

  return description ||
    (testNames.length > 0 ? testNames.join('; ') : '') ||
    itemName ||
    '';
}

function makeComments({ sourcePath, hasResponseExample, dataFilePath, extraNotes }) {
  const comments = [`Source: ${toPosixPath(sourcePath)}`];

  if (dataFilePath && fs.existsSync(dataFilePath)) {
    comments.push(`Data-driven: ${toPosixPath(dataFilePath)}`);
  }

  if (!hasResponseExample) {
    comments.push('No saved response example in source file');
  }

  if (extraNotes) {
    comments.push(extraNotes);
  }

  return comments.join('; ');
}

function getPostmanModuleNames(folderPath, itemName, collectionName) {
  if (folderPath.length === 0) {
    return {
      moduleName: collectionName,
      subModuleName: itemName || ''
    };
  }

  return {
    moduleName: folderPath[0] || collectionName,
    subModuleName: [...folderPath.slice(1), itemName].filter(Boolean).join(' / ')
  };
}

function collectionDataFile(collectionName, sourcePath) {
  const safeName = collectionName.replace(/\s+/g, '_');
  const relativeCollectionDir = sourcePath
    ? path.dirname(path.relative(COLLECTIONS_DIR, sourcePath))
    : '.';
  const testDataDirs = relativeCollectionDir === '.'
    ? [path.join(ROOT_DIR, 'test-data')]
    : [
        path.join(ROOT_DIR, 'test-data', relativeCollectionDir),
        path.join(ROOT_DIR, 'test-data')
      ];
  const candidates = testDataDirs.flatMap((testDataDir) => [
    path.join(testDataDir, `${collectionName}.csv`),
    path.join(testDataDir, `${safeName}.csv`)
  ]);

  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

function postmanItemToRow({ item, folderPath, collection, collectionName, sourcePath, owner }) {
  const request = typeof item.request === 'string'
    ? { method: '', url: item.request }
    : item.request || {};
  const rawUrl = getPostmanUrlRaw(request.url);
  const { baseUrl, endpointPath } = splitBaseAndPath(rawUrl, request.url);
  const scriptText = getEventScriptText(item.event);
  const description = [
    readDescription(item.description),
    readDescription(request.description)
  ].filter(Boolean).join('\n');
  const { moduleName, subModuleName } = getPostmanModuleNames(
    folderPath,
    item.name,
    collectionName
  );
  const queryParams = getPostmanQueryParams(request.url, rawUrl);
  const headers = getPostmanHeaders(request.header);
  const auth = request.auth || item.auth || collection.auth;
  const authorizationHeader = getPostmanAuthorizationHeader(auth);
  if (
    authorizationHeader &&
    !headers.some((header) => /^Authorization=/i.test(header))
  ) {
    headers.push(authorizationHeader);
  }
  const pathVariables = getPostmanPathVariables(request.url, endpointPath);
  const requestBody = getPostmanBody(request.body);
  const sourceText = [
    rawUrl,
    headers.join('\n'),
    requestBody,
    scriptText
  ].join('\n');
  const dataFilePath = collectionDataFile(
    collectionName.replace(/\s+API$/i, '_API'),
    sourcePath
  );
  const response = extractPostmanResponseDetails(item, scriptText, endpointPath);
  const row = {
    'Module Name': moduleName,
    'Sub-Module Name': subModuleName,
    Access: detectPostmanAccess(item, request, collection, scriptText),
    'Functional Purpose': makeFunctionalPurpose({
      itemName: item.name,
      description,
      scriptText,
      bru: false
    }),
    'Base URL': baseUrl,
    'Endpoint / Path': endpointPath,
    'HTTP Method': cleanText(request.method).toUpperCase(),
    'Request Parameters': buildRequestParameters({
      queryParams,
      pathVariables,
      headers
    }),
    'Request Body': requestBody,
    'Example Request Payload': makeExampleRequestPayload(requestBody, dataFilePath),
    'Request Body Schema': getPostmanBodySchema(request.body),
    'Response (example/200)': response.responseSummary,
    'Example Response Payload': response.exampleResponsePayload,
    'Dependent APIs / Services': extractDependencies(sourceText),
    'Owner / Developer': owner,
    Comments: makeComments({
      sourcePath,
      hasResponseExample: Array.isArray(item.response) && item.response.length > 0,
      dataFilePath
    }),
    __produces: extractProducedVariables(sourceText),
    __consumes: extractConsumedVariables(sourceText)
  };

  row['API Identifier'] = makeApiIdentifier(row);
  return row;
}

function walkPostmanItems({ items, folderPath, collection, collectionName, sourcePath, owner, rows }) {
  (items || []).forEach((item) => {
    if (item.request) {
      rows.push(postmanItemToRow({
        item,
        folderPath,
        collection,
        collectionName,
        sourcePath,
        owner
      }));
      return;
    }

    if (Array.isArray(item.item)) {
      walkPostmanItems({
        items: item.item,
        folderPath: [...folderPath, item.name || ''],
        collection,
        collectionName,
        sourcePath,
        owner,
        rows
      });
    }
  });
}

function readPostmanRows() {
  const files = listFiles(
    COLLECTIONS_DIR,
    (filePath) => filePath.endsWith('.json') && !filePath.includes('.pending.')
  ).sort();
  const rows = [];

  files.forEach((sourcePath) => {
    try {
      const collection = JSON.parse(stripBom(fs.readFileSync(sourcePath, 'utf8')));
      const collectionName = collection.info && collection.info.name
        ? collection.info.name
        : path.basename(sourcePath, '.json');

      walkPostmanItems({
        items: collection.item,
        folderPath: [],
        collection,
        collectionName,
        sourcePath,
        owner: getGitAuthor(sourcePath),
        rows
      });
    } catch (error) {
      console.warn(`Skipping invalid Postman collection ${toPosixPath(sourcePath)}: ${error.message}`);
    }
  });

  return rows;
}

function findNamedBlock(content, blockName) {
  const escaped = blockName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return findFirstBlock(content, new RegExp(`(^|\\n)\\s*(${escaped})\\s*\\{`, 'g')).body;
}

function findFirstBlock(content, regex) {
  const match = regex.exec(content);

  if (!match) {
    return { name: '', body: '' };
  }

  const name = match[2] || match[1] || '';
  const openIndex = content.indexOf('{', match.index);

  if (openIndex === -1) {
    return { name, body: '' };
  }

  let depth = 0;
  let quote = '';
  let escaped = false;

  for (let index = openIndex; index < content.length; index += 1) {
    const char = content[index];

    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (char === '\\') {
        escaped = true;
      } else if (char === quote) {
        quote = '';
      }
      continue;
    }

    if (char === '"' || char === "'" || char === '`') {
      quote = char;
      continue;
    }

    if (char === '{') {
      depth += 1;
    } else if (char === '}') {
      depth -= 1;
      if (depth === 0) {
        return {
          name,
          body: content.slice(openIndex + 1, index).trim()
        };
      }
    }
  }

  return { name, body: '' };
}

function parseBruValue(blockBody, key) {
  const escaped = key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const regex = new RegExp(`(?:^|[\\s,])${escaped}\\s*:\\s*([^,\\n]+)`, 'm');
  const match = regex.exec(blockBody);
  return match ? stripOuterQuotes(match[1]) : '';
}

function findBruRequest(content) {
  const methodPattern = new RegExp(`(^|\\n)\\s*(${HTTP_METHODS.join('|')})\\s*\\{`, 'gi');
  const block = findFirstBlock(content, methodPattern);

  return {
    method: cleanText(block.name).toUpperCase(),
    body: block.body
  };
}

function getBruModuleNames(sourcePath, metaName) {
  const relativeParts = path.relative(BRUNO_DIR, sourcePath).split(path.sep);

  if (relativeParts.length === 1) {
    return {
      moduleName: 'Bruno',
      subModuleName: metaName || path.basename(sourcePath, '.bru')
    };
  }

  return {
    moduleName: relativeParts[0],
    subModuleName: [
      ...relativeParts.slice(1, -1),
      metaName || path.basename(sourcePath, '.bru')
    ].filter(Boolean).join(' / ')
  };
}

function detectBruAccess(requestBlock, authBlock, sourceText) {
  const authValue = parseBruValue(requestBlock, 'auth').toLowerCase();

  if (authValue === 'none') {
    return 'public';
  }

  if (authValue || authBlock || /\bauthToken\b|Bearer/i.test(sourceText)) {
    return 'private';
  }

  return 'public';
}

function bruFileToRow(sourcePath) {
  const content = fs.readFileSync(sourcePath, 'utf8');
  const meta = findNamedBlock(content, 'meta');
  const request = findBruRequest(content);

  if (!request.method) {
    return null;
  }

  const tests = findNamedBlock(content, 'tests');
  const bodyJson = findNamedBlock(content, 'body:json');
  const authBearer = findNamedBlock(content, 'auth:bearer');
  const metaName = parseBruValue(meta, 'name') || path.basename(sourcePath, '.bru');
  const rawUrl = parseBruValue(request.body, 'url');
  const { baseUrl, endpointPath } = splitBaseAndPath(rawUrl);
  const pathVariables = extractVariableNames(endpointPath);
  const authToken = parseBruValue(authBearer, 'token');
  const requestBody = cleanText(bodyJson);
  const responseStatuses = extractExpectedStatuses(tests);
  const exampleResponsePayload = inferExampleResponsePayload(tests, endpointPath);
  const sourceText = [
    rawUrl,
    request.body,
    authBearer,
    requestBody,
    tests
  ].join('\n');
  const moduleNames = getBruModuleNames(sourcePath, metaName);
  const params = [];

  if (pathVariables.length > 0) {
    params.push(`path variables: ${pathVariables.join('; ')}`);
  }

  if (authToken) {
    params.push(`auth: bearer token=${authToken}`);
  }

  const row = {
    'Module Name': moduleNames.moduleName,
    'Sub-Module Name': moduleNames.subModuleName,
    Access: detectBruAccess(request.body, authBearer, sourceText),
    'Functional Purpose': makeFunctionalPurpose({
      itemName: metaName,
      description: '',
      scriptText: tests,
      bru: true
    }),
    'Base URL': baseUrl,
    'Endpoint / Path': endpointPath,
    'HTTP Method': request.method,
    'Request Parameters': params.join(' | '),
    'Request Body': requestBody,
    'Example Request Payload': makeExampleRequestPayload(requestBody, ''),
    'Request Body Schema': inferSchemaFromRawBody(requestBody),
    'Response (example/200)': [
      responseStatuses.length > 0
        ? `Expected status(es): ${responseStatuses.join(', ')}`
        : '',
      exampleResponsePayload
    ].filter(Boolean).join('\n'),
    'Example Response Payload': exampleResponsePayload,
    'Dependent APIs / Services': extractDependencies(sourceText),
    'Owner / Developer': getGitAuthor(sourcePath),
    Comments: makeComments({
      sourcePath,
      hasResponseExample: false,
      extraNotes: 'Parsed from Bruno file'
    }),
    __produces: extractProducedVariables(sourceText),
    __consumes: extractConsumedVariables(sourceText)
  };

  row['API Identifier'] = makeApiIdentifier(row);
  return row;
}

function readBrunoRows() {
  return listFiles(
    BRUNO_DIR,
    (filePath) =>
      filePath.endsWith('.bru') &&
      !filePath.includes('.pending.') &&
      !toPosixPath(filePath).startsWith(BRUNO_UNVERIFIED_PREFIX)
  )
    .sort()
    .map((sourcePath) => {
      try {
        return bruFileToRow(sourcePath);
      } catch (error) {
        console.warn(`Skipping invalid Bruno file ${toPosixPath(sourcePath)}: ${error.message}`);
        return null;
      }
    })
    .filter(Boolean);
}

function makeApiIdentifier(row) {
  // Deliberately excludes Base URL. The identifier is a join key the platform
  // stores, so every component of it has to be immutable; a base URL is not.
  // The same endpoint moves between {{baseUrl}}, a literal DEV host and a
  // literal UAT host over its life -- attenedance-july2026 already carries two
  // different base URLs across its own rows -- and each move silently reminted
  // the ref, orphaning anything holding the old one. An orphaned ref reports
  // NOT_APPLICABLE, which reads as a metadata gap rather than a broken
  // reference, so the failure is quiet and misleading.
  //
  // Method + path + module + sub-module is unique across all 45 inventory rows
  // (verified: 45 distinct keys, zero collisions), so dropping the segment
  // costs no identity.
  return [
    row['HTTP Method'],
    row['Endpoint / Path'],
    row['Module Name'],
    row['Sub-Module Name']
  ].map((value) => compactText(value).toLowerCase()).join('|');
}

function readExistingApiRows() {
  if (fs.existsSync(JSON_OUT)) {
    try {
      const rows = JSON.parse(stripBom(fs.readFileSync(JSON_OUT, 'utf8')));
      return Array.isArray(rows) ? rows : [];
    } catch (error) {
      console.warn(`Could not parse existing ${toPosixPath(JSON_OUT)}: ${error.message}`);
    }
  }

  if (fs.existsSync(CSV_OUT)) {
    try {
      return readCsvRows(CSV_OUT);
    } catch (error) {
      console.warn(`Could not parse existing ${toPosixPath(CSV_OUT)}: ${error.message}`);
    }
  }

  return [];
}

function readCsvRows(filePath) {
  const lines = stripBom(fs.readFileSync(filePath, 'utf8'))
    .split(/\r?\n/)
    .filter(Boolean);
  if (lines.length === 0) {
    return [];
  }

  const headers = parseCsvLine(lines[0]);
  return lines.slice(1).map((line) => {
    const cells = parseCsvLine(line);
    return headers.reduce((row, header, index) => {
      row[header] = cells[index] || '';
      return row;
    }, {});
  });
}

function mergeWithExistingRows(discoveredRows) {
  const existingRows = readExistingApiRows();
  const discoveredByKey = new Map();
  const usedKeys = new Set();

  discoveredRows.forEach((row) => {
    const key = row['API Identifier'] || makeApiIdentifier(row);
    row['API Identifier'] = key;
    discoveredByKey.set(key, row);
  });

  const audit = {
    mode: existingRows.length === 0 ? 'created' : 'merged',
    newApis: [],
    refreshedApis: [],
    missingApis: []
  };

  if (existingRows.length === 0) {
    audit.newApis = discoveredRows.map(apiLabel);
    return { rows: discoveredRows, audit };
  }

  const rows = [];

  existingRows.forEach((existingRow) => {
    const key = existingRow['API Identifier'] || makeApiIdentifier(existingRow);
    const discovered = discoveredByKey.get(key);

    if (discovered) {
      usedKeys.add(key);
      audit.refreshedApis.push(apiLabel(discovered));
      rows.push({
        ...existingRow,
        ...discovered,
        'API Identifier': key
      });
      return;
    }

    audit.missingApis.push(apiLabel(existingRow));
    usedKeys.add(key);
  });

  discoveredRows.forEach((row) => {
    const key = row['API Identifier'] || makeApiIdentifier(row);
    if (!usedKeys.has(key)) {
      audit.newApis.push(apiLabel(row));
      rows.push(row);
    }
  });

  return { rows, audit };
}

function apiLabel(row) {
  return [
    row['Module Name'],
    row['HTTP Method'],
    row['Endpoint / Path'],
    row['Sub-Module Name']
  ].filter(Boolean).join(' - ');
}

function createHistorySnapshot(newJson, newCsv, audit) {
  const oldJson = fs.existsSync(JSON_OUT) ? fs.readFileSync(JSON_OUT, 'utf8') : '';
  const oldCsv = fs.existsSync(CSV_OUT) ? fs.readFileSync(CSV_OUT, 'utf8') : '';

  if (oldJson === newJson && oldCsv === newCsv) {
    return null;
  }

  if (!oldJson && !oldCsv) {
    return null;
  }

  fs.mkdirSync(HISTORY_DIR, { recursive: true });
  const timestamp = historyTimestamp();
  const entry = {
    version: nextHistoryVersion(),
    timestamp,
    reason: 'API File regenerated from collections and Bruno files',
    previousJson: oldJson ? `api-docs/history/API_File_${timestamp}.json` : '',
    previousCsv: oldCsv ? `api-docs/history/API_File_${timestamp}.csv` : '',
    newApis: audit.newApis,
    refreshedCount: audit.refreshedApis.length,
    missingApis: audit.missingApis
  };

  if (oldJson) {
    fs.writeFileSync(path.join(HISTORY_DIR, `API_File_${timestamp}.json`), oldJson, 'utf8');
  }

  if (oldCsv) {
    fs.writeFileSync(path.join(HISTORY_DIR, `API_File_${timestamp}.csv`), oldCsv, 'utf8');
  }

  const history = readHistoryIndex();
  history.push(entry);
  fs.writeFileSync(HISTORY_INDEX, `${JSON.stringify(history, null, 2)}\n`, 'utf8');
  return entry;
}

function readHistoryIndex() {
  if (!fs.existsSync(HISTORY_INDEX)) {
    return [];
  }

  try {
    const parsed = JSON.parse(stripBom(fs.readFileSync(HISTORY_INDEX, 'utf8')));
    return Array.isArray(parsed) ? parsed : [];
  } catch (error) {
    return [];
  }
}

function nextHistoryVersion() {
  return readHistoryIndex().length + 1;
}

function historyTimestamp() {
  const now = new Date();
  const pad = (value) => String(value).padStart(2, '0');
  return [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    '_',
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds())
  ].join('');
}

function main() {
  const discoveredRows = enrichDependencies([
    ...readPostmanRows(),
    ...readBrunoRows()
  ]);
  const { rows: mergedRows, audit } = mergeWithExistingRows(discoveredRows);
  const rows = mergedRows.map((row, index) =>
    normalizeRow({
      ...row,
      'API Identifier': row['API Identifier'] || makeApiIdentifier(row)
    }, index)
  );
  const newJson = `${JSON.stringify(rows, null, 2)}\n`;
  const newCsv = makeCsv(rows);

  fs.mkdirSync(OUT_DIR, { recursive: true });
  const historyEntry = createHistorySnapshot(newJson, newCsv, audit);
  fs.writeFileSync(JSON_OUT, newJson, 'utf8');
  fs.writeFileSync(CSV_OUT, newCsv, 'utf8');

  console.log(`Generated ${rows.length} API endpoint row(s).`);
  console.log(`Discovered ${discoveredRows.length} endpoint row(s) from source files.`);
  console.log(`Appended ${audit.newApis.length} new API row(s).`);
  console.log(`Removed ${audit.missingApis.length} stale API row(s).`);
  if (historyEntry) {
    console.log(`History snapshot: api-docs/history/API_File_${historyEntry.timestamp}.*`);
  }
  console.log(`JSON: ${toPosixPath(JSON_OUT)}`);
  console.log(`CSV:  ${toPosixPath(CSV_OUT)}`);
}

main();

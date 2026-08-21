const fs = require('fs');
const path = require('path');

const AUTH_FAILURE_401_MARKER = 'AUTH_FAILURE_401';
const APPLICATION_AUTH_403_MARKER = 'APPLICATION_AUTH_FAILURE_403';
const GATEWAY_WAF_403_MARKER = 'GATEWAY_WAF_EMPTY_BODY_403';
const FAILURE_STATUSES = new Set(['failed', 'broken']);

function responseCode(result) {
  const parameter = (result.parameters || []).find(
    item => item.name === 'Response Code'
  );
  return Number(parameter?.value);
}

function attachmentText(result, resultsDir, attachmentName) {
  const attachment = (result.attachments || []).find(
    item => item.name === attachmentName
  );

  if (!attachment?.source) {
    return '';
  }

  const resultsRoot = path.resolve(resultsDir);
  const attachmentPath = path.resolve(resultsRoot, attachment.source);
  if (
    attachmentPath !== resultsRoot &&
    !attachmentPath.startsWith(`${resultsRoot}${path.sep}`)
  ) {
    return '';
  }

  try {
    return fs.readFileSync(attachmentPath, 'utf8');
  } catch (error) {
    return '';
  }
}

function normalizedResponseHeaders(result, resultsDir) {
  const rawHeaders = attachmentText(result, resultsDir, 'Response Headers');
  if (!rawHeaders.trim()) {
    return {};
  }

  try {
    return Object.fromEntries(
      Object.entries(JSON.parse(rawHeaders)).map(([name, value]) => [
        name.toLowerCase(),
        String(value)
      ])
    );
  } catch (error) {
    return {};
  }
}

function hasApplicationErrorMessage(body) {
  if (!body.trim()) {
    return false;
  }

  try {
    const parsed = JSON.parse(body);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return false;
    }

    return ['message', 'error', 'errorMessage', 'detail'].some(key => {
      const value = parsed[key];
      if (typeof value === 'string') {
        return value.trim().length > 0;
      }
      return value && typeof value === 'object';
    });
  } catch (error) {
    return false;
  }
}

function classifyAuthFailure(result, resultsDir) {
  if (!FAILURE_STATUSES.has(result.status)) {
    return '';
  }

  const code = responseCode(result);
  if (code === 401) {
    return AUTH_FAILURE_401_MARKER;
  }
  if (code !== 403) {
    return '';
  }

  const headers = normalizedResponseHeaders(result, resultsDir);
  const body = attachmentText(result, resultsDir, 'Response Body');
  const contentLength = headers['content-length']?.trim();
  const contentType = headers['content-type'] || '';
  const isEmptyGatewayResponse = (
    contentLength === '0' &&
    body.trim().length === 0 &&
    !/json/i.test(contentType)
  );

  if (isEmptyGatewayResponse) {
    return GATEWAY_WAF_403_MARKER;
  }
  if (hasApplicationErrorMessage(body)) {
    return APPLICATION_AUTH_403_MARKER;
  }

  return '';
}

function annotateAuthFailure(result, resultsDir) {
  const marker = classifyAuthFailure(result, resultsDir);
  if (!marker) {
    return '';
  }

  result.statusDetails = result.statusDetails || {};
  for (const field of ['message', 'trace']) {
    const existingValue = result.statusDetails[field]?.trim() || '';
    result.statusDetails[field] = existingValue.includes(marker)
      ? existingValue
      : existingValue
        ? `${existingValue} [${marker}]`
        : `[${marker}]`;
  }
  return marker;
}

module.exports = {
  APPLICATION_AUTH_403_MARKER,
  AUTH_FAILURE_401_MARKER,
  GATEWAY_WAF_403_MARKER,
  annotateAuthFailure,
  classifyAuthFailure
};

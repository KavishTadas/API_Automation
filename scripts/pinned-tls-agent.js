'use strict';

/**
 * Fixed-host certificate-pinned HTTPS helper for dev_mcdp_be.omfysgroup.com.
 *
 * Normal certificate-chain, expiry, and trusted-root validation remains enabled.
 * Only RFC hostname-string comparison is skipped for the exact underscore host;
 * the leaf certificate is then pinned before the TLS handshake can complete and
 * before any queued HTTP request bytes can be transmitted.
 */

const crypto = require('crypto');
const https = require('https');


const PINNED_HOST = 'dev_mcdp_be.omfysgroup.com';
const PINNED_PORT = 443;

// Leaf certificate updated on dev_mcdp_be.omfysgroup.com
const EXPECTED_CERT_SHA256 =
  'C139A6EB97F44676BD7A79897211B02FC3DEAFB988E8B08705F6AEFC82D1F569';

const DEFAULT_TIMEOUT_MS = 30_000;
const TEST_ONLY_PIN_OVERRIDE = Symbol('test-only-pin-override');


class CertificatePinMismatch extends Error {
  constructor(message) {
    super(message);
    this.name = 'CertificatePinMismatch';
    this.code = 'ERR_TLS_CERT_PIN_MISMATCH';
    this.beforeHttpData = true;
  }
}


class PinnedTlsScopeError extends Error {
  constructor(message) {
    super(message);
    this.name = 'PinnedTlsScopeError';
    this.code = 'ERR_PINNED_TLS_HOST_SCOPE';
    this.beforeHttpData = true;
  }
}


function normalizeFingerprint(value) {
  const normalized = String(value).replaceAll(':', '').trim().toUpperCase();
  if (!/^[A-F0-9]{64}$/.test(normalized)) {
    throw new TypeError(
      'Pinned SHA-256 fingerprint must contain exactly 64 hexadecimal characters'
    );
  }
  return normalized;
}


function fingerprintFromCertificate(certificate) {
  if (!certificate || !Buffer.isBuffer(certificate.raw)) {
    throw new CertificatePinMismatch(
      `TLS peer ${PINNED_HOST} did not expose a leaf certificate; connection refused`
    );
  }
  return crypto
    .createHash('sha256')
    .update(certificate.raw)
    .digest('hex')
    .toUpperCase();
}


function fingerprintsMatch(actual, expected) {
  const actualBytes = Buffer.from(normalizeFingerprint(actual), 'hex');
  const expectedBytes = Buffer.from(normalizeFingerprint(expected), 'hex');
  return crypto.timingSafeEqual(actualBytes, expectedBytes);
}


function getHeader(headers, requestedName) {
  if (!headers) {
    return undefined;
  }

  if (Array.isArray(headers)) {
    for (let index = 0; index < headers.length - 1; index += 2) {
      if (String(headers[index]).toLowerCase() === requestedName.toLowerCase()) {
        return String(headers[index + 1]);
      }
    }
    return undefined;
  }

  for (const [name, value] of Object.entries(headers)) {
    if (name.toLowerCase() === requestedName.toLowerCase()) {
      return Array.isArray(value) ? value.join(', ') : String(value);
    }
  }
  return undefined;
}


function assertPinnedHostHeader(headers) {
  const suppliedHost = getHeader(headers, 'host');
  if (suppliedHost !== undefined && suppliedHost.toLowerCase() !== PINNED_HOST) {
    throw new PinnedTlsScopeError(
      `Host header must remain scoped to ${PINNED_HOST}; connection refused`
    );
  }
}


function assertPinnedConnectionOptions(options) {
  const requestedHost = String(options.hostname || options.host || '').toLowerCase();
  if (requestedHost !== PINNED_HOST) {
    throw new PinnedTlsScopeError(
      `Pinned agent cannot connect to ${requestedHost || '<missing host>'}; ` +
        `only ${PINNED_HOST} is allowed`
    );
  }

  const servername = String(options.servername || requestedHost).toLowerCase();
  if (servername !== PINNED_HOST) {
    throw new PinnedTlsScopeError(
      `TLS servername must remain ${PINNED_HOST}; connection refused`
    );
  }

  assertPinnedHostHeader(options.headers);
}


function assertOriginRelativePath(path) {
  if (
    typeof path !== 'string' ||
    !path.startsWith('/') ||
    path.startsWith('//') ||
    path.includes('://')
  ) {
    throw new PinnedTlsScopeError(
      `Only origin-relative paths for ${PINNED_HOST} are allowed`
    );
  }
}


class PinnedTlsAgent extends https.Agent {
  constructor(options = {}) {
    const expectedFingerprint = normalizeFingerprint(
      options[TEST_ONLY_PIN_OVERRIDE] || EXPECTED_CERT_SHA256
    );
    const onPinVerified = options.onPinVerified;
    if (onPinVerified !== undefined && typeof onPinVerified !== 'function') {
      throw new TypeError('onPinVerified must be a function when provided');
    }

    super({
      keepAlive: false,
      maxCachedSessions: 0,
      rejectUnauthorized: true,
      checkServerIdentity(hostname, certificate) {
        if (String(hostname).toLowerCase() !== PINNED_HOST) {
          return new PinnedTlsScopeError(
            `Pinned identity check received ${hostname}; only ${PINNED_HOST} is allowed`
          );
        }

        // Node invokes this callback only after normal CA-chain, validity, and
        // trusted-root verification succeeds. For this exact underscore host,
        // skip only the standard hostname-string comparison and require the pin.
        const actualFingerprint = fingerprintFromCertificate(certificate);
        if (!fingerprintsMatch(actualFingerprint, expectedFingerprint)) {
          return new CertificatePinMismatch(
            `Certificate pin mismatch for ${PINNED_HOST}: expected ` +
              `${expectedFingerprint}, received ${actualFingerprint}; connection refused`
          );
        }

        if (onPinVerified) {
          onPinVerified({
            hostname: PINNED_HOST,
            fingerprint: actualFingerprint
          });
        }

        return undefined;
      }
    });

    this.expectedFingerprint = expectedFingerprint;
  }

  addRequest(request, options) {
    assertPinnedConnectionOptions(options);
    return super.addRequest(request, options);
  }
}


function createPinnedTlsAgent(options = {}) {
  return new PinnedTlsAgent({
    onPinVerified: options.onPinVerified
  });
}


// Test-only factory used to prove a mismatched pin fails closed. Application
// callers should always use createPinnedTlsAgent(), which has the fixed pin.
function createPinnedTlsAgentForTest(expectedFingerprint) {
  return new PinnedTlsAgent({
    [TEST_ONLY_PIN_OVERRIDE]: expectedFingerprint
  });
}


function setDefaultHeader(headers, name, value) {
  if (getHeader(headers, name) === undefined) {
    headers[name] = value;
  }
}


function pinnedRequest(path, options = {}) {
  assertOriginRelativePath(path);

  const {
    method = 'GET',
    headers: suppliedHeaders = {},
    body = undefined,
    jsonBody = undefined,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    agent = createPinnedTlsAgent()
  } = options;

  if (!(agent instanceof PinnedTlsAgent)) {
    throw new TypeError('agent must be a host-scoped PinnedTlsAgent');
  }
  if (body !== undefined && jsonBody !== undefined) {
    throw new TypeError('Provide either body or jsonBody, not both');
  }
  if (Array.isArray(suppliedHeaders)) {
    throw new TypeError('pinnedRequest headers must be an object');
  }

  const headers = { ...suppliedHeaders };
  assertPinnedHostHeader(headers);

  let requestBody = body;
  if (jsonBody !== undefined) {
    requestBody = Buffer.from(JSON.stringify(jsonBody), 'utf8');
    setDefaultHeader(headers, 'Content-Type', 'application/json');
  }

  return new Promise((resolve, reject) => {
    let request;
    try {
      request = https.request(
        {
          protocol: 'https:',
          hostname: PINNED_HOST,
          port: PINNED_PORT,
          servername: PINNED_HOST,
          method: String(method).toUpperCase(),
          path,
          headers,
          agent,
          rejectUnauthorized: true,
          timeout: timeoutMs
        },
        (response) => {
          const chunks = [];
          response.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
          response.on('end', () => {
            const content = Buffer.concat(chunks);
            resolve({
              statusCode: response.statusCode,
              statusMessage: response.statusMessage,
              headers: response.headers,
              rawHeaders: response.rawHeaders,
              content,
              text: content.toString('utf8')
            });
          });
        }
      );
    } catch (error) {
      agent.destroy();
      reject(error);
      return;
    }

    request.once('timeout', () => {
      request.destroy(new Error(`Pinned HTTPS request timed out after ${timeoutMs}ms`));
    });
    request.once('error', (error) => {
      agent.destroy();
      reject(error);
    });
    request.once('close', () => agent.destroy());
    request.end(requestBody);
  });
}


module.exports = {
  CertificatePinMismatch,
  EXPECTED_CERT_SHA256,
  PINNED_HOST,
  PinnedTlsAgent,
  PinnedTlsScopeError,
  createPinnedTlsAgent,
  createPinnedTlsAgentForTest,
  pinnedRequest
};

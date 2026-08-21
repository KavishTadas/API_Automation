'use strict';

/**
 * Maintained live regression verification for the fixed development-auth pin.
 * The current leaf certificate is valid from Aug 7 00:00:00 2026 GMT through
 * Feb 21 23:59:59 2027 GMT. Re-run this script whenever the pin is updated.
 */

const fs = require('fs');
const path = require('path');
const dotenv = require('dotenv');

const {
  CertificatePinMismatch,
  EXPECTED_CERT_SHA256,
  createPinnedTlsAgent,
  createPinnedTlsAgentForTest,
  pinnedRequest
} = require('../pinned-tls-agent');


const ROOT_DIR = path.resolve(__dirname, '..', '..');
const CURRENT_CERT_SHA256 =
  'C139A6EB97F44676BD7A79897211B02FC3DEAFB988E8B08705F6AEFC82D1F569';
const STALE_CERT_SHA256 =
  'C3524D47998E616A31634A3A4E75899629FDBE58DAD17318AF51FC2288F375C8';


async function main() {
  if (EXPECTED_CERT_SHA256 !== CURRENT_CERT_SHA256) {
    throw new Error(
      `Production pin ${EXPECTED_CERT_SHA256} does not match the current expected pin ${CURRENT_CERT_SHA256}`
    );
  }

  const dotenvValues = dotenv.parse(
    fs.readFileSync(path.join(ROOT_DIR, '.env'), 'utf8')
  );
  const empCode = dotenvValues.EMP_CODE || '';
  const empPassword = dotenvValues.EMP_PASSWORD || '';
  if (!empCode || !empPassword) {
    throw new Error('EMP_CODE or EMP_PASSWORD is absent/empty in .env');
  }

  const liveAgent = createPinnedTlsAgent();
  const liveResponse = await pinnedRequest('/auth/token', {
    method: 'POST',
    agent: liveAgent,
    jsonBody: {
      empCode,
      password: empPassword
    }
  });

  let livePayload = null;
  try {
    livePayload = JSON.parse(liveResponse.text);
  } catch (_error) {
    livePayload = null;
  }
  const tokenReturned =
    typeof livePayload?.token === 'string' && livePayload.token.length > 0;

  console.log('===== CORRECT PIN LIVE REQUEST =====');
  console.log(`Status code: ${liveResponse.statusCode}`);
  console.log(`Token returned: ${tokenReturned ? 'yes' : 'no'}`);
  console.log(
    liveResponse.statusCode === 200 && tokenReturned ? 'Result: PASS' : 'Result: FAIL'
  );
  console.log();

  const wrongAgent = createPinnedTlsAgentForTest(STALE_CERT_SHA256);

  console.log('===== RETIRED/STALE PIN =====');
  try {
    await pinnedRequest('/', { agent: wrongAgent });
  } catch (error) {
    const failedClosed =
      error instanceof CertificatePinMismatch && error.beforeHttpData === true;
    console.log(`Rejected: ${failedClosed ? 'yes' : 'no'}`);
    console.log(`Exception type: ${error.name}`);
    console.log(`Failure detail: ${error.message}`);
    console.log(
      failedClosed
        ? 'Result: PASS (failed closed before sending the HTTP request)'
        : 'Result: FAIL (request failed for an unexpected reason)'
    );
    if (!failedClosed) {
      throw error;
    }
    return;
  }

  console.log('Rejected: no');
  console.log('Result: FAIL (connection unexpectedly remained open)');
  process.exitCode = 1;
}


main().catch((error) => {
  console.error(`${error.name}: ${error.message}`);
  process.exitCode = 1;
});

'use strict';

/**
 * Maintained live regression verification for the fixed development-auth pin.
 * Re-run this script whenever the pin is updated after the current certificate
 * expires on Aug 11 2026.
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


function deliberatelyWrongFingerprint(correctFingerprint) {
  const replacement = correctFingerprint[0] === '0' ? '1' : '0';
  return replacement + correctFingerprint.slice(1);
}


async function main() {
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

  const wrongAgent = createPinnedTlsAgentForTest(
    deliberatelyWrongFingerprint(EXPECTED_CERT_SHA256)
  );

  console.log('===== DELIBERATELY WRONG PIN =====');
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

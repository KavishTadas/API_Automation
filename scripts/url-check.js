const https = require('https');
const process = require('process');

const TOKEN = process.env.LEAVE_BASE_URL_CONFIRMED || '';

const urls = [
  'https://uat-mcdp-be.omfysgroup.com',
  'https://uat-mcdp-be.omfysgroup.com'
];

const path = '/user/leaves/approvals';

function probe(baseUrl) {
  return new Promise((resolve) => {
    const url = new URL(path, baseUrl);
    const req = https.request(
      {
        hostname: url.hostname,
        path: url.pathname,
        method: 'POST',
        headers: {
          Authorization: 'Bearer probe-token',
          'Content-Length': '0'
        },
        timeout: 8000
      },
      (res) => {
        res.resume();
        resolve({
          url: baseUrl,
          status: res.statusCode,
          result: res.statusCode === 401 || res.statusCode === 403
            ? 'SERVER REACHABLE - returns ' + res.statusCode
              + ' (expected - probe token is invalid)'
            : 'SERVER REACHABLE - returns ' + res.statusCode
        });
      }
    );
    req.on('error', (e) => resolve({
      url: baseUrl,
      status: null,
      result: 'UNREACHABLE - ' + e.message
    }));
    req.on('timeout', () => {
      req.destroy();
      resolve({ url: baseUrl, status: null, result: 'TIMEOUT' });
    });
    req.end();
  });
}

async function run() {
  console.log('Probing both base URL variants for /user/leaves/approvals...\n');
  for (const url of urls) {
    const r = await probe(url);
    console.log(`${r.result}`);
    console.log(`  URL: ${r.url}`);
    console.log(`  Status: ${r.status || 'n/a'}\n`);
  }
  console.log('USE the URL that shows SERVER REACHABLE in environments/uat.json');
}

run();

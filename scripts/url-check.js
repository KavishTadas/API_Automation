'use strict';
require('dotenv').config();
const https = require('https');

const CANDIDATES = [
  {
    label: 'Hyphen URL (/auth/token)',
    base: 'https://uat-mcdp-be.omfysgroup.com',
    path: '/auth/token',
    method: 'POST',
  },
  {
    label: 'Hyphen URL (/user/leaves/approvals)',
    base: 'https://uat-mcdp-be.omfysgroup.com',
    path: '/user/leaves/approvals',
    method: 'GET',
  },
];

function probe(candidate) {
  return new Promise(resolve => {
    const url = new URL(candidate.path, candidate.base);
    const req = https.request(
      { hostname: url.hostname, path: url.pathname,
        method: candidate.method, timeout: 8000,
        headers: { 'Authorization': 'Bearer probe-token' } },
      res => {
        const reachable = [200,400,401,403,404,422].includes(res.statusCode);
        resolve({
          label: candidate.label,
          url: candidate.base + candidate.path,
          status: res.statusCode,
          result: reachable ? 'REACHABLE (' + res.statusCode + ')' : 'UNEXPECTED STATUS'
        });
      }
    );
    req.on('error', e => resolve({ label: candidate.label,
      url: candidate.base + candidate.path, status: null,
      result: 'UNREACHABLE — ' + e.message }));
    req.on('timeout', () => { req.destroy();
      resolve({ label: candidate.label, url: candidate.base + candidate.path,
        status: null, result: 'TIMEOUT' }); });
    req.end();
  });
}

async function run() {
  console.log('Probing API endpoint reachability...\n');
  for (const c of CANDIDATES) {
    const r = await probe(c);
    console.log(r.label);
    console.log('  URL:    ' + r.url);
    console.log('  Result: ' + r.result + '\n');
  }
}

run();

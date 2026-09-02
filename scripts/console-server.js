'use strict';

/**
 * HCM API Test Automation — Console Bridge Server
 *
 * Provides real-time API execution with host-scoped TLS certificate pinning,
 * Newman test execution, dynamic catalog streaming, and persistent reporting.
 */

require('dotenv').config();
const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const url = require('url');
const { spawn } = require('child_process');
const {
  createPinnedTlsAgent,
  PINNED_HOST,
  pinnedRequest
} = require('./pinned-tls-agent');

const PORT = process.env.CONSOLE_PORT || process.env.PORT || 8765;
const ROOT_DIR = path.join(__dirname, '..');

// Helper to determine Content-Type
function getContentType(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  const map = {
    '.html': 'text/html; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.csv': 'text/csv; charset=utf-8',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.txt': 'text/plain; charset=utf-8'
  };
  return map[ext] || 'application/octet-stream';
}

// Read JSON Body helper
function parseJsonBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => {
      body += chunk;
      if (body.length > 5 * 1024 * 1024) { // 5MB limit
        reject(new Error('Payload too large'));
      }
    });
    req.on('end', () => {
      if (!body.trim()) return resolve({});
      try {
        resolve(JSON.parse(body));
      } catch (err) {
        reject(new Error('Invalid JSON payload'));
      }
    });
    req.on('error', reject);
  });
}

// Outbound HTTP/HTTPS Request Dispatcher with TLS Pinning
async function dispatchApiRequest({ method = 'GET', targetUrl, headers = {}, body = null, timeoutMs = 30000 }) {
  const startTime = Date.now();
  const parsedUrl = new url.URL(targetUrl);
  const isPinnedHost = parsedUrl.hostname.toLowerCase() === PINNED_HOST.toLowerCase();

  // If targeting pinned host (dev_mcdp_be.omfysgroup.com), use host-pinned helper
  if (isPinnedHost) {
    const relativePath = parsedUrl.pathname + parsedUrl.search;
    const reqHeaders = { ...headers };
    if (!reqHeaders.Host && !reqHeaders.host) {
      reqHeaders.Host = PINNED_HOST;
    }

    const response = await pinnedRequest(relativePath, {
      method,
      headers: reqHeaders,
      jsonBody: body ? (typeof body === 'object' ? body : JSON.parse(body)) : undefined,
      timeoutMs
    });

    const latencyMs = Date.now() - startTime;
    let parsedBody;
    try {
      parsedBody = JSON.parse(response.text);
    } catch {
      parsedBody = response.text;
    }

    return {
      statusCode: response.statusCode,
      statusMessage: response.statusMessage,
      headers: response.headers,
      body: parsedBody,
      latencyMs,
      timestamp: new Date().toISOString(),
      tlsPinned: true
    };
  }

  // Generic HTTP / HTTPS request
  return new Promise((resolve, reject) => {
    const isHttps = parsedUrl.protocol === 'https:';
    const client = isHttps ? https : http;
    const reqHeaders = { ...headers };
    
    let payloadData = null;
    if (body) {
      payloadData = typeof body === 'string' ? body : JSON.stringify(body);
      if (!reqHeaders['Content-Type'] && !reqHeaders['content-type']) {
        reqHeaders['Content-Type'] = 'application/json';
      }
      reqHeaders['Content-Length'] = Buffer.byteLength(payloadData);
    }

    const reqOptions = {
      protocol: parsedUrl.protocol,
      hostname: parsedUrl.hostname,
      port: parsedUrl.port || (isHttps ? 443 : 80),
      path: parsedUrl.pathname + parsedUrl.search,
      method: method.toUpperCase(),
      headers: reqHeaders,
      timeout: timeoutMs
    };

    const req = client.request(reqOptions, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => {
        const rawText = Buffer.concat(chunks).toString('utf8');
        const latencyMs = Date.now() - startTime;
        let parsedBody;
        try {
          parsedBody = JSON.parse(rawText);
        } catch {
          parsedBody = rawText;
        }

        resolve({
          statusCode: res.statusCode,
          statusMessage: res.statusMessage,
          headers: res.headers,
          body: parsedBody,
          latencyMs,
          timestamp: new Date().toISOString(),
          tlsPinned: false
        });
      });
    });

    req.on('timeout', () => {
      req.destroy(new Error(`Request timed out after ${timeoutMs}ms`));
    });

    req.on('error', err => {
      reject(err);
    });

    if (payloadData) {
      req.write(payloadData);
    }
    req.end();
  });
}

// Server Request Handler
const server = http.createServer(async (req, res) => {
  // Enable CORS for local cross-origin development
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  const parsedUrl = url.parse(req.url, true);
  const pathname = parsedUrl.pathname;

  // 1. API: Catalog Endpoint (Loads API_File.json)
  if (pathname === '/api/catalog' && req.method === 'GET') {
    const catalogPath = path.join(ROOT_DIR, 'api-docs', 'API_File.json');
    if (fs.existsSync(catalogPath)) {
      const content = fs.readFileSync(catalogPath, 'utf8');
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(content);
    } else {
      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: 'API_File.json not found' }));
    }
    return;
  }

  // 2. API: Environment Endpoint
  if (pathname === '/api/env' && req.method === 'GET') {
    const uatEnvPath = path.join(ROOT_DIR, 'environments', 'uat.json');
    let uatValues = {};
    if (fs.existsSync(uatEnvPath)) {
      try {
        const uatJson = JSON.parse(fs.readFileSync(uatEnvPath, 'utf8'));
        uatJson.values?.forEach(v => { uatValues[v.key] = v.value; });
      } catch (e) {}
    }

    const envInfo = {
      defaultEnv: process.env.ENV || 'uat',
      authBaseUrl: process.env.AUTH_BASE_URL || uatValues.authBaseUrl || 'https://dev_mcdp_be.omfysgroup.com',
      leaveBaseUrl: process.env.LEAVE_BASE_URL || uatValues.leaveBaseUrl || 'https://devmcdphcmplatform.omfysgroup.com',
      attendanceBaseUrl: process.env.ATTENDANCE_BASE_URL || uatValues.attendanceBaseUrl || 'https://uat_mcdp_hcm.omfysgroup.com',
      hasAuthCredentials: Boolean(process.env.EMP_CODE && process.env.EMP_PASSWORD),
      empCode: process.env.EMP_CODE || ''
    };

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(envInfo));
    return;
  }

  // 3. API: Single Live API Execution
  if (pathname === '/api/execute' && req.method === 'POST') {
    try {
      const payload = await parseJsonBody(req);
      const { method = 'GET', url: targetUrl, headers = {}, body = null, timeoutMs = 30000 } = payload;

      if (!targetUrl) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Target URL is required' }));
        return;
      }

      const result = await dispatchApiRequest({ method, targetUrl, headers, body, timeoutMs });
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify(result));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({
        error: err.message,
        statusCode: 500,
        latencyMs: 0,
        timestamp: new Date().toISOString()
      }));
    }
    return;
  }

  // 4. API: Batch Live API Execution
  if (pathname === '/api/batch' && req.method === 'POST') {
    try {
      const payload = await parseJsonBody(req);
      const { requests = [], stopOnFailure = false } = payload;

      if (!Array.isArray(requests) || requests.length === 0) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Requests array is required' }));
        return;
      }

      const results = [];
      for (const item of requests) {
        try {
          const resItem = await dispatchApiRequest({
            method: item.method,
            targetUrl: item.url,
            headers: item.headers || {},
            body: item.body,
            timeoutMs: item.timeoutMs || 30000
          });
          results.push({ id: item.id, name: item.name, ...resItem, success: resItem.statusCode >= 200 && resItem.statusCode < 400 });
          if (stopOnFailure && (resItem.statusCode < 200 || resItem.statusCode >= 400)) {
            break;
          }
        } catch (err) {
          results.push({
            id: item.id,
            name: item.name,
            error: err.message,
            statusCode: 500,
            success: false,
            timestamp: new Date().toISOString()
          });
          if (stopOnFailure) break;
        }
      }

      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ total: requests.length, executed: results.length, results }));
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  // 5. API: Trigger Newman / Allure Suite Run
  if (pathname === '/api/run-suite' && req.method === 'POST') {
    try {
      const payload = await parseJsonBody(req);
      const envName = payload.env || 'uat';
      const newmanProcess = spawn('node', ['scripts/run-newman.js'], {
        cwd: ROOT_DIR,
        env: { ...process.env, ENV: envName }
      });

      let output = '';
      newmanProcess.stdout.on('data', data => { output += data.toString(); });
      newmanProcess.stderr.on('data', data => { output += data.toString(); });

      newmanProcess.on('close', code => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          exitCode: code,
          success: code === 0,
          output,
          reportUrl: '/reports/html/index.html',
          dashboardUrl: '/enterprise-dashboard.html'
        }));
      });
    } catch (err) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: err.message }));
    }
    return;
  }

  // 6. Static File Serving
  let relativePath = pathname;
  if (pathname === '/' || pathname === '/console' || pathname === '/console.html') {
    // The build product, not a copy of it. Serving a root console.html meant
    // the page could sit arbitrarily far behind docs/platform-ui, and a stale
    // console is indistinguishable from a broken one.
    relativePath = '/docs/platform-ui/unified-console.html';
  } else if (pathname === '/dashboard' || pathname === '/enterprise-dashboard' || pathname === '/enterprise-dashboard.html') {
    relativePath = '/enterprise-dashboard.html';
  }
  let filePath = path.join(ROOT_DIR, relativePath);

  // Safety check to prevent directory traversal
  if (!filePath.startsWith(ROOT_DIR)) {
    res.writeHead(403, { 'Content-Type': 'text/plain' });
    res.end('Forbidden');
    return;
  }

  if (fs.existsSync(filePath) && fs.statSync(filePath).isFile()) {
    const contentType = getContentType(filePath);
    res.writeHead(200, { 'Content-Type': contentType });
    fs.createReadStream(filePath).pipe(res);
  } else {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('File Not Found');
  }
});

server.listen(PORT, '0.0.0.0', () => {
  console.log(`\n🚀 HCM API Test Console Server running on: http://127.0.0.1:${PORT}/console`);
  console.log(`📡 Console UI:            http://127.0.0.1:${PORT}/console`);
  console.log(`📊 Enterprise Dashboard:  http://127.0.0.1:${PORT}/dashboard`);
  console.log(`📑 Allure Reports:        http://127.0.0.1:${PORT}/reports/html/index.html\n`);
});

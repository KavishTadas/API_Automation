'use strict';
const fs   = require('fs');
const path = require('path');

function generateIndex(results) {
  const reportsDir = path.join(__dirname, '..', 'reports', 'html');
  const outFile    = path.join(reportsDir, 'index.html');
  const runDate    = new Date().toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    dateStyle: 'medium',
    timeStyle: 'short'
  });

  const totalRequests  = results.reduce((s, r) => s + r.Requests, 0);
  const totalPassed    = results.reduce((s, r) => s + r.Passed, 0);
  const totalFailed    = results.reduce((s, r) => s + r.Failed, 0);
  const totalDuration  = results.reduce((s, r) =>
    s + (r['Duration(ms)'] || 0), 0);
  const passRate = (totalPassed + totalFailed) > 0
    ? Math.round((totalPassed / (totalPassed + totalFailed)) * 100)
    : 0;
  const overallStatus  = totalFailed === 0 ? 'PASSED' : 'FAILED';
  const statusColor    = totalFailed === 0 ? '#1D9E75' : '#D85A30';

  const collectionRows = results.map(r => {
    const colPassed  = r.Passed;
    const colFailed  = r.Failed;
    const colRate    = (colPassed + colFailed) > 0
      ? Math.round((colPassed / (colPassed + colFailed)) * 100)
      : 0;
    const colStatus  = colFailed === 0 ? 'PASS' : 'FAIL';
    const colColor   = colFailed === 0 ? '#1D9E75' : '#D85A30';
    const reportFile = r.reportFile
      ? `<a href="${path.basename(r.reportFile)}"
             style="color:#378ADD;text-decoration:none">
             View Report →</a>`
      : '—';

    return `
      <tr>
        <td style="padding:12px 16px;font-weight:500">
          ${r.Collection}
        </td>
        <td style="padding:12px 16px;text-align:center">
          ${r.Requests}
        </td>
        <td style="padding:12px 16px;text-align:center;
                   color:#1D9E75;font-weight:500">
          ${colPassed}
        </td>
        <td style="padding:12px 16px;text-align:center;
                   color:${colFailed > 0 ? '#D85A30' : '#999'};
                   font-weight:500">
          ${colFailed}
        </td>
        <td style="padding:12px 16px;text-align:center">
          ${(r['Duration(ms)'] / 1000).toFixed(1)}s
        </td>
        <td style="padding:12px 16px;text-align:center">
          <span style="background:${colColor}22;
                       color:${colColor};
                       padding:3px 10px;border-radius:12px;
                       font-size:12px;font-weight:600">
            ${colStatus}
          </span>
        </td>
        <td style="padding:12px 16px;text-align:center">
          ${reportFile}
        </td>
      </tr>`;
  }).join('');

  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>API Automation — Consolidated Test Report</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
         sans-serif;background:#0f1117;color:#e4e6ea;
         min-height:100vh;padding:32px 24px}
    .header{margin-bottom:32px}
    .header h1{font-size:22px;font-weight:600;color:#fff;
               margin-bottom:6px}
    .header p{font-size:13px;color:#8b8fa8}
    .summary{display:grid;grid-template-columns:repeat(
             auto-fit,minmax(160px,1fr));gap:12px;
             margin-bottom:32px}
    .card{background:#1a1d27;border:1px solid #2a2d3a;
          border-radius:10px;padding:18px 20px}
    .card-label{font-size:11px;font-weight:500;
                text-transform:uppercase;letter-spacing:.06em;
                color:#8b8fa8;margin-bottom:8px}
    .card-value{font-size:28px;font-weight:600;color:#fff}
    .card-value.green{color:#1D9E75}
    .card-value.red{color:#D85A30}
    .card-value.blue{color:#378ADD}
    .status-banner{padding:14px 20px;border-radius:10px;
                   margin-bottom:24px;font-size:14px;
                   font-weight:500;border:1px solid}
    .table-wrap{background:#1a1d27;border:1px solid #2a2d3a;
                border-radius:10px;overflow:hidden}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th{padding:11px 16px;text-align:left;font-size:11px;
       font-weight:500;text-transform:uppercase;
       letter-spacing:.06em;color:#8b8fa8;
       background:#14161f;border-bottom:1px solid #2a2d3a}
    td{border-bottom:1px solid #1f2130}
    tr:last-child td{border-bottom:none}
    tr:hover td{background:#1f2233}
  </style>
</head>
<body>
  <div class="header">
    <h1>API Automation — Consolidated Test Report</h1>
    <p>Run date: ${runDate} &nbsp;|&nbsp; Environment: UAT</p>
  </div>

  <div class="summary">
    <div class="card">
      <div class="card-label">Overall status</div>
      <div class="card-value" style="color:${statusColor}">
        ${overallStatus}
      </div>
    </div>
    <div class="card">
      <div class="card-label">Collections</div>
      <div class="card-value blue">${results.length}</div>
    </div>
    <div class="card">
      <div class="card-label">Total requests</div>
      <div class="card-value">${totalRequests}</div>
    </div>
    <div class="card">
      <div class="card-label">Passed</div>
      <div class="card-value green">${totalPassed}</div>
    </div>
    <div class="card">
      <div class="card-label">Failed</div>
      <div class="card-value ${totalFailed > 0 ? 'red' : ''}">
        ${totalFailed}
      </div>
    </div>
    <div class="card">
      <div class="card-label">Pass rate</div>
      <div class="card-value ${passRate === 100 ? 'green' :
        passRate >= 80 ? 'blue' : 'red'}">
        ${passRate}%
      </div>
    </div>
    <div class="card">
      <div class="card-label">Total duration</div>
      <div class="card-value">
        ${(totalDuration / 1000).toFixed(1)}s
      </div>
    </div>
  </div>

  <div class="status-banner" style="
    background:${statusColor}18;
    border-color:${statusColor}44;
    color:${statusColor}">
    ${overallStatus === 'PASSED'
      ? '✓ All assertions passed across all collections'
      : '✗ One or more collections have failing assertions'}
  </div>

  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Collection</th>
          <th style="text-align:center">Requests</th>
          <th style="text-align:center">Passed</th>
          <th style="text-align:center">Failed</th>
          <th style="text-align:center">Duration</th>
          <th style="text-align:center">Status</th>
          <th style="text-align:center">Full Report</th>
        </tr>
      </thead>
      <tbody>${collectionRows}</tbody>
    </table>
  </div>
</body>
</html>`;

  fs.mkdirSync(reportsDir, { recursive: true });
  fs.writeFileSync(outFile, html, 'utf8');
  console.log('  ✓ Consolidated HTML index → reports/html/index.html');
  return outFile;
}

module.exports = { generateIndex };

/* Export test: drive a real run in jsdom, capture what download() is handed,
   write the bytes to disk, and assert they are valid OOXML packages.
   Structural validation happens in check-export.py, which opens them. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const HERE = __dirname;
const OUT = path.join(HERE, '..', '..', '.export-test');
const F = path.join(HERE, 'unified-console.html');

const dom = new JSDOM(fs.readFileSync(F, 'utf8'),
  { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/' });
const { window } = dom;
const doc = window.document;
const $ = s => doc.querySelector(s);
const $$ = s => [...doc.querySelectorAll(s)];
const click = el => el.dispatchEvent(new window.Event('click', { bubbles: true }));
const wait = ms => new Promise(r => setTimeout(r, ms));

let bad = 0;
const ok = (n, c, d) => { console.log((c ? '  PASS  ' : '  FAIL  ') + n + (c ? '' : '\n          -> ' + d)); if (!c) bad++; };

(async () => {
  await wait(150);
  fs.rmSync(OUT, { recursive: true, force: true });
  fs.mkdirSync(OUT, { recursive: true });

  // capture instead of downloading
  const captured = [];
  window.download = (data, name, mime) => {
    const buf = (typeof data === 'string') ? Buffer.from(data, 'utf8') : Buffer.from(data);
    fs.writeFileSync(path.join(OUT, name), buf);
    captured.push({ name, mime, bytes: buf.length });
  };

  // a run big enough to exercise every state
  click($('#btnSelAll'));
  await wait(60);
  click($('#btnRun'));
  await wait(5400);   // 45 endpoints step at 90ms each
  const R = JSON.parse(window.localStorage.getItem('hcm-console-v1')).result;
  ok('a run produced a result to export', !!R && R.summary.total > 0,
     R ? R.summary.total + ' results' : 'no result');

  console.log('\nexport chooser:');
  window.exportModal();
  await wait(60);
  ok('chooser opens', $('#ovModal').classList.contains('open'));
  const opts = $$('#ovModal [data-exp]').map(b => b.dataset.exp);
  ok('offers Excel, Word, text, CSV and JSON',
     ['xlsx', 'docx', 'txt', 'csv', 'json'].every(k => opts.includes(k)), opts.join(','));
  ok('each option is a button with a label and a description',
     $$('#ovModal .exp-opt').every(b =>
       b.tagName === 'BUTTON' && b.querySelector('.exp-t') && b.querySelector('.exp-d')));
  ok('the chooser says how much is being exported',
     /result\(s\) across .* endpoint\(s\)/.test($('#mBody').textContent));
  ok('it states no credential is written',
     /no secret value is written/i.test($('#mBody').textContent));

  console.log('\ndownloads:');
  for (const k of ['xlsx', 'docx', 'txt', 'csv', 'json']) {
    captured.length = 0;
    window[{xlsx:'exportXlsx',docx:'exportDocx',txt:'exportTxt',
             csv:'exportCsv',json:'exportJson'}[k]](R);
    await wait(40);
    ok(`${k} produces a download`, captured.length === 1, captured.length + ' files');
    if (captured.length) {
      const c = captured[0];
      ok(`  ${k} filename carries the run stamp and extension`,
         c.name.startsWith('HCM-API-Report-') && c.name.includes(R.runId) &&
         c.name.endsWith('.' + k), c.name);
      ok(`  ${k} is not empty`, c.bytes > 200, c.bytes + ' bytes');
    }
  }

  console.log('\ncontent:');
  const txt = fs.readFileSync(path.join(OUT, fs.readdirSync(OUT).find(f => f.endsWith('.txt'))), 'utf8');
  ok('text report names the run', txt.includes(R.runId));
  ok('text report states the pass-rate basis', txt.includes('PASS / (PASS + FAIL)'));
  ok('text report lists every state', ['PASS', 'FAIL', 'WARN', 'NOT_ASSERTED',
     'NOT_APPLICABLE', 'SKIPPED_NO_TOKEN', 'INFORMATIONAL'].every(s => txt.includes(s)));
  // The D7 note belongs to the ASSERTION GAPS section, which the report emits
  // only when there are gaps. Every endpoint now carries authored cases, so the
  // section is correctly absent -- assert the pairing, not the old data.
  const hasGapSection = /ASSERTION GAPS/.test(txt);
  ok('text report carries the D7 note exactly when it reports gaps',
     hasGapSection === /never rendered as a pass/i.test(txt),
     hasGapSection ? 'gaps section present' : 'no gaps, section correctly omitted');
  // look for credential *values*, not the word -- the report's own footer
  // says "no secret value appears here", which a naive scan would flag
  const leaks = blob => (/Bearer\s+ey[A-Za-z0-9_.-]{10,}/.test(blob) ? 'jwt ' : '') +
    (/(password|passwd|pwd|secret|token)\s*[:=]\s*["']?[A-Za-z0-9!@#$%^&*_.-]{6,}/i.test(blob) ? 'assignment' : '');
  ok('no credential value in the text report', !leaks(txt), leaks(txt));

  const csv = fs.readFileSync(path.join(OUT, fs.readdirSync(OUT).find(f => f.endsWith('.csv'))), 'utf8');
  ok('csv has a header row', csv.split('\r\n')[0].includes('"Endpoint Path"'));
  ok('csv row count matches the result count',
     csv.trim().split('\r\n').length - 1 === R.apis.flatMap(a => a.results).length,
     (csv.trim().split('\r\n').length - 1) + ' vs ' + R.apis.flatMap(a => a.results).length);
  ok('csv leads with a BOM so Excel reads UTF-8', csv.charCodeAt(0) === 0xFEFF);

  const json = JSON.parse(fs.readFileSync(path.join(OUT, fs.readdirSync(OUT).find(f => f.endsWith('.json'))), 'utf8'));
  ok('json round-trips the result document', json.runId === R.runId &&
     json.summary.total === R.summary.total);

  console.log('\nzip container:');
  for (const ext of ['xlsx', 'docx']) {
    const p = path.join(OUT, fs.readdirSync(OUT).find(f => f.endsWith('.' + ext)));
    const b = fs.readFileSync(p);
    ok(`${ext} starts with a local file header (PK\\x03\\x04)`,
       b[0] === 0x50 && b[1] === 0x4B && b[2] === 0x03 && b[3] === 0x04,
       [...b.slice(0, 4)].join(','));
    ok(`${ext} ends with an end-of-central-directory record`,
       b.readUInt32LE(b.length - 22) === 0x06054b50);
    ok(`${ext} declares its entry count consistently`,
       b.readUInt16LE(b.length - 14) === b.readUInt16LE(b.length - 12));
  }

  console.log(`\nwrote ${fs.readdirSync(OUT).length} file(s) to ${OUT}`);
  console.log('%s', bad === 0 ? 'EXPORT OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

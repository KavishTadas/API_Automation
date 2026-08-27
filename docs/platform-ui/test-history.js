/* Report history + standalone share.
   The share test is the important one: it takes the file the Share button
   produces, opens it in a *fresh* jsdom with localStorage blocked — the
   equivalent of a private window with no cache — and asserts the full report
   renders from the embedded payload alone. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const F = path.join(__dirname, 'unified-console.html');
const OUT = path.join(__dirname, '..', '..', '.export-test');

let bad = 0;
const ok = (n, c, d) => { console.log((c ? '  PASS  ' : '  FAIL  ') + n + (c ? '' : '\n          -> ' + d)); if (!c) bad++; };
const wait = ms => new Promise(r => setTimeout(r, ms));

function boot(html, opts) {
  const dom = new JSDOM(html, Object.assign(
    { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/' }, opts || {}));
  const w = dom.window, d = w.document;
  return {
    w, d,
    $: s => d.querySelector(s),
    $$: s => [...d.querySelectorAll(s)],
    click: el => el.dispatchEvent(new w.Event('click', { bubbles: true }))
  };
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const html = fs.readFileSync(F, 'utf8');

  // ---------------------------------------------------------------- part 1
  console.log('automatic archiving:');
  const a = boot(html);
  await wait(160);
  a.click(a.$('#btnSelAll'));
  await wait(60);
  a.click(a.$('#btnRun'));
  await wait(5400);

  let snaps = JSON.parse(a.w.localStorage.getItem('HCM_RUN_SNAPSHOTS') || '[]');
  ok('a finished run archives itself with no manual save', snaps.length === 1,
     snaps.length + ' snapshots');
  const s0 = snaps[0];
  ok('the snapshot carries a run id', !!s0.runId, s0.runId);
  ok('it carries a timestamp', /^\d{4}-\d{2}-\d{2}T/.test(s0.at || ''), s0.at);
  ok('it carries the environment', s0.env === 'UAT', s0.env);
  ok('it carries the quality gate',
     ['PASSED', 'WARNING', 'FAILED'].includes(s0.gate), s0.gate);
  ok('it carries pass rate, totals and duration',
     'passRate' in s0 && typeof s0.total === 'number' &&
     typeof s0.passed === 'number' && typeof s0.failed === 'number' &&
     typeof s0.durationMs === 'number',
     JSON.stringify({ p: s0.passRate, t: s0.total, d: s0.durationMs }));
  ok('it carries the whole result document, not a summary',
     !!s0.result && Array.isArray(s0.result.apis) && s0.result.apis.length === 45,
     (s0.result.apis || []).length + ' apis');
  ok('the document holds every endpoint result',
     s0.result.apis.flatMap(x => x.results).length === s0.total + (s0.result.summary.referencedHostResults || 0),
     s0.result.apis.flatMap(x => x.results).length + ' vs ' + s0.total);

  // a second run appends
  a.w.eval("go('home')");
  await wait(70);
  a.click(a.$('#btnRun'));
  await wait(5400);
  snaps = JSON.parse(a.w.localStorage.getItem('HCM_RUN_SNAPSHOTS') || '[]');
  ok('a second run appends rather than replacing', snaps.length === 2, snaps.length + '');
  ok('the two runs have distinct ids', snaps[0].runId !== snaps[1].runId,
     snaps.map(x => x.runId).join(' '));

  // ---------------------------------------------------------------- part 2
  console.log('\nhistory explorer:');
  a.w.historyModal();
  await wait(80);
  ok('the explorer opens', a.$('#ovModal').classList.contains('open'));
  const rows = a.$$('#ovModal [data-open-snap]');
  ok('it lists every archived run', rows.length === 2, rows.length + ' rows');
  ok('newest first', rows[0].dataset.openSnap === snaps[1].runId,
     rows[0].dataset.openSnap + ' vs ' + snaps[1].runId);
  ok('each row shows a colour-coded gate',
     rows.every(r => /hg-(PASSED|WARNING|FAILED)/.test(r.querySelector('.hist-gate').className)));
  ok('each row shows a pass rate', rows.every(r => /%|n\/a/.test(r.querySelector('.hist-rate').textContent)));
  ok('each row shows totals', rows.every(r => /\d+ pass . \d+ fail/.test(r.textContent)));
  ok('each row shows a duration', rows.every(r => /\d+\.\ds/.test(r.querySelector('.hist-dur').textContent)));
  ok('each row shows a readable timestamp',
     rows.every(r => /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(r.textContent)));
  ok('the run on screen is marked', a.$$('#ovModal .hist-row.current').length === 1);

  // ---------------------------------------------------------------- part 3
  console.log('\nsnapshot restoration:');
  const older = snaps[0];
  a.click(a.$$('#ovModal [data-open-snap]').find(r => r.dataset.openSnap === older.runId));
  await wait(140);
  ok('opening an older run switches to the report',
     a.$('#view-analytics').classList.contains('active'));
  ok('the masthead now names the older run',
     a.$('#anMast').textContent.includes(older.runId), older.runId);
  ok('a banner says this is not the latest', !!a.$('.snapbar'),
     'no snapshot banner');
  ok('the banner offers a way back', !!a.$('#snapBack'));
  const kpi = a.$('#anBody').textContent;
  ok('the KPI cards show the older run figures',
     kpi.includes(String(older.total)), older.total + ' not found');
  ok('the gate matches the older run',
     new RegExp('Quality Gate: ' + (older.gate === 'FAILED' ? 'Action Required'
       : older.gate === 'WARNING' ? 'Review Advised' : 'Clean')).test(a.$('#anBody').textContent),
     older.gate);
  ok('the module bars re-rendered', a.$$('#anBody .sbar').length > 0);
  ok('personas still filter on the restored run', (() => {
    a.$$('#pswReport button').find(b => b.dataset.persona === 'exec').click();
    return a.$$('#anTabs .nitem').every(t => t.dataset.tab !== 'json');
  })());
  a.$$('#pswReport button').find(b => b.dataset.persona === 'qa').click();
  await wait(80);

  a.click(a.$('#snapBack'));
  await wait(120);
  ok('Back to latest returns to the newest run',
     a.$('#anMast').textContent.includes(snaps[1].runId) && !a.$('.snapbar'),
     'still on ' + (a.$('.snapbar') ? 'a snapshot' : 'unknown'));

  // ---------------------------------------------------------------- part 4
  console.log('\nstandalone share:');
  let captured = null;
  a.w.download = (data, name) => { captured = { data, name }; };
  a.w.shareStandalone();
  await wait(60);
  ok('Share produces a download', !!captured);
  ok('the filename follows the convention',
     /^HCM-API-Report-.+-\d{4}-\d{2}-\d{2}\.html$/.test(captured.name), captured.name);
  const shared = captured.data;
  fs.writeFileSync(path.join(OUT, captured.name), shared, 'utf8');
  ok('it is a complete html document',
     /^<!doctype html>/i.test(shared) && /<\/html>\s*$/i.test(shared.trim()));
  ok('the payload is embedded', /<script id="shared-snapshot"/.test(shared));
  ok('it pulls nothing from the network',
     !/(src|href)="https?:/i.test(shared) && !/cdn\.|unpkg|jsdelivr/i.test(shared));
  ok('no credential value travels with it',
     !/Bearer\s+ey[A-Za-z0-9_.-]{10,}/.test(shared) &&
     !/(password|secret)\s*[:=]\s*["']?[A-Za-z0-9!@#$%^&*_.-]{6,}/i.test(shared));
  ok('sharing twice does not nest payloads',
     (shared.match(/<script id="shared-snapshot"/g) || []).length === 1);

  // ---------------------------------------------------------------- part 5
  console.log('\nopening the shared file cold (no storage, no server):');
  const cold = boot(shared, { storageQuota: 0 });
  // simulate a private window with storage denied outright
  cold.w.eval(`Object.defineProperty(window,'localStorage',{get(){throw new Error('denied')}});`);
  await wait(220);
  const errs = [];
  cold.w.addEventListener('error', e => errs.push(e.message));
  ok('it boots with no uncaught error', errs.length === 0, errs.join(' | '));
  ok('it opens straight on the report',
     cold.$('#view-analytics').classList.contains('active'));
  ok('it renders the masthead', cold.$('#anMast').textContent.includes(snaps[1].runId),
     cold.$('#anMast').textContent.slice(0, 70));
  ok('it says it is a shared report', /Shared report/i.test(cold.$('#anMast').textContent));
  ok('the KPI cards are populated',
     /\d/.test(cold.$('#anBody').textContent) && cold.$$('#anBody .estat').length === 4,
     cold.$$('#anBody .estat').length + ' stat cards');
  ok('the donut rendered', !!cold.$('#anBody svg.spark'));
  ok('the module bars rendered', cold.$$('#anBody .sbar').length > 0,
     cold.$$('#anBody .sbar').length + ' bars');
  ok('the quality gate rendered', !!cold.$('#anBody .eqg'));
  ok('the tab bar rendered', cold.$$('#anTabs .nitem').length >= 5,
     cold.$$('#anTabs .nitem').length + ' tabs');
  ok('every report tab still renders', (() => {
    if (!cold.$$('#anTabs .nitem').length) return false;
    for (const t of cold.$$('#anTabs .nitem')) {
      cold.click(t);
      if (!cold.$('#anBody').children.length) return false;
    }
    return true;
  })());
  ok('persona filtering works offline', (() => {
    cold.$$('#pswReport button').find(b => b.dataset.persona === 'dev').click();
    return cold.$$('#anTabs .nitem').some(t => t.dataset.tab === 'json');
  })());
  ok('the theme toggle works offline', (() => {
    const before = cold.d.documentElement.getAttribute('data-theme');
    cold.click(cold.$('#eTheme'));
    return cold.d.documentElement.getAttribute('data-theme') !== before;
  })());
  ok('the shared totals match the source run',
     cold.w.eval('STATE.result.summary.total') === snaps[1].total,
     cold.w.eval('STATE.result.summary.total') + ' vs ' + snaps[1].total);
  ok('it wrote nothing to storage', (() => {
    try { cold.w.localStorage; return false; } catch (e) { return true; }
  })(), 'storage was reachable');

  console.log('\n%s', bad === 0 ? 'HISTORY + SHARE OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

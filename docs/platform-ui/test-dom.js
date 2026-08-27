/* Real-DOM smoke test: load the built page in jsdom and drive it the way a
   QA engineer would — pick APIs, run, View Report, walk the tabs, toggle theme. */
const fs = require('fs');
const { JSDOM } = require('jsdom');

const F = 'c:\\Users\\parth.divekar\\Downloads\\API_Automation\\docs\\platform-ui\\unified-console.html';
const dom = new JSDOM(fs.readFileSync(F, 'utf8'), {
  runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/'
});
const { window } = dom;
const doc = window.document;
const $ = s => doc.querySelector(s);
const $$ = s => [...doc.querySelectorAll(s)];
const click = el => el.dispatchEvent(new window.Event('click', { bubbles: true }));
const vis = id => $('#view-' + id).classList.contains('active');

let bad = 0, errs = [];
window.addEventListener('error', e => errs.push(e.message));
const ok = (n, c, d) => { console.log((c ? '  PASS  ' : '  FAIL  ') + n + (c ? '' : '\n          -> ' + d)); if (!c) bad++; };

const wait = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  await wait(150);

  console.log('boot:');
  ok('no uncaught error during boot', errs.length === 0, errs.join(' | '));
  ok('lands on the Home view', vis('home'));
  ok('status strip rendered', $('#strip').children.length >= 4,
     $('#strip').children.length + ' chips');
  ok('suite cards rendered', $$('#suitesGrid .suite-card').length > 0,
     $$('#suitesGrid .suite-card').length + ' cards');
  ok('every suite card shows an API count', $$('.sc-h .pill').length === $$('.suite-card').length);
  ok('endpoint rows rendered', $$('.sc-row').length === 45, $$('.sc-row').length + ' rows');
  ok('multi-select rendered', $$('#msBox .ms-item').length === 45,
     $$('#msBox .ms-item').length + ' items');
  ok('Run is disabled with nothing selected', $('#btnRun').disabled);
  ok('View Report is disabled before any run', $('#btnViewReportHome').disabled);

  console.log('\nselection:');
  click($('#btnSelAll'));
  await wait(30);
  ok('Select All selects everything', $('#btnRun').disabled === false &&
     /45 APIs Selected/.test($('#selBadge').textContent), $('#selBadge').textContent);
  click($('#btnSelNone'));
  await wait(30);
  ok('Clear Selection empties it', $('#btnRun').disabled === true);

  // select six endpoints via their checkboxes
  const boxes = $$('#msBox input[type=checkbox]').slice(0, 6);
  boxes.forEach(b => { b.checked = true; b.dispatchEvent(new window.Event('change', { bubbles: true })); });
  await wait(40);
  ok('checkbox selection updates the badge', /6 APIs Selected/.test($('#selBadge').textContent),
     $('#selBadge').textContent);
  ok('run button label counts the batch', /Run Selected Batch \(6\)/.test($('#btnRunLabel').textContent),
     $('#btnRunLabel').textContent);

  console.log('\nsuite card -> detail:');
  click($$('.sc-row')[0]);
  await wait(60);
  ok('clicking an endpoint opens Detail', vis('detail'));
  ok('Configure Run is populated', $('#dMethod').value.length > 0 && $('#dEndpoint').value.length > 0,
     $('#dMethod').value + ' ' + $('#dEndpoint').value);
  ok('endpoint URL is a real host, not a placeholder',
     /^https:\/\//.test($('#dEndpoint').value) && !/\{\{/.test($('#dEndpoint').value),
     $('#dEndpoint').value);
  ok('credential alias list offers only registered aliases',
     [...$('#dAlias').options].slice(1).every(o => /_UAT_01$/.test(o.value)),
     [...$('#dAlias').options].map(o => o.value).join(','));
  ok('auth provider selector is populated', $('#dProvider').options.length > 0);
  ok('12 global checks listed', $$('#dCases .tc').length >= 12, $$('#dCases .tc').length + ' cards');
  ok('pre-run state is PLANNED, never PASS',
     $$('#dCases .st').every(s => !/st-PASS/.test(s.className)),
     $$('#dCases .st').map(s => s.textContent).join(','));
  ok('View Report disabled before this API has a result', $('#btnViewReport').disabled);

  console.log('\nback + run:');
  click($('#btnBackHome'));
  await wait(40);
  ok('Back to Suites returns Home', vis('home'));

  click($('#btnRun'));
  await wait(1400);
  ok('a finished run lands on the Report view', vis('analytics'));
  ok('no uncaught error during the run', errs.length === 0, errs.join(' | '));
  const kpi = $('.scroll#anBody') ? $('#anBody').textContent : '';
  ok('report shows a pass rate', /%|n\/a/.test(kpi));
  ok('report is not empty', $('#anBody').children.length > 0);

  console.log('\nView Report handoff:');
  $$('.rail-btn[data-view]').find(b => b.dataset.view === 'home').click();
  await wait(60);
  ok('can return to Console', vis('home'));
  ok('View Report is now enabled', $('#btnViewReportHome').disabled === false);
  click($('#btnViewReportHome'));
  await wait(60);
  ok('View Report opens the Enterprise dashboard', vis('analytics'));

  click($$('.sc-row')[0]);   // rail is on analytics; go via detail
  await wait(60);

  console.log('\nreport tabs:');
  for (const t of $$('#anTabs .tab')) {
    const name = t.dataset.tab;
    errs.length = 0;
    $$('.rail-btn[data-view]').find(b => b.dataset.view === 'analytics').click();
    await wait(20);
    click(t);
    await wait(60);
    ok(`tab "${name}" renders`, $('#anBody').children.length > 0 && errs.length === 0,
       errs.join(' | ') || 'empty body');
  }

  console.log('\ntheme toggle:');
  const root = doc.documentElement;
  const start = root.getAttribute('data-theme');
  ok('toggle exists in the topbar', !!$('#btnTheme'));
  ok('toggle is a labelled switch', $('#btnTheme').getAttribute('role') === 'switch' &&
     !!$('#btnTheme').getAttribute('aria-label'));
  ok('label reflects the starting theme',
     $('#themeLbl').textContent.toLowerCase() === (start === 'dark' ? 'dark' : 'light'),
     `${start} vs "${$('#themeLbl').textContent}"`);
  click($('#btnTheme'));
  await wait(60);
  const flipped = root.getAttribute('data-theme');
  ok('clicking flips the theme', flipped !== start, `${start} -> ${flipped}`);
  ok('aria-checked tracks the theme',
     $('#btnTheme').getAttribute('aria-checked') === String(flipped === 'dark'));
  ok('label tracks the theme', $('#themeLbl').textContent.toLowerCase() === flipped);
  ok('charts survive a theme flip', $('#anBody').children.length > 0 && errs.length === 0,
     errs.join(' | '));
  click($('#btnTheme'));
  await wait(60);
  ok('toggling back restores the original theme', root.getAttribute('data-theme') === start);

  console.log('\npersistence:');
  const saved = JSON.parse(window.localStorage.getItem('hcm-console-v1') || '{}');
  ok('run result persisted', !!saved.result);
  ok('theme persisted', !!saved.theme);
  ok('selection persisted', Array.isArray(saved.selected) && saved.selected.length === 6,
     JSON.stringify(saved.selected || []).slice(0, 80));

  console.log('\nnavigator:');
  $$('.rail-btn[data-view]').find(b => b.dataset.view === 'home').click();
  await wait(40);
  click($('#btnOpenNav'));
  await wait(60);
  ok('navigator opens', $('#navPanel').classList.contains('on'));
  ok('navigator lists endpoints', $$('#navBody [data-nav]').length === 45,
     $$('#navBody [data-nav]').length + '');
  click($('#btnCloseNav'));
  await wait(40);
  ok('navigator closes', !$('#navPanel').classList.contains('on'));

  console.log('\n%s', bad === 0 ? 'DOM SMOKE OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

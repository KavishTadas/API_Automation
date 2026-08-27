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
const goHome   = () => click($('#railMenu [data-menu-act="suites"]'));
const goReport = () => click($('#railMenu [data-view="analytics"]'));

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
  const kpi = $('#anBody').textContent;
  ok('report shows a pass rate', /%|n\/a/.test(kpi));
  ok('report is not empty', $('#anBody').children.length > 0);

  console.log('\nView Report handoff:');
  goHome();
  await wait(60);
  ok('can return to Console', vis('home'));
  ok('View Report is now enabled', $('#btnViewReportHome').disabled === false);
  click($('#btnViewReportHome'));
  await wait(60);
  ok('View Report opens the Enterprise dashboard', vis('analytics'));

  click($$('.sc-row')[0]);   // rail is on analytics; go via detail
  await wait(60);

  console.log('\nreport tabs:');
  for (const t of $$('#anTabs .nitem')) {
    const name = t.dataset.tab;
    errs.length = 0;
    goReport();
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

  console.log('\nmasthead + quality gate:');
  goReport();
  await wait(80);
  const mast = $('#anMast').textContent;
  ok('masthead shows environment', /ENV:\s*UAT/.test(mast), mast.slice(0, 90));
  ok('masthead shows the run id', /Run:\s*run-/.test(mast));
  ok('masthead shows a timestamp', /\d{4}-\d{2}-\d{2}T/.test(mast));
  ok('masthead shows total duration', /\d+\.\ds Total Duration/i.test(mast));
  ok('masthead marks the run simulated', /simulated/i.test(mast));
  ok('masthead lists engines', $$('#anMast .eng-c').length >= 1);
  ok('masthead scores the contract rules', /\d+ \/ \d+ Rules Passed/i.test(mast));
  ok('quality gate banner present', !!$('.eqg'));
  ok('gate level is one of the three',
     /Quality Gate: (PASSED|WARNING|FAILED)/.test(mast), mast.match(/Quality Gate: \w+/));
  ok('Back to workbench present in masthead', !!$('#anMast [data-back]'));

  console.log('\ntrend + sign-off:');
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'overview').click();
  await wait(60);
  ok('sign-off panel rendered', /Executive Sign-Off Status/i.test($('#anBody').textContent));
  ok('sign-off states the SLA gate at 700ms', /700ms/.test($('#anBody').textContent));
  ok('trend card rendered', /Historical Build Trend/i.test($('#anBody').textContent));
  ok('one run shows the not-enough-runs notice',
     /Not enough runs yet/.test($('#anBody').textContent) || !!$('.trend'));

  // second run -> trend should draw
  goHome();
  await wait(50);
  click($('#btnRun'));
  await wait(1400);
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'overview').click();
  await wait(80);
  ok('trend chart draws after a second run', !!$('.trend'));
  ok('trend has a point per run', $$('.trend circle').length + $$('.trend text').filter(t =>
     t.textContent === 'n/a').length >= 2, $$('.trend circle').length + ' points');
  ok('trend is labelled for screen readers', /role="img"/.test($('#anBody').innerHTML));

  console.log('\nshared data contract:');
  const shared = JSON.parse(window.localStorage.getItem('HCM_SHARED_RUN_DATA') || 'null');
  ok('HCM_SHARED_RUN_DATA is published', !!shared);
  ok('bundle carries runId, environment, summary',
     !!(shared.runId && shared.environment && shared.summary));
  ok('bundle lists executed APIs', Array.isArray(shared.executedApis) && shared.executedApis.length > 0,
     (shared.executedApis || []).length + '');
  ok('bundle lists modules with pass/fail', Array.isArray(shared.modules) &&
     shared.modules.every(m => m.name && 'passed' in m && 'failed' in m));
  ok('bundle carries a quality gate',
     ['PASSED', 'WARNING', 'FAILED'].includes(shared.summary.qualityGate), shared.summary.qualityGate);
  ok('bundle keeps the contract pass-rate basis',
     shared.summary.passRateBasis === 'PASS / (PASS + FAIL)', shared.summary.passRateBasis);
  ok('bundle pass rate is null (not 0) when nothing asserted',
     shared.summary.passRateApplicable || shared.summary.passRate === null);
  ok('defects carry a reproducer cURL',
     (shared.defects || []).every(d => /^curl /.test(d.curl || '')));
  ok('no credential value in the shared bundle',
     !/password|secret|Bearer\s+ey/i.test(JSON.stringify(shared)));
  ok('every defect names its module and endpoint',
     (shared.defects || []).every(d => d.module && d.endpoint));

  console.log('\npersonas:');
  const personas = $$('#pswReport button').map(b => b.dataset.persona);
  ok('five personas offered', personas.length === 5, personas.join(','));
  ok('Exec, Dev, QA, DevOps and All present',
     ['exec', 'dev', 'qa', 'devops', 'all'].every(p => personas.includes(p)), personas.join(','));

  const tabsFor = () => $$('#anTabs .nitem').map(t => t.dataset.tab);
  $$('#pswReport button').find(b => b.dataset.persona === 'exec').click();
  await wait(80);
  const execTabs = tabsFor();
  ok('Exec loses the raw-JSON tab', !execTabs.includes('json'), execTabs.join(','));
  ok('Exec loses the payload-inspection tab', !execTabs.includes('payloads'), execTabs.join(','));
  ok('Exec keeps performance and contract', execTabs.includes('perf') && execTabs.includes('compliance'));
  ok('Exec sees the sign-off panel',
     [...$('#anBody').querySelectorAll('[data-persona-for]')]
       .filter(e => /Executive Sign-Off Status/i.test(e.textContent)).every(e => e.style.display !== 'none'));

  $$('#pswReport button').find(b => b.dataset.persona === 'dev').click();
  await wait(80);
  ok('Dev gets the JSON tab back', tabsFor().includes('json'), tabsFor().join(','));
  ok('Dev hides the exec sign-off',
     [...$('#anBody').querySelectorAll('[data-persona-for]')]
       .filter(e => /Executive Sign-Off Status/i.test(e.textContent)).every(e => e.style.display === 'none'));

  $$('#pswReport button').find(b => b.dataset.persona === 'all').click();
  await wait(80);
  ok('All sees every tab', tabsFor().length === 9, tabsFor().join(','));
  ok('All hides no content',
     [...$('#view-analytics').querySelectorAll('[data-persona-for]')]
       .every(e => e.style.display !== 'none'));
  $$('#pswReport button').find(b => b.dataset.persona === 'qa').click();
  await wait(60);

  console.log('\nback navigation:');
  click($('#anMast [data-back]'));
  await wait(60);
  ok('Back to workbench returns to Home', vis('home'));
  ok('selection survives the round trip', /6 APIs Selected/.test($('#selBadge').textContent),
     $('#selBadge').textContent);

  console.log('\nsuites header + live search:');
  const type = v => { $('#apiSearch').value = v;
                      $('#apiSearch').dispatchEvent(new window.Event('input', { bubbles: true })); };

  ok('heading reads Test Suites & API Endpoints',
     /Test Suites & API Endpoints/.test($('.sect-head h2').textContent),
     $('.sect-head h2').textContent);
  ok('subtitle sits under the heading', $('.sect-head .sub') !== null);
  ok('subtitle counts all suites when unfiltered',
     /Showing all\s*11\s*suites/.test($('#suiteMatchHint').textContent.replace(/\s+/g, ' ')),
     $('#suiteMatchHint').textContent.trim());
  ok('search sits inside the header, below the heading',
     !!$('.sect-head .searchwrap') &&
     $('.sect-head .searchwrap').compareDocumentPosition($('.sect-head h2')) &
       window.Node.DOCUMENT_POSITION_PRECEDING);
  ok('all 11 suite cards render', $$('#suitesGrid .suite-card').length === 11,
     $$('#suitesGrid .suite-card').length + ' cards');
  ok('all 45 endpoint rows render', $$('#suitesGrid .sc-row').length === 45,
     $$('#suitesGrid .sc-row').length + ' rows');
  ok('every row has method, id, name and path',
     $$('#suitesGrid .sc-row').every(r =>
       r.querySelector('.m') && r.querySelector('.id') &&
       r.querySelector('.nm') && r.querySelector('.pa')));
  ok('clear button hidden with no query', $('#apiSearchClear').hidden);

  // by method
  type('POST');
  await wait(60);
  ok('filters by method', $$('#suitesGrid .sc-row').length > 0 &&
     $$('#suitesGrid .sc-row').every(r => /POST/i.test(r.querySelector('.m').textContent)),
     $$('#suitesGrid .sc-row').length + ' rows');
  ok('method matches are highlighted', $$('#suitesGrid mark').length > 0);
  ok('subtitle reports the filtered counts',
     /of 45 endpoint/.test($('#suiteMatchHint').textContent),
     $('#suiteMatchHint').textContent.trim());
  ok('clear button appears with a query', !$('#apiSearchClear').hidden);
  ok('the multi-select filters in step',
     $$('#msBox .ms-item').length === $$('#suitesGrid .sc-row').length,
     $$('#msBox .ms-item').length + ' vs ' + $$('#suitesGrid .sc-row').length);

  // by path
  type('/attendance');
  await wait(60);
  ok('filters by path', $$('#suitesGrid .sc-row').length > 0 &&
     $$('#suitesGrid .sc-row').every(r => /attendance/i.test(r.textContent)),
     $$('#suitesGrid .sc-row').length + ' rows');

  // by module
  type('Leave');
  await wait(60);
  ok('filters by module', $$('#suitesGrid .suite-card').length > 0 &&
     $$('#suitesGrid .suite-card').every(c => /leave/i.test(c.textContent)),
     $$('#suitesGrid .suite-card').length + ' cards');

  // by display id
  type('API-001');
  await wait(60);
  ok('filters by display id', $$('#suitesGrid .sc-row').length === 1,
     $$('#suitesGrid .sc-row').length + ' rows');

  // case-insensitive
  type('leave');
  const lower = $$('#suitesGrid .sc-row').length;
  type('LEAVE');
  await wait(60);
  ok('search is case-insensitive', $$('#suitesGrid .sc-row').length === lower,
     lower + ' vs ' + $$('#suitesGrid .sc-row').length);

  // no matches
  type('zzzznope');
  await wait(60);
  ok('empty state shown when nothing matches', !!$('#suitesGrid .empty'));
  ok('empty state says what it searched',
     /Nothing matches/.test($('#suitesGrid').textContent));
  ok('subtitle says no match', /No endpoint matches/.test($('#suiteMatchHint').textContent),
     $('#suiteMatchHint').textContent.trim());

  // a query that looks like markup must not become markup
  type('<img src=x onerror=alert(1)>');
  await wait(60);
  ok('a markup-shaped query cannot inject', $$('#suitesGrid img').length === 0 &&
     $$('#suiteMatchHint img').length === 0);

  click($('#apiSearchClear'));
  await wait(60);
  ok('clear restores every suite', $$('#suitesGrid .suite-card').length === 11,
     $$('#suitesGrid .suite-card').length + ' cards');
  ok('clear restores every row', $$('#suitesGrid .sc-row').length === 45);
  ok('clear hides its own button', $('#apiSearchClear').hidden);
  ok('clear restores the unfiltered subtitle',
     /Showing all/.test($('#suiteMatchHint').textContent));

  click($$('#suitesGrid .sc-row')[0]);
  await wait(60);
  ok('a row still opens the endpoint', vis('detail'));
  goHome();
  await wait(60);

  console.log('\nside menu:');
  ok('menu rendered on every view', $$('#railMenu .rail-item').length > 0,
     $$('#railMenu .rail-item').length + ' rows');
  ok('menu has Workbench, Report and Actions sections',
     $$('#railMenu .rail-sec').map(s => s.textContent.trim())
       .filter(x => /^(Workbench|Report|Actions)$/.test(x)).length === 3,
     $$('#railMenu .rail-sec').map(s => s.textContent.trim()).join(' | '));

  const wb = $$('#railMenu .rail-item').filter(b =>
    ['suites', 'apis'].includes(b.dataset.menuAct));
  ok('Workbench offers exactly Suites and APIs', wb.length === 2,
     wb.map(b => b.dataset.menuAct).join(','));
  ok('the removed Workbench rows are gone',
     !$$('#railMenu .rail-item').some(b => /Endpoint detail|Run selected/i.test(b.textContent)),
     $$('#railMenu .rail-item').map(b => b.textContent.trim().split('\n')[0]).join(' | '));
  ok('Report offers exactly Open Report',
     $$('#railMenu [data-view]').length === 1 &&
     /Open Report/i.test($('#railMenu [data-view="analytics"]').textContent));
  ok('no per-section report rows remain', $$('#railMenu [data-menu-tab]').length === 0,
     $$('#railMenu [data-menu-tab]').length + ' rows');
  ok('Suites counts the modules',
     /\b11\b/.test($('#railMenu [data-menu-act="suites"]').textContent),
     $('#railMenu [data-menu-act="suites"]').textContent.trim());
  ok('APIs counts the endpoints',
     /45/.test($('#railMenu [data-menu-act="apis"]').textContent),
     $('#railMenu [data-menu-act="apis"]').textContent.trim());

  click($('#railMenu [data-menu-act="apis"]'));
  await wait(70);
  ok('APIs row lands on the console', vis('home'));
  ok('APIs row marks itself active',
     $('#railMenu [data-menu-act="apis"]').classList.contains('active'));
  goHome();
  await wait(70);
  ok('Suites row marks itself active',
     $('#railMenu [data-menu-act="suites"]').classList.contains('active'));

  goReport();
  await wait(80);
  ok('Open Report opens the report', vis('analytics'));
  ok('menu still present on the report', $$('#railMenu .rail-item').length > 0);
  ok('Open Report marks itself active',
     $('#railMenu [data-view="analytics"]').classList.contains('active'));

  console.log('\nreport theme switch:');
  ok('report masthead carries a theme switch', !!$('#eTheme'));
  ok('it is a labelled switch', $('#eTheme').getAttribute('role') === 'switch' &&
     !!$('#eTheme').getAttribute('aria-label'));
  const beforeT = doc.documentElement.getAttribute('data-theme');
  errs.length = 0;
  click($('#eTheme'));
  await wait(80);
  const afterT = doc.documentElement.getAttribute('data-theme');
  ok('it flips the theme', afterT !== beforeT, beforeT + ' -> ' + afterT);
  ok('both switches report the same state',
     $('#eTheme').getAttribute('aria-checked') === $('#btnTheme').getAttribute('aria-checked'),
     $('#eTheme').getAttribute('aria-checked') + ' vs ' + $('#btnTheme').getAttribute('aria-checked'));
  ok('the report survives the flip', $('#anBody').children.length > 0 && errs.length === 0,
     errs.join(' | '));
  click($('#eTheme'));
  await wait(70);
  ok('flipping back restores it', doc.documentElement.getAttribute('data-theme') === beforeT);

  click($('#btnRailCollapse'));
  await wait(40);
  ok('menu collapses', $('#rail').classList.contains('collapsed'));
  ok('collapsed state persisted', window.localStorage.getItem('hcm-rail') === '1');
  click($('#btnRailCollapse'));
  await wait(40);
  ok('menu expands again', !$('#rail').classList.contains('collapsed'));

  goHome();
  await wait(60);

  console.log('\nnavigator:');
  goHome();
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

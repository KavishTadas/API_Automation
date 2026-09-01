/* Real-DOM smoke test: load the built page in jsdom and drive it the way a
   QA engineer would — pick APIs, run, View Report, walk the tabs, toggle theme. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const F = path.join(__dirname, 'unified-console.html');
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
  ok('endpoint rows rendered', $$('.sc-row').length === 44, $$('.sc-row').length + ' rows');
  ok('multi-select rendered', $$('#msBox .ms-item').length === 44,
     $$('#msBox .ms-item').length + ' items');
  ok('Run is disabled with nothing selected', $('#btnRun').disabled);
  ok('View Report is disabled before any run', $('#btnViewReportHome').disabled);

  console.log('\nselection:');
  click($('#btnSelAll'));
  await wait(30);
  ok('Select All selects everything', $('#btnRun').disabled === false &&
     /44 APIs Selected/.test($('#selBadge').textContent), $('#selBadge').textContent);
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
     /Showing all\s*10\s*suites/.test($('#suiteMatchHint').textContent.replace(/\s+/g, ' ')),
     $('#suiteMatchHint').textContent.trim());
  ok('search sits inside the header, below the heading',
     !!$('.sect-head .searchwrap') &&
     $('.sect-head .searchwrap').compareDocumentPosition($('.sect-head h2')) &
       window.Node.DOCUMENT_POSITION_PRECEDING);
  ok('all 10 suite cards render', $$('#suitesGrid .suite-card').length === 10,
     $$('#suitesGrid .suite-card').length + ' cards');
  ok('all 44 endpoint rows render', $$('#suitesGrid .sc-row').length === 44,
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
     /of 44 endpoint/.test($('#suiteMatchHint').textContent),
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
  ok('clear restores every suite', $$('#suitesGrid .suite-card').length === 10,
     $$('#suitesGrid .suite-card').length + ' cards');
  ok('clear restores every row', $$('#suitesGrid .sc-row').length === 44);
  ok('clear hides its own button', $('#apiSearchClear').hidden);
  ok('clear restores the unfiltered subtitle',
     /Showing all/.test($('#suiteMatchHint').textContent));

  click($$('#suitesGrid .sc-row')[0]);
  await wait(60);
  ok('a row still opens the endpoint', vis('detail'));
  goHome();
  await wait(60);

  console.log('\nsuites layout + clickable cards:');
  goHome();
  await wait(80);
  const css3 = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');

  // The bug: .view.active{display:flex} laid home's children out in a row,
  // so heading, search and grid were crushed into columns beside each other.
  ok('a scrolling view stacks rather than laying out in a row',
     /\.view\.scroll\.active\{display:block\}/.test(css3));
  ok('the report is still a flex column',
     /#view-analytics\{[^}]*flex-direction:column/.test(css3));

  const head = $('#view-home .sect-head');
  ok('header, search and grid are siblings in order', (() => {
    const kids = [...$('#view-home').children];
    return kids.indexOf(head) < kids.indexOf($('#suitesGrid'));
  })());
  ok('the search sits inside the header, under the heading',
     !!$('.sect-head .searchwrap') &&
     [...head.children].indexOf($('.sect-head h2')) <
     [...head.children].indexOf($('.sect-head .searchwrap')));
  ok('the search spans the full width',
     /\.sect-head \.searchwrap\{display:block;width:100%/.test(css3));
  ok('the header block spans the full width',
     /\.sect-head\{display:block;width:100%/.test(css3));
  ok('suite cards fill their grid track', /\.suite-card\{[^}]*width:100%/.test(css3));
  ok('card titles cannot bleed into their neighbour',
     /\.sc-t \.nm\{display:block[^}]*text-overflow:ellipsis;white-space:nowrap\}/.test(css3));
  ok('the grid keeps a real gutter', /\.suites-grid\{[^}]*gap:var\(--gap-md\)/.test(css3));

  // clickable suite headers
  const cards = $$('#suitesGrid .suite-card');
  ok('all 10 suites render as cards', cards.length === 10, cards.length + ' cards');
  ok('every card header is a button',
     cards.every(c => c.querySelector('.sc-h') &&
                      c.querySelector('.sc-h').tagName === 'BUTTON'));
  ok('every card header reports its expanded state',
     cards.every(c => c.querySelector('.sc-h').hasAttribute('aria-expanded')));
  ok('every endpoint row is reachable by keyboard',
     $$('#suitesGrid .sc-row').every(r => r.getAttribute('role') === 'button' &&
                                          r.getAttribute('tabindex') === '0'));

  const first = cards[0];
  const mod = first.dataset.suite;
  const rowsBefore = first.querySelectorAll('.sc-row').length;
  ok('a suite lists its endpoints', rowsBefore > 0, rowsBefore + ' rows');
  click(first.querySelector('.sc-h'));
  await wait(70);
  const after = $(`#suitesGrid [data-suite="${mod.replace(/"/g, '\\"')}"]`);
  ok('clicking a suite header collapses it', after.classList.contains('collapsed'));
  ok('collapsed state is remembered',
     (JSON.parse(window.localStorage.getItem('hcm-console-v1') || '{}').closedSuites || [])
       .includes(mod));
  click(after.querySelector('.sc-h'));
  await wait(70);
  ok('clicking again expands it',
     !$(`#suitesGrid [data-suite="${mod.replace(/"/g, '\\"')}"]`).classList.contains('collapsed'));

  // an endpoint row still opens its detail
  click($$('#suitesGrid .sc-row')[0]);
  await wait(70);
  ok('an endpoint row opens the endpoint', vis('detail'));
  goHome();
  await wait(70);

  // a filter must override a collapsed suite, or matches would hide
  click($$('#suitesGrid .suite-card')[0].querySelector('.sc-h'));
  await wait(60);
  $('#apiSearch').value = 'GET';
  $('#apiSearch').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(70);
  ok('a search expands collapsed suites so matches stay visible',
     $$('#suitesGrid .suite-card.collapsed').length === 0,
     $$('#suitesGrid .suite-card.collapsed').length + ' still collapsed');
  click($('#apiSearchClear'));
  await wait(70);

  console.log('\nmenu colour:');
  const rows = $$('#railMenu .rail-item');
  ok('every row wraps its icon in a tintable span',
     rows.every(b => b.querySelector('.ri > svg')));
  const tints = rows.filter(b => !b.classList.contains('active'))
    .map(b => (b.querySelector('.ri').getAttribute('style') || ''));
  ok('inactive rows carry a colour', tints.every(x => /color:#/.test(x)), tints.join(' | '));
  // distinct *within a section* -- across sections a hue may repeat, which is
  // what keeps Export amber instead of being pushed onto a danger colour
  ok('tints are distinct within each section', (() => {
    const kids = [...$('#railMenu').children];
    let seen = [], okAll = true;
    for (const el of kids) {
      if (el.classList.contains('rail-sec')) { seen = []; continue; }
      if (!el.classList.contains('rail-item') || el.classList.contains('active')) continue;
      const c = el.querySelector('.ri').getAttribute('style') || '';
      if (seen.includes(c)) okAll = false;
      seen.push(c);
    }
    return okAll;
  })(), 'a section repeats a tint');
  ok('the active row drops its tint and takes the accent',
     rows.filter(b => b.classList.contains('active'))
         .every(b => !b.querySelector('.ri').getAttribute('style')));
  ok('section headers carry a matching dot',
     $$('#railMenu .rail-sec .rs-dot').length === $$('#railMenu .rail-sec').length,
     $$('#railMenu .rail-sec .rs-dot').length + ' of ' + $$('#railMenu .rail-sec').length);
  ok('section dots are coloured',
     $$('#railMenu .rs-dot').every(d => /background:#/.test(d.getAttribute('style') || '')));
  ok('the assertion-gap chip is called out',
     !!$('#railMenu .rail-gap') &&
     /\d+ assertion gap/.test($('#railMenu .rail-gap').textContent),
     ($('#railMenu .rail-gap') || {}).textContent);
  ok('the gap chip explains itself on hover',
     /assert nothing/.test(($('#railMenu .rail-gap') || {}).title || ''));
  ok('Open Report badges the failure count once a run exists',
     !$('#railMenu [data-view="analytics"]').disabled
       ? !!$('#railMenu [data-view="analytics"] .ct') : true,
     ($('#railMenu [data-view="analytics"] .ct') || {}).textContent);
  ok('labels stay in the text colour, so contrast never rides on the tint',
     rows.every(b => !(b.querySelector('.lb').getAttribute('style') || '').includes('color')));

  console.log('\nside menu:');
  ok('menu rendered on every view', $$('#railMenu .rail-item').length > 0,
     $$('#railMenu .rail-item').length + ' rows');
  ok('menu has Workbench, Report and Actions sections',
     $$('#railMenu .rail-sec').map(s => s.textContent.trim())
       .filter(x => /^(Workbench|Report|Actions)$/.test(x)).length === 3,
     $$('#railMenu .rail-sec').map(s => s.textContent.trim()).join(' | '));

  const wb = $$('#railMenu .rail-item').filter(b => b.dataset.menuAct === 'suites');
  ok('Workbench offers a single Suites & APIs row', wb.length === 1,
     $$('#railMenu .rail-item').map(b => b.dataset.menuAct || b.dataset.view).join(','));
  ok('the duplicate APIs row is gone',
     !$$('#railMenu .rail-item').some(b => b.dataset.menuAct === 'apis'));
  ok('the removed Workbench rows are gone',
     !$$('#railMenu .rail-item').some(b => /Endpoint detail|Run selected/i.test(b.textContent)),
     $$('#railMenu .rail-item').map(b => b.textContent.trim().split('\n')[0]).join(' | '));
  ok('Report offers exactly Open Report',
     $$('#railMenu [data-view]').length === 1 &&
     /Open Report/i.test($('#railMenu [data-view="analytics"]').textContent));
  ok('no per-section report rows remain', $$('#railMenu [data-menu-tab]').length === 0,
     $$('#railMenu [data-menu-tab]').length + ' rows');
  ok('the row counts suites and endpoints',
     /10\s*\/\s*44/.test($('#railMenu [data-menu-act="suites"]').textContent),
     $('#railMenu [data-menu-act="suites"]').textContent.trim());

  goHome();
  await wait(70);
  ok('the Suites row lands on the console', vis('home'));
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

  console.log('\nlight theme contrast:');
  const cssL = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');
  const lum = h => {
    const v = h.replace('#', '');
    const [r, g, b] = [0, 2, 4].map(i => parseInt(v.slice(i, i + 2), 16) / 255);
    const f = c => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const tok = name => {
    const m = cssL.match(new RegExp('--' + name + ':\s*(#[0-9a-fA-F]{6})'));
    return m && m[1];
  };

  // :root is the light theme; dark overrides every one of these
  for (const [name, floor] of [['text', 7], ['text-dim', 4.5], ['text-faint', 4.5]]) {
    const hex = tok(name);
    const r = hex ? ratio(hex, '#ffffff') : 0;
    ok(`--${name} reads on a white panel (${hex} ${r.toFixed(2)}:1)`, r >= floor,
       `needs ${floor}:1`);
  }
  for (const name of ['s400', 's500', 's600']) {
    const hex = (cssL.match(new RegExp('--' + name + ':\s*(#[0-9a-fA-F]{6})', 'g')) || [])
      .pop().split(':')[1].trim();
    const r = ratio(hex, '#ffffff');
    ok(`report --${name} reads on white (${hex} ${r.toFixed(2)}:1)`, r >= 4.5, 'needs 4.5:1');
  }
  // surfaces are blue-tinted now, so white is no longer the only background
  // text lands on -- check the darkest tint too
  for (const [surface, label] of [['#eef4fd', 'the blue inset'],
                                  ['#eaf1fc', 'a table header'],
                                  ['#e6eefb', 'a hovered row'],
                                  ['#e0eaf9', 'the deepest hover']]) {
    for (const name of ['text', 'text-dim', 'text-faint']) {
      const hex = tok(name), r = ratio(hex, surface);
      ok(`--${name} reads on ${label} (${r.toFixed(2)}:1)`, r >= 4.5, `${hex} on ${surface}`);
    }
  }
  ok('the accent still reads on the blue inset',
     ratio(tok('accent'), '#eef4fd') >= 4.5,
     tok('accent') + ' = ' + ratio(tok('accent'), '#eef4fd').toFixed(2));

  ok('the page is distinguishable from a panel',
     ratio(tok('bg'), '#ffffff') >= 1.12,
     tok('bg') + ' vs #ffffff = ' + ratio(tok('bg'), '#ffffff').toFixed(2));

  ok('every light-only rule is scoped away from dark',
     (cssL.match(/:root:not\(\[data-theme="dark"\]\)/g) || []).length >= 10 &&
     !/:root:not\(\[data-theme="light"\]\)/.test(cssL),
     'a light rule could leak into dark');

  // and the dark theme still overrides what light just changed
  const darkBlock = (cssL.match(/:root\[data-theme="dark"\]\{([\s\S]*?)\}/) || [])[1] || '';
  ok('dark still defines its own text tokens',
     ['--text:', '--text-dim:', '--text-faint:', '--bg:', '--line:']
       .every(t => darkBlock.includes(t)),
     'dark would inherit a light value');

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

  console.log('\nreport header icons:');
  goReport();
  await wait(90);
  const css = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');

  const mastSvgs = $$('#anMast svg');
  ok('masthead renders icons', mastSvgs.length > 0, mastSvgs.length + ' glyphs');
  ok('every masthead glyph carries a size class',
     mastSvgs.every(g => g.classList.contains('rico')),
     mastSvgs.filter(g => !g.classList.contains('rico'))
       .map(g => g.getAttribute('class')).join(' | ') || 'none');
  ok('no masthead glyph sets its own width attribute',
     mastSvgs.every(g => !g.hasAttribute('width')),
     mastSvgs.filter(g => g.hasAttribute('width')).length + ' with width');
  ok('.rico is pinned to 14px', /\.rico\{width:14px;height:14px/.test(css));
  ok('the ENV-line glyphs are pinned to 14px',
     /\.emast-meta \.ic svg\{width:14px;height:14px\}/.test(css));

  // the same rule must not have caught the charts
  ok('charts are not sized as icons',
     $$('#anBody .spark, #anBody .trend').every(c => !c.classList.contains('rico')),
     $$('#anBody .spark, #anBody .trend').length + ' charts');
  ok('the donut keeps its own dimensions',
     !$('#anBody .spark') || $('#anBody .spark').hasAttribute('width'));

  ok('metadata items are laid out as flex rows',
     /\.emast-meta>span\{display:inline-flex/.test(css));
  const seps = $$('#anMast .emast-meta .sep');
  ok('separator dots between metadata items', seps.length === 3,
     seps.length + ' separators');
  ok('separators are bullets', seps.every(x => x.textContent.trim() === '•'),
     seps.map(x => x.textContent.trim()).join(''));

  console.log('\npersona buttons:');
  const pbtns = $$('#pswReport button');
  ok('five persona buttons', pbtns.length === 5, pbtns.length + '');
  ok('buttons are spaced apart', /\.psw\{[^}]*gap:5px/.test(css));
  ok('exactly one is active', pbtns.filter(b => b.classList.contains('active')).length === 1,
     pbtns.filter(b => b.classList.contains('active')).map(b => b.dataset.persona).join(','));
  ok('the active button carries the glow',
     /\.psw button\.active\{[^}]*box-shadow:0 0 12px rgba\(62,217,197,\.4\)/.test(css));
  ok('the glow pulses', /animation:pswPulse/.test(css) && /@keyframes pswPulse/.test(css));
  ok('the pulse is stilled for reduced motion',
     /prefers-reduced-motion:reduce\)\{\s*\.psw button\.active\{animation:none/.test(css));
  ok('buttons show a focus ring', /\.psw button:focus-visible\{outline/.test(css));

  // the highlight must follow the selection
  const wasActive = pbtns.find(b => b.classList.contains('active')).dataset.persona;
  pbtns.find(b => b.dataset.persona === 'devops').click();
  await wait(90);
  const now = $$('#pswReport button');
  ok('the glow follows the selection',
     now.filter(b => b.classList.contains('active')).length === 1 &&
     now.find(b => b.classList.contains('active')).dataset.persona === 'devops',
     now.filter(b => b.classList.contains('active')).map(b => b.dataset.persona).join(','));
  now.find(b => b.dataset.persona === wasActive).click();
  await wait(80);

  console.log('\ncategory + suite filters:');
  goReport();
  await wait(90);
  const css2 = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');

  // --- Categories tab ---
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'defects').click();
  await wait(90);
  const catBar = $('[data-fbar="catFilter"]');
  ok('Categories carries a filter bar', !!catBar);
  ok('every category is a real button',
     $$('[data-fbar="catFilter"] .fpill').length >= 5 &&
     $$('[data-fbar="catFilter"] .fpill').every(b => b.tagName === 'BUTTON'),
     $$('[data-fbar="catFilter"] .fpill').length + ' pills');
  ok('each pill carries its own count',
     $$('[data-fbar="catFilter"] .fpill').every(b => b.querySelector('.n')));
  ok('All is active to begin with',
     $('[data-fbar="catFilter"] .fpill.active').dataset.f === 'all',
     $('[data-fbar="catFilter"] .fpill.active').dataset.f);
  ok('pill counts sum to the All count',
     (() => {
       const pills = $$('[data-fbar="catFilter"] .fpill');
       const all = +pills.find(p => p.dataset.f === 'all').querySelector('.n').textContent;
       const rest = pills.filter(p => p.dataset.f !== 'all')
         .reduce((n, p) => n + (+p.querySelector('.n').textContent), 0);
       return all === rest;
     })(), 'sum mismatch');

  const secPill = $$('[data-fbar="catFilter"] .fpill').find(b => b.dataset.f === 'security');
  const secN = +secPill.querySelector('.n').textContent;
  click(secPill);
  await wait(90);
  ok('clicking a category filters the table',
     $('[data-fbar="catFilter"] .fpill.active').dataset.f === 'security',
     $('[data-fbar="catFilter"] .fpill.active').dataset.f);
  ok('the filtered table shows only that many rows',
     secN === 0 || $$('#anBody tbody tr').length === secN,
     secN + ' expected, ' + $$('#anBody tbody tr').length + ' shown');
  ok('an empty category says so rather than showing a blank pane',
     secN > 0 || /Nothing in this category/.test($('#anBody').textContent));

  click($$('[data-fbar="catFilter"] .fpill').find(b => b.dataset.f === 'all'));
  await wait(90);
  ok('All restores every row',
     $('[data-fbar="catFilter"] .fpill.active').dataset.f === 'all');

  // --- Suites tab ---
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'suites').click();
  await wait(90);
  ok('Suites carries a module filter bar', !!$('[data-fbar="modFilter"]'));
  const modPills = $$('[data-fbar="modFilter"] .fpill');
  ok('one pill per executed module plus All', modPills.length > 1,
     modPills.length + ' pills');
  ok('module pills are colour-coded by health',
     modPills.filter(p => p.dataset.f !== 'all').every(p => p.querySelector('.dot')));

  const firstMod = modPills.find(p => p.dataset.f !== 'all');
  const modN = +firstMod.querySelector('.n').textContent;
  click(firstMod);
  await wait(90);
  ok('clicking a module filters the matrix',
     $$('#anBody tbody tr').length === modN,
     modN + ' expected, ' + $$('#anBody tbody tr').length + ' shown');
  ok('the card title names the module',
     new RegExp(firstMod.dataset.f.slice(0, 12).replace(/[.*+?^${}()|[\]\\]/g, '.'), 'i')
       .test($('#anBody .card-h h3').textContent),
     $('#anBody .card-h h3').textContent);
  ok('the filter survives a re-render',
     $('[data-fbar="modFilter"] .fpill.active').dataset.f === firstMod.dataset.f);

  click($$('[data-fbar="modFilter"] .fpill').find(p => p.dataset.f === 'all'));
  await wait(90);
  ok('All restores every module',
     $$('#anBody tbody tr').length ===
       +$$('[data-fbar="modFilter"] .fpill').find(p => p.dataset.f === 'all')
          .querySelector('.n').textContent,
     $$('#anBody tbody tr').length + ' rows vs All count');

  console.log('\nfilter pulse + scrollbar:');
  ok('the active filter pill glows',
     /\.fpill\.active\{[^}]*box-shadow:0 0 12px rgba\(62,217,197,\.4\)/.test(css2));
  ok('the glow pulses', /\.fpill\.active\{[^}]*animation:pswPulse/.test(css2));
  ok('reduced motion stills the filter pulse',
     /prefers-reduced-motion:reduce\)\{\s*\.fpill\.active\{animation:none/.test(css2));
  ok('filter pills take a focus ring', /\.fpill:focus-visible\{outline/.test(css2));

  ok('scrollbar is 6px', /::-webkit-scrollbar\{width:6px;height:6px\}/.test(css2));
  ok('scrollbar track is transparent and borderless',
     /::-webkit-scrollbar-track\{background:transparent;border:0\}/.test(css2));
  ok('scrollbar thumb is a translucent token with no border',
     /::-webkit-scrollbar-thumb\{background:var\(--scroll-thumb\);border-radius:99px;border:0\}/.test(css2));
  ok('thumb token defined for both themes',
     (css2.match(/--scroll-thumb:rgba/g) || []).length >= 2,
     (css2.match(/--scroll-thumb:rgba/g) || []).length + ' definitions');
  ok('Firefox scrollbar styled too', /scrollbar-width:thin/.test(css2) &&
     /scrollbar-color:var\(--scroll-thumb\) transparent/.test(css2));
  ok('no element re-styles its own scrollbar',
     !/\.(enav-in|rail-scroll)::-webkit-scrollbar/.test(css2));

  console.log('\nspacing scale:');
  ok('a spacing scale is defined',
     /--pad-card:16px/.test(css2) && /--gap-sm:8px/.test(css2) &&
     /--gap-md:14px/.test(css2) && /--gap-lg:20px/.test(css2));
  ok('report cards use it', /\.ecard\{padding:var\(--pad-card\)/.test(css2));
  ok('stat cards use it', /\.estat\{padding:var\(--pad-card\)/.test(css2));
  ok('the gate banner uses it', /\.eqg\{[^}]*padding:var\(--pad-card\)/.test(css2));
  ok('table rows use it', /td\{padding:var\(--pad-row\)/.test(css2));
  ok('suite rows use it', /\.sc-row\{[^}]*padding:var\(--pad-row\)/.test(css2));
  ok('grids use it', /\.estats\{[^}]*gap:var\(--gap-md\)/.test(css2) &&
     /\.egrid3\{[^}]*gap:var\(--gap-lg\)/.test(css2));

  console.log('\nlive HCM data:');
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'suites').click();
  await wait(90);
  goHome();
  await wait(70);
  const allText = $('#suitesGrid').textContent;
  for (const [label, needle] of [
    ['Employee Auth POST /auth/token', '/auth/token'],
    ['Leave reports', '/user/leaves/getAllLeaveReports'],
    ['Attendance policies', '/api/attendancepolicy'],
    ['Shift master', '/api/v1/attendance/shift/master'],
    ['Status thresholds', '/api/attendance/status-thresholds'],
    ['Holiday templates', '/api/attendance/holiday-templates'],
    ['Weekoffs', '/api/attendance/week-off']
  ]) ok('catalogue carries ' + label, allText.includes(needle), needle);
  ok('no placeholder host survives', !/\{\{|localhost|example\.com/.test(allText));

  console.log('\nmodule bars:');
  goReport();
  await wait(90);
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'overview').click();
  await wait(90);
  const barCard = $$('#anBody .ecard').find(c => /Suite Execution/.test(c.textContent));
  const bars = [...barCard.querySelectorAll('.sbar')];
  ok('one row per module in the run', bars.length > 0, bars.length + ' rows');
  ok('every module is labelled',
     bars.every(b => b.querySelector('.sbar-l').textContent.trim().length > 0),
     bars.map(b => b.querySelector('.sbar-l').textContent.trim()).join(' | '));
  ok('labels are real text, not svg glyphs',
     bars.every(b => b.querySelector('.sbar-l').tagName === 'DIV'));
  ok('labels are not cut off in the markup',
     bars.every(b => !b.querySelector('.sbar-l').textContent.includes('\u2026')),
     'a label still carries an ellipsis');
  ok('each label carries the full name as a tooltip',
     bars.every(b => b.querySelector('.sbar-l').getAttribute('title')));
  ok('every row draws at least one segment',
     bars.every(b => b.querySelectorAll('.sbar-s').length > 0));
  ok('every segment names its module and state',
     bars.every(b => [...b.querySelectorAll('.sbar-s')].every(sg => {
       const title = sg.getAttribute('title') || '';
       return title.includes(b.querySelector('.sbar-l').textContent.trim()) &&
         /(PASS|FAIL|WARN|SKIPPED_NO_TOKEN|NOT_ASSERTED|INFORMATIONAL|NOT_APPLICABLE): \d+/
           .test(title);
     })),
     (bars[0].querySelector('.sbar-s') || {}).title);
  ok('every row states its pass rate and totals',
     bars.every(b => /(\d|n\/a)/.test(b.querySelector('.sbar-n').textContent)),
     bars.map(b => b.querySelector('.sbar-n').textContent.replace(/\s+/g, ' ').trim()).join(' | '));
  ok('an axis is drawn beneath the bars',
     barCard.querySelectorAll('.sbar-axis span').length >= 2,
     barCard.querySelectorAll('.sbar-axis span').length + ' ticks');
  ok('bar widths are proportional, never over 100%',
     bars.every(b => parseFloat(b.querySelector('.sbar-t').style.width) <= 100));

  console.log('\ntrend graph:');
  goReport();
  await wait(90);
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'overview').click();
  await wait(90);

  // earlier blocks already ran batches, so pin history to a single entry first
  window.eval('STATE.history = STATE.history.slice(-1); persist();');
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'overview').click();
  await wait(90);

  const trendCard = $$('#anBody .ecard').find(c => /Historical Build Trend/.test(c.textContent));
  ok('the trend card is on Overview', !!trendCard);
  ok('it draws an svg after one run', !!trendCard.querySelector('svg.trend'),
     trendCard.textContent.slice(0, 60));
  // Counts the node marks, not every circle: a point is now drawn as a node
  // plus a ring plus, on the current run, a pulse.
  ok('one run plots one point',
     trendCard.querySelectorAll('svg.trend .tg-node').length === 1,
     trendCard.querySelectorAll('svg.trend .tg-node').length + ' points');
  ok('it says a line needs a second run',
     /a line appears from the second/i.test(trendCard.textContent));
  // Targets the trendline specifically: the volume columns are paths too.
  ok('no line path is drawn for a single point',
     trendCard.querySelectorAll('svg.trend .tg-line').length === 0);
  ok('the y axis is labelled in percent',
     [...trendCard.querySelectorAll('svg.trend text')].some(t => /%$/.test(t.textContent)));
  ok('the newest point is labelled current',
     [...trendCard.querySelectorAll('svg.trend text')]
       .some(t => /^current$/i.test(t.textContent.trim())));
  // Across all titles, not the first: the chart draws volume columns before
  // the data points, so depending on draw order made this assert the wrong mark.
  ok('a trend mark carries a tooltip with its gate',
     [...trendCard.querySelectorAll('svg.trend title')]
       .some(n => /gate (PASSED|WARNING|FAILED)/.test(n.textContent)),
     [...trendCard.querySelectorAll('svg.trend title')].map(n => n.textContent).join(' | '));
  ok('an Add sample runs button is offered', !!$('#anBody [data-hist="seed"]'));

  // seed samples
  click($('#anBody [data-hist="seed"]'));
  await wait(140);
  const t2 = $$('#anBody .ecard').find(c => /Historical Build Trend/.test(c.textContent));
  const pts = t2.querySelectorAll('svg.trend circle').length;
  ok('sample runs populate the trend', pts >= 5, pts + ' points');
  ok('a line is drawn once there are several points',
     t2.querySelectorAll('svg.trend path').length >= 1);
  ok('samples are visually distinguished',
     [...t2.querySelectorAll('svg.trend circle')].some(c => c.getAttribute('stroke-width') !== '0'));
  ok('the chart says which points are samples',
     /Hollow points are sample runs/i.test(t2.textContent));
  ok('sample points name themselves in their tooltip',
     [...t2.querySelectorAll('svg.trend title')].some(x => /sample/.test(x.textContent)));
  ok('the card breaks down real versus sample runs',
     /\d+ real/.test(t2.textContent) && /\d+ sample/.test(t2.textContent),
     (t2.textContent.match(/\d+ real[^<]*/) || [''])[0].trim());

  // samples must be real engine output, and must vary
  const hist = JSON.parse(window.localStorage.getItem('hcm-console-v1')).history;
  ok('history persisted', Array.isArray(hist) && hist.length >= 5, (hist || []).length + '');
  ok('every entry carries a pass rate and a gate',
     hist.every(r => 'passRate' in r && /^(PASSED|WARNING|FAILED)$/.test(r.gate)));
  ok('samples are flagged, the real run is not',
     hist.filter(r => r.sample).length === hist.length - 1,
     hist.map(r => r.sample ? 'S' : 'R').join(''));
  const rates = hist.map(r => r.passRate);
  ok('salted runs differ from one another', new Set(rates).size > 1,
     rates.map(r => r == null ? 'n/a' : (r * 100).toFixed(1)).join(', '));
  ok('every rate is a real fraction',
     rates.every(r => r === null || (r >= 0 && r <= 1)), rates.join(','));

  // clear drops only the samples
  click($('#anBody [data-hist="clear"]'));
  await wait(120);
  const hist2 = JSON.parse(window.localStorage.getItem('hcm-console-v1')).history;
  ok('Clear removes the samples', !hist2.some(r => r.sample), hist2.length + ' left');
  ok('Clear keeps the real run', hist2.length === 1, hist2.length + '');

  // a second real run must extend the trend
  goHome();
  await wait(60);
  click($('#btnRun'));
  await wait(1400);
  const hist3 = JSON.parse(window.localStorage.getItem('hcm-console-v1')).history;
  ok('a real run appends to history', hist3.length === 2, hist3.length + '');
  $$('#anTabs .nitem').find(t => t.dataset.tab === 'overview').click();
  await wait(90);
  const t3 = $$('#anBody .ecard').find(c => /Historical Build Trend/.test(c.textContent));
  ok('two real runs draw a line', t3.querySelectorAll('svg.trend .tg-line').length >= 1);
  ok('two real runs plot two points',
     t3.querySelectorAll('svg.trend .tg-node').length === 2,
     t3.querySelectorAll('svg.trend .tg-node').length + '');

  console.log('\nfirst-view seeding:');
  const css5 = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');
  ok('the trend was seeded without being asked',
     JSON.parse(window.localStorage.getItem('hcm-console-v1')).seededTrend === true);
  ok('the seed flag is persisted so it happens once',
     /seededTrend/.test([...doc.querySelectorAll('script')].map(s => s.textContent).join('')));
  ok('cards no longer stretch to the tallest in the row',
     /\.egrid3\{[^}]*align-items:start/.test(css5));
  ok('the chart cannot balloon on a wide screen',
     /\.trend\{[^}]*max-height:260px/.test(css5));

  console.log('\nreport overflow:');
  const css4 = [...doc.querySelectorAll('style')].map(s => s.textContent).join('\n');
  ok('grid children may shrink', /\.egrid3>\*\{min-width:0\}/.test(css4));
  ok('report cards may shrink', /\.ecard\{[^}]*min-width:0/.test(css4));
  ok('wide tables scroll inside their card rather than pushing the page',
     /\.card-b\{[^}]*overflow-x:auto/.test(css4));

  console.log('\nevery control works when actually clicked:');
  /* The export chooser regressed because exportModal gained a parameter while
     staying wired as a bare handler -- an Event landed where a run document
     was expected. The tests missed it by calling exportModal() directly.
     These click the real controls the way a user does. */
  goHome();
  await wait(70);
  click($('#btnSelAll'));
  await wait(60);
  click($('#btnRun'));
  await wait(5600);

  const clickOpensModal = (sel, label) => {
    errs.length = 0;
    const el = $(sel);
    if (!el) { ok(`${label} exists`, false, sel + ' missing'); return; }
    click(el);
    const opened = $('#ovModal').classList.contains('open');
    ok(`${label} opens when clicked`, opened && errs.length === 0,
       errs[0] || 'modal did not open');
    if (opened) click($('#mFoot [data-close]') || $('#ovModal [data-close]'));
  };

  clickOpensModal('#btnExport', 'the topbar Export button');
  await wait(80);
  goReport();
  await wait(90);
  clickOpensModal('#eExport', 'the masthead Export button');
  await wait(80);
  clickOpensModal('#eHistory', 'the masthead History button');
  await wait(80);
  goHome();
  await wait(70);
  clickOpensModal('#btnCurl', 'the Add cURL button');
  await wait(80);

  ok('no handler takes an Event where a run is expected', (() => {
    // exportModal must ignore anything that is not a result document
    const before = window.eval('STATE.result.runId');
    window.eval("exportModal(new window.Event('click'))");
    const stillOpen = $('#ovModal').classList.contains('open');
    if (stillOpen) click($('#mFoot [data-close]'));
    return stillOpen && window.eval('STATE.result.runId') === before;
  })(), 'an Event was treated as a run');

  ok('every menu row that claims a target has a handler',
     $$('#railMenu .rail-item').filter(b => !b.disabled)
       .every(b => typeof b.onclick === 'function'),
     $$('#railMenu .rail-item').filter(b => !b.disabled && typeof b.onclick !== 'function')
       .map(b => b.dataset.menuAct || b.dataset.view).join(',') || 'none');

  console.log('\nnavigator:');
  goHome();
  await wait(40);
  click($('#btnOpenNav'));
  await wait(60);
  ok('navigator opens', $('#navPanel').classList.contains('on'));
  ok('navigator lists endpoints', $$('#navBody [data-nav]').length === 44,
     $$('#navBody [data-nav]').length + '');
  click($('#btnCloseNav'));
  await wait(40);
  ok('navigator closes', !$('#navPanel').classList.contains('on'));

  console.log('\n%s', bad === 0 ? 'DOM SMOKE OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

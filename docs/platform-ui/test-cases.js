/* Test-case ordering, the Test Cases explorer, and opening an archived run
   in a new tab. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const F = path.join(__dirname, 'unified-console.html');
let bad = 0;
const ok = (n, c, d) => { console.log((c ? '  PASS  ' : '  FAIL  ') + n + (c ? '' : '\n          -> ' + d)); if (!c) bad++; };
const wait = ms => new Promise(r => setTimeout(r, ms));

const dom = new JSDOM(fs.readFileSync(F, 'utf8'),
  { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/' });
const { window } = dom, doc = window.document;
const $ = s => doc.querySelector(s), $$ = s => [...doc.querySelectorAll(s)];
const click = el => el.dispatchEvent(new window.Event('click', { bubbles: true }));

(async () => {
  await wait(170);

  console.log('ordering:');
  const order = window.orderedChecks().map(t => t.category);
  const RANK = ['functional', 'schema', 'security', 'performance', 'resilience'];
  ok('checks are grouped by category in a fixed sequence',
     order.every((c, i) => i === 0 || RANK.indexOf(order[i - 1]) <= RANK.indexOf(c)),
     order.join(','));
  const titles = window.orderedChecks().map(t => t.title);
  ok('within a category they are alphabetical', (() => {
    const byCat = {};
    window.orderedChecks().forEach(t => (byCat[t.category] ||= []).push(t.title));
    return Object.values(byCat).every(v => v.join('|') === v.slice().sort().join('|'));
  })());
  ok('every check gets a stable number',
     window.orderedChecks().every(t => /^TC-\d\d$/.test(window.tcNum(t.id))),
     window.orderedChecks().map(t => window.tcNum(t.id)).join(' '));
  ok('numbers are unique and sequential', (() => {
    const ns = window.orderedChecks().map(t => window.tcNum(t.id));
    return new Set(ns).size === ns.length &&
           ns.join(',') === ns.map((_, i) => 'TC-' + String(i + 1).padStart(2, '0')).join(',');
  })());
  ok('the same check numbers the same everywhere',
     window.tcNum(window.orderedChecks()[3].id) === 'TC-04');

  console.log('\nendpoint screen:');
  click($$('.sc-row')[0]);
  await wait(90);
  const cards = $$('#dCases .tc');
  ok('cards render', cards.length >= 12, cards.length + ' cards');
  ok('every card is a three-part grid: number, body, state',
     cards.every(c => c.querySelector('.tc-n') && c.querySelector('.tc-b') &&
                      c.querySelector(':scope > .st')));
  ok('titles are headings, not inline spans',
     cards.every(c => c.querySelector('h4.tc-t')));
  ok('the id sits under the title rather than beside it',
     cards.every(c => {
       const b = [...c.querySelector('.tc-b').children].map(x => x.className);
       return b.indexOf('tc-t') < b.indexOf('tc-id');
     }));
  ok('category headings group the list', $$('#dCases .tc-grp').length >= 4,
     $$('#dCases .tc-grp').length + ' groups');
  ok('each heading counts its checks',
     $$('#dCases .tc-grp').every(g => /\d/.test(g.querySelector('.tc-grp-n').textContent)));
  const nums = $$('#dCases .tc .tc-n').map(n => n.textContent.trim()).filter(x => x !== '—');
  ok('numbers ascend down the page',
     nums.join(',') === nums.slice().sort().join(','), nums.join(' '));
  ok('an assertion gap is called out first',
     !$('#dCases .tc.gap') || $$('#dCases .tc')[0].classList.contains('gap'));

  console.log('\ntest cases explorer:');
  click($('#railMenu [data-menu-act="cases"]'));
  await wait(110);
  ok('the explorer is its own view', $('#view-cases').classList.contains('active'));
  ok('it lists every endpoint', $$('#caseBody .case').length === 45,
     $$('#caseBody .case').length + ' endpoints');
  ok('each row names method, endpoint and module',
     $$('#caseBody .case-h').every(h => h.querySelector('.m') &&
       h.querySelector('.case-nm').textContent.trim() &&
       h.querySelector('.case-mod').textContent.trim()));
  ok('each row summarises its states',
     $$('#caseBody .case-cts').every(c => c.querySelectorAll('.st').length > 0));
  ok('state counts add up to the number of checks',
     $$('#caseBody .case-cts').every(c =>
       [...c.querySelectorAll('.st')].reduce((n, s) => n + (+s.textContent), 0) ===
       window.orderedChecks().length),
     'a row does not total ' + window.orderedChecks().length);
  ok('rows start collapsed', $$('#caseBody .case.open').length === 0);

  const first = $('#caseBody .case-h');
  click(first);
  await wait(90);
  ok('clicking a row expands its checks', $$('#caseBody .case.open').length === 1);
  ok('the expanded row lists the ordered checks',
     $$('#caseBody .case.open .tc').length >= 12,
     $$('#caseBody .case.open .tc').length + ' cards');
  ok('only one row is open at a time', (() => {
    click($$('#caseBody .case-h')[1]);
    return $$('#caseBody .case.open').length === 1;
  })());

  $('#caseSearch').value = 'attendance';
  $('#caseSearch').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(90);
  ok('the explorer filters', $$('#caseBody .case').length < 45 &&
     $$('#caseBody .case').length > 0, $$('#caseBody .case').length + ' shown');
  ok('the hint reports the filtered count',
     /of 45 endpoints match/.test($('#caseHint').textContent),
     $('#caseHint').textContent.trim());
  $('#caseSearch').value = 'no-such-thing-xyz';
  $('#caseSearch').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(80);
  ok('an empty filter says so', !!$('#caseBody .empty'));
  $('#caseSearch').value = '';
  $('#caseSearch').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(80);

  console.log('\ntest case detail:');
  click($('#railMenu [data-menu-act="cases"]'));
  await wait(110);
  click($('#caseBody .case-h'));
  await wait(100);
  const anyCard = $('#caseBody .case.open .tc[data-tc]');
  ok('cards advertise that they open', /details/i.test(anyCard.textContent));
  ok('cards are keyboard reachable',
     anyCard.getAttribute('role') === 'button' && anyCard.getAttribute('tabindex') === '0');
  click(anyCard);
  await wait(100);
  ok('clicking a check opens its detail', $('#ovModal').classList.contains('open'));
  const md = $('#mBody').textContent;
  ok('the title carries the case number', /^TC-\d\d · /.test($('#mTitle').textContent),
     $('#mTitle').textContent);

  ok('severity is shown', /Severity/.test(md) &&
     /(Critical|High|Medium|Low)/.test(md), md.slice(0, 80));
  ok('priority is shown', /Priority/.test(md) && /P[1-4]/.test(md));
  ok('both say why', $$('#mBody .td-bw').length === 2 &&
     $$('#mBody .td-bw').every(x => x.textContent.trim().length > 8),
     $$('#mBody .td-bw').map(x => x.textContent).join(' | '));
  ok('they are labelled derived, not authored',
     /derived/i.test(md) && /API_File\.json/.test(md));

  const plHead = $$('#mBody table.pl th').map(h => h.textContent.trim());
  ok('the payload table matches the Sample_Payloads columns',
     plHead.join(' | ') === 'API ID | Payload Type | Sample JSON', plHead.join(' | '));
  const types = $$('#mBody table.pl .pl-t').map(t => t.textContent.trim());
  ok('it lists request body, success and error response',
     ['Request Body', 'Success Response', 'Error Response'].every(x => types.includes(x)),
     types.join(', '));
  ok('every row carries the API ID',
     $$('#mBody table.pl .pl-id').every(c => /^API-\d\d\d$/.test(c.textContent.trim())),
     $$('#mBody table.pl .pl-id').map(c => c.textContent.trim()).join(','));
  ok('a missing example says so rather than showing an empty box',
     $$('#mBody table.pl .pl-j').every(c => c.querySelector('pre') || c.querySelector('.pl-none')));
  ok('the error row explains why it is empty',
     /no error column|best-effort/i.test(md));

  ok('the endpoint is described', /Purpose/.test(md) && /Access/.test(md) && /Host/.test(md));
  ok('the check is described', /Test id/.test(md) && /State/.test(md));
  ok('a cURL reproducer is offered', !!$('#tdCurl') && /curl -X/.test(md));
  ok('the cURL is redacted', /Bearer \[REDACTED\]/.test(md));
  ok('no credential value in the panel',
     !/Bearer\s+ey[A-Za-z0-9_.-]{10,}/.test(md) &&
     !/(password|secret)\s*[:=]\s*["']?[A-Za-z0-9!@#$%^&*_.-]{6,}/i.test(md),
     'a credential-shaped value appeared');

  // a real payload must actually reach the panel
  click($('#mFoot [data-close]'));
  await wait(60);
  $('#caseSearch').value = 'auth/token';
  $('#caseSearch').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(90);
  click($('#caseBody .case-h'));
  await wait(90);
  click($('#caseBody .case.open .tc[data-tc]'));
  await wait(90);
  const auth = $('#mBody').textContent;
  ok('a real request body reaches the panel from the inventory',
     /empCode/.test(auth), 'no empCode in the auth payload');
  ok('a real response example reaches the panel', /token/.test(auth));
  ok('the payload is pretty-printed JSON, not a prose blob',
     /\{\s*\n\s+"/.test($('#mBody table.pl pre').textContent),
     JSON.stringify($('#mBody table.pl pre').textContent.slice(0, 60)));
  click($('#mFoot [data-close]'));
  await wait(60);

  // severity must vary with the endpoint, not be a constant
  const sevs = new Set(), pris = new Set();
  window.eval('SEED.apis').slice(0, 24).forEach(a => {
    sevs.add(window.severityOf(a).k);
    pris.add(window.priorityOf(a, null).k);
  });
  ok('severity varies across endpoints', sevs.size >= 3, [...sevs].join(','));
  ok('DELETE and auth rate Critical',
     window.severityOf(window.eval("SEED.apis.find(a=>a.method==='DELETE')")).k === 'Critical');
  ok('a plain read does not rate Critical',
     window.severityOf({ method: 'GET', module: 'Leave API', path: '/x' }).k !== 'Critical');
  ok('priority reflects an assertion gap',
     window.priorityOf({ assertionState: 'not-asserted', method: 'GET', module: 'x' }, null).k === 'P2');
  ok('priority reflects a failure in the last run',
     window.priorityOf({ method: 'GET', module: 'x' },
       { summary: { counts: { FAIL: 2 } } }).k === 'P1');
  $('#caseSearch').value = '';
  $('#caseSearch').dispatchEvent(new window.Event('input', { bubbles: true }));
  await wait(80);

  console.log('\nexpected vs actual:');
  click($('#railMenu [data-menu-act="suites"]'));
  await wait(70);
  click($('#btnSelAll'));
  await wait(60);
  click($('#btnRun'));
  await wait(5600);
  const RES = JSON.parse(window.localStorage.getItem('hcm-console-v1')).result;
  const flat = RES.apis.flatMap(a => a.results);

  ok('executed results carry evidence',
     flat.filter(r => r.executed && r.state !== 'NOT_ASSERTED').every(r => !!r.evidence),
     flat.filter(r => r.executed && !r.evidence).length + ' without');
  ok('unexecuted results carry none',
     flat.filter(r => r.executed === false).every(r => !r.evidence));
  ok('every evidence names where actual came from',
     flat.filter(r => r.evidence).every(r => r.evidence.actual.from === 'simulated'));
  ok('every evidence states what is expected',
     flat.filter(r => r.evidence).every(r => (r.evidence.expected.expects || '').length > 8));

  const openFor = pred => {
    const r = flat.find(pred);
    if (!r) return null;
    window.tcDetail(window.apiByRef(r.apiRef),
      window.eval('SEED.globalTestCases').find(t => t.id === r.testId),
      RES.apis.find(a => a.apiRef === r.apiRef));
    return r;
  };

  const pf = openFor(r => r.state === 'FAIL' && r.testId.endsWith('test_transport_is_https'));
  ok('a property check shows no HTTP line', !!pf && !$('#mBody .ea-s'));
  ok('a property check still states its assertion',
     /resolved base URL uses https/.test($('#mBody').textContent));
  ok('a failure is flagged on the actual column', !!$('#mBody .ea-col.bad'));
  click($('#mFoot [data-close]'));
  await wait(50);

  const sf = openFor(r => r.state === 'FAIL' && r.testId.endsWith('test_status_code_matches_spec'));
  ok('a status check compares statuses', !!sf && $$('#mBody .ea-s').length === 2,
     $$('#mBody .ea-s').length + ' status lines');
  ok('expected and actual statuses differ on a failure',
     $$('#mBody .ea-s')[0].textContent.trim() !== $$('#mBody .ea-s')[1].textContent.trim(),
     $$('#mBody .ea-s').map(x => x.textContent.trim()).join(' vs '));
  click($('#mFoot [data-close]'));
  await wait(50);

  const pp = openFor(r => r.state === 'PASS' && r.testId.endsWith('test_401_without_valid_token'));
  ok('a pass is not flagged as a mismatch', !!pp && !$('#mBody .ea-col.bad'));
  ok('a pass says so rather than leaving the column blank',
     /Held\. Nothing to report/.test($('#mBody').textContent));
  click($('#mFoot [data-close]'));
  await wait(50);

  ok('the panel says actual is simulated',
     (() => { openFor(r => !!r.evidence);
              const t = $('#mBody').textContent;
              click($('#mFoot [data-close]'));
              return /Actual is from/.test(t) && /simulated run/.test(t); })());
  ok('the panel names the missing-body gap',
     (() => { openFor(r => !!r.evidence);
              const t = $('#mBody').textContent;
              click($('#mFoot [data-close]'));
              return /does\s+not\s+carry response bodies/.test(t); })());
  await wait(50);

  console.log('\ntiers kept apart:');
  click($('#railMenu [data-menu-act="cases"]'));
  await wait(110);
  click($('#caseBody .case-h'));
  await wait(110);
  const tiers = $$('#caseBody .case.open .tc-tier');
  ok('two tiers are separated', tiers.length === 2,
     tiers.map(t => t.querySelector('.tc-tier-t').textContent.trim()).join(' | '));
  ok('collection assertions are named first',
     /Collection assertions/.test(tiers[0].textContent));
  ok('global contract checks are named second',
     /Global contract checks/.test(tiers[1].textContent));
  ok('the global tier carries the engine count',
     tiers[1].querySelector('.tc-tier-n').textContent.trim() ===
       String(window.orderedChecks().length),
     tiers[1].querySelector('.tc-tier-n').textContent.trim() + ' vs ' + window.orderedChecks().length);
  ok('each tier explains what it is',
     tiers.every(t => t.querySelector('.tc-tier-d').textContent.trim().length > 10));

  console.log('\nhistory opens in a new tab:');
  click($('#railMenu [data-menu-act="suites"]'));
  await wait(70);
  click($('#btnSelAll'));
  await wait(60);
  click($('#btnRun'));
  await wait(5500);

  let opened = null, revoked = 0;
  window.open = (url, target) => { opened = { url, target }; return { closed: false }; };
  window.URL.createObjectURL = () => 'blob:mock/report';
  window.URL.revokeObjectURL = () => { revoked++; };

  window.historyModal();
  await wait(90);
  const row = $('#ovModal [data-open-snap]');
  ok('history rows advertise the new tab', /New tab/i.test(row.textContent));
  ok('history rows also offer opening in place', !!$('#ovModal [data-open-here]'));
  click(row);
  await wait(120);
  ok('clicking a run opens a new tab', !!opened, 'window.open was not called');
  ok('it targets a blank tab', opened && opened.target === '_blank', opened && opened.target);
  ok('the tab is handed a blob, not the live page',
     opened && /^blob:/.test(opened.url), opened && opened.url);
  ok('the current tab keeps its own run',
     window.eval('STATE.viewing') === null, window.eval('STATE.viewing'));

  // popup blocked -> must fall back rather than doing nothing
  window.open = () => null;
  const snaps = JSON.parse(window.localStorage.getItem('HCM_RUN_SNAPSHOTS'));
  window.openSnapshot(snaps[0].runId);
  await wait(120);
  ok('a blocked popup falls back to opening in place',
     $('#view-analytics').classList.contains('active') &&
     $('#anMast').textContent.includes(snaps[0].runId),
     'did not open in place');

  console.log('\n%s', bad === 0 ? 'CASES + NEW TAB OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

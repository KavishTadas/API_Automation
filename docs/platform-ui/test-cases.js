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

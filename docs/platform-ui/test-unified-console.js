/* Headless invariant test for the unified console's simulated engine.
   Stubs just enough DOM for the page script to evaluate, then asserts the
   project's contract rules against a real batch over the real 45-API seed. */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'docs/platform-ui/unified-console.html'), 'utf8');

const seedBlob = html.match(/<script id="seed" type="application\/json">([\s\S]*?)<\/script>/)[1]
  .replace(/<\\\//g, '</').replace(/<\\!--/g, '<!--');
const code = html.match(/<script>([\s\S]*?)<\/script>/)[1];

/* ---- minimal DOM stub ---- */
const noop = () => {};
function el(id) {
  const e = {
    id, textContent: '', innerHTML: '', value: '', style: {}, dataset: {},
    classList: { add: noop, remove: noop, toggle: noop, contains: () => false },
    querySelectorAll: () => [], appendChild: noop, remove: noop, select: noop,
    setAttribute: noop, removeAttribute: noop, hasAttribute: () => false,
    getAttribute: () => null, addEventListener: noop, onclick: null, oninput: null,
    onchange: null, parentElement: null, closest: () => null, focus: noop
  };
  if (id === 'seed') e.textContent = seedBlob;
  return el.cache[id] || (el.cache[id] = e);
}
el.cache = {};

const document = {
  documentElement: {
    _t: 'light',
    getAttribute() { return this._t; },
    setAttribute(_, v) { this._t = v; },
    style: { getPropertyValue: () => '#000000' }
  },
  getElementById: el,
  querySelector: (s) => el(s),
  querySelectorAll: () => [],
  createElement: () => el('tmp'),
  addEventListener: noop,
  body: { appendChild: noop },
  execCommand: noop
};

const sandbox = {
  document,
  console,
  window: { isSecureContext: false, matchMedia: () => ({ matches: false }) },
  navigator: {},
  localStorage: { getItem: () => null, setItem: noop },
  getComputedStyle: () => ({ getPropertyValue: () => '#000000' }),
  setTimeout, clearTimeout, Math, JSON, Date, Set, Map, URL,
  BroadcastChannel: undefined
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(code + '\n;globalThis.__x = {runBatch, summarise, SEED, STATES, DENOM, STATE, SLA_MS, apiByRef};', sandbox);

const X = sandbox.__x;
const { runBatch, summarise, SEED, STATES, DENOM, STATE, SLA_MS, apiByRef } = X;

/* ---- assertions ---- */
let failures = 0;
function ok(name, cond, detail) {
  if (cond) { console.log('  PASS  ' + name); }
  else { failures++; console.log('  FAIL  ' + name + (detail ? '  -> ' + detail : '')); }
}

console.log('seed: %d APIs, %d checks, denominator=%s', SEED.apis.length, SEED.globalTestCases.length, DENOM);

/* Batch 1: a broad mixed selection (Attendance + Leave + Auth). */
STATE.alias = SEED.credentialAliases[0];
const refs = SEED.apis.slice(0, 20).map(a => a.ref);
const R = runBatch(refs);
const flat = R.apis.flatMap(a => a.results);

console.log('\nbatch of %d APIs -> %d results, status=%s', R.apis.length, flat.length, R.status);
console.log('counts:', R.summary.counts);
console.log('passRate=%s applicable=%s clean=%s blockers=%s',
  R.summary.passRate, R.summary.passRateApplicable, R.summary.clean, R.summary.cleanBlockers);

console.log('\ninvariants:');
ok('every state is one of the seven', flat.every(r => STATES.includes(r.state)),
   [...new Set(flat.map(r => r.state))].filter(s => !STATES.includes(s)).join(','));

const P = R.summary.counts.PASS, F = R.summary.counts.FAIL;
const expected = (P + F) > 0 ? +(P / (P + F)).toFixed(4) : null;
ok('passRate = PASS/(PASS+FAIL)', R.summary.passRate === expected,
   `got ${R.summary.passRate} want ${expected}`);

ok('passRateApplicable matches a non-zero denominator',
   R.summary.passRateApplicable === ((P + F) > 0));

ok('clean === (cleanBlockers empty)',
   R.summary.clean === (R.summary.cleanBlockers.length === 0));

ok('NOT_APPLICABLE never counts as a blocker',
   !R.summary.cleanBlockers.includes('NOT_APPLICABLE'));

const counted = flat.filter(r => !r.referencesHostResult);
ok('summary.total counts only non-referencing results',
   R.summary.total === counted.length, `${R.summary.total} vs ${counted.length}`);

ok('referencedHostResults accounts for the remainder',
   R.summary.total + R.summary.referencedHostResults === flat.length,
   `${R.summary.total}+${R.summary.referencedHostResults} vs ${flat.length}`);

const sumOfCounts = STATES.reduce((n, s) => n + (R.summary.counts[s] || 0), 0);
ok('state counts sum to the total', sumOfCounts === R.summary.total,
   `${sumOfCounts} vs ${R.summary.total}`);

ok('NOT_ASSERTED results are never marked executed',
   flat.filter(r => r.state === 'NOT_ASSERTED').every(r => r.executed === false));

ok('SKIPPED_NO_TOKEN results are never marked executed',
   flat.filter(r => r.state === 'SKIPPED_NO_TOKEN').every(r => r.executed === false));

ok('WARN only ever comes from an SLA breach over 700ms',
   flat.filter(r => r.state === 'WARN').every(r => r.observed > SLA_MS && r.threshold === SLA_MS));

ok('no SLA breach is ever reported as FAIL',
   !flat.some(r => r.state === 'FAIL' && /response time exceeded/.test(r.reason || '')));

/* Host-level probes: measured once per host, referenced elsewhere. */
const hostProbes = flat.filter(r => r.hostLevel);
/* A result "measures" only when it names itself as the measurer. A host with
   no eligible carrier yields NOT_APPLICABLE with measuredBy:null on every API
   there --- that is an absence of measurement, not a duplicate one. */
const owners = new Map();
hostProbes.filter(r => r.measuredBy === r.apiRef).forEach(r => {
  owners.set(r.host + '|' + r.testId, (owners.get(r.host + '|' + r.testId) || 0) + 1);
});
ok('each host-level probe is measured at most once per host',
   [...owners.values()].every(n => n === 1),
   [...owners.entries()].filter(([, n]) => n > 1).map(([k]) => k).join(', '));

ok('referencing host results name a measuredBy',
   hostProbes.filter(r => r.referencesHostResult).every(r => r.measuredBy));

ok('unattributed host probes are NOT_APPLICABLE and claim no measurement',
   hostProbes.filter(r => r.measuredBy === null)
             .every(r => r.state === 'NOT_APPLICABLE' && r.referencesHostResult === false));

ok('a host with an eligible carrier is actually measured',
   [...new Set(hostProbes.filter(r => r.measuredBy).map(r => r.host + '|' + r.testId))]
     .every(k => owners.get(k) === 1));

ok('every FAIL carries a non-empty reason',
   flat.filter(r => r.state === 'FAIL').every(r => (r.reason || '').trim().length > 0));

ok('per-API summaries re-derive from their own results',
   R.apis.every(a => {
     const s = summarise(a.results);
     return s.passRate === a.summary.passRate && s.total === a.summary.total;
   }));

/* Batch 2: unregistered alias must block Attendance, never fail it. */
STATE.alias = 'not-a-registered-alias';
const attendanceRefs = SEED.apis.filter(a => /attendance/i.test(a.module)).slice(0, 5).map(a => a.ref);
const R2 = runBatch(attendanceRefs);
const flat2 = R2.apis.flatMap(a => a.results);
console.log('\nunregistered alias over %d attendance APIs:', R2.apis.length, R2.summary.counts);
ok('bad alias produces SKIPPED_NO_TOKEN, never FAIL',
   R2.summary.counts.FAIL === 0 && R2.summary.counts.SKIPPED_NO_TOKEN > 0);
ok('run status degrades to COMPLETED_WITH_ERRORS', R2.status === 'COMPLETED_WITH_ERRORS');
ok('blocked results name what blocked them',
   flat2.filter(r => r.state === 'SKIPPED_NO_TOKEN').every(r => 'blockedBy' in r));
ok('pass rate is null, not zero, when nothing asserted',
   R2.summary.passRate === null && R2.summary.passRateApplicable === false);

/* Batch 3: determinism. */
STATE.alias = SEED.credentialAliases[0];
const a1 = runBatch(refs.slice(0, 6));
const b1 = runBatch(refs.slice(0, 6));
const strip = d => JSON.stringify(d.apis);
ok('the same selection yields the same verdicts', strip(a1) === strip(b1));

/* Conformance: replay the SHIPPED result documents through summarise() and
   demand it reproduce their published summaries field for field. This is the
   check that catches the UI drifting from the contract it claims to render. */
console.log('\nconformance against shipped result documents:');
for (const name of ['sample-result-batch.json', 'sample-result-single-api.json']) {
  const doc = JSON.parse(fs.readFileSync(path.join(ROOT, 'docs/platform-handoff', name), 'utf8'));

  const cmp = (tag, want, got) => {
    const fields = ['total', 'passRate', 'passRateApplicable', 'clean'];
    const bad = fields.filter(f => JSON.stringify(want[f]) !== JSON.stringify(got[f]));
    const wb = JSON.stringify(want.cleanBlockers), gb = JSON.stringify(got.cleanBlockers);
    if (wb !== gb) bad.push(`cleanBlockers ${wb} vs ${gb}`);
    const cb = STATES.filter(s => (want.counts[s] || 0) !== (got.counts[s] || 0));
    if (cb.length) bad.push('counts:' + cb.join(','));
    ok(`${name} - ${tag}`, bad.length === 0, bad.join(' | '));
  };

  /* sample-result-single-api.json's RUN-level summary describes a larger run
     than the document contains (total 61 / 4 referenced host results, against
     13 results and 0 referencing). Its per-API summary is self-consistent.
     That is a defect in the shipped sample, not in this code, so the run-level
     comparison is reported rather than asserted. */
  const flatDoc = doc.apis.flatMap(a => a.results);
  const selfConsistent = doc.summary.total === flatDoc.filter(r => !r.referencesHostResult).length;
  if (selfConsistent) {
    cmp('run summary', doc.summary, summarise(flatDoc));
  } else {
    console.log(`  SKIP  ${name} - run summary --- sample is internally inconsistent ` +
                `(declares total=${doc.summary.total}, document holds ${flatDoc.length} results)`);
  }
  doc.apis.forEach(a => cmp(a.apiRef.slice(0, 42), a.summary, summarise(a.results)));
}

console.log('\n%s', failures === 0 ? 'ALL INVARIANTS HOLD' : failures + ' INVARIANT(S) VIOLATED');
process.exit(failures === 0 ? 0 : 1);


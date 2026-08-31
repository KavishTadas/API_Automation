/* File import.

   The load-bearing assertion here is not that each format parses -- it is that
   a credential never survives the trip. An export taken from a working session
   is precisely the file most likely to carry a live bearer token, and the
   fixtures below all contain one deliberately so that a regression in the
   stripping shows up as a failure rather than as a token in someone's report. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const F = path.join(__dirname, 'unified-console.html');
const FIX = path.join(__dirname, 'fixtures-import');

let bad = 0;
const ok = (n, c, d) => {
  console.log((c ? '  PASS  ' : '  FAIL  ') + n + (c ? '' : '\n          -> ' + d));
  if (!c) bad++;
};
const wait = ms => new Promise(r => setTimeout(r, ms));

// Chrome provides DecompressionStream; jsdom does not. Injecting Node's keeps
// the zip path exercised here instead of silently skipped.
function boot(html) {
  const dom = new JSDOM(html, {
    runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/',
    beforeParse(w) {
      w.DecompressionStream = DecompressionStream;
      w.Blob = Blob;
      w.Response = Response;
    }
  });
  return dom.window;
}

// jsdom's File does not implement text()/arrayBuffer() the way the page needs.
function fileOf(name) {
  const buf = fs.readFileSync(path.join(FIX, name));
  return {
    name,
    text: async () => buf.toString('utf8'),
    arrayBuffer: async () => new Uint8Array(buf).buffer
  };
}

(async () => {
  const w = boot(fs.readFileSync(F, 'utf8'));
  await wait(320);

  const cases = [
    ['sample.postman_collection.json', 2, 'postman', 2],
    ['openapi.json',                   2, 'openapi', 0],
    ['manual.txt',                     2, 'curl',    1],
    ['get-thresholds.bru',             1, 'bruno',   1],
    ['bruno-export.zip',               2, 'bruno',   2],
    ['notes.docx',                     1, 'curl',    0],
  ];

  console.log('every format yields endpoints:');
  const all = [];
  for (const [file, count, via, stripped] of cases) {
    w.__f = fileOf(file);
    let r = null, err = null;
    try { r = await w.eval('extractFromFile(__f)'); } catch (e) { err = e.message; }
    ok(`${file} -> ${count} endpoint(s)`,
       !!r && r.found.length === count,
       err || (r ? r.found.length + ' found; ' + (r.notes || []).join('; ') : 'threw'));
    if (!r) continue;
    ok(`  parsed as ${via}`, r.found.every(x => x.sourceType === via),
       r.found.map(x => x.sourceType).join(','));
    ok(`  ${stripped} credential header(s) stripped`,
       r.found.reduce((n, x) => n + (x.strippedHeaders || 0), 0) === stripped,
       String(r.found.reduce((n, x) => n + (x.strippedHeaders || 0), 0)));
    all.push(...r.found);
  }

  console.log('\nno credential survives the trip:');
  const blob = JSON.stringify(all);
  ok('no bearer token anywhere in the imported set',
     !/LIVE\.SECRET\.TOKEN|LIVE\.TOKEN|LIVE\.BRU\.TOKEN/.test(blob));
  ok('no api key either', !/k-123/.test(blob));
  ok('no Authorization header retained',
     all.every(p => !Object.keys(p.importedHeaders || {}).some(h => /^authorization$/i.test(h))));
  ok('harmless headers are kept',
     all.some(p => Object.keys(p.importedHeaders || {}).some(h => /content-type|accept/i.test(h))),
     'every header was dropped, not just the credentials');

  console.log('\nshape of what comes back:');
  ok('every endpoint has a method and a path',
     all.every(p => /^[A-Z]+$/.test(p.method) && p.path.startsWith('/')),
     all.filter(p => !p.path.startsWith('/')).map(p => p.path).join(','));
  ok('path parameters are not percent-encoded',
     all.every(p => !/%7[bB]|%7[dD]/.test(p.path)),
     all.filter(p => /%7/i.test(p.path)).map(p => p.path).join(','));
  ok('every ref is unique', new Set(all.map(p => p.ref)).size === all.length);
  ok('nothing is marked as carrying assertions',
     all.every(p => p.assertionState === 'global-only'));

  console.log('\nit fails honestly:');
  w.__f = { name: 'junk.bin', text: async () => 'not a request in sight',
            arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  const empty = await w.eval('extractFromFile(__f)');
  ok('an unrecognisable file yields nothing rather than guessing',
     empty.found.length === 0, empty.found.length + ' invented');

  console.log('\n%s', bad === 0 ? 'IMPORT OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

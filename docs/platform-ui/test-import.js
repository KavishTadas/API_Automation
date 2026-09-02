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

  // Deliberately the dialog's accept list. The suite previously covered six of
  // nine advertised formats, and that gap is exactly how three shipped
  // offered-but-unreadable -- a reader whose file yields nothing concludes the
  // file is empty, not that the tool cannot read it.
  const cases = [
    ['sample.postman_collection.json', 2, 'postman', 2],
    ['openapi.json',                   2, 'openapi', 0],
    ['manual.txt',                     2, 'curl',    1],
    ['get-thresholds.bru',             1, 'bruno',   1],
    ['bruno-export.zip',               2, 'bruno',   2],
    ['notes.docx',                     1, 'curl',    0],
    ['sample-request.yml',             1, 'yaml',    1],
    ['inventory.csv',                  2, 'csv',     0],
    ['spec.xlsx',                      5, 'xlsx',    0],
    // Bruno's brace syntax saved with a .yml extension -- 162 of the real
    // export look like this. Dispatching on the extension imported every
    // one as GET.
    ['bruno-braces.yml',               1, 'bruno',   0],
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

  console.log('\na workbook is joined across its sheets:');
  w.__f = fileOf('spec.xlsx');
  const wb = await w.eval('extractFromFile(__f)');
  ok('the endpoint sheet is found by its own column name',
     wb.found.length === 5, wb.found.length + ' rows');
  // The payload lives on a second sheet keyed by API ID. Reading sheets in
  // isolation recovers neither side, which is why this is asserted separately
  // from the row count.
  ok('request bodies are joined from Sample_Payloads on API ID',
     wb.found.filter(e => Object.keys(e.samplePayload || {}).length).length === 3,
     wb.found.map(e => Object.keys(e.samplePayload || {}).length).join(','));
  ok('formatted-but-empty rows are not imported as endpoints',
     wb.found.every(e => e.path && e.path !== '/'),
     'an empty row produced an endpoint');

  console.log('\nthe verb comes from the file, never a default:');
  w.__f = fileOf('bruno-braces.yml');
  const br = await w.eval('extractFromFile(__f)');
  ok('a POST written in brace syntax imports as POST, not GET',
     br.found.length === 1 && br.found[0].method === 'POST',
     br.found.map(e => e.method).join(','));
  ok('and it carries the body from its body:json block',
     br.found.length === 1 && Object.keys(br.found[0].samplePayload || {}).length > 0,
     JSON.stringify(br.found[0] && br.found[0].samplePayload).slice(0, 70));

  console.log('\na report exported from this console reads back into it:');
  w.__f = fileOf('report-export.xlsx');
  const rt = await w.eval('extractFromFile(__f)');
  // The header sits on row 2, under a title and a blank row. Taking row 0 on
  // faith found no endpoint column and returned nothing, without saying why.
  ok('the header is found below a title row',
     rt.found.length > 0, 'nothing extracted');
  // Test_Results carries the same endpoint columns with one row per result,
  // so 1059 rows became 1059 endpoints before duplicates were merged.
  ok('one endpoint per method+path, not one per test result',
     rt.found.length === 39, rt.found.length + ' endpoints');
  ok('every one carries a method and an absolute path',
     rt.found.every(e => /^[A-Z]+$/.test(e.method) && e.path.startsWith('/')));

  console.log('\nit writes a Bruno collection that reads back:');
  // The round trip is the only assertion that proves the format. Bruno's brace
  // syntax is whitespace-sensitive in ways that are easy to get subtly wrong
  // and impossible to eyeball.
  w.__f = fileOf('sample.postman_collection.json');
  const src = (await w.eval('extractFromFile(__f)')).found;
  w.eval('STATE.imported = ' + JSON.stringify(src) + ';');
  const files = w.eval('bruCollection(STATE.imported, "x")');
  const brus = files.filter(f => f.name.endsWith('.bru'));

  ok('one .bru per endpoint, plus a bruno.json',
     brus.length === src.length && files.some(f => f.name === 'bruno.json'),
     files.map(f => f.name).join(', '));
  ok('files are foldered by module',
     brus.every(f => f.name.includes('/')), brus.map(f => f.name).join(', '));

  let mismatched = 0;
  for (let i = 0; i < brus.length; i++) {
    w.__t = brus[i].data;
    const back = w.eval('fromBru(__t,"x","' + brus[i].name + '")')[0];
    if (!back || back.method !== src[i].method || back.path !== src[i].path) mismatched++;
    else if (Object.keys(back.samplePayload || {}).length !==
             Object.keys(src[i].samplePayload || {}).length) mismatched++;
  }
  ok('every exported endpoint re-imports identically', mismatched === 0,
     mismatched + ' of ' + brus.length + ' differed');

  const blobBru = brus.map(f => f.data).join('\n');
  ok('the credential is written as a variable, not a value',
     /\{\{authToken\}\}/.test(blobBru) &&
     !/LIVE\.SECRET\.TOKEN|LIVE\.TOKEN|k-123/.test(blobBru),
     'a real credential reached the exported collection');
  // The structured block, not a header. `headers { Authorization: ... }` is
  // valid Bruno and invisible to generate-api-file.js, which reads auth:bearer
  // -- an export written the header way reached the inventory with no
  // credential and no access level, while looking imported correctly.
  ok('auth is written as the structured block the generator reads',
     brus.some(f => /auth:bearer\s*\{[^}]*token:\s*\{\{authToken\}\}/.test(f.data)),
     'no auth:bearer block — the inventory would receive no credential');
  ok('and the method block declares bearer, not none',
     brus.some(f => /\n\s*auth:\s*bearer/.test(f.data)),
     'the method block still says auth: none');
  ok('the credential is not also left in a header',
     brus.every(f => !/^\s*Authorization:/mi.test(f.data)),
     'Authorization duplicated as a header');
  ok('duplicate request names do not collide into one file',
     new Set(files.map(f => f.name)).size === files.length);

  console.log('\nprovenance is visible:');
  ok('an endpoint from bruno/ is badged as bruno',
     /src-badge bruno/.test(w.eval('sourceBadge({ref:"x",sourceType:"bruno"})')));
  ok('an endpoint from collections/ is badged as postman',
     /src-badge newman/.test(w.eval('sourceBadge({ref:"x",sourceType:"newman"})')));
  ok('an endpoint only in this browser is badged local',
     /src-badge local/.test(w.eval('sourceBadge(STATE.imported[0])')),
     'an uploaded endpoint is indistinguishable from a committed one');
  ok('the console knows when its inventory was built',
     /\d/.test(String(w.eval('SEED.generatedAt || ""'))),
     String(w.eval('SEED.generatedAt')));

  console.log('\nit fails honestly:');
  console.log('\nevery Postman body mode is read, not just raw:');
  // Reading only body.raw dropped form-encoded and GraphQL requests silently:
  // they imported with an empty payload, and an empty payload renders as a
  // request that sends nothing. A body the importer cannot see must never be
  // indistinguishable from a body that does not exist.
  const modes = [
    ['raw',        { mode: 'raw', raw: '{"a":1}' },                            'a'],
    ['urlencoded', { mode: 'urlencoded', urlencoded: [{ key: 'a', value: '1' }] }, 'a'],
    ['formdata',   { mode: 'formdata', formdata: [{ key: 'a', value: '1' }] },     'a'],
    ['graphql',    { mode: 'graphql', graphql: { query: '{me}' } },             'query']
  ];
  for (const [name, body, key] of modes) {
    w.__pb = body;
    const got = w.eval('postmanBody(__pb)');
    ok('  ' + name + ' yields a body', !!got && got.includes(key),
       'got ' + JSON.stringify(got));
  }
  ok('  a field unticked in Postman is not sent',
     !w.eval('postmanBody({mode:"formdata",formdata:[{key:"a",value:"1",disabled:true}]})'),
     'a disabled form field still reached the payload');

  console.log('\nan import can be undone from the page, not just from devtools:');
  // removeImported() and its undo stack shipped with imports and nothing ever
  // called them: no delete control existed on any row, and #btnRevert was not
  // in the markup at all. The only way to undo a bad upload was clearing
  // browser storage.
  w.__d = { info: { name: 'Dupes' }, item: [
    { name: 'a', request: { method: 'GET',  url: { raw: 'https://h.com/api/a' } } },
    { name: 'b', request: { method: 'POST', url: { raw: 'https://h.com/api/b' } } }
  ] };
  w.eval('STATE.imported = fromPostman(__d, "dupes"); renderMultiSelect(); syncSel();');
  const total = w.eval('allApis().length');
  const rows = [...w.document.querySelectorAll('#msBox [data-del]')];
  ok('every row offers a delete', rows.length === total,
     rows.length + ' buttons for ' + total + ' rows');
  ok('only imported rows can actually be removed',
     rows.filter(b => !b.disabled).length === 2,
     rows.filter(b => !b.disabled).length + ' enabled; a repo endpoint would return on reload');
  ok('a locked row says why', /repositor/i.test((rows.find(b => b.disabled) || {}).title || ''),
     'a disabled control with no reason reads as broken');

  w.eval('removeImported(STATE.imported[0].ref)');
  ok('deleting removes exactly one', w.eval('allApis().length') === total - 1,
     'got ' + w.eval('allApis().length'));
  w.eval('undoImportStep()');
  ok('undo puts it back', w.eval('allApis().length') === total,
     'got ' + w.eval('allApis().length'));

  // A bad upload arrives as a suite, so that is the unit that has to be
  // undoable in one step -- otherwise reversing a 12-endpoint mistake costs
  // twelve clicks and the undo stack caps at 20.
  const mod = w.eval('STATE.imported[0].module');
  w.__m = mod;
  const removed = w.eval('removeImportedSuite(__m)');
  ok('a whole imported suite goes at once', removed === 2 && w.eval('allApis().length') === total - 2,
     'removed ' + removed);
  ok('and comes back in a single undo', (() => {
     w.eval('undoImportStep()');
     return w.eval('allApis().length') === total;
  })(), 'restoring the suite took more than one step');

  w.__f = { name: 'junk.bin', text: async () => 'not a request in sight',
            arrayBuffer: async () => new Uint8Array([1, 2, 3]).buffer };
  const empty = await w.eval('extractFromFile(__f)');
  ok('an unrecognisable file yields nothing rather than guessing',
     empty.found.length === 0, empty.found.length + ' invented');

  console.log('\n%s', bad === 0 ? 'IMPORT OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

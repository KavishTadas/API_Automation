/* Motion layer.

   The layer is decoration, so these assertions come in two halves that matter
   equally: that the effects actually attach to what the report drew, and that
   turning the layer off leaves no trace of it on the page. A decorative layer
   that cannot be switched off cleanly is a change to the design, not a layer
   over it. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const F = path.join(__dirname, 'unified-console.html');

let bad = 0;
const ok = (n, c, d) => {
  console.log((c ? '  PASS  ' : '  FAIL  ') + n + (c ? '' : '\n          -> ' + d));
  if (!c) bad++;
};
const wait = ms => new Promise(r => setTimeout(r, ms));

function boot(html, opts) {
  const dom = new JSDOM(html, Object.assign(
    { runScripts: 'dangerously', pretendToBeVisual: true, url: 'http://localhost/' },
    opts || {}));
  const w = dom.window, d = w.document;
  return {
    w, d,
    $: s => d.querySelector(s),
    $$: s => [...d.querySelectorAll(s)],
    click: el => el.dispatchEvent(new w.Event('click', { bubbles: true }))
  };
}

(async () => {
  const html = fs.readFileSync(F, 'utf8');

  console.log('the layer switches on:');
  const a = boot(html);
  await wait(200);
  ok('the root carries the fx flag',
     a.d.documentElement.getAttribute('data-fx') === 'on',
     a.d.documentElement.getAttribute('data-fx'));
  ok('the bot is on the page', !!a.$('#qabot'));
  ok('the bot has an accessible name',
     !!(a.$('#qabot') || {}).getAttribute &&
     /assistant/i.test(a.$('#qabot').getAttribute('aria-label') || ''));
  ok('the speech region announces politely',
     a.$('#qasay') && a.$('#qasay').getAttribute('aria-live') === 'polite');

  console.log('\nit decorates what the report drew:');
  a.click(a.$('#btnSelAll'));
  await wait(60);
  a.click(a.$('#btnRun'));
  await wait(5600);

  ok('the report rendered', a.$$('#anBody .estat').length === 4,
     a.$$('#anBody .estat').length + ' stat cards');
  ok('charts were given an arrival', a.$$('#anBody .fx-rise').length > 0,
     a.$$('#anBody .fx-rise').length + ' risen');
  ok('charts were given depth', a.$$('#anBody .fx-tilt').length > 0,
     a.$$('#anBody .fx-tilt').length + ' tilted');
  ok('the glow takes a tone from the run',
     a.$$('#anBody [data-fx-tone]').length > 0 &&
     ['pass', 'fail', 'warn', 'quiet'].includes(
       a.$('#anBody [data-fx-tone]').getAttribute('data-fx-tone')),
     a.$('#anBody [data-fx-tone]') &&
     a.$('#anBody [data-fx-tone]').getAttribute('data-fx-tone'));
  ok('the donut sweeps in', !!a.$('#anBody svg.spark.fx-sweep'));
  ok('each ring knows where to sweep from', (() => {
    const c = a.$('#anBody svg.spark.fx-sweep circle');
    return !!c && /-?\d/.test(c.style.getPropertyValue('--fx-dash-from'));
  })(), 'no --fx-dash-from set');

  console.log('\nthe bot reports, it does not invent:');
  a.click(a.$('#qabot'));
  await wait(80);
  const said = a.$('#qasay').textContent;
  ok('clicking the bot says something', a.$('#qasay').classList.contains('on'));
  ok('what it says carries a real number from the run',
     /\d/.test(said), said.slice(0, 80));
  ok('it never claims a run is clean when it is not', (() => {
    const clean = a.w.eval('STATE.result.summary.clean');
    return clean || !/\bis clean\b/i.test(said);
  })(), said.slice(0, 90));

  console.log('\nit switches off without a trace:');
  a.w.eval('fxToggle()');
  await wait(40);
  ok('the flag flips to off',
     a.d.documentElement.getAttribute('data-fx') === 'off',
     a.d.documentElement.getAttribute('data-fx'));
  ok('the report itself is untouched by the flip',
     a.$$('#anBody .estat').length === 4 && !!a.$('#anBody svg.spark'),
     'report content changed when the layer was switched off');
  ok('the choice is remembered', a.w.localStorage.getItem('hcm-fx') === '0',
     a.w.localStorage.getItem('hcm-fx'));

  console.log('\na reader who asked for less motion gets none:');
  const calm = boot(html, {
    beforeParse(w) {
      w.matchMedia = q => ({
        matches: /prefers-reduced-motion/.test(q),
        media: q, addListener() {}, removeListener() {},
        addEventListener() {}, removeEventListener() {}
      });
    }
  });
  await wait(220);
  ok('the layer stays off for reduced motion',
     calm.d.documentElement.getAttribute('data-fx') === 'off',
     calm.d.documentElement.getAttribute('data-fx'));
  ok('and the console still renders',
     !!calm.$('#view-home') || !!calm.$('#anBody'));

  console.log('\nit survives a host that offers nothing:');
  ok('no listener API, no crash', (() => {
    // The contract suite runs the page script against a bare stub; this is the
    // same shape, asserted here so the failure names the layer if it regresses.
    const stub = boot(html, {
      beforeParse(w) {
        w.requestAnimationFrame = undefined;
        w.MutationObserver = undefined;
      }
    });
    return !!stub.d.documentElement.getAttribute('data-fx');
  })(), 'layer threw without rAF/MutationObserver');

  console.log('\n%s', bad === 0 ? 'MOTION OK' : bad + ' ISSUE(S)');
  process.exit(bad === 0 ? 0 : 1);
})();

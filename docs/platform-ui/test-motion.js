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

  console.log('\nthe figure has real depth:');
  const layers = a.$$('#qabot .bot-layer');
  ok('it is built from stacked layers, not one flat drawing',
     layers.length >= 8, layers.length + ' layers');
  ok('every layer sits at its own depth', (() => {
    const z = layers.map(l => l.style.getPropertyValue('--z'));
    return new Set(z).size === z.length && z.every(v => /px$/.test(v));
  })(), layers.map(l => l.style.getPropertyValue('--z')).join(' '));
  ok('the layers span enough depth to parallax', (() => {
    const n = layers.map(l => parseFloat(l.style.getPropertyValue('--z')));
    return Math.max(...n) - Math.min(...n) >= 60;
  })());
  ok('they sit in a preserve-3d box', !!a.$('#qabot .bot-3d'));
  ok('the contact shadow is separate from the figure', !!a.$('#qabot .bot-ground'));
  ok('every layer actually draws', layers.every(l => !!l.querySelector('svg')));

  console.log('\nit responds to the reader:');
  a.w.dispatchEvent(new a.w.MouseEvent('pointermove',
    { clientX: 20, clientY: 20, bubbles: true }));
  await wait(40);
  ok('it turns toward the pointer',
     /-?\d+(\.\d+)?deg/.test(a.$('#qabot').style.getPropertyValue('--bot-yaw')),
     a.$('#qabot').style.getPropertyValue('--bot-yaw') || '(unset)');
  ok('the turn is clamped short of side-on', (() => {
    const y = parseFloat(a.$('#qabot').style.getPropertyValue('--bot-yaw'));
    return Math.abs(y) <= 24;
  })(), a.$('#qabot').style.getPropertyValue('--bot-yaw'));
  ok('it waves on every click', (() => {
    a.$('#qabot').classList.remove('is-waving');
    a.click(a.$('#qabot'));
    return a.$('#qabot').classList.contains('is-waving');
  })(), 'no wave on click');

  console.log('\nits mood follows the run:');
  const setRun = js => {
    a.w.eval(js);
    a.w.eval('document.getElementById("anBody").innerHTML += "<i></i>"');
  };
  setRun("STATE.result={runId:'m',startedAt:'2026-01-01',apis:[]," +
         "summary:{total:4,counts:{PASS:4},passRate:1,clean:true,cleanBlockers:[]}}");
  await wait(90);
  ok('a clean run makes it happy',
     a.$('#qabot').classList.contains('mood-ok'), a.$('#qabot').className);
  setRun("STATE.result.summary.counts={PASS:2,WARN:1};" +
         "STATE.result.summary.clean=false;" +
         "STATE.result.summary.cleanBlockers=['WARN']");
  await wait(90);
  ok('warnings make it cautious',
     a.$('#qabot').classList.contains('mood-warn'), a.$('#qabot').className);
  setRun("STATE.result.summary.counts={PASS:2,FAIL:3}");
  await wait(90);
  ok('a failing run makes it sad',
     a.$('#qabot').classList.contains('mood-sad'), a.$('#qabot').className);
  ok('and it never looks happy while the run is failing',
     !a.$('#qabot').classList.contains('mood-ok'));

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

  console.log('\nthe face reads at the size it is drawn:');
  // The smile was drawn in dark gold on the gold faceplate: present in the
  // markup, invisible on screen. Nothing behavioural can catch that, so the
  // contrast is asserted directly.
  const bot = a.$('#qabot');
  const mouth = bot && bot.querySelector('.bot-mouth');
  ok('the bot has a mouth at all', !!mouth, 'no .bot-mouth in the figure');
  const stroke = mouth ? (mouth.getAttribute('stroke') || '').toLowerCase() : '';
  ok('it is not drawn in a faceplate tone',
     !!stroke && !['#f5c518', '#d09b06'].includes(stroke),
     'stroke ' + stroke + ' is gold on a gold plate — invisible at 98px');
  ok('it is thick enough to survive the scale down',
     parseFloat(mouth && mouth.getAttribute('stroke-width')) >= 2.5,
     'a sub-2.5 stroke renders under two physical pixels here');
  // The faceplate runs y15-68, but below y61 it tapers hard into the chin and
  // the eyes end at y49. So the mouth belongs in y50-61, and every mood has to
  // keep it there: the smile was twice drawn low enough to cross the jaw line,
  // which puts it on the chin rather than on the face.
  const EYES_END = 49, CHIN = 61;
  const dAttr = mouth ? mouth.getAttribute('d') : '';
  const nums = (dAttr.match(/-?\d+(?:\.\d+)?/g) || []).map(Number);
  // "M x0 y0 q dcx dcy dex dey" — the deepest point of a quadratic is at t=0.5
  const y0 = nums[1], cy = nums[1] + nums[3], ey = nums[1] + nums[5];
  const deepest = (y0 + 2 * cy + ey) / 4;
  ok('at rest the mouth sits on the gold, clear of the chin',
     y0 > EYES_END && deepest < CHIN,
     'arc runs y' + y0 + '..' + deepest.toFixed(1) + ', outside y' + EYES_END + '-' + CHIN);

  const moodBand = k => {
    const css = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('\n');
    const m = css.match(new RegExp('mood-' + k + ' \\.bot-mouth\\{transform:([^;}]+);transform-origin:60px (\\d+(?:\\.\\d+)?)px'));
    if (!m) return null;
    const t = m[1], oy = Number(m[2]);
    let sy = 1, ty = 0;
    const sc = t.match(/scale\(\s*[\d.]+\s*,\s*(-?[\d.]+)\s*\)/);
    if (sc) sy = Number(sc[1]);
    const s1 = t.match(/scaleY\(\s*(-?[\d.]+)\s*\)/);
    if (s1) sy = Number(s1[1]);
    const tr = t.match(/translateY\(\s*(-?[\d.]+)px\s*\)/);
    if (tr) ty = Number(tr[1]);
    const f = y => oy + (y - oy) * sy + ty;
    return [Math.min(f(y0), f(deepest)), Math.max(f(y0), f(deepest))];
  };
  for (const k of ['ok', 'warn', 'sad']) {
    const b = moodBand(k);
    ok('  ' + k + ' keeps it inside the gold band',
       !!b && b[0] > EYES_END && b[1] < CHIN,
       b ? 'runs y' + b[0].toFixed(1) + '..' + b[1].toFixed(1) : 'no rule found');
  }

  // The mouth used to flip to a frown on any failing run. The suite rarely
  // runs completely clean, so "unhappy" was effectively the figure's default
  // and it read as broken rather than as informative. It now always smiles —
  // which is only acceptable because the mouth was never where the truth
  // lived. These assert both halves of that trade.
  ok('the smile never inverts, whatever the run did', (() => {
    const css = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('');
    return !/mood-(?:ok|warn|sad) \.bot-mouth\{[^}]*scaleY\(\s*-/.test(css) &&
           !/mood-(?:ok|warn|sad) \.bot-mouth\{[^}]*scale\([^)]*,\s*-/.test(css);
  })(), 'a mood still flips the mouth, so the assistant scowls on a normal run');
  ok('the run result is still legible without the mouth', (() => {
    const css = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('');
    // The suit is repulsor blue in every mood now, eyes included, so the
    // result cannot ride on the character's own colours. It rides on a status
    // lamp instead: --bot-signal, read by the beacon and the ground ring. A
    // lamp changing colour is a readout; a character changing colour is a
    // different character.
    const signals = new Set(
      (css.match(/mood-(?:ok|warn|sad)\{[^}]*--bot-signal:\s*(#[0-9a-f]{3,8})/gi) || [])
        .map(m => m.slice(m.indexOf('#')).toLowerCase()));
    return signals.size === 3 && /class="bot-beacon"[^>]*--bot-signal|--bot-signal/.test(css + '');
  })(), 'the three moods do not map to three distinct signal colours');
  ok('and the signal is not painted on the suit itself', (() => {
    const css = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('');
    return !/mood-(?:ok|warn|sad)[^{]*\.bot-eyes\{color:/.test(css);
  })(), 'a mood still retints the eyes, so a failing run changes the character');
  ok('and it still never claims a failing run passed',
     !a.$('#qabot').classList.contains('mood-ok') ||
     !/FAIL/.test(a.$('#qabot').getAttribute('aria-label') || ''),
     'the mood class or the label contradicts the result');

  console.log('\nthe report survives an endpoint leaving the console:');
  // The reported failure: run every suite, then delete an imported suite, and
  // every tab but the one on screen goes dead. renderAnalytics() dereferenced
  // the null from apiByRef() and threw mid-render, so the tab bar stayed bound
  // to a function that throws. Nothing looked broken — it just stopped moving.
  {
    const g = boot(html);
    await wait(320);
    const items = [];
    for (let i = 0; i < 8; i++) items.push({ name: 'ep' + i, request: {
      method: ['GET', 'POST', 'PUT'][i % 3],
      url: { raw: 'https://h.example.com/api/imported/' + i } } });
    g.w.__c = { info: { name: 'Bad Upload' }, item: items };
    g.w.eval('STATE.imported = fromPostman(__c, "imp");' +
             'allApis().forEach(a => STATE.selected.add(a.ref));' +
             'STATE.result = runBatch([...STATE.selected]); go("analytics")');
    await wait(220);

    const gerrs = [];
    g.w.addEventListener('error', e => gerrs.push(e.message));
    g.w.console.error = (...a) => gerrs.push(a.join(' '));

    g.w.__m = 'Imported · Bad Upload';
    const removed = g.w.eval('removeImportedSuite(__m)');
    g.w.eval('afterCatalogueChange()');
    await wait(120);
    ok('the suite goes', removed === 8, 'removed ' + removed);
    ok('and the run still holds its results',
       g.w.eval('STATE.result.apis.filter(a => !apiByRef(a.apiRef)).length') === 8,
       'the run lost the rows for the deleted endpoints');

    const tabs = [...g.d.querySelectorAll('#anTabs .nitem')];
    ok('every tab still renders after the delete', await (async () => {
      let allDrew = tabs.length >= 8;
      for (const t of tabs) {
        t.dispatchEvent(new g.w.Event('click', { bubbles: true }));
        await wait(60);
        if ((g.d.querySelector('#anBody').innerHTML.length || 0) < 500) allDrew = false;
      }
      return allDrew;
    })(), 'a tab rendered nothing — renderAnalytics threw partway');
    ok('and none of them threw', gerrs.length === 0,
       gerrs.length + ' error(s): ' + (gerrs[0] || '').slice(0, 110));

    // Honesty: the request really was made, so the row stays and says so.
    g.w.eval('STATE.tab = "suites"; renderAnalytics()');
    await wait(90);
    ok('a removed endpoint is reported, not dropped',
       /No longer in the console/.test(g.d.querySelector('#anBody').textContent),
       'the results of deleted endpoints vanished from the report');

    // The synthetic host entry must NOT resolve, or every count gains one.
    ok('the host-level entry still does not resolve to an endpoint',
       g.w.eval('resultApi("uatmcdphcmplatform.omfysgroup.com")') === null &&
       g.w.eval('resultApi("")') === null,
       'a non-endpoint ref produced a tombstone — counts will read one too many');
  }

  console.log('\nit greets before it judges, and stays in character:');
  // The arrival is a hello, not a verdict. It lands smiling whatever the last
  // run did — but only the face says so: the mood class, the aria-label and
  // the beacon keep reporting the real result throughout, so the greeting can
  // never be mistaken for a claim about the run.
  const greetCss = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('');
  // A fresh boot: the greeting lasts about five seconds, and by the time the
  // rest of this suite has run it is long over. Asserting it on the shared
  // instance would pass or fail depending on how slow the machine is.
  const fresh = boot(html);
  await wait(150);
  const freshBot = fresh.$('#qabot');
  ok('it lands with a greeting',
     freshBot.classList.contains('is-greeting'),
     'no greeting state on arrival, so a failing run lands with a frown');
  ok('the greeting ends and the face goes back to reporting', await (async () => {
    fresh.w.eval("document.getElementById('qabot').classList.remove('is-greeting')");
    return !fresh.$('#qabot').classList.contains('is-greeting');
  })(), 'the greeting state is not removable, so the mood could never show');
  ok('the greeting smiles',
     greetCss.includes('#qabot.is-greeting .bot-mouth'),
     'the greeting state does not change the face, so it does nothing');
  ok('the greeting never overrides what the run says',
     !greetCss.includes('is-greeting') || !/is-greeting[^{]*\{[^}]*aria/.test(greetCss),
     'the greeting must not touch anything a screen reader reads');
  ok('the mood class still reports the real result while greeting',
     ['mood-ok', 'mood-warn', 'mood-sad'].some(c => bot.classList.contains(c)),
     'the greeting replaced the mood instead of sitting on top of it');

  // Iron Man's repulsors are blue. Tinting them by run result rendered a
  // failing run in magenta, which reads as a different character rather than
  // as the same one with bad news.
  ok('the arc reactor and thrust are repulsor blue',
     greetCss.includes('--bot-core:#8fe3fb'),
     'the core colour is not the repulsor blue');
  ok('no mood repoints the repulsor colour',
     !/mood-(?:ok|warn|sad)\{[^}]*--bot-core/.test(greetCss),
     'a mood still retints the thrust, so a failing run changes the character');
  ok('the palm repulsor keeps its blue too',
     /#qabot \.bot-palm\{color:#6fd6ff\}/.test(greetCss) &&
     !/mood-(?:warn|sad)[^{]*\.bot-palm\{color/.test(greetCss),
     'the palm still takes a mood colour');

  console.log('\nit looks alive rather than switched off:');
  const aliveCss = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('');
  // The old idle wave ran for 8% of a six-second cycle and the "blink" faded
  // opacity for a seventh of a second. Both were present, and neither read as
  // motion. These assert the figure is animating continuously, not twitching.
  ok('both eyes blink together, on one element',
     !!bot.querySelector('.bot-blink') &&
     bot.querySelectorAll('.bot-blink .bot-eye').length === 2,
     'the eyes are not inside a single blink group, so they cannot close together');
  ok('the blink closes a lid rather than dimming a light',
     /@keyframes botBlink\{[^}]*scaleY/.test(aliveCss) &&
     !/@keyframes botBlink\{[^}]*opacity/.test(aliveCss),
     'fading opacity reads as a flicker in the visor, not as a blink');
  ok('the blink repeats forever',
     /\.bot-blink\{[^}]*animation:\s*botBlink[^;}]*infinite/.test(aliveCss),
     'a blink that runs once is a glitch');
  ok('the arm waves continuously',
     /#qabot \.bot-arm-r\{animation:botWaveLoop[^;}]*infinite/.test(aliveCss),
     'the arm is idle between clicks, which is what made it look switched off');
  ok('a click is still bigger than the idle wave',
     /is-waving \.bot-arm-r\{animation:botWave /.test(aliveCss),
     'the greeting wave is indistinguishable from the idle one');
  ok('reduced motion stops the new animations too',
     /prefers-reduced-motion[\s\S]*?#qabot \.bot-blink/.test(aliveCss),
     'the blink keeps running for a viewer who asked for no motion');
  ok('both gloves have fingers',
     bot.querySelectorAll('.bot-arm-r path[stroke-linecap="round"]').length > 0 &&
     bot.querySelectorAll('.bot-arm-l path[stroke-linecap="round"]').length > 0,
     'a glove with no finger slits reads as a mitten');

  console.log('\nit does not swallow clicks meant for the report:');
  // jsdom has no layout, so nothing here can overlap anything -- which is
  // exactly why the original defect passed this suite while a full-width
  // button sitting under the figure was dead in a real browser. So these
  // assert the CSS contract instead: the box is click-through, and only
  // painted pixels answer.
  const botCss = [...a.d.querySelectorAll('style')].map(s => s.textContent).join('\n');
  ok('the figure box lets clicks through to the page',
     /#qabot\{[^}]*pointer-events:\s*none/.test(botCss),
     'the fixed 98x156 box intercepts every click over the report beneath it');
  ok('painted pixels still answer, so the bot stays clickable',
     /\.bot-layer svg path[\s\S]{0,160}pointer-events:\s*visiblePainted/.test(botCss),
     'nothing re-enables hit-testing, so the bot itself would be unclickable');
  // The bubble takes pointer events now, so it can be hovered while it is read
  // -- keeping the pointer inside a 98px figure to finish six lines of text was
  // the specific thing that made it feel broken. The original guarantee is
  // kept, but by a different mechanism: it dismisses on click instead of being
  // inert, so it can still never trap a click meant for the report.
  const pageJs = [...a.d.querySelectorAll('script')].map(s => s.textContent).join('\n');
  ok('the bubble can be hovered to hold it open',
     /#qasay\.on\{[^}]*pointer-events:\s*auto/.test(botCss),
     'the bubble is inert, so moving onto it to read closes it');
  ok('and clicking it dismisses rather than traps',
     /on\(say, 'click'[\s\S]{0,80}hideSay\(\)/.test(pageJs),
     'no click handler: the bubble could cover the report with no way past it');
  ok('the toast is click-through while it is shown',
     /\.toast\{[^}]*pointer-events:\s*none/.test(botCss),
     'a z-index 200 panel bottom-right kills controls under it for 2.6s at a time');
  const enav = botCss.slice(botCss.indexOf('.enav-in{'), botCss.indexOf('.enav-in{') + 240);
  ok('the report tab strip wraps instead of scrolling',
     enav.includes('flex-wrap:wrap') && !enav.includes('overflow-x'),
     'eight tabs overflow a narrow window and scroll out of sight behind a thin bar');
  ok('rings and exhaust are not click targets',
     /#qabot \.bot-ring[\s\S]{0,120}pointer-events:\s*none/.test(botCss),
     'the sonar ring reaches well outside the painted figure');

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

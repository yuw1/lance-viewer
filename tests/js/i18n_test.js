// Language-switch regression: the tab body is generated HTML, so switching language must re-render
// it — not just update the static data-i18n chrome. setLang re-renders via the sidebar's
// loadCurrentTab only when a dataset is open, and never on the boot-time setLang() call.
//
// Run with: node tests/js/i18n_test.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const JS_DIR = process.env.LV_JS_DIR
  || path.join(__dirname, '..', '..', 'src', 'lance_viewer', 'static', 'js');

function makeNode(tag) {
  return {
    tagName: tag,
    innerHTML: '',
    textContent: '',
    style: {},
    setAttribute() {},
    getAttribute() { return null; },
    querySelectorAll() { return []; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  };
}
const byId = {};
const document = {
  documentElement: { lang: '' },
  getElementById(id) { return byId[id] || (byId[id] = makeNode('div')); },
  createElement(tag) { return makeNode(tag); },
  querySelectorAll() { return []; },
  addEventListener() {},
};

const calls = { n: 0 };
const sandbox = {
  console,
  document,
  localStorage: { getItem() { return 'en'; }, setItem() {} },
  navigator: { sendBeacon() {} },
  crypto: { getRandomValues(buf) { buf.fill(0); return buf; } },
  fetch: () => Promise.resolve({ json: async () => ({}) }),
  setInterval: () => 0,
  clearInterval() {},
  addEventListener() {},
  setTimeout,
  clearTimeout,
  // Stand-in for the real loadCurrentTab declared in sidebar.js; we only assert it is invoked.
  loadCurrentTab: () => { calls.n += 1; return Promise.resolve(); },
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
const ctx = vm.createContext(sandbox);

vm.runInContext(fs.readFileSync(path.join(JS_DIR, 'tools.js'), 'utf8'), ctx, { filename: 'tools.js' });

const failures = [];
function check(label, fn) {
  try { fn(); console.log('  ok    ' + label); }
  catch (e) { failures.push(`${label}: ${e.message}`); console.log('  FAIL  ' + label + ': ' + e.message); }
}

check('boot setLang does not re-render (no dataset open yet)', () => {
  // tools.js ends with setLang(currentLang) while currentPath is still ''.
  if (calls.n !== 0) throw new Error(`expected 0 loadCurrentTab calls at boot, got ${calls.n}`);
});

check('switching language re-renders once a dataset is open', () => {
  vm.runInContext('currentPath = "/data/x"; setLang("zh");', ctx);
  if (calls.n !== 1) throw new Error(`expected 1 re-render, got ${calls.n}`);
  vm.runInContext('setLang("en");', ctx);
  if (calls.n !== 2) throw new Error(`expected 2 re-renders, got ${calls.n}`);
});

check('clearing the path stops the re-render', () => {
  vm.runInContext('currentPath = ""; setLang("zh");', ctx);
  if (calls.n !== 2) throw new Error(`clearing path must not re-render; still ${calls.n}`);
});

if (failures.length) {
  console.error('\n' + failures.length + ' i18n check(s) failed:');
  for (const f of failures) console.error(' - ' + f);
  process.exit(1);
}
console.log('\nlanguage switch re-renders the tab body');
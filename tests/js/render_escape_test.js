// Frontend escaping test: loads the real frontend modules into a VM with a minimal DOM stub and
// feeds every renderer a dataset whose names/values try to break out of the generated HTML.
//
// The threat is concrete: a Lance dataset is arbitrary input (downloaded, shared, extracted from an
// archive). A column named `<img src=x onerror=...>` used to reach the page as live HTML, and the
// viewer origin can read /api/datasets — which returns the stored S3 credentials.
//
// Run with: node tests/js/render_escape_test.js   (exit code 0 = all renderers escape)
const fs = require('fs');
const path = require('path');
const vm = require('vm');

// Override to run the harness against another copy of the JS (used to confirm it catches the bug).
const JS_DIR = process.env.LV_JS_DIR
  || path.join(__dirname, '..', '..', 'src', 'lance_viewer', 'static', 'js');

// --- minimal DOM ------------------------------------------------------------
function makeNode(tag) {
  return {
    tagName: tag,
    innerHTML: '',
    textContent: '',
    title: '',
    className: '',
    value: '',
    style: {},
    dataset: {},
    children: [],
    appendChild(child) { this.children.push(child); return child; },
    addEventListener() {},
    querySelector() { return makeNode('span'); },
    querySelectorAll() { return []; },
    setAttribute() {},
    getAttribute() { return null; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  };
}

const byId = {};
const document = {
  documentElement: {},
  getElementById(id) { return byId[id] || (byId[id] = makeNode('div')); },
  createElement(tag) { return makeNode(tag); },
  querySelectorAll() { return []; },
  addEventListener() {},
};

const sandbox = {
  console,
  document,
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: { sendBeacon() {} },
  crypto: { getRandomValues(buf) { buf.fill(0); return buf; } },
  fetch: () => Promise.resolve({ json: async () => ({}) }),
  setInterval: () => 0,
  clearInterval() {},
  addEventListener() {},
  setTimeout,
  clearTimeout,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
const ctx = vm.createContext(sandbox);

// --- load the real frontend modules, in the same order as index.html ---------
for (const file of ['icons.js', 'tools.js', 'files.js', 'render.js']) {
  const src = fs.readFileSync(path.join(JS_DIR, file), 'utf8');
  vm.runInContext(src, ctx, { filename: file });
}

// Function declarations land on the VM global; `refsCache` is a `let`, so it needs a setter
// compiled in the same lexical scope.
vm.runInContext(`
  globalThis.__api = {
    renderTree, renderSchema, renderIndex, renderStorage, renderHealth, renderTimeline, renderData,
    renderRefsBar,
    setRefs: r => { refsCache = r; },
  };
`, ctx, { filename: 'expose' });

const api = sandbox.__api;

// --- payloads ---------------------------------------------------------------
const TAG = '<img src=x onerror=alert(1)>';       // element injection
const ATTR = 'x" onmouseover="alert(1)';          // attribute breakout
const SCRIPT = "');alert(1);//";                   // inline-handler string breakout

const failures = [];
function check(label, fn) {
  try {
    fn();
    console.log(`  ok    ${label}`);
  } catch (e) {
    failures.push(`${label}: ${e.message}`);
    console.log(`  FAIL  ${label}: ${e.message}`);
  }
}

function assertNoLeak(html, label) {
  if (html.includes('<img')) throw new Error('raw element survived');
  if (html.includes('onmouseover="alert')) throw new Error('attribute breakout survived');
  if (html.includes("');alert")) throw new Error('inline-handler breakout survived');
  if (!html.includes('&lt;img')) throw new Error('escaped payload missing — renderer did not run?');
}

const view = () => byId.view.innerHTML;

// --- tree -------------------------------------------------------------------
check('tree: file and dir names', () => {
  api.renderTree({ tree: [
    { name: TAG, type: 'dir', mtime: ATTR, children: [
      { name: ATTR, type: 'file', size: 10, mtime: TAG },
    ] },
  ] });
  const rows = byId.treeTbody.children.map(c => c.innerHTML).join('');
  assertNoLeak(view() + rows, 'tree');
});

// --- schema -----------------------------------------------------------------
check('schema: field name and type', () => {
  api.renderSchema({ path: '/tmp/x', fields: [{ name: TAG, type: ATTR, nullable: false }] });
  assertNoLeak(view(), 'schema');
});

// --- index ------------------------------------------------------------------
check('index: name, type, fields, params', () => {
  api.renderIndex({ path: '/tmp/x', indices: [
    { name: TAG, type: ATTR, fields: [TAG], version: 1, uuid: 'abcdef012345',
      stats: { num_indexed_rows: 1, num_unindexed_rows: 0,
               indices: [{ num_tokens: 3, num_docs: 1, params: { [ATTR]: TAG } }] } },
  ] });
  assertNoLeak(view(), 'index');
});

// --- storage ----------------------------------------------------------------
check('storage: file type label, column name, path', () => {
  api.renderStorage({ path: '/tmp/x', total_size: 100, data_files: [
    { file: 'data/001.lance', size: 100, columns: [
      { name: TAG, buffer_size: 100, compression: [ATTR], pages: 2 },
    ] },
  ], file_types: [{ key: 'k', label: TAG, count: 1, size: 100 }],
     top_files: [{ path: ATTR, size: 100 }] });
  assertNoLeak(view(), 'storage');
});

// --- timeline ---------------------------------------------------------------
check('timeline: operation, timestamp, file name', () => {
  api.renderTimeline({ path: '/tmp/x', has_snapshot: true,
    op_stats: { [ATTR]: 1 },
    transactions: [
      { file: '0-test.txn', version: 1, operation: TAG, mtime: TAG, read_version: 0,
        snapshot: { timestamp: TAG, rows: 1, data_files: 1, fragments: 1,
                    deletion_files: 0, deletion_rows: 0, size_bytes: 10 } },
      // An undecodable txn renders its file name and error text; both are dataset-controlled.
      { file: TAG, error: TAG },
    ] });
  assertNoLeak(view(), 'timeline');
});

// --- data table -------------------------------------------------------------
check('data: column name, string cell, chip handler', () => {
  api.renderData({ path: '/tmp/x', count: 2, offset: 0, limit: 20, shown: 2, versions: 1,
    filter: ATTR,
    schema: [{ name: ATTR, type: TAG, nullable: true }],
    columns: { [ATTR]: [TAG, SCRIPT] },
    display: [{ name: ATTR, timestamp: false }] });
  assertNoLeak(view(), 'data');
  if (!view().includes('toggleDataColumnAt(0)')) {
    throw new Error('chip should pass a schema index, not the column name');
  }
});

// --- health -----------------------------------------------------------------
check('health: column names, types and index badges', () => {
  api.renderHealth({
    path: '/tmp/x', rows: 10, fragments: 1, versions: 1, data_files: 1,
    size_bytes: 10, deleted_rows: 0, fragment_stats: { min: 1, median: 1, max: 1 },
    format: { data_storage_version: TAG },
    coverage: [{ field: TAG, type: ATTR, index_types: [ATTR] }],
    issues: [{ code: 'tombstones', severity: 'warn', params: { rows: 1, pct: 10 } }],
  });
  assertNoLeak(view(), 'health');
});

// --- refs bar ---------------------------------------------------------------
check('refs bar: branch and tag names', () => {
  api.setRefs({ branches: [{ name: ATTR, version: 1 }], versions: [{ version: 1, timestamp: TAG }],
                tag_by_version: { 1: [TAG] } });
  assertNoLeak(api.renderRefsBar(), 'refs');
});

if (failures.length) {
  console.error(`\n${failures.length} escaping check(s) failed:`);
  for (const f of failures) console.error(' - ' + f);
  process.exit(1);
}
console.log('\nall renderers escape dataset-controlled text');
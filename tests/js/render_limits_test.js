// Frontend limit tests: the four places that used to build one DOM node per dataset record.
//
// These are behaviour checks, not cosmetics: a manifest with 10k fragments, a 5000-version timeline
// or a 5000-entry version dropdown all used to be built eagerly, so the tab froze before painting.
// Run with: node tests/js/render_limits_test.js
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const JS_DIR = process.env.LV_JS_DIR
  || path.join(__dirname, '..', '..', 'src', 'lance_viewer', 'static', 'js');

// --- DOM stub that can be clicked ------------------------------------------
let created = 0;

function makeNode(tag) {
  created++;
  const node = {
    tagName: tag,
    innerHTML: '',
    textContent: '',
    className: '',
    style: {},
    dataset: {},
    children: [],
    _listeners: {},
    appendChild(child) { this.children.push(child); return child; },
    prepend(child) { this.children.unshift(child); return child; },
    remove() { this.removed = true; },
    addEventListener(type, fn) { (this._listeners[type] = this._listeners[type] || []).push(fn); },
    click() { (this._listeners.click || []).forEach(fn => fn({ stopPropagation() {} })); },
    querySelector() { return makeNode('span'); },
    querySelectorAll() { return []; },
    setAttribute() {},
    getAttribute() { return null; },
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  };
  return node;
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
  console, document,
  localStorage: { getItem() { return null; }, setItem() {} },
  navigator: { sendBeacon() {} },
  crypto: { getRandomValues(buf) { buf.fill(0); return buf; } },
  fetch: () => Promise.resolve({ json: async () => ({}) }),
  setInterval: () => 0,
  clearInterval() {},
  addEventListener() {},
  setTimeout, clearTimeout,
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
const ctx = vm.createContext(sandbox);

for (const file of ['icons.js', 'tools.js', 'files.js', 'render.js']) {
  vm.runInContext(fs.readFileSync(path.join(JS_DIR, file), 'utf8'), ctx, { filename: file });
}
vm.runInContext(`
  globalThis.__api = {
    renderJsonTree, renderTimeline, renderStorage, renderRefsBar,
    setRefs: r => { refsCache = r; },
  };
`, ctx, { filename: 'expose' });

const api = sandbox.__api;
const view = () => byId.view;

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

function countRows(node) {
  let n = 0;
  for (const child of node.children || []) {
    if (child.className === 'row') n++;
    n += countRows(child);
  }
  return n;
}

// --- JSON tree: nothing is built until a collection is expanded -------------
check('json tree builds only the root, not 1000 collapsed children', () => {
  const big = { fragments: Array.from({ length: 1000 }, (_, i) => ({ id: i })) };
  const container = document.createElement('div');
  const before = created;

  api.renderJsonTree(big, container);

  const built = created - before;
  if (built > 8) throw new Error(`built ${built} nodes for a collapsed tree`);
  if (countRows(container) > 3) throw new Error('collapsed rows were built eagerly');
});

check('json tree renders collections in chunks of 200 with a show-more control', () => {
  const big = { fragments: Array.from({ length: 1000 }, (_, i) => ({ id: i })) };
  const container = document.createElement('div');
  const before = created;
  api.renderJsonTree(big, container);

  // container.children = [row(root), children(root)]; inside it, the fragments collection.
  const rootChildren = container.children[1];
  const fragmentsRow = rootChildren.children[0];
  const fragmentsChildren = rootChildren.children[1];
  fragmentsRow.children[0].click();   // the chevron toggle prepended to the row

  const rows = countRows(fragmentsChildren);
  if (rows !== 200) throw new Error(`expanded ${rows} rows, expected one 200-item chunk`);

  // Each rendered item costs a row plus its (collapsed) collection shell, so ~3 nodes per item: the
  // point is that 1000 items are not built, not that a chunk is free.
  const built = created - before;
  if (built > 800) throw new Error(`built ${built} nodes for one 200-item chunk`);

  const more = fragmentsChildren.children[fragmentsChildren.children.length - 1];
  const moreLabel = more.children.length ? more.children[0].textContent : '';
  if (!moreLabel.includes('Show 200 more of 1000')) {
    throw new Error(`show-more label missing: ${moreLabel}`);
  }

  // The control builds the next chunk instead of re-rendering everything.
  more.children[0].click();
  const grown = countRows(fragmentsChildren);
  if (grown !== 400) throw new Error(`after "show more": ${grown} rows, expected 400`);
});

// --- timeline: older chunks are opt-in -------------------------------------
const txn = i => ({
  file: `${i}-x.txn`, version: i, operation: 'append', operation_label: 'Append',
  read_version: i - 1, mtime: null, snapshot: null,
});

check('timeline offers "load earlier" only when the server says older rows exist', () => {
  api.renderTimeline({ transactions: [txn(8), txn(9)], has_more: true, total: 500, has_snapshot: false });
  const html = view().innerHTML;
  if (!html.includes('loadEarlierTransactions()')) throw new Error('load-earlier button missing');
  if (!html.includes('Showing the newest 2 of 500 transactions')) throw new Error('window label missing');

  api.renderTimeline({ transactions: [txn(0)], has_more: false, total: 1, has_snapshot: false });
  if (view().innerHTML.includes('loadEarlierTransactions()')) {
    throw new Error('load-earlier button shown when there is nothing older');
  }
});

// --- storage: the analysed subset is named ---------------------------------
check('storage says when only the largest files were analysed', () => {
  api.renderStorage({
    total_size: 1000, file_types: [], top_files: [],
    data_files: [{ file: 'data/a.lance', size: 1000, columns: [] }],
    data_files_total: 40, data_files_analyzed: 15,
  });
  if (!view().innerHTML.includes('Analysing the largest 15 of 40 data files')) {
    throw new Error('subset note missing');
  }

  api.renderStorage({
    total_size: 1000, file_types: [], top_files: [],
    data_files: [{ file: 'data/a.lance', size: 1000, columns: [] }],
    data_files_total: 1, data_files_analyzed: 1,
  });
  if (view().innerHTML.includes('Analysing the largest')) {
    throw new Error('subset note shown when everything was analysed');
  }
});

// --- version bar: capped options plus a way to reach older versions --------
check('version dropdown caps at 100 options and adds a jump box', () => {
  const versions = Array.from({ length: 500 }, (_, i) => ({ version: i + 1, timestamp: null }));
  api.setRefs({ branches: [], versions, tag_by_version: {} });
  const html = api.renderRefsBar();

  const options = (html.match(/<option/g) || []).length;
  if (options > 101) throw new Error(`${options} options rendered (branch + at most 100 versions)`);
  if (!html.includes('id="refVersionJump"')) throw new Error('jump box missing');
  if (!html.includes('Showing the newest 100 of 500 versions')) throw new Error('trim note missing');
  if (options < 100) throw new Error('the newest versions should all be there');
});

check('a short version list renders no trim note or jump box', () => {
  const versions = Array.from({ length: 5 }, (_, i) => ({ version: i + 1, timestamp: null }));
  api.setRefs({ branches: [], versions, tag_by_version: {} });
  const html = api.renderRefsBar();

  if (html.includes('id="refVersionJump"')) throw new Error('jump box shown for 5 versions');
  if (html.includes('Showing the newest')) throw new Error('trim note shown for 5 versions');
});

if (failures.length) {
  console.error(`\n${failures.length} limit check(s) failed:`);
  for (const f of failures) console.error(' - ' + f);
  process.exit(1);
}
console.log('\nall four list-rendering limits hold');
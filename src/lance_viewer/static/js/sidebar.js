// Lance Viewer - dataset sidebar + navigation + init
// Deps: tools.js, render.js, files.js. Loaded last (includes event binding).

// ---------- Loading logic ----------

let activeTab = 'tree';
// ---------- Dataset sidebar (SQLite backend) ----------
let datasets = [];
let activeDsId = null;

async function refreshDatasets() {
  const r = await fetch('/api/datasets');
  const d = await r.json();
  datasets = d.datasets || [];
  renderSidebar();
}

function dsName(ds) {
  return ds.name || ds.path.split('/').pop() || ds.path;
}

function renderSidebar() {
  const list = $('dsList');
  if (!datasets.length) {
    list.innerHTML = '<div class="ds-empty">' + t('noDatasets') + '</div>';
    return;
  }
  list.innerHTML = datasets.map(ds => {
    const active = activeDsId === ds.id;
    return `<li class="ds-item${active ? ' active' : ''}" data-id="${ds.id}" title="${esc(ds.path)}">
      <div class="ds-info">
        <div class="ds-name">${esc(dsName(ds))}</div>
        <div class="ds-path">${esc(ds.path)}</div>
      </div>
      <div class="ds-actions">
        <button class="btn-icon" title="${t('edit')}" data-act="edit">${icon('pencil', 14)}</button>
        <button class="btn-icon" title="${t('del')}" data-act="del">${icon('trash-2', 14)}</button>
      </div>
    </li>`;
  }).join('');
  // Click to select
  list.querySelectorAll('.ds-item').forEach(li => {
    li.addEventListener('click', e => {
      const act = e.target.closest('[data-act]')?.dataset.act;
      if (act === 'del') { deleteDataset(li.dataset.id); return; }
      if (act === 'edit') { editDataset(li.dataset.id); return; }
      selectDataset(li.dataset.id);
    });
  });
}

function selectDataset(id) {
  const ds = datasets.find(x => x.id == id);
  if (!ds) return;
  activeDsId = id;
  renderSidebar();
  currentPath = ds.path;
  updateCurPath();
  dataPage = 0; // switching dataset resets to first page
  dataPageSize = 20; // and to the default page size: the new dataset may be far wider
  dataColumns = null; // and the column picker: the new dataset has a different schema
  dataFilter = ''; // and the row filter: it likely names columns this dataset does not have
  loadCurrentTab();
}

function updateCurPath() {
  const el = $('curPath');
  if (!el) return;
  el.innerHTML = currentPath
    ? icon('folder', 13) + ' ' + esc(currentPath)
    : '';
  el.title = currentPath || '';
}

async function deleteDataset(id) {
  const ds = datasets.find(x => x.id == id);
  if (!confirm(t('confirmDelete', { name: dsName(ds), path: ds.path }))) return;
  await fetch(`/api/datasets?id=${id}`, { method: 'DELETE' });
  if (activeDsId == id) { activeDsId = null; currentPath = ''; $('view').innerHTML = '<div class="empty">' + t('selectOne') + '</div>'; }
  await refreshDatasets();
}

function editDataset(id) {
  const ds = datasets.find(x => x.id == id);
  if (!ds) return;
  $('dsId').value = ds.id;
  $('dsName').value = ds.name || '';
  $('dsPath').value = ds.path;
  // Backfill the four object-storage fields (split out of options)
  const opts = ds.options || {};
  const isOss = Object.prototype.hasOwnProperty.call(opts, 'access_key_secret');
  $('dsStoreType').value = isOss ? 'oss' : 's3';
  applyStoreType();
  $('dsAk').value = opts.access_key_id || '';
  $('dsSk').value = isOss ? (opts.access_key_secret || '') : (opts.secret_access_key || '');
  $('dsEndpoint').value = opts.endpoint || '';
  $('dsRegion').value = opts.region || '';
  const extra = {};
  Object.keys(opts).forEach(k => {
      if (['access_key_id', 'secret_access_key', 'access_key_secret', 'endpoint', 'region'].indexOf(k) === -1) extra[k] = opts[k];
  });
  renderKvRows(extra);
  $('dsModalTitle').innerHTML = icon('pencil', 16) + ' ' + esc(t('dsModalEdit'));
  toggleDsModal(true);
}

// Apply the selected storage type: only the secret-key field name changes
// (s3 -> secret_access_key, oss -> access_key_secret); the other three stay unprefixed.
function applyStoreType() {
  const label = $('dsSkLabel');
  if (!label) return;
  const isOss = $('dsStoreType').value === 'oss';
  label.textContent = isOss ? 'access_key_secret' : 'secret_access_key';
}

function toggleDsModal(show) {
  const m = $('dsModal');
  m.style.display = show ? 'flex' : 'none';
  if (show) {
    $('dsPath').focus();
  } else {
    $('dsId').value = '';
  }
}

function openAddDsModal() {
  // New: clear all fields
  $('dsId').value = '';
  $('dsName').value = '';
  $('dsPath').value = '';
  $('dsAk').value = '';
  $('dsSk').value = '';
  $('dsEndpoint').value = '';
  $('dsRegion').value = '';
  $('dsStoreType').value = 's3';
  applyStoreType();
  renderKvRows({});
  $('dsModalTitle').innerHTML = icon('plus', 16) + ' ' + esc(t('dsModalAdd'));
  toggleDsModal(true);
}

// ---------- Advanced key-value row editor ----------

// Add a key-value row (optionally pre-filled)
function addKvRow(key, value) {
  const wrap = $('dsKvRows');
  const row = document.createElement('div');
  row.className = 'ds-kv-row';
  row.innerHTML =
    `<input class="ds-kv-key" type="text" placeholder="key" value="${esc(key || '')}" style="font-family:ui-monospace,monospace">` +
    `<input class="ds-kv-val" type="text" placeholder="value" value="${esc(value || '')}" style="font-family:ui-monospace,monospace">` +
    `<button class="ds-kv-del" type="button" onclick="removeKvRow(this)" title="${t('del')}">${icon('x', 13)}</button>`;
  wrap.appendChild(row);
}

// Delete a row
function removeKvRow(btn) {
  btn.closest('.ds-kv-row').remove();
}

// Clear and refill rows from the given dict (used when backfilling on edit)
function renderKvRows(dict) {
  const wrap = $('dsKvRows');
  wrap.innerHTML = '';
  Object.keys(dict || {}).forEach(k => addKvRow(k, dict[k]));
  if (!Object.keys(dict || {}).length) addKvRow('', ''); // ensure at least one row
}

// Collect key-values from all rows (rows with an empty key are skipped)
function collectKvRows() {
  const out = {};
  document.querySelectorAll('#dsKvRows .ds-kv-row').forEach(row => {
    const key = row.querySelector('.ds-kv-key').value.trim();
    const val = row.querySelector('.ds-kv-val').value.trim();
    if (key) out[key] = val;
  });
  return out;
}

async function saveDataset() {
  const id = $('dsId').value;
  const path = $('dsPath').value.trim();
  const name = $('dsName').value.trim();
  if (!path) { showError(t('pathRequired')); return; }

  // Merge: four form fields + advanced kv rows.
  // endpoint/region/access_key_id stored unprefixed; secret key name depends on storage type.
  const isOss = $('dsStoreType').value === 'oss';
  const skKey = isOss ? 'access_key_secret' : 'secret_access_key';
  const options = {};
  const ak = $('dsAk').value.trim();
  const sk = $('dsSk').value.trim();
  const ep = $('dsEndpoint').value.trim();
  const rg = $('dsRegion').value.trim();
  if (ak) options.access_key_id = ak;
  if (sk) options[skKey] = sk;
  if (ep) options.endpoint = ep;
  if (rg) options.region = rg;
  Object.assign(options, collectKvRows());

  const method = id ? 'PUT' : 'POST';
  const url = id ? `/api/datasets?id=${id}` : '/api/datasets';
  const r = await fetch(url, { method, headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, name, options }) });
  const ds = await r.json();
  if (ds.error) { showError(ds.error); return; }
  toggleDsModal(false);
  await refreshDatasets();
  selectDataset(ds.id);
}

async function loadCurrentTab() {
  showError(null);
  showLoading(true);
  $('view').innerHTML = '';
  try {
    let data;
    if (activeTab === 'tree') data = await fetchAPI('tree');
    else if (activeTab === 'schema') data = await fetchAPI('schema');
    else if (activeTab === 'index') data = await fetchAPI('index');
    else if (activeTab === 'diff') { loadVersionDiffUI(); return; }
    else if (activeTab === 'storage') data = await fetchAPI('storage');
    else if (activeTab === 'health') data = await fetchAPI('health');
    else if (activeTab === 'timeline') data = await fetchAPI('transactions');
    else {
      // Data tab: refs (branches/versions/tags) ride along with the row data, so the dataset is
      // opened once on the server instead of once for /api/refs and again for /api/dataset.
      const params = { limit: dataPageSize, offset: dataPage * dataPageSize, refs: 1 };
      if (curSnapshotVersion != null) params.version = curSnapshotVersion;
      data = await fetchAPI('dataset', params);
      if (applyRefs(data.refs)) {
        // The requested snapshot is gone; the dataset call may have already failed on it. Retry at
        // the latest version so the tab recovers instead of showing a stale-version error.
        const retry = { limit: dataPageSize, offset: dataPage * dataPageSize, refs: 1 };
        data = await fetchAPI('dataset', retry);
        applyRefs(data.refs);
      }
    }
    showLoading(false);
    if (data.error) { showError(data.error); return; }
    if (activeTab === 'tree') renderTree(data);
    else if (activeTab === 'schema') renderSchema(data);
    else if (activeTab === 'index') renderIndex(data);
    else if (activeTab === 'storage') renderStorage(data);
    else if (activeTab === 'health') renderHealth(data);
    else if (activeTab === 'timeline') renderTimeline(data);
    else renderData(data);
  } catch (e) {
    showLoading(false);
    showError(t('requestFailed', { err: e }));
  }
}

// Tab switching
document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    activeTab = t.dataset.tab;
    // Leaving the data tab no longer resets the page: switching to Schema and back should return you
    // to the rows you were reading. Row count only changes with the dataset/version, and those
    // paths reset the page themselves.
    if (currentPath) loadCurrentTab();
    else $('view').innerHTML = '<div class="empty">' + t('selectFromSidebar') + '</div>';
  });
});

$('dsAdd').addEventListener('click', openAddDsModal);
$('dsCancel').addEventListener('click', () => toggleDsModal(false));
$('dsSave').addEventListener('click', saveDataset);
$('dsKvAdd').addEventListener('click', () => addKvRow('', ''));
$('dsPath').addEventListener('keydown', e => { if (e.key === 'Enter') saveDataset(); });
$('dsStoreType').addEventListener('change', applyStoreType);
// Close modal when clicking outside
document.addEventListener('keydown', e => { if (e.key === 'Escape') toggleDsModal(false); });

// Boot: load the dataset list, default to the most recently accessed one
(async () => {
  await refreshDatasets();
  if (datasets.length) {
    selectDataset(datasets[0].id);
  }
  // With no history: the right pane shows the empty state, guiding to add from the sidebar
})();

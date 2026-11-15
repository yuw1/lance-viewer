// Lance Viewer - core utilities and global state
// Deps: none. Loaded first.

const $ = id => document.getElementById(id);
const TABS = ['tree', 'schema', 'index', 'diff', 'storage', 'health', 'timeline', 'data'];
let currentPath = '';

// ---------- i18n ----------
// Simple dictionary-based i18n: t(key) returns the string in the current language.
const I18N = {
  zh: {
    appSubtitle: 'Lance 数据集浏览器',
    dsTitle: '数据集',
    dsAdd: '添加',
    tab_tree: '文件树',
    tab_schema: '表结构',
    tab_index: '索引',
    tab_diff: '版本对比',
    tab_storage: '存储分析',
    tab_health: '健康检查',
    tab_timeline: '事务时间线',
    tab_data: '文件内容',
    loading: '正在读取…',
    dsModalAdd: '添加数据集',
    dsModalEdit: '编辑数据集',
    dsNameLabel: '数据集名称',
    dsNameOpt: '(可选，留空自动取路径末段)',
    dsPathLabel: '数据集路径',
    dsStorageTitle: '连接参数（对象存储用）',
    dsAdvToggle: '高级：额外连接参数（可选）',
    dsKvAdd: '添加参数',
    save: '保存',
    cancel: '取消',
    selectDataset: '从左侧选择一个数据集',
    noDatasets: '还没有数据集<br>在上方输入路径加载，或点「添加」',
    footer: 'Lance Viewer · pylance 驱动',
    totalRows: '总行数',
    shown: '已显示',
    versions: '版本数',
    cols: '列数',
    pageInfo: '共 {total} 行 · 第 {cur}/{pages} 页',
    colsShow: '点击隐藏此列',
    colsHide: '点击显示此列',
    colsShown: '已选 {n}/{total} 列',
    colsAll: '全选',
    prev: '‹ 上一页',
    next: '下一页 ›',
    pageSize: '每页',
    firstPage: '首页',
    lastPage: '末页',
    jumpTo: '跳至',
    pageUnit: '页',
    jump: '跳转',
    vecExpand: '{dims}d 向量 · 点击展开',
    vecDims: '[{dims} dims]',
    vecNorm: '范数',
    vecSparsity: '稀疏度',
    vecMin: 'min',
    vecMax: 'max',
    vecMean: '均值',
    vecPosRatio: '正值占比',
    vecNormed: '已归一化',
    vecNotNormed: '未归一化',
    itemCount: '{n} 项',
    selectOne: '请选择一个数据集',
    selectFromSidebar: '从左侧选择一个数据集',
    confirmDelete: '删除数据集「{name}」？\n{path}',
    requestFailed: '请求失败: {err}',
    pathRequired: '请输入数据集路径',
    edit: '编辑',
    del: '删除',
    // tree
    colName: '名称',
    colSize: '大小',
    colMtime: '修改时间',
    itemCount: '{n} 项',
    openDatafile: '点击查看 Lance 文件内部结构 (footer/页/编码)',
    openManifest: '点击查看 protobuf 格式化的 manifest 内容',
    openTxn: '点击查看 transaction 内容',
    openArrow: '点击查看删除文件内容 (Arrow IPC, 被删行 ID)',
    openJson: '点击查看 JSON 内容',
    // index file labels
    labelIdxMain: '向量索引主文件',
    labelIdxAux: '向量索引辅助',
    labelTokenDict: 'token 词典',
    labelInvertList: '倒排表',
    labelDocMap: '文档映射',
    labelIdxMeta: '索引元数据',
    labelPageLookup: '页查找表',
    labelPageData: '页数据',
    // schema
    colField: '列名',
    colType: '类型',
    nullable: 'Nullable',
    yesNullable: '可空',
    noNullable: '非空',
    // index overview
    idxCount: '索引数',
    idxIndexedRows: '已索引行',
    idxNone: '此数据集没有任何索引',
    idxOverview: '索引总览',
    colName2: '名称',
    colType2: '类型',
    colField2: '字段',
    idxRows: '索引行',
    unidxRows: '未索引行',
    colMetric: '指标',
    colValue: '值',
    idxUnindexedFrag: '未索引 fragments',
    idxSegments: '分段数',
    idxUpdated: '更新时间',
    idxIndexedFrag: '索引 fragments',
    idxCentroids: '{n} 个质心 × dim {dim}',
    idxFolded: '折叠',
    idxKeys: '{n} 键',
    invDetail: '倒排索引详情',
    tokenCount: 'token 数',
    docCount: '文档数',
    tokenParams: '分词参数',
    btreeDetail: 'BTree 详情',
    vecDetail: '向量索引详情',
    vecDim: '维度',
    numPartitions: '分区数',
    idxFileVersion: '索引文件版本',
    vecCentroids: '分区质心',
    bfDetail: 'BloomFilter',
    bfDesc: 'BloomFilter 索引',
    // diff
    compare: '对比',
    diffRows: '行数 (v{from}→v{to})',
    diffDataFiles: 'Data Files',
    diffFragments: 'Fragments',
    diffTombstones: '墓碑 (删除文件)',
    diffSize: '大小变化',
    schemaDiff: 'Schema 差异',
    schemaNoChange: 'Schema 无变化',
    added: '新增',
    removed: '移除',
    typeChanged: '类型变化',
    indexDiff: '索引差异',
    indexNoChange: '索引无变化',
    verTimeline: '版本时间线 (v{from} → v{to})',
    colVersion2: '版本',
    colTime: '时间',
    colRows: '行数',
    tombstoneCount: '{n} 个墓碑 · 累计 {m} 条',
    noTombstone: '无墓碑',
    noVersions: '无版本可对比',
    colChange: '变化',
    colIndex: '索引',
    // storage
    totalSize: '总大小',
    dataFileCount: '数据文件',
    storageTypes: '存储类型分布',
    colType3: '类型',
    colCount: '文件数',
    colPct: '占比',
    colStorage: '存储大小',
    colCompress: '压缩',
    colPages: '页数',
    colFile: '文件',
    notCompressed: '未压缩',
    colLevelStorage: '数据文件列级存储',
    storageTopN: '仅分析最大的 {n} 个数据文件（共 {total} 个）',
    topFiles: '占用空间最大的文件',
    // timeline
    txnTimeline: '事务时间线 ({n} 个操作)',
    noTxns: '此数据集没有任何事务记录',
    timelineWindow: '显示最近 {n} / 共 {total} 个事务',
    loadEarlier: '加载更早的事务',
    colOp: '操作',
    colReadVersion: 'read_version',
    op_append: '追加',
    op_delete: '删除',
    op_overwrite: '覆盖',
    op_create_index: '建索引',
    op_rewrite: '重写',
    op_merge: '合并',
    op_project: '投影',
    op_restore: '恢复',
    op_update: '更新',
    op_update_config: '配置更新',
    op_data_replacement: '数据替换',
    op_clone: '克隆',
    op_reserve_fragments: '保留分区',
    op_data_overlay: '覆盖层',
    op_unknown: '未知',
    // health
    healthDiagnosis: '诊断',
    healthOk: '没有发现明显问题',
    healthFormat: '存储格式',
    healthFragments: 'fragments',
    healthDataFiles: '数据文件',
    healthSize: '占用空间',
    healthDeletedRows: '已删除行',
    healthFragmentSizes: 'Fragment 行数',
    healthMin: '最小',
    healthMedian: '中位数',
    healthMax: '最大',
    healthCoverage: '列与索引覆盖',
    healthNoIndex: '无索引',
    issue_empty: '数据集为空',
    issue_tombstones: '{rows} 行已标记删除（{pct}%），compact 可以回收',
    issue_small_fragments: '{n}/{total} 个 fragment 小于 {threshold} 行',
    issue_fragment_skew: 'fragment 大小不均：最大约为中位数的 {ratio} 倍',
    issue_version_churn: '{versions} 个版本累计写入约 {ratio} 倍当前行数，历史版本占用较大',
    issue_no_vector_index: '向量列 {field} 没有索引',
    // refs bar / data
    branchLabel: '分支',
    versionLabel: '版本/标签',
    snapshotViewing: '当前查看 v{ver} 快照',
    versionsTrimmed: '仅显示最近 {n} / 共 {total} 个版本',
    versionJumpPlaceholder: '版本号',
    versionJumpGo: '跳转',
    versionNotFound: '没有 v{v} 这个版本',
    jsonShowMore: '显示更多 {n} 个（共 {total} 个）',
    emptyDataset: '数据集为空',
    clickExpand: '点击展开',
    // data tab: row filter + column stats
    filterPlaceholder: 'SQL 过滤条件，如 id > 100',
    filterApply: '过滤',
    filterClear: '清除',
    filterScope: '当前过滤：{expr}',
    filterNoRows: '没有满足过滤条件的行',
    // index explain (files.js)
    explainTitle: '{title}',
    field_vector_id: 'HNSW 图节点 ID',
    field_neighbors: '节点的邻居列表 (HNSW 边)',
    field_distance: '邻居的距离 (HNSW 权重)',
    field_rowid: '行 ID（row id 映射）',
    field_flat: '向量质心（IVF 分区中心）',
    field_item: '嵌套列表元素',
    field_token: '索引 token（词典）',
    field_doc_id: '文档 ID（倒排索引）',
    field_term_frequency: '词频（倒排索引）',
    idxTitle_tokens: 'token 词典（倒排索引）',
    idxDesc_tokens: '这个文件存的是分词后的 token 词典——倒排索引的词条。',
    idxTitle_invert: '倒排表（inverted list）',
    idxDesc_invert: '这是倒排索引的核心文件。它不是单列文件，而是用多个列共同描述"每个 token 映射到哪些文档"：· _posting 存每个 token 的文档列表（二进制压缩）；· _max_score 存该 posting 的最大 BM25 评分；· _length 存文档长度；· _impacts 存影响度。所以一个倒排索引文件有多个列——它们共同构成倒排表的物理存储，列本身以 MiniBlock 页编码。',
    idxTitle_docs: '文档映射（docs）',
    idxDesc_docs: '这个文件存文档 ID 与行 ID 的映射关系。',
    idxTitle_btree: 'BTree 标量索引',
    idxDesc_btree: '这是 BTree 标量索引文件。page_data 存索引节点的数据，page_lookup 存查找表。',
    idxTitle_index: '向量索引主文件（IVF + HNSW）',
    idxDesc_index: '这是向量索引的核心文件。列 __vector_id 存节点 ID，__neighbors 存 HNSW 图的邻居列表，_distance 存邻居距离。',
    idxTitle_aux: '向量索引辅助文件（IVF 质心）',
    idxDesc_aux: '这个文件存 IVF 分区的质心向量。_rowid 存行 ID，flat 存 128 维质心向量（分区中心）。',
    idxTitle_meta: '索引元数据',
    idxDesc_meta: '这个文件存索引的元数据信息（索引类型、参数等）。',
    // files.js - manifest/txn/json/arrow/datafile viewers
    decoding: '解码中…',
    fullJsonProto: '完整 JSON (protobuf 格式化)',
    unknownOp: '未知操作',
    jsonContent: 'JSON 内容',
    rowsDeleted: '{n} 行被删',
    col: '列',
    hintLatestVersionTitle: 'latest_version_hint.json',
    hintLatestVersionDesc: '这是 Lance 数据集 <span class="mono">_versions/</span> 目录下的轻量版本提示文件，记录当前指向的最新版本号。Lance 用它在快速定位最新 manifest，而不用扫描整个版本目录。真正的完整版本信息在对应版本的 <span class="mono">*.manifest</span> 文件里。',
    deletionTitle: '删除文件 (Arrow IPC)',
    deletionDesc: '这是 Lance 数据集的删除文件（deletion file），存在 <span class="mono">_deletions/</span> 目录。它用 Arrow IPC 格式记录被删除的物理行位置（<span class="mono">row_id</span>），实现墓碑式删除——数据文件不动，只在这里标记哪些行已删。读取时这些行会被跳过。文件名格式为 <span class="mono">fragment_id-read_version-id.arrow</span>：<span class="mono">fragment_id</span> 是删除目标所在的 fragment（水平分区），<span class="mono">read_version</span> 是触发这次删除所基于的版本号（读取视图），<span class="mono">id</span> 是写入时生成的随机 64 位唯一 ID（保证文件名不冲突）。例如 <span class="mono">0-2-4981651701452455612.arrow</span> = 删除 fragment <b>0</b> 的行 · 基于版本 <b>2</b> · 随机 ID <b>4981651701452455612</b>。',
    deletedRowsTitle: '删除的行 (row_id)',
    deletionEmpty: '删除文件为空（无被删行）',
    appendFrags: 'Append — 追加 Fragments ({n})',
    deleteOp: 'Delete — 删除操作',
    overwriteOp: 'Overwrite — 覆盖重写',
    noCompression: '无压缩',
    footerTitle: 'Footer (40 字节尾部结构)',
    colFieldOffset: '字段',
    colOffValue: '偏移/值',
    colSchemaTitle: '列 Schema ({n} 字段)',
    colExplain: '说明',
    colPage: '页',
    colRows: '行数',
    colBuffers: 'buffers',
    colLayout: '布局',
    colEncodingDetail: '编码细节',
    colCompression: '压缩',
    colPagesTitle: '列 & 页 ({n} 列)',
    globalBuffers: '全局 Buffers ({n})',
    fullJson: '完整 JSON',
    schemaFieldsTitle: 'Schema 字段 ({n})',
    fragsTitle: 'Fragments ({n})',
    colDataFiles: 'data files',
    colDeletionFile: 'deletion file',
    tombstoneDel: '墓碑·删{n}行',
    indicesTitle: '索引 ({n})',
    colId: 'id',
    colParentId: 'parent_id',
    colLogicalType: 'logical_type',
    colEncoding: 'encoding',
    colNullable: 'nullable',
    colName3: '列名',
  },
  en: {
    appSubtitle: 'Lance Dataset Browser',
    dsTitle: 'Datasets',
    dsAdd: 'Add',
    tab_tree: 'File Tree',
    tab_schema: 'Schema',
    tab_index: 'Index',
    tab_diff: 'Version Diff',
    tab_storage: 'Storage',
    tab_health: 'Health',
    tab_timeline: 'Timeline',
    tab_data: 'Data',
    loading: 'Loading…',
    dsModalAdd: 'Add Dataset',
    dsModalEdit: 'Edit Dataset',
    dsNameLabel: 'Dataset Name',
    dsNameOpt: '(optional, defaults to path basename)',
    dsPathLabel: 'Dataset Path',
    dsStorageTitle: 'Connection Params (object storage)',
    dsAdvToggle: 'Advanced: extra connection params (optional)',
    dsKvAdd: 'Add param',
    save: 'Save',
    cancel: 'Cancel',
    selectDataset: 'Select a dataset from the left sidebar',
    noDatasets: 'No datasets yet<br>Enter a path above to load, or click Add',
    footer: 'Lance Viewer · pylance powered',
    totalRows: 'Total Rows',
    shown: 'Shown',
    versions: 'Versions',
    cols: 'Columns',
    pageInfo: '{total} rows · Page {cur}/{pages}',
    colsShow: 'Click to hide this column',
    colsHide: 'Click to show this column',
    colsShown: '{n}/{total} columns selected',
    colsAll: 'Select all',
    prev: '‹ Prev',
    next: 'Next ›',
    pageSize: 'Rows',
    firstPage: 'First',
    lastPage: 'Last',
    jumpTo: 'Go to',
    pageUnit: 'page',
    jump: 'Go',
    vecExpand: '{dims}d vector · click to expand',
    vecDims: '[{dims} dims]',
    vecNorm: 'norm',
    vecSparsity: 'sparsity',
    vecMin: 'min',
    vecMax: 'max',
    vecMean: 'mean',
    vecPosRatio: 'pos ratio',
    vecNormed: 'normalized',
    vecNotNormed: 'not normalized',
    itemCount: '{n} items',
    selectOne: 'Select a dataset',
    selectFromSidebar: 'Select a dataset from the left sidebar',
    confirmDelete: 'Delete dataset "{name}"?\n{path}',
    requestFailed: 'Request failed: {err}',
    pathRequired: 'Please enter a dataset path',
    edit: 'Edit',
    del: 'Delete',
    // tree
    colName: 'Name',
    colSize: 'Size',
    colMtime: 'Modified',
    itemCount: '{n} items',
    openDatafile: 'Click to view Lance file internals (footer/pages/encoding)',
    openManifest: 'Click to view protobuf-formatted manifest',
    openTxn: 'Click to view transaction content',
    openArrow: 'Click to view deletion file content (Arrow IPC, deleted row IDs)',
    openJson: 'Click to view JSON content',
    // index file labels
    labelIdxMain: 'Vector index main file',
    labelIdxAux: 'Vector index auxiliary',
    labelTokenDict: 'Token dictionary',
    labelInvertList: 'Inverted list',
    labelDocMap: 'Document map',
    labelIdxMeta: 'Index metadata',
    labelPageLookup: 'Page lookup table',
    labelPageData: 'Page data',
    // schema
    colField: 'Field',
    colType: 'Type',
    nullable: 'Nullable',
    yesNullable: 'nullable',
    noNullable: 'not null',
    // index overview
    idxCount: 'Indexes',
    idxIndexedRows: 'Indexed rows',
    idxNone: 'This dataset has no indexes',
    idxOverview: 'Index Overview',
    colName2: 'Name',
    colType2: 'Type',
    colField2: 'Field',
    idxRows: 'Indexed rows',
    unidxRows: 'Unindexed rows',
    colMetric: 'Metric',
    colValue: 'Value',
    idxUnindexedFrag: 'Unindexed fragments',
    idxSegments: 'Segments',
    idxUpdated: 'Updated',
    idxIndexedFrag: 'Indexed fragments',
    idxCentroids: '{n} centroids × dim {dim}',
    idxFolded: 'folded',
    idxKeys: '{n} keys',
    invDetail: 'Inverted Index Detail',
    tokenCount: 'Tokens',
    docCount: 'Docs',
    tokenParams: 'Tokenizer Params',
    btreeDetail: 'BTree Detail',
    vecDetail: 'Vector Index Detail',
    vecDim: 'Dimension',
    numPartitions: 'Partitions',
    idxFileVersion: 'Index file version',
    vecCentroids: 'Partition Centroids',
    bfDetail: 'BloomFilter',
    bfDesc: 'BloomFilter index',
    // diff
    compare: 'Compare',
    diffRows: 'Rows (v{from}→v{to})',
    diffDataFiles: 'Data Files',
    diffFragments: 'Fragments',
    diffTombstones: 'Tombstones (deletion files)',
    diffSize: 'Size change',
    schemaDiff: 'Schema Diff',
    schemaNoChange: 'Schema unchanged',
    added: 'Added',
    removed: 'Removed',
    typeChanged: 'Type changed',
    indexDiff: 'Index Diff',
    indexNoChange: 'Indexes unchanged',
    verTimeline: 'Version Timeline (v{from} → v{to})',
    colVersion2: 'Version',
    colTime: 'Time',
    colRows: 'Rows',
    tombstoneCount: '{n} tombstones · {m} rows total',
    noTombstone: 'No tombstones',
    noVersions: 'No versions to compare',
    colChange: 'Change',
    colIndex: 'Index',
    // storage
    totalSize: 'Total size',
    dataFileCount: 'Data files',
    storageTypes: 'Storage Type Breakdown',
    colType3: 'Type',
    colCount: 'Files',
    colPct: 'Percent',
    colStorage: 'Storage size',
    colCompress: 'Compression',
    colPages: 'Pages',
    colFile: 'File',
    notCompressed: 'Not compressed',
    colLevelStorage: 'Column-level Storage',
    storageTopN: 'Analysing the largest {n} of {total} data files',
    topFiles: 'Largest Files',
    // timeline
    txnTimeline: 'Transaction Timeline ({n} ops)',
    noTxns: 'This dataset has no transaction records',
    timelineWindow: 'Showing the newest {n} of {total} transactions',
    loadEarlier: 'Load earlier transactions',
    colOp: 'Operation',
    colReadVersion: 'read_version',
    op_append: 'Append',
    op_delete: 'Delete',
    op_overwrite: 'Overwrite',
    op_create_index: 'Create index',
    op_rewrite: 'Rewrite',
    op_merge: 'Merge',
    op_project: 'Project',
    op_restore: 'Restore',
    op_update: 'Update',
    op_update_config: 'Config update',
    op_data_replacement: 'Data replacement',
    op_clone: 'Clone',
    op_reserve_fragments: 'Reserve fragments',
    op_data_overlay: 'Overlay',
    op_unknown: 'Unknown',
    // health
    healthDiagnosis: 'Diagnosis',
    healthOk: 'No obvious problems found',
    healthFormat: 'Storage format',
    healthFragments: 'Fragments',
    healthDataFiles: 'Data files',
    healthSize: 'On disk',
    healthDeletedRows: 'Deleted rows',
    healthFragmentSizes: 'Fragment rows',
    healthMin: 'Min',
    healthMedian: 'Median',
    healthMax: 'Max',
    healthCoverage: 'Columns and index coverage',
    healthNoIndex: 'No index',
    issue_empty: 'The dataset is empty',
    issue_tombstones: '{rows} rows are marked deleted ({pct}%); compact reclaims them',
    issue_small_fragments: '{n}/{total} fragments hold fewer than {threshold} rows',
    issue_fragment_skew: 'Fragments are uneven: the largest is about {ratio}x the median',
    issue_version_churn: '{versions} versions wrote about {ratio}x the current row count; history is large',
    issue_no_vector_index: 'Vector column {field} has no index',
    // refs bar / data
    branchLabel: 'Branch',
    versionLabel: 'Version/Tag',
    snapshotViewing: 'Viewing snapshot v{ver}',
    versionsTrimmed: 'Showing the newest {n} of {total} versions',
    versionJumpPlaceholder: 'version',
    versionJumpGo: 'Go',
    versionNotFound: 'There is no v{v}',
    jsonShowMore: 'Show {n} more of {total}',
    emptyDataset: 'Dataset is empty',
    clickExpand: 'Click to expand',
    // data tab: row filter + column stats
    filterPlaceholder: 'SQL filter, e.g. id > 100',
    filterApply: 'Filter',
    filterClear: 'Clear',
    filterScope: 'Filter: {expr}',
    filterNoRows: 'No rows match the filter',
    // index explain (files.js)
    explainTitle: '{title}',
    field_vector_id: 'HNSW graph node ID',
    field_neighbors: 'Node neighbor list (HNSW edges)',
    field_distance: 'Neighbor distance (HNSW weight)',
    field_rowid: 'Row ID (row id mapping)',
    field_flat: 'Vector centroid (IVF partition center)',
    field_item: 'Nested list element',
    field_token: 'Index token (dictionary)',
    field_doc_id: 'Document ID (inverted index)',
    field_term_frequency: 'Term frequency (inverted index)',
    idxTitle_tokens: 'Token Dictionary (inverted index)',
    idxDesc_tokens: 'This file stores the tokenized token dictionary — the terms of the inverted index.',
    idxTitle_invert: 'Inverted List',
    idxDesc_invert: 'This is the core file of the inverted index. It is not a single-column file; it uses multiple columns to jointly describe "which docs each token maps to": · _posting stores each token\'s doc list (binary compressed); · _max_score stores the max BM25 score of that posting; · _length stores doc length; · _impacts stores impact scores. So an inverted index file has multiple columns — they jointly form the physical storage of the inverted list, and the columns themselves are encoded as MiniBlock pages.',
    idxTitle_docs: 'Document Map (docs)',
    idxDesc_docs: 'This file stores the mapping between document IDs and row IDs.',
    idxTitle_btree: 'BTree Scalar Index',
    idxDesc_btree: 'This is a BTree scalar index file. page_data stores the index node data, page_lookup stores the lookup table.',
    idxTitle_index: 'Vector Index Main File (IVF + HNSW)',
    idxDesc_index: 'This is the core file of the vector index. Column __vector_id stores node IDs, __neighbors stores the HNSW graph neighbor lists, _distance stores neighbor distances.',
    idxTitle_aux: 'Vector Index Auxiliary File (IVF centroids)',
    idxDesc_aux: 'This file stores the IVF partition centroid vectors. _rowid stores row IDs, flat stores the 128-dim centroid vectors (partition centers).',
    idxTitle_meta: 'Index Metadata',
    idxDesc_meta: 'This file stores index metadata (index type, parameters, etc.).',
    // files.js - manifest/txn/json/arrow/datafile viewers
    decoding: 'Decoding…',
    fullJsonProto: 'Full JSON (protobuf formatted)',
    unknownOp: 'Unknown operation',
    jsonContent: 'JSON Content',
    rowsDeleted: '{n} rows deleted',
    col: 'Cols',
    hintLatestVersionTitle: 'latest_version_hint.json',
    hintLatestVersionDesc: 'This is a lightweight version-hint file in the <span class="mono">_versions/</span> directory of a Lance dataset. It records the latest version currently pointed to. Lance uses it to quickly locate the latest manifest without scanning the whole versions directory. The full version info lives in the corresponding <span class="mono">*.manifest</span> file.',
    deletionTitle: 'Deletion File (Arrow IPC)',
    deletionDesc: 'This is a Lance dataset deletion file, stored in the <span class="mono">_deletions/</span> directory. It records deleted physical row positions (<span class="mono">row_id</span>) in Arrow IPC format, implementing tombstone-style deletes — the data file stays untouched, only the deleted rows are marked here, and readers skip them. File names follow <span class="mono">fragment_id-read_version-id.arrow</span>: <span class="mono">fragment_id</span> is the target fragment (horizontal partition), <span class="mono">read_version</span> is the version the delete was based on (read view), and <span class="mono">id</span> is a random 64-bit ID generated at write time (to avoid name collisions). For example <span class="mono">0-2-4981651701452455612.arrow</span> = delete rows of fragment <b>0</b> · based on version <b>2</b> · random ID <b>4981651701452455612</b>.',
    deletedRowsTitle: 'Deleted Rows (row_id)',
    deletionEmpty: 'Deletion file is empty (no deleted rows)',
    appendFrags: 'Append — Fragments Added ({n})',
    deleteOp: 'Delete — Operation',
    overwriteOp: 'Overwrite — Rewrite',
    noCompression: 'No compression',
    footerTitle: 'Footer (40-byte trailer)',
    colFieldOffset: 'Field',
    colOffValue: 'Offset/Value',
    colSchemaTitle: 'Column Schema ({n} fields)',
    colExplain: 'Notes',
    colPage: 'Page',
    colRows: 'Rows',
    colBuffers: 'buffers',
    colLayout: 'Layout',
    colEncodingDetail: 'Encoding detail',
    colCompression: 'Compression',
    colPagesTitle: 'Columns & Pages ({n} cols)',
    globalBuffers: 'Global Buffers ({n})',
    fullJson: 'Full JSON',
    schemaFieldsTitle: 'Schema Fields ({n})',
    fragsTitle: 'Fragments ({n})',
    colDataFiles: 'data files',
    colDeletionFile: 'deletion file',
    tombstoneDel: 'tombstone · {n} rows deleted',
    indicesTitle: 'Indexes ({n})',
    colId: 'id',
    colParentId: 'parent_id',
    colLogicalType: 'logical_type',
    colEncoding: 'encoding',
    colNullable: 'nullable',
    colName3: 'Field',
  },
};

// ---------- icons ----------
// Which icon to show is a structural decision, not a translatable one, so it
// lives here (keyed by the same i18n keys) instead of inside the strings.
const ICON_BY_KEY = {
  // sidebar / tabs
  dsTitle: 'database',
  dsAdd: 'plus',
  dsKvAdd: 'plus',
  dsModalAdd: 'plus',
  dsModalEdit: 'pencil',
  dsStorageTitle: 'key-round',
  dsAdvToggle: 'settings-2',
  tab_tree: 'folder-tree',
  tab_schema: 'table-properties',
  tab_index: 'scan-search',
  tab_diff: 'git-compare',
  tab_storage: 'hard-drive',
  tab_health: 'list-checks',
  tab_timeline: 'history',
  tab_data: 'table',
  // booleans
  yesNullable: 'check',
  noNullable: 'x',
  // index tab
  idxOverview: 'list-checks',
  invDetail: 'archive',
  tokenParams: 'settings-2',
  btreeDetail: 'trees',
  vecDetail: 'brain',
  vecCentroids: 'crosshair',
  bfDetail: 'target',
  // diff / storage / timeline sections
  schemaDiff: 'table-properties',
  indexDiff: 'scan-search',
  verTimeline: 'chart-line',
  storageTypes: 'chart-pie',
  colLevelStorage: 'columns-3',
  topFiles: 'trophy',
  txnTimeline: 'chart-line',
  // refs bar
  branchLabel: 'git-branch',
  versionLabel: 'tag',
  // file / index explain panels
  explainTitle: 'lightbulb',
  idxTitle_tokens: 'library',
  idxTitle_invert: 'link-2',
  idxTitle_docs: 'file-text',
  idxTitle_btree: 'trees',
  idxTitle_index: 'brain',
  idxTitle_aux: 'crosshair',
  idxTitle_meta: 'clipboard-list',
  hintLatestVersionTitle: 'lightbulb',
  deletionTitle: 'trash-2',
  deletedRowsTitle: 'clipboard-list',
  appendFrags: 'download',
  deleteOp: 'trash-2',
  overwriteOp: 'refresh-cw',
  footerTitle: 'map-pin',
  // datafile sections
  colSchemaTitle: 'clipboard-list',
  colPagesTitle: 'columns-3',
  globalBuffers: 'package',
  schemaFieldsTitle: 'list',
  fragsTitle: 'boxes',
  indicesTitle: 'scan-search',
  fullJsonProto: 'braces',
  fullJson: 'braces',
};

// HTML-escape (kept local so tools.js stays loadable before files.js).
function escHtml(s) {
  return String(s).replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// Translated label prefixed by its icon; returns HTML.
function ti(key, params, size) {
  const label = t(key, params);
  const ic = ICON_BY_KEY[key];
  return ic ? icon(ic, size || 16) + ' ' + label : label;
}

// current language: 'zh' or 'en' (persisted); default to English on first open
let currentLang = localStorage.getItem('lv_lang') || 'en';

function t(key, params) {
  let s = (I18N[currentLang] && I18N[currentLang][key]) || (I18N.zh[key] || key);
  if (params) {
    for (const k in params) s = s.replace('{' + k + '}', params[k]);
  }
  return s;
}

function setLang(lang) {
  currentLang = lang === 'en' ? 'en' : 'zh';
  localStorage.setItem('lv_lang', currentLang);
  applyStaticI18n();
  document.documentElement.lang = currentLang === 'en' ? 'en' : 'zh-CN';
  const btn = $('langToggle');
  if (btn) btn.textContent = currentLang === 'en' ? '中文' : 'English';
}

function toggleLang() { setLang(currentLang === 'en' ? 'zh' : 'en'); }

// Translate static HTML elements that carry data-i18n attributes.
function applyStaticI18n() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    const ic = el.getAttribute('data-icon') || ICON_BY_KEY[key];
    // data-icon="none" opts an element out of the automatic icon.
    const prefix = (ic && ic !== 'none') ? icon(ic, 16) + ' ' : '';
    el.innerHTML = prefix + escHtml(t(key));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.setAttribute('title', t(el.getAttribute('data-i18n-title')));
  });
}

function showLoading(on) { $('loading').style.display = on ? 'block' : 'none'; }
function showError(msg) {
  if (!msg) { $('error').style.display = 'none'; return; }
  $('error').innerHTML = icon('circle-alert', 16) + ' ' + escHtml(msg);
  $('error').style.display = 'block';
}

function fmtSize(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b / 1024).toFixed(1) + ' KB';
  return (b / 1048576).toFixed(1) + ' MB';
}

// One id per page load: the server caches open datasets per session, so tab switches reuse one
// handle and a reload (new id) starts fresh and sees the latest version.
const SESSION_ID = (() => {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return [...b].map(x => x.toString(16).padStart(2, '0')).join('');
})();

async function fetchAPI(endpoint, params) {
  // Repeated keys for arrays (cols=a&cols=b): URLSearchParams would otherwise join them with a
  // comma, which a column name could contain.
  const qs = new URLSearchParams({ path: currentPath });
  for (const [k, v] of Object.entries(params || {})) {
    if (Array.isArray(v)) v.forEach(x => qs.append(k, x));
    else if (v != null) qs.set(k, v);
  }
  const r = await fetch(`/api/${endpoint}?` + qs.toString(), {
    headers: { 'X-Lance-Session': SESSION_ID },
  });
  return r.json();
}

// Liveness for the server-side dataset cache. The server releases a session after 90s without a
// ping (browsers throttle background-tab timers to ~60s, so the window must be a few beats wide),
// and after 2 minutes without a real API request. pagehide releases immediately on close/reload.
const HEARTBEAT_MS = 20000;

function pingServer(bye) {
  const qs = `?sid=${encodeURIComponent(SESSION_ID)}` + (bye ? '&bye=1' : '');
  // sendBeacon survives page unload, where fetch() would be cancelled.
  if (bye && navigator.sendBeacon) {
    // sendBeacon cannot set headers, so the id travels in the query string here.
    navigator.sendBeacon('/api/heartbeat' + qs);
    return;
  }
  fetch('/api/heartbeat' + qs, {
    method: 'POST',
    headers: { 'X-Lance-Session': SESSION_ID },
    keepalive: bye,
  }).catch(() => {});  // a missed ping only costs an extra reopen later
}

setInterval(() => pingServer(false), HEARTBEAT_MS);
window.addEventListener('pagehide', () => pingServer(true));

// Apply persisted language on load
setLang(currentLang);

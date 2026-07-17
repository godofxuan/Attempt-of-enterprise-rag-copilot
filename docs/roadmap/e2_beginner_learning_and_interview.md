# E2 Parser 与索引生命周期：初学者代码地图和面试问答

最后更新：2026-07-16

这份文档回答三个问题：E2 到底做了什么；代码分别在哪里；面试时怎样用自己的话解释。它不是“已掌握证明”。只有完成第 8 节的动手实验并能脱离文档复述，才适合把相关能力写进简历。

## 1. 先用一句话理解 E2

E1 造出了受控的企业文档和评估题。E2 把这些文件变成带权限、版本和来源信息的 chunks，再把索引作为可校验、可切换、可回滚的版本产物管理起来。

```text
文件 + corpus manifest
-> Parser Registry
-> ParseResult
-> DocumentRecord
-> 去重和版本治理
-> ChunkRecord
-> BM25 tokens + FAISS vectors
-> IndexManifest
-> versions/<run-id>
-> active.json
```

旧项目只有“读取 md/txt -> 四字段 dict -> 原地覆盖三个索引文件”。新流程多出来的不是装饰，而是回答企业工程中的四个问题：

1. 这份文本来自哪一页、哪一行、哪张表？
2. 这个用户是否有权看到它，它属于哪个版本和制度？
3. 当前索引由哪批语料、parser、chunk config 和 embedding 生成？
4. 新构建失败时，怎样保证旧索引仍可用？

## 2. 文件地图

| 层 | 主要文件 | 它负责什么 |
|---|---|---|
| Domain | `app/domain/documents.py` | 定义 ParseResult、DocumentRecord、ChunkRecord 和结构化错误 |
| Parser | `app/ingestion/parsers.py`、`parsers_pdf.py`、`parsers_docx.py` | 把七种文件变成 section/table/locator，不处理企业治理 |
| Normalizer | `app/ingestion/normalize.py` | 合并 parser 结果与 corpus manifest，校验路径/hash/字节数 |
| Chunker | `app/ingestion/chunking.py` | fixed、heading、parent-child、table chunks 和稳定 ID |
| Governance | `app/ingestion/versions.py` | 安全域内去重、canonical/alias、版本图校验 |
| Manifest | `app/indexing/manifest.py` | 定义索引 provenance、计数和 artifact hash contract |
| Builder | `app/indexing/builder.py` | 生成 JSON/BM25/FAISS，写后重新打开验证 |
| Store | `app/indexing/store.py` | staging、版本目录、active pointer、rollback、force 边界 |
| CLI | `scripts/build_indexes_v2.py` | dry-run、build+activate、activate-existing 三条操作路径 |
| Adapter | `app/retriever.py` 中 `load_v2_indexes()` | 显式加载 v2，暂不改变 legacy hybrid_search 默认 |
| Experiment | `scripts/eval_chunking_ablation.py` | 在 dev 上隔离比较三种 chunking 的 BM25 文档召回 |
| Tests | `tests/ingestion/`、`tests/indexing/` | 77 个 E2 测试，覆盖失败和成功路径 |

## 3. 一步一步读代码

### 3.1 Parser 为什么不直接返回最终 chunk

`ParserRegistry.parse(path)` 只关心文件结构。例如 PDF 的 page、DOCX 的 paragraph/table、CSV 的 row。它不知道 tenant、ACL、制度版本，因为这些不是文件格式知识，而是企业治理知识。

如果 parser 同时做治理，未来同一个 DOCX parser 会被迫知道每个公司的权限模型，职责会混乱。现在的边界是：

```text
parser input:  文件 bytes
parser output: ParseResult(text, sections, tables, warnings)

normalizer input: ParseResult + ManifestDocument
normalizer output: DocumentRecord
```

`DocumentParseError` 保存 `code/path/parser/message`。CLI 和测试可以读取字段，不必解析异常字符串。

### 3.2 Normalizer 为什么再次检查 hash

manifest 声明了相对路径、SHA256 和 byte count。`ingest_corpus()` 在 parse 前重新读取 bytes 并核对：

```text
manifest 写的是 documents/a.md
-> resolve 后必须仍在 corpus root 内
-> 实际 byte_count 必须相同
-> 实际 SHA256 必须相同
-> 才交给 parser
```

这可以发现路径穿越、文件被替换和生成后被手改。SHA256 不是加密文档内容，而是给当前产物做完整性指纹。

### 3.3 DocumentRecord 与 ChunkRecord 的区别

`DocumentRecord` 表示一整份规范化文档，保存 title、完整 text、sections/tables、tenant、region、ACL、policy/version、authority 和 parser provenance。

`ChunkRecord` 表示可检索单元。它继承必要治理字段，并增加：

- `chunk_id`：稳定标识；
- `kind`：fixed/section/parent/child/table；
- `indexable`：parent 只用于展开，不直接进入向量/BM25；
- `parent_chunk_id`：child 找回后可扩展上下文；
- `locator/section_path`：引用可以回到原文位置。

权限字段必须复制到 chunk，因为检索阶段处理的是 chunk。如果只有 DocumentRecord 有 ACL，候选 chunk 在过滤前可能已经进入融合、trace 或 prompt。

### 3.4 三种 chunking 是什么

`fixed`：把整篇 normalized text 按字符窗口切分。优点是简单、chunk 少；缺点是可能跨标题或把无关段落混在一起。

`heading`：每个 section 独立切，不跨 section。优点是语义更集中；缺点是 chunk 数增加，表格结构和跨章节信息仍需额外处理。

`parent_child`：大 parent 保存完整上下文但 `indexable=false`，小 child 负责检索。找到 child 后，E3 可以通过 `parent_chunk_id` 打开 parent。优点是兼顾匹配精度和回答上下文；代价是对象和索引数量更多，而且没有 parent expansion 时只完成了一半。

chunk ID 的 hash 输入包括 doc ID、完整 chunk config、kind、section、locator、ordinal、text hash 和 parent ID，不包括绝对路径和 ingestion 时间。因此同一输入重复构建 ID 稳定，改了 chunk config 或文本后 ID 会变化。

### 3.5 为什么去重不能只比较文本

假设 HR 文档与公开文档文本完全相同，但 ACL 不同。如果只按文本 hash 去重，公开用户可能通过 canonical alias 指到 HR 文档，造成安全边界混乱。

所以 `govern_documents()` 先按下面的安全域分桶：

```text
tenant + region + sorted ACL + policy + version + filed department
```

只在同一桶内比较 source checksum 和 normalized text hash。canonical 选择还考虑 variant precedence，避免 `duplicate_*` 因字母序成为主记录。版本图只把 authoritative 文档当正式制度，检查 supersedes target、cycle、effective overlap 和 active head 数量。

### 3.6 IndexManifest 为什么重要

“目录里有 faiss.index”不能证明它与 chunks/BM25 属于同一批。`IndexManifest` 保存：

- corpus manifest SHA256；
- embedding model、dimension、normalization；
- FAISS/BM25 参数；
- chunker config 和 parser versions；
- source/canonical/duplicate/chunk counts；
- build 起止时间；
- 每个 artifact 的 path、byte count、SHA256。

`validate_index_directory()` 重新打开所有文件，检查 JSON/pickle 数量、FAISS `ntotal/dimension` 和 hashes。manifest 是可验证合同，不只是日志。

### 3.7 fake embedder 在测试里做什么

fake embedder 根据文本稳定返回固定维度数字。它不测试语义质量，只测试：

- 每个 indexable chunk 是否恰好 embedding 一次；
- 向量维度是否一致；
- FAISS 行数是否等于 chunks/BM25 行数；
- dry-run 是否完全不 embedding；
- embedding 中途失败是否不留下正式版本。

如果这些生命周期测试依赖 Ollama，测试会慢、受模型和网络状态影响，也无法稳定构造“第二个向量维度错误”之类的故障。

### 3.8 active.json 为什么能回滚

目录结构：

```text
indexes_v2/
  active.json
  versions/
    run-one/
    run-two/
```

构建 run-two 不删除 run-one。`activate_version()` 先完整验证 run-two，再在 index root 内写一个完整临时 pointer，`flush + fsync` 后用 `os.replace()` 替换 active.json。

rollback 就是：

```python
activate_version(root, "run-one")
```

它不重新 parse、chunk 或 embedding。当前 active run 不能被 `--force` 原地覆盖，否则进程可能在“目录已换、pointer 未换”时崩溃，使旧 pointer hash 失效。

### 3.9 为什么 E2 没让 hybrid_search 自动读 v2

E2 只新增 `load_v2_indexes(root)`。旧 `hybrid_search()` 仍调用 `load_indexes()`。

原因是 v2 chunks 已带 ACL/version metadata，但 production retrieval 还没有 E3 的 pre-filter、authority/current ranking、query decomposition 和 EvidenceLedger。如果此时直接切换，失败时无法区分是 parser、chunking、索引还是 retrieval policy 导致。

## 4. C09 实验怎么读

18 道 answered dev，BM25/jieba，ACL filter，unique document top-5：

| mode | indexable chunks | Recall@5 | MRR@5 | failures |
|---|---:|---:|---:|---:|
| fixed | 64 | 0.8333 | 0.3769 | 5 |
| heading | 112 | 0.8611 | 0.5157 | 4 |
| parent-child | 131 | 0.8611 | 0.5898 | 4 |

不能只说“parent-child 最好”。正确解释是：

1. heading/parent-child 对 fact/completeness 排名更好，并修复一题 fixed miss。
2. 三者所有 comparison 都没有完整召回两份 gold。
3. parent-child 总对象 243，成本明显增加。
4. 这是 synthetic dev、BM25-only、18 题，不是 dense/answer/Agent 或线上结论。
5. 当前不改默认，E3 加 metadata 和 query decomposition 后再做端到端 admission。

## 5. 面试常见问题与参考答案

### Q1：为什么 parser 不用 LLM

文件格式解析需要可复现的 page/row/paragraph locator 和明确错误。确定性库更便宜、稳定、可测试。LLM 可以在后续做语义理解，但不应替代基础字节、结构和完整性校验。

### Q2：PDF 支持到什么程度

使用 pypdf 提取文本并保留 page locator。空页给 warning，全空文档 fail closed。它不做 OCR，因此扫描件或图片型 PDF 不能宣传为已支持；OCR 是后续扩展。

### Q3：为什么要把 parser 与 normalizer 分开

parser 负责格式结构，normalizer 负责企业 metadata 和 provenance。这样 parser 可复用，治理规则也不会散落在七种格式实现中。

### Q4：稳定 chunk ID 有什么价值

可比较两次构建、关联 citation/eval failure、判断 chunk 是否真的变化。ID 依赖内容和 config，不依赖机器绝对路径或构建时间，所以跨机器可复现。

### Q5：为什么去重键包含 ACL 和版本

相同文本不代表相同安全身份和业务时效。跨 ACL 去重可能泄漏，跨版本去重会丢失历史与 current/retired 关系。因此先限定安全与版本域，再比内容。

### Q6：为什么 manifest 要保存 artifact hash

防止 FAISS、BM25 和 chunks 来自不同构建，或文件在构建后被改动。loader 先验证 manifest 和 hashes，再反序列化 pickle/FAISS，减少加载不可信或错配产物的风险。

### Q7：原子替换 active.json 就完全安全吗

不完全。它只保证 pointer 文件不会被读到半截。还要保证版本目录不可变，所以当前 active run 不允许 force 原地覆盖。两条约束一起才能避免 pointer hash 指向变化中的目录。

### Q8：为什么构建失败不会破坏旧索引

新版本先在 sibling staging 中生成和复检。失败时删除 staging；成功后才 rename 为正式 version；最后才原子切 active pointer。任何前序失败都不修改旧 pointer。

### Q9：为什么测试不用真实 bge-m3

生命周期测试要控制调用次数、错误位置和向量维度，fake embedder 更适合。真实模型属于单独的 live integration/evaluation，不能让单元测试依赖本机 Ollama 状态。

### Q10：为什么 BM25 消融不加入 dense

目标是隔离 chunking。加入 dense 会同时引入模型、维度、服务状态和向量相似度变量。BM25-only 先给低成本、可复现的方向证据，后续仍需 dense 和端到端验证。

### Q11：为什么 parent-child MRR 最高却不切默认

它只在 18 道 synthetic dev 上提高 MRR，Recall 与 heading 相同，comparison 还低于 fixed，并增加索引和对象成本。没有端到端 parent expansion 与多查询证据时，自动切换属于过度结论。

### Q12：E2 后最需要做什么

E3 要让 retrieval 真正消费 UserContext、ACL、current/authority metadata，提供 search/find/open 和 EvidenceLedger，并对 comparison 做受控 query decomposition。然后重新跑 retrieval/security/Agent 分层评估。

## 6. 可以写进项目介绍的内容

可以说：

- 实现七格式 deterministic parser registry 和结构化 provenance；
- 建立包含 ACL/version/authority 的 DocumentRecord/ChunkRecord；
- 实现安全域内 dedup、版本图校验和稳定 chunk IDs；
- 实现带 artifact hash 的 versioned full rebuild、validated activation 和 rollback；
- 用 77 个 E2 tests 和 18-case dev ablation 验证生命周期与 chunking 取舍。

暂时不能说：

- 支持扫描 PDF OCR；
- 支持增量 upsert/delete；
- v2 已在 production query 中启用；
- ACL 零泄漏已经端到端证明；
- parent-child 让 Agent 答案质量显著提升；
- 这是生产规模、高并发或真实线上分布。

## 7. 常用命令

```powershell
# 只预览，不调用 Ollama、不写索引
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 `
  --input-dir data\generated\demo `
  --output-dir data\indexes_v2 `
  --profile demo --chunker fixed --dry-run

# 真实构建会调用本机 Ollama embedding
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 `
  --input-dir data\generated\demo `
  --output-dir data\indexes_v2 `
  --profile demo --run-id demo-001 --chunker fixed

# 不重建，切回已有版本
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 `
  --output-dir data\indexes_v2 `
  --activate-existing demo-001

# dev-only BM25 chunking 消融
.\.venv\Scripts\python.exe -m scripts.eval_chunking_ablation `
  --input-dir data\generated\demo --top-k 5

# E2 focused 和全仓库测试
.\.venv\Scripts\python.exe -m pytest tests\ingestion tests\indexing -q -p no:cacheprovider
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

## 8. 动手验收

不要直接在唯一索引上做破坏实验。使用临时 run 或复制目录。

1. 运行 dry-run，解释为什么 `written=false` 且 output 不存在。
2. 在 `preview_build()` 打断点，观察 72 source 如何变成 64 canonical。
3. 对比 fixed/heading/parent-child 的一个同源文档，指出 section path、parent ID 和 locator 差异。
4. 用 fake embedder 构建两个 run，打开两个 manifest，找出 corpus hash、dimension、chunk counts 和 artifact hashes。
5. 激活 run-two，再调用 `activate_version(root, "run-one")`，证明 embedding 调用数没有变化。
6. 在复制的 inactive run 中翻转 `chunks.json` 一个字节，观察 activation 被 hash mismatch 拒绝，旧 active 不变。
7. 从 C09 `details.json` 选一条 comparison failure，口述 gold、top-5、missed doc 和为什么单纯缩小 chunk 不够。
8. 不看本文，用两分钟回答：“新索引构建到上线经历哪些校验，任一步失败会发生什么？”

建议把第 8 项录音。能准确说出 staging、post-write validation、immutable version、atomic pointer 和 rollback，再把这部分列为“已掌握”。

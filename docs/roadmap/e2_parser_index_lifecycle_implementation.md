# E2 解析与索引生命周期：实时实施记录

开始日期：2026-07-16

状态：进行中；先记录基线和设计，尚未修改 parser/index 生产代码

分支/HEAD：`codex/rag-eval-system` / `7aec4b950e012d3f24b8e1877d6391201e9b8f90`

授权命令：`批准E1，执行E2解析与索引生命周期`

## 1. 先说人话

E1 已经能够生成有版本、权限、事实和 hash 的企业文档，但旧系统还只会扫描 Markdown/TXT，并把每个 chunk 保存成四字段 dict。也就是说，E1 像准备好了一批带档案袋和标签的材料，旧 ingestion 却在入口把大部分标签丢掉。

E2 要建立一条可检查的数据生产线：每种格式先通过专门 parser，统一变成 `DocumentRecord`；再用可比较的 chunker 生成稳定 `ChunkRecord`；最后在新版本目录构建索引、写 manifest、验证文件，并切换一个很小的 active pointer。任何空文本、解析错误或不合法 metadata 都不能进入索引。

## 2. 改前真实状态

### 2.1 旧数据流

```text
data/raw_docs/*.md + *.txt
-> read_text_file(path)
-> chunk_text(text, source)
-> dict{chunk_id, source, section, text}
-> 每个 chunk 调 Ollama bge-m3
-> 直接覆盖 data/indexes/faiss.index
-> 直接覆盖 chunks.json / bm25_tokens.pkl
```

### 2.2 已观察问题

- `app/retriever.py:build_indexes()` 只 glob `.md/.txt`。
- `app/chunker.py` 只识别 Markdown `#`，没有多级 section path、table locator 或 parent-child。
- chunk ID 由文件名和计数器构成；改变切块顺序会改变全部后续 ID。
- E1 manifest 的 tenant、region、ACL、版本、有效期、authority 和 fact IDs 没有进入旧 chunk。
- `scripts/build_indexes.py --help` 没有 argparse，执行脚本就直接建库。
- 三个索引文件直接写到 active 目录，中断时可能混合新旧产物。
- 没有 index manifest，无法知道索引由哪个 corpus、模型、chunker 和 parser 产生。
- 没有正式 ingestion/indexing tests；只有手动 `scripts/test_chunking.py` 等脚本。

### 2.3 可复现基线

`[REPRODUCED]` E2 开始前：

```text
E1 focused tests: 39 passed
full repository: 148 passed, 5 existing warnings
demo dry-run: 72 documents
benchmark dry-run: 600 documents
frozen test: 556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
```

## 3. 初学者术语

| 术语 | 白话解释 | E2 中的作用 |
|---|---|---|
| parser | 把某种文件读成结构化内容的代码 | PDF parser 输出每页文本和 page locator |
| registry | 后缀到 parser 的受控映射 | `.csv` 只能交给 CSV parser |
| normalization | 不同 parser 输出统一成同一模型 | 都转成 `DocumentRecord` |
| locator | 内容在原文中的位置 | page 2、paragraph 5、row 3 |
| parent-child | 小 chunk 用于召回，大 parent 用于扩展上下文 | child 保存 `parent_chunk_id` |
| dedup | 识别重复内容并选择 canonical 文档 | exact checksum / normalized hash |
| index manifest | 一次索引构建的完整身份证 | corpus hash、model、dimension、file hashes |
| staging | 在临时目录完成后再激活 | 避免半套 index 对外可见 |
| active pointer | 一个很小的文件，指出当前读取哪个版本目录 | `active.json` |
| fake embedder | 测试用的确定性向量函数 | 不启动 Ollama也能测生命周期 |

## 4. 已确定设计决策

<a id="e2-d01"></a>
### E2-D01：ParseResult 与 DocumentRecord 分层

parser 只负责文件格式，输出文本、sections、tables、locator、warnings 和 parser metadata。normalizer 再把 E1 manifest 治理字段合并成 `DocumentRecord`。

原因：文件 parser 不应该自己猜 tenant、ACL 或制度版本；这些字段来自 corpus manifest。分层后可以单独测试“解析是否保真”和“治理 metadata 是否完整”。

<a id="e2-d02"></a>
### E2-D02：两项 parser 依赖通过 gate

- PDF 使用 `pypdf>=6.14,<7`。官方 API 提供 `PdfReader(...).pages[n].extract_text()`；它不是 OCR，扫描图片页只能 warning/失败，不能静默当空文档。
- DOCX 使用 `python-docx>=1.2,<2`。1.2 的 `iter_inner_content()` 可以按文档顺序遍历 paragraph/table。
- Markdown、TXT、HTML、CSV、JSONL 使用 Python 标准库，当前 fixture 不需要 BeautifulSoup/lxml。

依赖来源：

- <https://pypdf.readthedocs.io/en/stable/user/extract-text.html>
- <https://pypi.org/project/pypdf/>
- <https://python-docx.readthedocs.io/en/latest/api/document.html>
- <https://pypi.org/project/python-docx/>

<a id="e2-d03"></a>
### E2-D03：保留三种 chunk mode，不预设新方案更好

- `fixed`：兼容旧 500/80 字符窗口，作为 baseline。
- `heading`：按 parser section 切分，超长 section 再窗口化。
- `parent_child`：section 是 parent；较小 child 用于索引，命中后可扩展 parent；table 单独按 header + row group 切分。

parent record 本身保存但默认不进入向量/BM25 索引，避免 parent/child 双重占据排名。所有 ID 由 doc ID、mode、locator、ordinal 的稳定 hash 产生。

<a id="e2-d04"></a>
### E2-D04：版本目录 + active pointer

目标布局：

```text
<output>/
├── active.json
└── versions/
    └── <run_id>/
        ├── faiss.index
        ├── chunks.json
        ├── documents.json
        ├── bm25_tokens.pkl
        └── manifest.json
```

新版本先在同父目录 staging 构建并验证，再 rename 到 `versions/<run_id>`，最后原子替换 `active.json`。旧版本保留，因此回滚只需把 active pointer 指回已验证版本，不需要重建。

<a id="e2-d05"></a>
### E2-D05：测试与 live embedding 分层

builder 接收 `embed_text: Callable[[str], list[float]]`。自动测试注入确定性 fake embedder，验证维度、FAISS 数量、hash、staging 和 active switch；CLI 实际 build 才使用现有 Ollama `_embed_text`。

`--help` 和 `--dry-run` 不调用 Ollama。这样 CI 不把本地模型当隐式依赖，也不把 fake semantic quality 宣传成真实检索效果。

<a id="e2-d06"></a>
### E2-D06：chunking 消融先做 BM25-only 可复现实验

E2 用同一 v2 dev、同一 top-k，对 fixed/heading/parent-child 做 BM25-only doc retrieval 对比。它回答“切块边界是否影响 lexical retrieval”，不会冒充 dense 或完整 Agent 结果。若新 chunker 没提升或退化，保留原数字和失败分析。

## 5. Change 列表

| ID | 行为变化 | 状态 | RED 证据 | GREEN/结果 |
|---|---|---|---|---|
| `E2-C01` | domain schema 与结构化错误 | complete | `ModuleNotFoundError: app.domain` | 6 model tests passed |
| `E2-C02` | 七格式 Parser Registry | complete | text registry missing; office suffixes unsupported | 21 ingestion tests passed |
| `E2-C03` | manifest normalization / DocumentRecord | complete | `ModuleNotFoundError: app.ingestion.normalize` | 5 normalization / 26 ingestion tests passed; demo 72/72 |
| `E2-C04` | fixed/heading/parent-child/table chunking | complete | `ModuleNotFoundError: app.ingestion.chunking` | 10 chunk tests; demo measured 72/127/274 |
| `E2-C05` | exact/normalized dedup 与版本治理 | complete | `ModuleNotFoundError: app.ingestion.versions` | 9 governance / 45 ingestion tests; demo 72 -> 64 |
| `E2-C06` | index manifest 与 deterministic builder | complete | `ModuleNotFoundError: app.indexing` | 8 manifest/builder tests passed；demo preview 72 -> 64；64 chunks/64 embedding calls |
| `E2-C07` | version store、active switch、rollback | complete | `ModuleNotFoundError: app.indexing.store`；active force test initially did not raise | 8 store / 16 indexing / 61 ingestion+indexing tests passed |
| `E2-C08` | 安全 `build_indexes_v2` CLI 与 legacy adapter | complete | CLI import missing；config/loader 3 expected failures | 9 C08 / 25 indexing / 44 focused regression tests passed；real dry-run no write |
| `E2-C09` | chunking ablation、文档与阶段验收 | complete | ablation module missing；full-suite duplicate `test_cli` module name | 7 ablation / 77 E2 / 225 full tests passed；dev experiment recorded |

## 6. 实时问题日志

| ID | 时间点 | 症状 | 当前判断 | 下一证据 |
|---|---|---|---|---|
| `E2-I01` | baseline | `.venv` 没有 pypdf/python-docx；PyMuPDF 是未声明的环境依赖 | 不能偷偷依赖本机偶然安装；按官方版本范围显式加入 | dependency install + parser fixture tests |
| `E2-I02` | dependency gate | 首次同时安装两个包 124 秒无输出且超时后遗留 pip 子进程 | pip 索引可达；子进程停留在本机代理连接。终止遗留进程后拆成单包、no-cache、有限 timeout/retry | pypdf 20.7s、python-docx/lxml 25.1s 成功；pip check clean |
| `E2-I03` | C03 regression | 新增 `filed_department` 后，旧 model test helper 先报字段缺失，遮住 timezone 断言 | production contract 正确，测试 fixture 未同步 | 只补 fixture 合法默认值；累计 ingestion 26 passed |
| `E2-I04` | C05 real-corpus audit | 1 个 duplicate variant 被选为 canonical | 初版 rank 只区分 authoritative/other，同 authority 时 `duplicate_*` 字母序早于 `support_*` | 新增正确 RED，增加 variant precedence；duplicate canonical 降为 0 |
| `E2-I05` | C06 代码写完后的会话恢复 | 对话停在 production code 已写、测试和记录尚未执行的窗口 | 不是项目异常或后台卡死，而是上下文压缩发生在两个动作之间；旧 handoff 因而落后一个动作 | 检查后台进程为 0；直接运行既有 C06 tests 得到 8 passed；随后同步 handoff |
| `E2-I06` | C07 force safety review | `--force` 可原地替换当前 active run，目录替换后、指针更新前崩溃会留下 hash 不匹配 | 原子写 `active.json` 只保护指针字节完整，不能保护被原地改写的版本目录 | 新增 RED；active run 在 embedding 前拒绝覆盖，要求新 run ID；16 indexing tests passed |
| `E2-I07` | C08 multi-file patch | 首次同时修改 config/retriever/CLI 时 context verification failed | `apply_patch` 原子拒绝整组补丁，没有半修改文件；retriever 上下文匹配粒度过大 | 核对 diff/Test-Path 后拆成三个小补丁，随后 9 C08 tests passed |
| `E2-I08` | E2 full pytest collection | corpus/indexing 都有 `test_cli.py`，局部测试通过但全量 collection 报 import file mismatch | 两个无 package namespace 的测试文件都被导入为顶层 `test_cli` | 将新文件改名 `test_index_cli.py`；双 CLI 9 passed；full 225 passed |

## 8. 实施日志

### E2-C01 RED：domain contract 尚不存在

命令：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ingestion\test_document_models.py -q -p no:cacheprovider
```

结果：collection 阶段 `ModuleNotFoundError: No module named 'app.domain'`。这是预期 RED，说明测试确实依赖新 domain boundary，而不是在验证旧 dict 行为。

本轮只实现 model 和 `DocumentParseError`；parser、normalizer、chunker 与 index 仍未开始。

### E2-C01 GREEN：统一模型可以独立拒绝坏状态

新增 `app/domain/documents.py`：

- `SourceLocator` 统一 page/line/paragraph/row 等位置；
- `ParseWarning` 区分可继续 warning 与结构化错误；
- `ParseResult` 保存 parser 原始结构；
- `DocumentVersion/DocumentRecord` 保存治理字段；
- `ChunkRecord` 保存 parent-child、ACL 和 locator；
- `DocumentParseError.to_dict()` 让 CLI/tests 不必解析异常字符串。

GREEN 命令与结果：

```text
pytest tests/ingestion/test_document_models.py
6 passed
```

为什么把 timezone 作为 validator：没有时区的 `2026-07-16 09:00` 在跨机器 provenance 中有歧义。为什么 child 必须有 parent ID：否则 parent expansion 只能靠文本猜关系。

### E2-C02 第一轮：五种标准库 parser

RED 为 `ModuleNotFoundError: app.ingestion`。随后新增显式 suffix registry 和 Markdown/TXT/HTML/CSV/JSONL parser。

关键边界：

- registry 不按内容猜格式，未知 suffix 返回 `unsupported_format`；
- UTF-8 错误返回 `decode_error`；
- JSONL 报告准确 line；
- CSV 空/重复 header 和行宽错误 fail closed；
- HTML 使用标准库并保留 heading path、paragraph 和 table；
- 空文档不能构造可索引 `ParseResult`。

GREEN：文本 parser 10 tests，累计 ingestion 16 tests。PDF/DOCX 仍未注册，因此 E2-C02 尚未完成。

### E2-C02 第二轮 RED：office parser 尚未接入

`test_parsers_office.py` 共 5 项全部失败。成功 fixture 与 malformed fixture 都先得到 `unsupported_format`，说明 registry 还没有 `.pdf/.docx` parser；这是 dependency gate 前的预期 RED。

选择范围 `pypdf>=6.14,<7`、`python-docx>=1.2,<2`，避免无上限升级跨越下一主版本。PyMuPDF 虽然当前机器偶然安装，但不在项目 requirements，因此不作为 parser 实现依赖。

### E2-I02：依赖安装为什么看起来又“停止”

第一次把两个包放在同一 pip 命令中，工具 124 秒超时且没有转发 stdout；外层结束后两个 python/pip 子进程仍存在。检查发现包没有安装，进程连接停留在本机代理 `127.0.0.1:7897`。只读 `pip index` 可以返回，说明不是完全断网。

处理：终止仅由本次超时命令产生的两个遗留进程，随后逐包执行、禁用 cache/progress/retry，并设置网络 timeout。结果：

```text
pypdf 6.14.2       installed in 20.7s
python-docx 1.2.0 installed in 25.1s
lxml 6.1.1        installed dependency
pip check         no broken requirements
```

根因边界：能确认“外层 timeout + 子进程经本机代理未完成”；无法证明代理内部具体为何未及时结束，因此不写成已确定的代理故障。

### E2-C02 GREEN：七格式 registry

新增 `parsers_pdf.py` 和 `parsers_docx.py`：

- PDF 按页调用 pypdf `extract_text()`；空页保留 `empty_page` warning 和 page locator；全空文档返回 `empty_document`，明确 OCR disabled。
- DOCX 使用 `iter_inner_content()` 保留 heading、paragraph、table 的文档顺序；Heading style 构建 section path，table 第一行作为 headers。
- malformed PDF/DOCX 被 registry 包装成带 parser/path/code 的结构化错误。

三个 synthetic binary fixtures 固定 SHA256，并在 README 声明不测试 OCR。office 5 tests、全部 ingestion 21 tests 通过。

### E2-C03：manifest normalization

RED：`ModuleNotFoundError: app.ingestion.normalize`。

实现分成三层：

```text
load_source_manifest
-> 验证 corpus/smoke schema

_confined_source_path + bytes validation
-> 相对路径必须留在 corpus root
-> SHA256/byte_count 必须匹配

registry.parse + normalize_document
-> ParseResult + ManifestDocument
-> DocumentRecord
```

发现并修正的 contract 缺口：E1 `supersedes` 保存 version ID，不能直接假装是 doc ID。`DocumentVersion` 现在同时保存 `supersedes_version_id`；只有 corpus manifest 中存在对应 authoritative document 时才补 `supersedes_doc_id`。`filed_department`、`duplicate_of` 也进入 record，避免 misfiled/duplicate 治理信息在 ingestion 消失。

GREEN：normalization 5 tests，累计 ingestion 26 tests。真实 `data/generated/demo` 得到 72 records，五种格式分布与 E1 manifest 一致，0 parse warnings。

### E2-I03：旧 test helper 没跟上新必填字段

C03 tests 先通过，但全 ingestion suite 中 timezone test 报 `filed_department Field required`。数据流说明 production validator 还没执行到 timezone 分支；原因是测试 helper 仍构造 C01 旧字段集。

修复只更新 test fixture 的 `filed_department="hr"` 和 `duplicate_of=None`，不改 production 校验。随后 26 tests 全部通过。

### E2-C04：三种 chunk mode

RED：`ModuleNotFoundError: app.ingestion.chunking`。

实现：

- fixed：按完整 normalized document 做字符窗口，保留 legacy comparison；
- heading：每个 `ParsedSection` 独立窗口化，绝不跨 section；
- parent-child：section/parent window 保存为 `indexable=false` parent，小 child 保存 parent ID 并进入索引；
- table：按 row group 切分，每块重复 headers，并保留原始 row range；
- stable ID 输入包括 doc ID、完整 chunker config、kind、section path、locator、ordinal、text hash 和 parent ID，不包括 absolute path 或 ingested_at。

ChunkRecord 同时继承 tenant/region/ACL、policy、department/filed department、version/effective dates、authority、fact IDs 和 variant，为 E3 filter/coverage 保留治理字段。

GREEN：10 tests，累计 ingestion 36。真实 demo：

```text
fixed        72 all / 72 indexable
heading     127 all / 127 indexable
parent-child 274 all / 147 indexable
  parent    127 non-indexable
  child     134 indexable
  table      13 indexable
all chunk IDs unique
```

这些是 measured chunk counts，不是 retrieval improvement。

### E2-C05：security-aware dedup 与版本图

RED：`ModuleNotFoundError: app.ingestion.versions`。

去重域包含 tenant、region、sorted ACL、policy、version 和 filed department。这样不会跨权限、跨版本或跨误归档状态合并。桶内先比 source checksum，再比 whitespace/case normalized text hash；alias 指向 canonical，原始 ID 不丢失。

版本图只读取 authoritative records：检查 supersedes target、cycle、effective overlap 和恰好一个 active head。retired documents 保留用于历史解释，不因去重全部删除。

真实 demo 首次运行发现 `duplicate_0003` 因字母序被选为 canonical。新增测试先得到反向 alias RED，再加入 variant precedence：authoritative > supporting > misfiled/stale > near_duplicate > duplicate。

最终 demo：72 source -> 64 canonical、8 aliases、8 active heads、0 duplicate canonical。9 governance tests、累计 ingestion 45 tests。

### E2-C06：可核验的 index manifest 与 deterministic builder

#### RED：索引边界尚不存在

先新增：

```text
tests/indexing/test_manifest.py
tests/indexing/test_builder.py
```

第一次运行在 collection 阶段得到：

```text
ModuleNotFoundError: No module named 'app.indexing'
```

这个 RED 证明测试没有误走旧 `scripts/build_indexes.py`，而是在要求一条新的 v2 索引构建边界。测试事先固定了四类行为：manifest provenance 必填且内部计数一致；preview 不 embedding/不写盘；每个 indexable chunk 恰好调用一次 embedder；坏维度和非空目标目录必须 fail closed。

#### 实现位置与数据流

新增：

```text
app/indexing/__init__.py
app/indexing/manifest.py
app/indexing/builder.py
```

`manifest.py` 定义的不是普通运行日志，而是“这份索引是如何产生的”这一可验证 contract：

- `EmbeddingSpec`：模型、向量维度、是否 L2 normalization；
- `FaissSpec` / `BM25Spec`：两类索引的实现参数；
- `IndexManifest`：corpus manifest hash、parser versions、chunker config、源文档/去重文档/chunk 数量、开始结束时间；
- `ArtifactFile`：每个产物的相对路径、SHA256 和 byte count，拒绝绝对路径、`..` 越界和重复路径。

`builder.py` 的主链路是：

```text
source manifest
-> ingest_corpus
-> govern_documents
-> chunk_document
-> embed each indexable chunk once
-> L2 normalize vectors
-> FAISS IndexFlatIP + BM25 tokens + JSON records
-> write manifest last
-> reopen every artifact and validate hash/count/dimension
```

关键代码设计：

- `_prepare()` 只做 parse/govern/chunk，并检查全局 chunk ID 唯一、同名 parser 版本一致；
- `preview_build()` 只返回真实测量值，不调用 embedder，也不创建输出目录；
- `_build_artifact_bytes()` 先在内存生成全部 bytes，遇到空向量或维度不一致时，输出目录仍不存在；
- 向量先做 L2 normalization，再写 `IndexFlatIP`，这样 inner product 才表示 cosine-style similarity；
- `chunks.json` 的顺序与 embedding、BM25 token 和 FAISS vector 的行号顺序严格相同；
- `manifest.json` 最后写，避免只有 manifest、没有正文产物的假成功；
- `validate_index_directory()` 重新打开文件，检查 SHA256、byte count、JSON/pickle 数量、FAISS `ntotal` 和维度。

当前 C06 直接 builder 只接受不存在或空输出目录；版本 staging、原子 active switch 和失败清理属于紧接着的 C07，而不是在 C06 偷偷混入。

#### GREEN 与结果边界

恢复后运行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests\indexing\test_manifest.py tests\indexing\test_builder.py -q -p no:cacheprovider
```

结果：

```text
8 passed, 3 FAISS SWIG deprecation warnings
```

demo fixed preview 的真实结果为 72 source documents、64 canonical documents、8 duplicate aliases、64 indexable chunks。fake embedder 被调用 64 次，FAISS `ntotal=64`、dimension=4。fake embedding 只验证生命周期和对齐关系，不代表真实语义检索质量；真实 Ollama embedding 接线和 chunking retrieval ablation 仍在 C08/C09。

### E2-I05：为什么本轮看起来突然停止

上下文压缩发生在 `app/indexing` 三个 production 文件已经写入、C06 GREEN 尚未运行、handoff 尚未更新的动作边界。因此磁盘上的代码比 `CURRENT_EXECUTION_HANDOFF.md` 快一步。

恢复时没有凭聊天记忆猜状态，而是依次检查：工作树文件仍存在、项目后台 Python/pip 进程为 0、测试文件与 production 文件内容一致，然后运行既有测试。`8 passed` 后才把 C06 标记 complete。这说明停止原因是协作会话断点，不是代码异常、Ollama 卡住、pytest 仍在后台或文件丢失。

### E2-C07：版本目录、active pointer 与无重建回滚

#### RED：只有 builder，还没有“哪一版正在服务”的 contract

先新增 `tests/indexing/test_store.py`，首次 collection 得到：

```text
ModuleNotFoundError: No module named 'app.indexing.store'
```

测试把生命周期拆成以下可观察行为：

- 不存在或 artifact 被篡改的版本不能激活，旧 pointer bytes 完全不变；
- `active.json` 同时保存 run ID 和 manifest SHA256；
- 第二次构建保留第一版目录；
- rollback 只切 pointer，不调用 embedder、不改旧 manifest；
- pointer 临时文件在同一目录写完整、flush/fsync 后才 `os.replace()`；
- embedding 失败会清理 staging，不产生目标版本，不改变 active；
- `--force` 不能删除没有有效 v2 manifest 的陌生目录；
- run ID 不能用 `../` 逃逸 versions root。

#### 实现位置与目录结构

新增 `app/indexing/store.py`，更新 `app/indexing/__init__.py`。磁盘布局为：

```text
<index-root>/
  active.json
  versions/
    <run-id>/
      manifest.json
      documents.json
      chunks.json
      parents.json
      bm25_tokens.pkl
      faiss.index
```

主要接口：

- `build_index_version(...)`：在 `versions/.<run-id>.staging-*` 调用 C06 builder；复检后才 rename 到正式目录；可选择随后 activate；
- `load_index_version(root, run_id=None)`：显式 run ID 时加载指定版本；省略时先读 active pointer；两种情况都重新验证 manifest 与所有 artifact；
- `activate_version(root, run_id)`：先完整加载目标，再把带 manifest hash 的完整 pointer 原子替换为 `active.json`；
- `load_active_manifest(root)`：给后续 retriever/CLI 使用的窄接口；
- `LoadedIndexVersion`：把已解析 manifest、绝对版本路径和 manifest hash 绑定在一起，减少调用方自行拼路径。

这里的 rollback 没有单独的复杂算法：`activate_version(root, old_run_id)` 就是 rollback。旧版本目录从未被第二次构建覆盖，因此无需重新解析语料、重新切 chunk 或重新调用 Ollama embedding。

#### 第一次 GREEN 中的测试问题

第一次 store suite 是 6 passed、1 failed。测试通过给 `chunks.json` 追加换行制造损坏，却只接受 `hash mismatch`；实际校验先报告更快的 `byte count mismatch`。这说明 production 正在正确 fail closed，测试场景却没有隔离目标分支。

处理没有放宽断言，而是翻转首字节并保持总长度不变。第二次运行 7 passed，单独证明 SHA256 分支能抓住“长度相同、内容不同”的篡改。

#### E2-I06：原子 pointer 仍不够

代码审查发现：第一版允许 `force=True` 原地替换当前 active 的相同 run ID。即使 `active.json` 使用 `os.replace()`，如果进程在“新目录已替换、pointer 尚未更新”之间崩溃，旧 pointer 的 manifest hash 会与新目录不一致，active 就不可加载。

新增测试 `test_force_cannot_rewrite_the_active_version_in_place` 后，当前代码确实没有抛异常，并调用了 fake embedder，形成正确 RED。修复在构建前预检 pointer：目标 run ID 若 active，立即 `PermissionError`，要求创建新 run ID。修复后测试在 embedding 调用前结束，旧 pointer 和旧 manifest byte-for-byte 不变。

这体现两个不同层次的不可变性：

```text
atomic pointer replace
  保护 active.json 不会被读到半截

immutable active version directory
  保护 pointer 指向的 manifest/artifacts 在切换前不会变
```

#### GREEN 证据与边界

```text
tests/indexing/test_store.py     8 passed
tests/indexing                  16 passed
tests/ingestion + tests/indexing 61 passed
compileall                      ok
git diff --check                clean
```

3 条 warning 仍是 FAISS SWIG 类型的 deprecation warning，不是生命周期失败。C07 证明的是版本构建、验证、切换和回滚机制；production `hybrid_search` 尚未读取 v2 active pointer，C08 只提供兼容加载入口，真正 ACL-aware retrieval 仍属于 E3。

### E2-C08：安全 CLI、独立配置和不偷换基线的 adapter

#### 先固定 legacy 行为

修改前读取 `app/config.py` 与 `app/retriever.py`，确认旧链路是：

```text
Settings.indexes_dir = data/indexes
hybrid_search()
-> load_indexes()
-> data/indexes/faiss.index + chunks.json + bm25_tokens.pkl
```

C08 的边界是“让 v2 可以被明确构建和加载”，不是“让生产查询自动切到 v2”。如果在没有 E3 ACL/filter/evidence contract 前直接切换，既有答案评测变化将同时混入 ingestion、chunking 和 retrieval 多个变量，无法解释回归原因。

#### RED 证据

先新增 `tests/indexing/test_cli.py` 和 `tests/indexing/test_legacy_adapter.py`。CLI collection 先得到：

```text
ImportError: cannot import name 'build_indexes_v2' from 'scripts'
```

adapter 单独运行得到 3 个预期失败：`Settings` 没有 `v2_indexes_dir`，`app.retriever` 没有 `load_v2_indexes`，因此 legacy-default guard 也无法 monkeypatch v2 loader。

测试 contract 包括：help 不写盘；必填路径；dry-run 0 embedding/0 write；`../` run ID 和磁盘根目录在 embedding 前拒绝；默认不覆盖；只有已验证且 inactive 的版本能 force；activate-existing 不 rebuild；UTF-8 JSON 保留中文路径；`hybrid_search` 仍只调用 legacy loader。

#### 修改 1：`app/config.py`

只新增三个字段：

```python
v2_indexes_dir = data/indexes_v2
v2_corpus_profile = "demo"
v2_chunker_mode = "fixed"
```

`indexes_dir = data/indexes` 未改变。profile/chunker 使用 `Literal`，错误环境变量会在启动时失败，而不是静默落到未知模式。C09 消融完成前用 fixed 作为保守默认，因为此时只有它是旧基线，尚无证据宣称 heading/parent-child 更好。

#### 修改 2：`app/retriever.py`

新增显式 `load_v2_indexes(index_root=None)`：

1. 调用 C07 `load_index_version()`，先验证 active pointer、manifest hash 和全部 artifacts；
2. 从已验证版本目录加载 FAISS、`chunks.json`、BM25 tokens；
3. 返回与 legacy loader 相同的 `(faiss_index, bm25, chunks)` 形状。

没有修改 `hybrid_search()` 中的 `faiss_index, bm25, chunks = load_indexes()`。测试把 `load_v2_indexes()` 替换成“一旦调用就失败”的函数，`hybrid_search()` 仍成功并且 legacy loader 调用恰好一次。这是“不偷换生产默认”的直接行为证据。

#### 修改 3：`scripts/build_indexes_v2.py`

CLI 有三条互斥路径：

```text
--dry-run
  source profile check -> preview_build -> JSON
  no embed, no output directory

new build
  arguments/path/profile check
  -> lazy import _embed_text
  -> build_index_version(activate=True)
  -> reload active version -> JSON

--activate-existing RUN_ID
  validate existing version -> atomic pointer switch -> JSON
  no corpus parse, no embed, no rebuild
```

安全细节：build 必须显式提供 input/output/run ID；output 不能是磁盘根目录或用户 home；source manifest profile 必须匹配；`--force` 与 dry-run/activate-existing 冲突；actual Ollama `_embed_text` 在参数、profile、chunker 和 output root 全部验证后才 import；tests 通过参数注入 fake embedder；stdout 输出 UTF-8 JSON，预期业务错误返回 code 2 并写 stderr。

#### E2-I07：第一次修改为什么没生效

首次把 config、retriever 和新 CLI 放在同一个 patch，`retriever.py` import 上下文验证失败。`apply_patch` 原子拒绝整组 patch。随即检查新脚本不存在、config/retriever diff 为空，证明没有半落盘。随后缩小上下文并拆成三个 patch，而不是覆盖写文件。

#### GREEN 与真实命令证据

```text
C08 targeted tests                         9 passed
all tests/indexing                        25 passed
indexing + legacy Agent/tool focused set  44 passed
compileall                                ok
git diff --check                          clean (only Windows EOL notices)
```

真实 `--help` 正常退出。真实 demo dry-run 输出 72 source、64 canonical、8 duplicates、64 indexed chunks；执行前后 `data/indexes_v2` 都不存在，也没有进入延迟 import 的 Ollama 分支。

C08 仍不能证明 v2 retrieval 质量更好，也没有让 production 问答使用 v2。它证明的是：操作者现在有一条可验证、不会默认覆盖、可回滚且能在中文路径下输出结构化结果的索引生命周期入口。

### E2-C09：BM25-only chunking 消融与阶段验收

#### 为什么只评 18 道题

demo dev 有 24 题：18 answered、2 permission、4 not_found。chunking ablation 的 gold 是“应该找回哪些文档”，因此只选择 `answer_mode=answered` 且 `gold_doc_ids` 非空的 18 题。permission/not_found 的正确目标是拒答或无证据，不应该被硬塞进普通 Recall 分母。

#### RED 与实现位置

先新增 `tests/indexing/test_chunking_ablation.py`，collection 得到：

```text
ImportError: cannot import name 'eval_chunking_ablation' from 'scripts'
```

随后新增 `scripts/eval_chunking_ablation.py`。它复用 `ingest_corpus -> govern_documents -> chunk_document`，每种 mode 建一个全局 `BM25Okapi`，同样使用 `tokenize_for_bm25/jieba`。每题按 tenant、region、ACL group 过滤可见 chunk，再按 BM25 分数和稳定 chunk ID 排序。

评测单位不是原始 top-k chunks，而是“每份文档最高分的可见 chunk”：相同 doc 的其余 chunks 被折叠，得到唯一 doc ranking。这样 parent-child 不会仅因为一份文档切得更碎就重复占满 top-k。

逐题指标：

```text
Hit@k      top-k 是否至少包含一个 gold doc
Recall@k   找回 gold doc 数 / gold doc 总数
RR         第一个 gold doc 的倒数排名；top-k 内没有则 0
full_recall 是否所有 gold docs 都在 top-k
```

failure 定义为 `full_recall=0`。因此 comparison 有两份 gold，只找回一份时 Hit=1、Recall=0.5，但仍进入 failure 记录。summary 同时按 task type 聚合，并保存每题 retrieved docs、支持 chunk、score 和 missed gold。

输出策略：没有 `--output-dir` 时只向 stdout 打印 UTF-8 JSON；显式输出时用 sibling staging 创建全新的 run directory，写 `summary.json/details.json`，目标已存在即拒绝，无 `--force`。

#### 正式 dev 实验

命令：

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_chunking_ablation `
  --input-dir data\generated\demo `
  --top-k 5 `
  --output-dir data\eval_outputs\e2_chunking_ablation_demo_dev_20260716
```

共同条件：72 source -> 64 canonical，8 duplicate aliases；dev 24 输入、18 scored、6 excluded；ACL filter 开；BM25/jieba；unique document top-5；未读取 frozen test；未调用 embedding/LLM。

| mode | total/indexable chunks | Hit@5 | Recall@5 | MRR@5 | full recall | failures |
|---|---:|---:|---:|---:|---:|---:|
| fixed | 64 / 64 | 0.9444 | 0.8333 | 0.3769 | 0.7222 | 5 |
| heading | 112 / 112 | 0.9444 | 0.8611 | 0.5157 | 0.7778 | 4 |
| parent-child | 243 / 131 | 0.9444 | 0.8611 | 0.5898 | 0.7778 | 4 |

parent-child 的 243 总 chunks 包含 112 non-indexable parents、119 children、12 table chunks。它的 MRR 最高，但索引 chunks 是 fixed 的约 2.05 倍，总对象约 3.80 倍。

产物 hashes：

```text
summary.json  45a9f3f3c053ec786775c099d81cbe103325e4cf780972795c687bd3ca7afc1c
details.json  2243f539f708d05b661e888534d38444fc6f938e10e21602d78f7cb924978131
```

#### 好结果、坏结果和原因

好结果：heading/parent-child 修复了 fixed 的 `complete_customer_refund` failure。更聚焦的 section/child chunk 减少整篇文档的无关词，fact lookup 与 completeness 的首个 gold 排名整体更靠前。

坏结果：三种模式的 4 道 comparison 都没有完整召回两份 gold。fixed comparison Recall@5 为 0.5，heading/parent-child 反而为 0.375。top-5 被 supporting、misfiled、near-duplicate 和 retired authority 文档占据；小 chunk 通常把其中一个制度推得更靠前，却没有同时覆盖第二个制度。

结论不是“parent-child 全面更好”。这个结果支持：

- chunk structure 能改善局部事实的排名；
- comparison 需要 E3 metadata/current/authority 约束和 query decomposition；
- parent-child 必须配合 parent expansion 才能验证最终回答上下文；
- 18 道 synthetic dev 的单次 BM25 结果不能证明 dense/Agent/线上质量。

所以 E2 不把 `v2_chunker_mode` 从 fixed 自动改为 parent-child。保留可比较基线，E3 实现受控检索后再做端到端 admission，而不是只追一个平均 MRR。

#### E2-I08：为什么局部全绿、全量 collection 却失败

新增的 `tests/indexing/test_cli.py` 与已有 `tests/corpus/test_cli.py` 同名。两个目录都没有 package namespace，pytest 默认 import mode 把前者导入成顶层 `test_cli` 后，再收集后者会发现同名模块的 `__file__` 不一致。

局部 indexing tests 看不到 corpus 文件，所以之前不会失败。处理不是删除 cache 掩盖问题，而是把新文件改名为 `test_index_cli.py`。随后两个 CLI 文件一起 9 passed，全仓库 225 passed。

#### E2 最终门禁

```text
tests/ingestion + tests/indexing  77 passed, 3 FAISS warnings
full repository                   225 passed, 5 warnings
pip check                         no broken requirements
compileall app/scripts/tests      ok
frozen test expected/actual       556ffed812...43338 (equal)
build_indexes_v2 dry-run          exit 0; indexes_v2 absent before/after
git diff --check                  exit 0; Windows EOL notices only
git index.lock                    absent
```

5 warnings 是 3 条 FAISS SWIG deprecation 和 2 条既有 FastAPI `on_event` deprecation；没有新增失败。E2 完成的是 ingestion/index lifecycle 及其 dev evidence，不是 E3 production retrieval。

## 7. 当前明确不做

- 不把 v2 index 接入 production `hybrid_search`；ACL-aware retrieval 属于 E3。
- 不加入 OCR；图片型 PDF 返回 warning/空文本失败。
- 不做增量 upsert/delete；E2 做可验证的 versioned full rebuild。
- 不加入 reranker、向量数据库、Redis 或后台任务队列。
- 不运行 frozen test 调参；chunking 消融只使用 dev。
- 未经本人确认不 commit 或 push。

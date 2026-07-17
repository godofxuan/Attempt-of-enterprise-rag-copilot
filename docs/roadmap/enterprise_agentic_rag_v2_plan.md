# Enterprise Agentic RAG v2 Implementation Plan

> **For agentic workers:** 每阶段必须先写该阶段的细粒度 TDD 计划，再使用 `superpowers:executing-plans` 逐任务执行。E0 之后一次只执行一个阶段，阶段验收后停止。

**Goal:** 在保留可比较 RAG 基线的前提下，将当前 15 文档本地 Demo 升级为可复现、可评估、带版本/权限/冲突意识且适合招聘展示的 R1 Enterprise Edition。

**Architecture:** 采用 data/eval-first 的兼容演进。E1 冻结事实骨架和 v2 eval；E2 形成规范化 ingestion/index contract；E3 用 QueryAnalysis、ACL-aware retrieval、search/find/open 和 EvidenceLedger 升级 Agent；E4-E6 再补全评测、安全工程和公开展示。旧 `/chat`、旧三种 retrieval baseline 和旧数据集保留到 E7，用于消融与回滚。

**Tech Stack:** Python 3.11、Pydantic 2、FastAPI、Streamlit、Ollama、BGE-M3、FAISS、rank-bm25、SQLite、pytest；新 parser/metrics 依赖只在相应阶段通过 admission gate 后加入。

## Global Constraints

- 当前不可改写基线提交：`7aec4b950e012d3f24b8e1877d6391201e9b8f90`。
- 每阶段开始记录 branch、HEAD、upstream、status、最近 8 个提交、进程和 lock；出现外部变化立即停止。
- 每个生产行为遵循 RED -> minimal GREEN -> targeted tests -> related eval -> full pytest -> diff review。
- 不使用 `git reset --hard`、`git clean`、force-push、历史改写或递归删除。
- 不提交 `.env`、数据库、索引、大型生成语料、eval runs、日志、简历或个人信息。
- deterministic 结果只描述契约；live 结果必须带模型、prompt、config、数据/index hash 和环境。
- v2 test 在 E1 冻结后不得用于调参；后续重复运行只称 regression。
- 不提前实现 R2，不加入多 Agent、长期记忆、Redis、Kafka、Kubernetes 或微服务。
- merge、push、PR、tag、release、默认分支和仓库重命名必须单独获得本人确认。

## 1. 阶段和预计工时

工时是 Codex 协作下的工程时间区间，不含本地模型长时间运行和本人学习/人工抽检时间。

| 阶段 | 工程工时 | 本人验收 | 核心交付 |
|---|---:|---:|---|
| E0 审计与设计 | 5-7h | 30-45min | 当前证据、设计、计划、gap matrix、学习卡 |
| E1 档案与评估集 | 16-24h | 2-3h | 事实骨架、生成器、demo/benchmark 配置、v2 eval、data card |
| E2 解析与索引生命周期 | 20-30h | 2h | parser registry、records、chunking、manifest、安全 build CLI |
| E3 检索与 Agent 工作流 | 24-36h | 3h | QueryAnalysis、ACL hybrid、search/find/open、ledger、claim citations |
| E4 评测与消融 | 16-24h | 4-6h | 四层 eval、run manifest、ablation、failure report、人工抽检模板 |
| E5 安全、服务与可观测性 | 20-28h | 2h | UserContext、lifespan、health、request ID、trace、CI、load profile |
| E6 演示与公开仓库 | 12-18h | 3h | 三页 UI、架构/数据/评测/安全/复现文档、面试材料 |
| E7 最终验收 | 4-8h | 2h | PASS/FAIL/NOT RUN 报告和 claims-evidence matrix |

R1 总工程量约 112-168 小时。按每周 15-20 小时计算约 6-10 周；任何阶段失败都先修该阶段，不用后续页面掩盖。

## 2. E1：企业档案与评估集

### 目标

先建立唯一权威事实骨架，再由确定性生成器渲染不同来源文档和 gold cases。禁止直接让模型自由写 500 份彼此不一致的文本。

### 计划文件

**Create:**

- `app/corpus/__init__.py`
- `app/corpus/schemas.py`：事实骨架、profile、document/eval specification 的 Pydantic 类型。
- `app/corpus/generator.py`：seeded facts -> logical document specs。
- `app/corpus/renderers.py`：Markdown/TXT/HTML/CSV/JSONL 公开渲染器；PDF/DOCX 由 E2 parser fixture 需要决定。
- `app/corpus/eval_cases.py`：从原子事实和关系构造 dev/test case specs。
- `scripts/generate_enterprise_corpus.py`：`--profile/--seed/--output-dir/--dry-run/--force` 安全 CLI。
- `data/v2/facts/company_facts_v1.json`
- `data/v2/config/demo.json`
- `data/v2/config/benchmark.json`
- `data/v2/fixtures/smoke/`：可提交的小型跨来源 fixture。
- `data/v2/eval/dev.json`
- `data/v2/eval/test.json`
- `data/v2/eval/test_manifest.sha256`
- `docs/data_card.md`
- `tests/corpus/` 下的 schema、seed、version、ACL、gold 和 split 测试。

**Modify:**

- `.gitignore`：忽略本地生成的 demo/benchmark corpus 和 manifests runs，但保留 facts/config/smoke/eval schema。
- `data/eval/metadata.json`：只增加 legacy/v2 边界，不覆盖旧数据说明。

### 门禁

- 同一 seed 的 corpus manifest byte-identical。
- doc/case IDs 唯一，版本链无环，effective interval 合法，ACL references 合法。
- gold facts 能定位到 gold docs，forbidden docs 存在且与 user context 一致。
- dev/test 问题无重复；test 文件冻结 SHA256。
- demo 实际 60-100 docs；benchmark 实际 500-800 docs。只报告生成器输出的真实规模。
- data card 明确声明全部为虚构合成企业档案。

### 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\corpus -q
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile demo --seed 20260716 --dry-run
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile demo --seed 20260716 --output-dir data\generated\demo
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

### 建议提交

`data: add reproducible synthetic enterprise corpus generator`

E1 完成后停止，等待 `批准E1，执行E2解析与索引生命周期`。

## 3. E2：解析、切块、治理与索引生命周期

### 目标

把“glob Markdown -> 四字段 dict -> 原地覆盖索引”升级为可验证的 parser/record/chunker/index contract。

### 计划文件

**Create:**

- `app/domain/documents.py`：`DocumentRecord/ChunkRecord/DocumentVersion/ParseWarning`。
- `app/ingestion/parsers.py`：Parser protocol、registry、Markdown/TXT/HTML/CSV/JSONL 实现。
- `app/ingestion/parsers_pdf.py`、`parsers_docx.py`：通过依赖 gate 后加入。
- `app/ingestion/normalize.py`：统一文本、tables、metadata 和 locators。
- `app/ingestion/versions.py`：dedup、supersedes、authority/effective-date 校验。
- `app/ingestion/chunking.py`：fixed、heading-aware、parent-child 和 table chunkers。
- `app/indexing/builder.py`：versioned full build、validation 和 manifest。
- `app/indexing/store.py`：读取指定/active index version，不在请求中构建。
- `app/indexing/manifest.py`：index/corpus/model/chunker/file hashes。
- `scripts/build_indexes_v2.py`：安全 CLI。
- `tests/ingestion/`、`tests/indexing/` 多格式 fixture 和生命周期测试。

**Modify:**

- `app/retriever.py`：保留 legacy adapter，把 v2 build/load 委派到新 indexing boundary。
- `app/config.py`：增加 corpus/index profile 和 active index path；不改变旧默认直到 v2 验证。
- `requirements.txt`：只加入已通过 fixture gate 的 parser 依赖并固定范围。

### 门禁

- 每种格式成功、warning、结构化失败均有 fixture。
- 空文本或 parse error 不进入索引。
- heading/table/parent-child 保留 locator；chunk_id 稳定且唯一。
- exact/normalized dedup 和版本链有独立测试。
- `--help` 退出 0 且不写文件；已有目标默认拒绝，`--dry-run` 不写，`--force` 显式。
- index manifest 包含 corpus/model/dimension/metric/BM25/chunker/parser/count/time/file hashes。
- baseline vs chunker 消融在同一 dev 集运行；不预设 v2 一定提升。

### 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\ingestion tests\indexing -q
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --help
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --profile demo --dry-run
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

### 建议提交

`feat: add normalized ingestion and versioned index manifest`

E2 完成后停止，等待 `批准E2，执行E3检索与Agent工作流`。

## 4. E3：ACL-aware retrieval 与证据闭环

### 目标

让分析结果真实改变 filters、retrieval、工具选择和停止原因，替换装饰性 route/planner。

### 计划文件

**Create:**

- `app/domain/queries.py`：`UserContext/QueryAnalysis/SearchRequest/SearchResult`。
- `app/domain/evidence.py`：`EvidenceItem/EvidenceLedger/ClaimCitation/AnswerResponse`。
- `app/domain/agent.py`：`AgentBudget/AgentAction/AnswerMode`。
- `app/retrieval/pipeline.py`：BM25/dense/RRF、metadata/temporal/ACL filters、dedup/diversity/parent expansion。
- `app/retrieval/navigation.py`：typed `search/find/open`。
- `app/security/access.py`：pre-context ACL policy 和 trace redaction。
- `app/agent/query_analysis.py`：规则优先、模型 fallback 的结构化分析。
- `app/agent/evidence_ledger.py`：required facts、support/conflict/missing/coverage/action。
- `app/agent/citation_verifier.py`：claim-to-chunk 支持检查。
- `tests/retrieval/`、`tests/security/`、`tests/agent_v2/`。

**Modify:**

- `app/agent/controller.py`：保留显式状态机，改用 typed budget/action/outcome。
- `app/agent/tools.py`：注册 typed search/find/open，限制参数、结果、timeout 和 allowlist。
- `app/agent/evidence.py`：从三字段 verdict 迁移到 ledger adapter；保留 fail-closed transport。
- `app/agent/runner.py`：记录 budget、stop reason、request-local spans。
- `app/agent/router.py`、`planner.py`：unsafe 规则保留，非安全逻辑迁移后降级为 legacy baseline。
- `app/rag_service.py`：生成使用 ledger 和 claims，不再独立重复分类意图。
- `app/schemas.py`、`app/agent/schemas.py`：兼容旧 API 并增加 v2 response。

### 门禁

- 未授权 chunks 在 fusion、context、answer、source list 和 trace 中均不可见。
- route/query analysis 至少改变 filters、工具或 answer mode；没有行为差异的字段不保留。
- search/find/open 均有 Pydantic args、budget、timeout、structured errors 和 deterministic tests。
- rewrite/decompose 由 missing facts 驱动并保留实体、时间、条件、比较/列举和权限范围。
- answer modes 至少区分 answered/partial/not_found/permission/unsafe/system/budget。
- claim citation presence、coverage、correctness 和 unsupported claim 可独立评分。
- reranker 默认不实现；只有 admission gate 满足时以 feature flag 加入。

### 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest tests\retrieval tests\security tests\agent_v2 -q
.\.venv\Scripts\python.exe -m pytest tests\test_agent_controller.py tests\test_agent_adaptive_runner.py -q
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

### 建议提交

`feat: add ACL-aware hybrid retrieval and document navigation tools`
`feat: add evidence ledger and bounded agent workflow`

E3 完成后停止，等待 `批准E3，执行E4评估与消融`。

## 5. E4：四层评测、消融和人工抽检

### 目标

建立不会覆盖、可追溯、能定位失败阶段的统一评测运行协议。

### 计划文件

**Create:**

- `app/evaluation/contracts.py`：run/case/result/failure category schemas。
- `app/evaluation/run_manifest.py`：Git/data/index/model/prompt/config/environment provenance。
- `app/evaluation/retrieval.py`、`answer.py`、`agent.py`、`security.py`。
- `app/evaluation/attribution.py`：主因/次因错误分类。
- `scripts/eval_enterprise_v2.py`：`--suite/--split/--run-id/--out-dir`，默认拒绝覆盖。
- `scripts/eval_ablation_v2_enterprise.py`：同数据、同 split、同 top-k/config。
- `docs/evaluation.md`
- `docs/ablation_report.md`
- 私人空白人工抽检表。
- `tests/evaluation/`。

**Modify:**

- 旧 evaluator 保留为 legacy adapter；不改旧结果以制造前后对比。
- `.gitignore` 增加 `eval_runs/`。

### 门禁

- 每个 run 独立目录，已存在 run-id 默认失败。
- manifest 保存非敏感实际配置，不只有哈希。
- Stage 8 case-pass 不再冒充答案正确；answer row 保存 claims、citations 和 source coverage。
- citation 不再令 `cited_sources = retrieved_sources`。
- 输出 retrieval/answer/agent/security 分层指标和按类别 failure report。
- 本人抽检 30-50 例；Codex 只生成空表，不填写人工结论。
- 主要比例可选 bootstrap CI，必须同时报告 n 和方法。

### 验证命令

```powershell
$RUN_ROOT = "$(Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ')_$(git rev-parse --short HEAD)"
.\.venv\Scripts\python.exe -m pytest tests\evaluation -q
.\.venv\Scripts\python.exe -m scripts.eval_enterprise_v2 --suite all --split dev --run-id "${RUN_ROOT}_suite"
.\.venv\Scripts\python.exe -m scripts.eval_ablation_v2_enterprise --split dev --run-id "${RUN_ROOT}_ablation"
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

`$RUN_ROOT` 在阶段开始时生成一次并写入审计记录；各 runner 使用不同后缀，同一完整 run ID 不复用。

### 建议提交

`eval: add enterprise benchmark and ablation reports`

E4 完成后停止，等待 `批准E4，执行E5安全、服务与可观测性`。

## 6. E5：安全、服务和可观测性

### 目标

让本地服务具有可解释的运行边界，而不是用“生产级”替代工程证据。

### 计划文件

**Create:**

- `app/api/errors.py`：统一错误模型和状态映射。
- `app/api/middleware.py`：request ID、deadline、结构化日志和脱敏。
- `app/observability/tracing.py`：阶段 span 和 persistence adapter。
- `app/observability/metrics.py`：最小 counters/histograms。
- `app/runtime/resources.py`：lifespan 加载索引、数据库和模型 readiness。
- `scripts/load_profile.py`：concurrency 1/5/10，可重复环境记录。
- `.github/workflows/ci.yml`
- `docs/security_threat_model.md`
- `docs/reproducibility.md`
- `tests/api_v2/`、`tests/observability/`。

**Modify:**

- `app/main.py`：lifespan、`/health/live`、`/health/ready`、versioned/compatible endpoints。
- `app/config.py`：timeout、deadline、budget、redaction 和 index version settings。
- `app/db.py`：只在需要时持久化 feedback/trace metadata，不保存完整敏感正文。
- `pytest.ini`：临时文件移到系统 temp 或 CI temp，不混入 `data/eval_outputs`。
- `requirements.txt`：固定依赖，metrics/psutil 只在 gate 通过后加入。

### 门禁

- readiness 实际检查 index/model/database；liveness 不做昂贵依赖调用。
- sync/blocking 模型调用有 deadline 和有限 retry；不可重试错误不重试。
- request ID 贯穿 API、trace 和 error；日志默认不写完整问题/正文。
- ACL/security test 覆盖跨租户、文档注入、trace/title 泄露和预算上限。
- CI 不调用 Ollama，只跑 deterministic/API/small fixture eval。
- demo/benchmark 记录 build size/time、cold/warm p50/p95、error、memory 和 model calls。

### 验证命令

```powershell
$RUN_ID = "$(Get-Date -AsUTC -Format 'yyyyMMddTHHmmssZ')_$(git rev-parse --short HEAD)"
.\.venv\Scripts\python.exe -m pytest tests\api_v2 tests\observability tests\security -q
.\.venv\Scripts\python.exe -m scripts.load_profile --profile demo --concurrency 1,5,10 --run-id $RUN_ID
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

### 建议提交

`security: enforce document access and prompt-injection boundaries`
`obs: add request tracing metrics and service health checks`
`ci: add deterministic Python test workflow`

E5 完成后停止，等待 `批准E5，执行E6演示与公开仓库收口`。

## 7. E6：演示、文档和招聘材料

### 目标

让招聘者在默认分支首页和三页 UI 中快速看懂真实业务问题、Agent 决策、证据和评测，不用阅读全部源码。

### 计划文件

**Create:**

- `streamlit_app/pages/1_Ask.py`
- `streamlit_app/pages/2_Trace.py`
- `streamlit_app/pages/3_Evaluation.py`
- `docs/architecture.md`
- `docs/known_limitations.md`
- `docs/demo_runbook.md`
- `docs/industrialization_backlog.md`
- UI screenshots/GIF 的生成说明与小型公开资产。
- 私人 `interview_script_30s.md`、`1min.md`、`3min.md`、`interview_qa.md`、`claims_evidence_matrix.md`。

**Modify:**

- `streamlit_app/ui.py`：只保留入口/共享状态，不复制三页业务逻辑。
- `README.md`：业务问题、架构图、demo、Agentic necessity、结果、三条命令、数据声明、限制和文档链接。
- `PROJECT_STATUS.md`：只保留一个当前状态入口并使用 E7 前的真实证据。
- `docs/AGENTIC_RAG_EVOLUTION_LOG.md`：保留历史，不再承担当前状态职责。

### 门禁

- UI 展示 role/context、answer mode、claim citations、actions、ledger coverage、latency 和 stop reason。
- 内置 demo 覆盖单文档、比较、版本冲突、条件、无答案、权限和文档注入。
- UI 只消费真实 API/trace/eval artifacts，不硬编码成功结果。
- 新终端按 runbook 可启动；截图与实际版本一致。
- 私人材料不进入 Git，所有简历数字来自 claims-evidence matrix。
- merge/default branch/tag/repository rename 仍需本人单独批准。

### 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn app.main:app
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py
git diff --check
```

服务启动与视觉验收必须使用独立进程，并在阶段结束前明确关闭；不得把后台进程留给下一阶段。

### 建议提交

`docs: publish enterprise v2 architecture evaluation and limitations`

E6 完成后停止，等待 `执行E7最终验收`。

## 8. E7：最终验收

### 目标

逐项输出 PASS/FAIL/NOT RUN，并只批准有证据的公开与简历主张。

### 输出

- 仓库内：最终 `PROJECT_STATUS.md`、reproducibility links、固定 release candidate commit。
- 私人：`<private-external-audit-path>/Enterprise_Agentic_RAG_v2_最终验收.md`。
- 每个验收项记录命令、退出码、artifact path/hash、结论和边界。

### 验收顺序

1. Git/隐私/ignored/large-file audit。
2. facts/corpus/manifest/test hash audit。
3. parser/index lifecycle 与 `--help` 无副作用。
4. baseline/v2 retrieval、Agent、ACL、citation 与四层 eval。
5. full pytest、CI、health、trace、load profile。
6. 新终端 demo 和三页 UI 视觉检查。
7. README/PROJECT_STATUS/default branch/links 一致性。
8. 本人代码实验、人工抽检和口述验收。
9. claims-evidence matrix 审批候选简历主张。

### 最终边界

任何未运行项目写 `NOT RUN`；任何失败项目写 `FAIL` 并保留。R1 验收通过不自动进入 R2，也不自动 merge、push、tag 或改仓库名。

## 9. E0 后准确命令

本轮结束后不执行实现。下一条允许进入开发的本人命令只有：

```text
批准E0，执行E1档案与评估集
```

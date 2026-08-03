# Enterprise Agentic RAG 工程决策与故障总账

更新日期：2026-08-03

## 1. 先说人话

这不是另一篇从头到尾的实施教程，而是一张“工程索引表”。当你记得“Windows 当时为什么报错”，却不记得它发生在哪个阶段时，可以先在这里按 ID 找到它，再跳转到阶段实施记录看完整代码、诊断和测试。

ID 的含义：

- `D` 是 Decision，表示设计选择；
- `I` 是 Incident，表示遇到的故障；
- `X` 是 Experiment，表示实验；
- `L` 是 Limitation，表示当前边界；
- 前面的 `E0`、`E1`、`E2`、`E3` 表示发生阶段。

证据标签：

- `[OBSERVED]`：当前文件、Git、测试或 hash 可以直接证明；
- `[REPRODUCED]`：回填时重新运行命令复现；
- `[INFERRED]`：根据现象和排除实验推断，不能冒充百分之百确定；
- `[RETROACTIVE]`：阶段结束后依据现存材料补写的解释；
- `[NOT_CAPTURED]`：原始输出没有保存，不补造内容。

## 2. E0 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E0-D01` | 项目很大，是否一次把所有能力都做完 | 分成 R1 简历门槛与 R2 可选工业扩展，再把 R1 拆成 E0-E7 | `[OBSERVED]` E0 design/plan | 防止 Redis、Kubernetes、多 Agent 等无关范围挤占核心工作 | [E0-D01](e0_readonly_audit_implementation.md#e0-d01) |
| `E0-D02` | 是先改 Agent，还是先建立能测量它的数据 | 先做版本化 facts、企业噪声 corpus 和冻结 eval，再改 parser/index/retrieval | `[OBSERVED]` E0 gap matrix；`[RETROACTIVE]` 因果解释 | E1 的所有文档和题目可以回到同一 `fact_id` | [E0-D02](e0_readonly_audit_implementation.md#e0-d02) |
| `E0-D03` | 新架构是否直接替换旧 BM25/dense/RRF | 保留旧基线，通过同数据消融决定新复杂度是否值得 | `[OBSERVED]` E0 design | 后续可以区分“功能更多”和“质量真的提升” | [E0-D03](e0_readonly_audit_implementation.md#e0-d03) |

## 3. E0 已知边界

| ID | 边界 | 证据 | 为什么重要 | 详细记录 |
|---|---|---|---|---|
| `E0-L01` | 已经反复运行的旧 test 只能称 regression，不能继续称 unseen held-out | `[OBSERVED]` 旧结果与 E0 审计 | 防止测试集过拟合后仍宣传泛化能力 | [E0-L01](e0_readonly_audit_implementation.md#e0-l01) |
| `E0-L02` | 15 文档、75 chunks 不能支持生产规模主张 | `[OBSERVED]` 旧 corpus/index 文件 | 小数据能跑通不代表治理、性能和冲突问题已解决 | [E0-L02](e0_readonly_audit_implementation.md#e0-l02) |

## 4. E1 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E1-D01` | 是否让 LLM 自由生成 600 篇文档 | 先定义 32 个原子事实，再确定性渲染文档 | `[OBSERVED]` facts/generator/tests | gold answer、文档和版本可以追溯 | [E1-C02](e1_enterprise_corpus_implementation.md#e1-c02) |
| `E1-D02` | seed 是否可以改变正式制度内容 | seed 只控制 supporting/noise，authoritative 直接由 facts 构造 | `[OBSERVED]` generator test | 换 seed 不会改变企业真相 | [E1-C03](e1_enterprise_corpus_implementation.md#e1-c03) |
| `E1-D03` | 错误数据在什么时候被发现 | 用 Pydantic validators 在生成前拒绝非法版本、ACL 和引用 | `[OBSERVED]` schema tests | 错误不会悄悄扩散到文档和 eval | [E1-C01](e1_enterprise_corpus_implementation.md#e1-c01) |
| `E1-D04` | 评估是否只保存 question/answer | 保存 required facts、gold、distractor、forbidden、UserContext 和 answer mode | `[OBSERVED]` eval JSON/tests | 后续可分离检索、版本、权限和生成错误 | [E1-C05](e1_enterprise_corpus_implementation.md#e1-c05) |
| `E1-D05` | test 失败后能否直接改题继续称 held-out | test 写独立 SHA256，canonical writer 不提供 force | `[OBSERVED]` artifact tests/hash；`[REPRODUCED]` hash | 冻结测试集变成流程约束 | [E1-C05](e1_enterprise_corpus_implementation.md#e1-c05) |
| `E1-D06` | 大量生成文件如何安全写盘和管理 | staging 完成后激活；`--force` 只覆盖本生成器目录；大 corpus 不进 Git | `[OBSERVED]` artifacts/CLI/ignore tests | 避免半写产物和误删任意目录 | [E1-C06](e1_enterprise_corpus_implementation.md#e1-c06) |

## 5. E1 故障总账

| ID | 用户看到的症状 | 原因或最可信解释 | 修复 | 证据等级 | 详细记录 |
|---|---|---|---|---|---|
| `E1-I01` | pytest 报找不到 `test_bytes` fixture | 名为 `test_manifest_line` 的生产 helper 被导入测试模块后又被 pytest 当成测试 | 改名 `build_test_manifest_line` | `[OBSERVED]` 当前代码；首次完整输出 `[NOT_CAPTURED]` | [E1-I01](e1_enterprise_corpus_implementation.md#e1-i01) |
| `E1-I02` | CLI 已生成文件，但 subprocess 读取输出时报 UnicodeDecodeError | Windows 子进程输出编码与测试按 UTF-8 解码不一致 | CLI 显式把 stdout/stderr 配置成 UTF-8 | `[OBSERVED]` CLI code/test；首次输出 `[NOT_CAPTURED]` | [E1-I02](e1_enterprise_corpus_implementation.md#e1-i02) |
| `E1-I03` | staging 目录偶发 `WinError 5`，重跑位置不固定 | Windows 扫描器或沙箱文件层短暂占用刚写完的目录，永久权限错误已被排除 | 仅对 WinError 5/32 且 target 不存在做有界退避 | `[INFERRED]` 根因；`[OBSERVED]` 回归测试 | [E1-I03](e1_enterprise_corpus_implementation.md#e1-i03) |
| `E1-I04` | 两个版本有效期重叠仍能通过 schema | 初版只校验单版本日期，没有校验 `supersedes` 两端区间 | 在 `PolicyFamily.validate_versions` 加跨版本检查 | `[OBSERVED]` 测试与 validator | [E1-I04](e1_enterprise_corpus_implementation.md#e1-i04) |
| `E1-I05` | permission 题最初 dev/test 为 4/1 | 全局切分满足总数，但没有保证稀少安全类别在 test 有足够样本 | 按 task type 分层并调整为 2/3 | `[OBSERVED]` eval tests/output | [E1-I05](e1_enterprise_corpus_implementation.md#e1-i05) |
| `E1-I06` | apply_patch 回执 `aborted`，界面看起来停止 | 工具权限状态刷新，但文件实际已经落盘 | 不猜测；重读文件、检查进程、运行 repository tests | `[OBSERVED]` 文件/测试；平台内部原因 `[INFERRED]` | [E1-I06](e1_enterprise_corpus_implementation.md#e1-i06) |
| `E1-I07` | PowerShell `ConvertFrom-Json` 报中文 JSON 无效，同时命令还打印成功 | Windows PowerShell 5 默认代码页误读 UTF-8，且错误是 non-terminating | 改用 Python `read_text(encoding='utf-8')` + `json.loads` 做 fail-fast 验证 | `[REPRODUCED]` 本轮回填前验证 | [E1-I07](e1_enterprise_corpus_implementation.md#e1-i07) |

## 6. E1 已知边界

| ID | 当前边界 | 证据 | 面试时应该怎么说 | 详细记录 |
|---|---|---|---|---|
| `E1-L01` | 文档和问题同源，存在 synthetic shortcut | `[OBSERVED]` generator/eval architecture | “这是受控 benchmark，不是线上业务分布” | [E1-L01](e1_enterprise_corpus_implementation.md#e1-l01) |
| `E1-L02` | v2 文档尚未进入 parser、chunker、embedding 和 index | `[OBSERVED]` E1 diff boundary | “E1 建立输入和 gold contract，E2 才验证 ingestion” | [E1-L02](e1_enterprise_corpus_implementation.md#e1-l02) |
| `E1-L03` | ACL 目前是数据契约，不是运行时 pre-filter | `[OBSERVED]` corpus/eval code | “已定义 forbidden cases，尚未证明 runtime 零泄漏” | [E1-L03](e1_enterprise_corpus_implementation.md#e1-l03) |
| `E1-L04` | E1 没有新的 retrieval、answer、Agent 或 latency 提升数字 | `[OBSERVED]` verification scope | “E1 让后续改进可测，不等于检索已经变好” | [E1-L04](e1_enterprise_corpus_implementation.md#e1-l04) |
| `E1-L05` | 600 份确定性文档不等于生产规模或真实复杂度 | `[OBSERVED]` benchmark profile/data card | “这是 R1 本地评测规模，不宣传高并发生产能力” | [E1-L05](e1_enterprise_corpus_implementation.md#e1-l05) |

## 7. E2 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E2-D01` | 七种文件是否直接变成零散 dict | parser 只输出结构，normalizer 合并 manifest 治理字段为 `DocumentRecord` | `[OBSERVED]` domain/parser/normalizer tests | 文件结构错误与企业治理字段有明确边界 | [E2-C01-C03](e2_parser_index_lifecycle_implementation.md) |
| `E2-D02` | 去重是否只看文本相同 | 先按 tenant/region/ACL/version/filed department 划安全域，再比 checksum/normalized text | `[OBSERVED]` 9 governance tests | 不会跨权限、跨版本或误归档边界合并 | [E2-C05](e2_parser_index_lifecycle_implementation.md) |
| `E2-D03` | build 成功是否只看文件存在 | manifest 保存 provenance/hash/count，写完重新打开 FAISS/JSON/pickle 全量校验 | `[OBSERVED]` 8 builder tests | 半写、错维度、错数量和内容篡改 fail closed | [E2-C06](e2_parser_index_lifecycle_implementation.md) |
| `E2-D04` | 新索引是否原地覆盖 active 文件 | 每个 run 独立版本目录，完整校验后原子替换 `active.json`；active run 不可 force 原地改写 | `[OBSERVED]` 8 store tests | 失败保留旧 active，rollback 不重新 embedding | [E2-C07](e2_parser_index_lifecycle_implementation.md) |
| `E2-D05` | E2 是否直接让生产查询切到 v2 | 只新增显式 `load_v2_indexes`，legacy `hybrid_search -> load_indexes` 不变 | `[OBSERVED]` adapter guard test | 保留因果清晰的旧基线，ACL-aware switch 留给 E3 | [E2-C08](e2_parser_index_lifecycle_implementation.md) |
| `E2-D06` | parent-child MRR 最高是否立刻设默认 | 不自动切换；记录成本和 comparison regression，E3 后再 admission | `[OBSERVED]` BM25 dev ablation | 避免用 18 道 synthetic dev 的单一均值替代端到端证据 | [E2-C09](e2_parser_index_lifecycle_implementation.md) |

## 8. E2 故障总账

| ID | 用户看到的症状 | 原因或最可信解释 | 修复 | 证据等级 | 详细记录 |
|---|---|---|---|---|---|
| `E2-I01` | pip 安装 124 秒无输出，超时后仍有两个子进程 | 外层 timeout，子进程连接停留在本机代理；不是完全断网 | 只终止本次遗留进程，逐包 no-cache/有限 retry 安装 | `[OBSERVED]` 进程/包状态/pip check；代理内部原因未强推 | [E2-I02](e2_parser_index_lifecycle_implementation.md) |
| `E2-I02` | 新字段后旧 timezone test 报字段缺失 | test helper 没补 `filed_department`，先于目标 validator 失败 | 只更新 fixture 合法默认值 | `[OBSERVED]` 26 ingestion tests | [E2-I03](e2_parser_index_lifecycle_implementation.md) |
| `E2-I03` | 一个 duplicate variant 被选成 canonical | authority 同级后按 doc ID，`duplicate_*` 字母序领先 | 新增 variant precedence 和真实语料 RED | `[OBSERVED]` duplicate canonical 1 -> 0 | [E2-I04](e2_parser_index_lifecycle_implementation.md) |
| `E2-I04` | C06 写完后对话看起来停止，handoff 落后一步 | 上下文压缩发生在代码写入与测试/记录之间 | 查文件、进程和测试，不凭聊天记忆猜；同步持久 handoff | `[OBSERVED]` 后台 0、C06 8 passed | [E2-I05](e2_parser_index_lifecycle_implementation.md) |
| `E2-I05` | force 可重写当前 active run | 原子 pointer 不保护被原地替换的目录，崩溃窗口会造成 hash mismatch | active run 在 embedding 前拒绝覆盖，要求新 run ID | `[OBSERVED]` 新 RED/GREEN | [E2-I06](e2_parser_index_lifecycle_implementation.md) |
| `E2-I06` | 多文件 patch context verification failed | 长 patch 对持续变化文件的匹配范围过大 | 验证无半落盘后拆成小 patch | `[OBSERVED]` Test-Path/diff/tests | [E2-I07](e2_parser_index_lifecycle_implementation.md) |
| `E2-I07` | 局部测试通过，全量 pytest collection 报 import file mismatch | corpus/indexing 都叫 `test_cli.py`，无 package namespace 时模块名冲突 | 新测试改名 `test_index_cli.py` | `[OBSERVED]` 双 CLI 9 passed；full 225 passed | [E2-I08](e2_parser_index_lifecycle_implementation.md) |

## 9. E2 实验

| ID | 问题 | 固定条件 | 结果 | 决策 | 详细记录 |
|---|---|---|---|---|---|
| `E2-X01` | fixed/heading/parent-child 哪个更适合当前 corpus | demo dev answered+gold 18；BM25/jieba；ACL；unique-doc top-5；不读 test | Recall 0.8333/0.8611/0.8611；MRR 0.3769/0.5157/0.5898；comparison 三者均未完整召回 | 不宣称全面提升，不改默认；E3 做 metadata/authority/query decomposition 后再测 | [E2-C09](e2_parser_index_lifecycle_implementation.md) |

## 10. E2 已知边界

| ID | 当前边界 | 证据 | 面试时应该怎么说 | 详细记录 |
|---|---|---|---|---|
| `E2-L01` | pypdf 不做 OCR，扫描件可能没有文本 | `[OBSERVED]` parser behavior/tests | “R1 对 image-only PDF fail closed，OCR 属于后续扩展” | [E2-C02](e2_parser_index_lifecycle_implementation.md) |
| `E2-L02` | v2 loader 已有，但 production retrieval 仍使用 legacy index | `[OBSERVED]` adapter guard | “E2 完成索引供给面，E3 才接 ACL-aware retrieval” | [E2-C08](e2_parser_index_lifecycle_implementation.md) |
| `E2-L03` | 消融是 18 道 synthetic dev 的 BM25-only 结果 | `[OBSERVED]` experiment config/hash | “它隔离 chunking，不代表 dense、回答或 Agent 质量” | [E2-C09](e2_parser_index_lifecycle_implementation.md) |
| `E2-L04` | R1 是安全全量重建，不支持增量 upsert/delete | `[OBSERVED]` store API/scope | “版本化 full rebuild 先保证一致性，增量生命周期属于 R2” | [E2-C07](e2_parser_index_lifecycle_implementation.md) |

## 11. E3 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E3-D01` | 新 Agent 是否直接替换旧 `/chat` 和 `/agent/chat` | 新增并行 `/agent/v2/chat` 垂直链路，保留 legacy 作为 E4 基线 | `[OBSERVED]` API、runner 和 compatibility tests | 可以比较新旧行为，v2 失败不会静默回退到无 ACL 的旧检索 | [E3-C09](e3_retrieval_agent_workflow_implementation.md#e3-c09generation-adapter-与-agentv2chat) |
| `E3-D02` | ACL 是检索后过滤，还是候选打分前过滤 | tenant、region、group 全部满足后，候选才可进入 fusion、context 和公开结果；不满足时 fail closed | `[OBSERVED]` access/pipeline/navigation tests | denied chunk 不影响排名，也不进入 source、trace 或 public error | [ACL 与检索](e3_beginner_learning_and_interview.md#4-从-acl-到检索结果) |
| `E3-D03` | QueryAnalysis 是否全部交给 LLM | unsafe、明确 intent、comparison decomposition 和时间规则 deterministic first；LLM 只给 schema-valid candidate，规则可否决 | `[OBSERVED]` analyzer tests | 硬安全边界可复现，fallback 不能扩大权限或绕过 unsafe | [Rule-first 边界](e3_beginner_learning_and_interview.md#6-rule-first-与-llm-fallback-的边界) |
| `E3-D04` | 模型是否可以自由决定工具、循环次数和停止条件 | Python registry/controller 强制 allowlist、分工具计数、step/context/deadline；模型不能递归调用工具 | `[OBSERVED]` tool/controller/runner tests | Agent 有清晰的最坏执行上界，budget failure 可测试 | [Budget 与 Controller](e3_beginner_learning_and_interview.md#9-budgetcontroller-和-runner) |
| `E3-D05` | 有 source list 是否就算引用正确 | 把 claim、声称引用的 chunk 和可见 evidence 建立显式关系；hard presence/visible checks 与 lexical heuristic 分开 | `[OBSERVED]` citation tests；`[OBSERVED]` dev no-answer failure | 可以抓无引用和引用不可见资源，但不冒充 semantic entailment | [Claim citation](e3_beginner_learning_and_interview.md#8-claim-level-citation-到底检查什么) |
| `E3-D06` | API 能否从服务端猜用户身份；unsafe 是否也先加载索引 | `/agent/v2/chat` 强制显式 `UserContext`；default runner lazy 构造，unsafe 在 snapshot/embedding/retrieval 前短路 | `[OBSERVED]` API/security tests | 缺身份请求被 schema 拒绝；unsafe probe 为 zero-tool | [Generation 与 API](e3_beginner_learning_and_interview.md#10-generation-和-api) |

## 12. E3 故障总账

| ID | 用户看到的症状 | 原因或最可信解释 | 修复 | 证据等级 | 详细记录 |
|---|---|---|---|---|---|
| `E3-I01` | 标准隔离 worktree 看不到 E0-E2 新模块 | E0-E2 都是当前 checkout 的未提交前置，worktree 只从 HEAD 建立 | 留在当前 checkout，小步 TDD，继续禁止 Git 写操作 | `[OBSERVED]` Git 状态和 baseline 225 passed | [E3 开工基线](e3_retrieval_agent_workflow_implementation.md#3-开工基线) |
| `E3-I02` | C01 首次 GREEN collection 报 `app/domain/__init__.py` IndentationError | patch 把部分 `__all__` 名称插在 list 结束符之后 | 只修 export list 结构，随后重跑 domain 和 E2 回归 | `[OBSERVED]` 25 domain + 77 E2 tests | [E3 incident table](e3_retrieval_agent_workflow_implementation.md#6-incidentexperiment-状态) |
| `E3-I03` | C04 11 passed、1 个 fixture `TypeError` | 参数化测试同时显式和通过 `**dict` 传入 `doc_id`，业务函数尚未被调用 | 先建默认 dict，再用 `update()` 覆盖；ACL 断言不变 | `[OBSERVED]` 12 pipeline + 133 combined tests | [E3 incident table](e3_retrieval_agent_workflow_implementation.md#6-incidentexperiment-状态) |
| `E3-I04` | C05 有 3 个 setup error，security 测试找不到 `chunk_factory` | fixture 位于 sibling `tests/retrieval/conftest.py`，Pytest 不向兄弟目录暴露 | 在根 `tests/conftest.py` 共享 fixture | `[OBSERVED]` 13 navigation + 146 combined tests | [E3 incident table](e3_retrieval_agent_workflow_implementation.md#6-incidentexperiment-状态) |
| `E3-I05` | citation verifier 不知道 claim 声称引用了哪个 chunk | 初版 `Claim` contract 缺少 citation candidate 字段 | 增加默认空 `cited_chunk_ids`，保持旧构造兼容；verifier 去重并做 hard checks | `[OBSERVED]` 26 C07/domain + 187 combined tests | [E3 incident table](e3_retrieval_agent_workflow_implementation.md#6-incidentexperiment-状态) |
| `E3-I06` | C10 计划中的 `demo_dev.jsonl/metadata.json` 找不到 | 计划示例与 E1 已落盘 canonical contract 不一致；实际是 `eval/dev.json` JSON array | evaluator 读取真实 E1 contract，不复制一份新数据，也不读取 frozen test | `[OBSERVED]` 文件布局和 evaluator tests | [E3-C10](e3_retrieval_agent_workflow_implementation.md#e3-c10dev-behavior-audit-failure-driven-gate-and-e3-verification) |
| `E3-I07` | 第二次 dev 计算结束后，staging directory rename 报 `WinError 5` | target 不存在、父目录可写、后台 0；最可信是 Windows 短暂目录句柄/rename 拒绝，不能百分百确定 | 使用绝对路径；仅对 `PermissionError` 最多重试五次；每次检查并发 target；其他错误立即失败并清 staging | 根因 `[INFERRED]`；修复和 writer test `[OBSERVED]` | [Writer incident](e3_retrieval_agent_workflow_implementation.md#writer-incident) |
| `E3-I08` | 最终门禁先显示 hash mismatch、后台进程 1 和 pytest cache WinError 5 | hash 检查误把 manifest 文件名算入；并行进程检查看到了 pytest 本身；旧 `.pytest_cache` 关闭 ACL 继承，Python sandbox SID 无权 stat 子目录 | 提取 manifest 首 token、测试结束后串行查进程、只给 cache 恢复继承；不改业务代码 | `[REPRODUCED]` Python stat；`[OBSERVED]` hash match、后台 0、targeted 6 和 full 380 无 cache warning | [Final gate diagnostics](e3_retrieval_agent_workflow_implementation.md#final-gate-diagnostics-incident) |

## 13. E3 实验

| ID | 问题 | 固定条件 | 结果 | 决策 | 详细记录 |
|---|---|---|---|---|---|
| `E3-X01` | v2 Agent 在 demo dev 上的第一轮行为基线是什么 | E1 demo dev 24 cases；fixed chunks；128D stable hash embedding；extractive deterministic runner；不读 frozen test | outcome 20/24；comparison 4/4；permission 2/2；unsafe 1/1；budget/trace/forbidden 全通过；四个 no-answer 被错误 answered | 不掩盖失败；逐题追到“命中政策不等于命题被支持” | [第一次 dev run](e3_retrieval_agent_workflow_implementation.md#第一次真实-dev-run) |
| `E3-X02` | query-anchor gate 是否修复四个 false answer，是否破坏其他 case | 与 X01 同条件，只新增 relevance admission gate | outcome 24/24；只有四个 no-answer mode 变为 not_found，其他 20 个 mode/failure 不变；citation 分母 26 -> 22 | 保留 gate；明确标记 dev-driven regression，E4 再做 frozen/人工评估 | [Query-anchor gate](e3_retrieval_agent_workflow_implementation.md#query-anchor-gate) |

## 14. E3 已知边界

| ID | 当前边界 | 证据 | 面试时应该怎么说 | 详细记录 |
|---|---|---|---|---|
| `E3-L01` | 第二次 24/24 使用了第一次 dev failure 反馈，不是 unseen/final | `[OBSERVED]` 两次 artifact 和改动顺序 | “这是 failure-driven dev regression；frozen test 在 E4 前未读” | [两次 dev 实验](e3_beginner_learning_and_interview.md#12-两次-dev-实验怎么解释) |
| `E3-L02` | query-anchor 和 citation relevance 都是 lexical heuristic，不理解完整语义蕴含 | `[OBSERVED]` implementation/tests | “能抓显式年份和词项缺失，仍可能同义词 false negative 或表面重合 false positive” | [从命中到支持](e3_beginner_learning_and_interview.md#7-从命中到支持) |
| `E3-L03` | deterministic hash embedding、extractive generation 和 synthetic corpus 不等于真实 Ollama/企业流量 | `[OBSERVED]` evaluator mode/data source | “C10 先测工作流 contract 和安全不变量；真实模型质量、延迟和人工正确性留到 E4/E5” | [E3-C10](e3_retrieval_agent_workflow_implementation.md#e3-c10dev-behavior-audit-failure-driven-gate-and-e3-verification) |
| `E3-L04` | R1 没有真实 IAM、服务端向量 ACL、durable execution、hot reload 或线上 observability | `[OBSERVED]` current modules/scope | “当前是单进程可复现 R1；这些能力不会靠接口名冒充” | [当前边界](e3_beginner_learning_and_interview.md#17-当前可以和不可以说什么) |
| `E3-L05` | snapshot/default runner 有进程内缓存，active index 切换后需要进程重启才能保证重新加载 | `[OBSERVED]` lazy cached construction | “E2 的磁盘 active pointer 可原子切换；运行时热更新和并发 reload 属于后续生命周期工作” | [E3 实施记录](e3_retrieval_agent_workflow_implementation.md) |

## 15. E3 阶段验收

```text
E3 focused domain/retrieval/security/agent_v2 155 passed, 5 warnings
legacy controller/runner/API/RAG               24 passed, 5 warnings
full repository                               380 passed, 5 warnings
pip check                                      clean
compileall app/scripts/tests                   ok
git diff --check                               exit 0, CRLF notices only
frozen test hash                               unchanged
project Python/pip background                  0
```

warning 来自 FAISS SWIG deprecation 和 legacy FastAPI `on_event` deprecation；后者的 lifespan 迁移属于 E5。

## 16. E4 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E4-D01` | 最终答案错了，怎么知道该改检索还是生成 | 分成 retrieval/answer/agent/security 四层，保存每层 metrics 与 failure signals | `[OBSERVED]` evaluation contracts/suite/artifacts | 可以按最早失败阶段定位，而不是用一个 accuracy 猜根因 | [E4-C01-C05](e4_evaluation_ablation_implementation.md) |
| `E4-D02` | 是否让另一个 LLM 判断所有答案 | gold facts/docs、ACL、budget、trace 和 citations 用 code hard gates；语义质量留空白人工抽检，未来 LLM judge 只作校准后辅助 | `[OBSERVED]` answer/security evaluators；50-row blank CSV | 自动结果稳定可复现，同时不冒充最终人工 factuality | [Failure attribution](e4_beginner_learning_and_interview.md#7-failure-attribution-是否需要另一个-llm) |
| `E4-D03` | 失败 run 能否被成功 run 覆盖 | 每个 run ID 不可覆盖，staging 校验后发布，manifest 保存 artifact hashes 和完整 provenance | `[OBSERVED]` writer tests/manifests | before/after 故障证据永久保留，可复查 dirty HEAD 与模型配置 | [Run artifacts](../evaluation.md#8-run-artifacts) |
| `E4-D04` | ACL/authority 能否作为质量消融开关 | 永远开启，只消融 BM25/dense/RRF/metadata/diversity/workflow | `[OBSERVED]` ablation implementation/results | 不用安全和当前版本正确性换取表面召回 | [E4-C06](e4_evaluation_ablation_implementation.md#13-e4-c06ablation-与-blank-human-review) |
| `E4-D05` | Agent 是否必须逐步匹配唯一标准轨迹 | exact trajectory 只作 deterministic 辅助，live hard gate 拆成 intent/tool/decomposition/budget/stop/outcome | `[OBSERVED]` agent evaluator/tests | 允许多条合理路径，又能抓必要步骤缺失和无界执行 | [Agent 指标](e4_beginner_learning_and_interview.md#6-agent-指标为什么不只比-exact-sequence) |
| `E4-D06` | fake 与真实模型结果是否混在一起 | deterministic 与 live 是不同 runtime variant，manifest 明确 embedding/chat/index/calls，live 不可回退 | `[OBSERVED]` runtime tests 和 run manifests | CI contract 与本机模型质量各自可解释 | [运行环境](e4_beginner_learning_and_interview.md#35-运行环境) |

## 17. E4 故障总账

| ID | 用户看到的症状 | 原因或最可信解释 | 修复 | 证据等级 | 详细记录 |
|---|---|---|---|---|---|
| `E4-I01` | 设计审计读取 `app/corpus/models.py`、v2 metadata 失败 | 计划示例路径与 E1 实际 schema/artifact 布局不同 | 用 `rg --files` 找真实 contract，不创建重复 metadata；并行只读用 all-settled | `[OBSERVED]` 文件布局与实施记录 | [E4-I01](e4_evaluation_ablation_implementation.md#6-incidents) |
| `E4-I02` | deterministic runtime smoke test 2 failed | smoke fixture 只有 retired 版本，不满足每个 policy 恰有一个 active authority 的 corpus 级治理约束 | 测试在 temp 中生成完整 demo；不放宽 production governance | `[OBSERVED]` stack trace、diagnostic build、runtime tests | [Runtime RED/GREEN](e4_evaluation_ablation_implementation.md#runtime-redgreen-与-e4-i02) |
| `E4-I03` | security regression 命令立刻退出、0 tests | 计划引用了不存在的 `test_api_security.py` | `rg --files` 找到真实 zero-leak/API 文件后重跑 | `[OBSERVED]` 首次 pytest error 与 30 passed | [E4-C04](e4_evaluation_ablation_implementation.md#11-e4-c04security-evaluator) |
| `E4-I04` | 首个 dev suite 20/24，四个 no-answer 全报 intent mismatch | evaluator 把查证后的 `not_found` outcome 错当成输入 intent 必须为 `no_answer` | 参数化 RED 后接受 fact/process/completeness/no_answer evidence-seeking intents | `[OBSERVED]` 两次 immutable dev runs、3 RED/1 pass、16 GREEN | [C07 dev audit](e4_evaluation_ablation_implementation.md#14-c07-dev-audit-与开发冻结) |
| `E4-I05` | 并行门禁出现 file-not-found，单组测试原本稳定 | 两个 pytest 共享 `pytest.ini --basetemp=data/eval_outputs/pytest_tmp`，互相清理临时目录 | 所有 pytest 门禁串行；不改业务 fixture 掩盖调度问题 | `[OBSERVED]` 2 failed/79 passed 后串行 81/461 passed | [E4-I05](e4_evaluation_ablation_implementation.md#e4-i05并行-pytest-共享-basetemp) |
| `E4-I06` | 首个 live suite 只有 6/24，18 个 answered 全部 system | 完整 JSON Schema 无法被当前 Ollama/llama.cpp 编译为 grammar，API 返回 400 `failed to parse grammar` | 先加 RED；sampling schema 仅保留兼容结构，Pydantic 严格校验不变 | `[REPRODUCED]` 单 API 探针；`[OBSERVED]` 1 RED、10 GREEN、live 23/24 | [Live schema incident](e4_evaluation_ablation_implementation.md#e4-i06ollama-json-schema-grammar-400) |

## 18. E4 实验

| ID | 问题 | 固定条件 | 结果 | 决策 | 详细记录 |
|---|---|---|---|---|---|
| `E4-X01` | 四层 deterministic dev contract 是否成立 | 24 synthetic dev；fixed 500/80；hash-128；extractive；top-k 5；ACL | evaluator label 修正后 retrieval/answer/agent/security 24/24，injection 0/4 | 冻结 E4 参数，再首次正式读 test | [Dev audit](e4_evaluation_ablation_implementation.md#14-c07-dev-audit-与开发冻结) |
| `E4-X02` | 冻结 test 是否保持相同行为 | hash `556ffe...43338`；28 synthetic test；与 dev 相同 deterministic config | 四层 28/28；answered Recall@5 21/21；injection 0/4 | 不依据 test 继续调参，只称 frozen regression | [Frozen test](e4_evaluation_ablation_implementation.md#15-frozen-test-正式运行) |
| `E4-X03` | 真实 bge-m3/qwen 是否能跑完整链路 | 64 fixed chunks；bge-m3 1024D；qwen2.5:3b；24 dev | schema 修复前 6/24，修复后 23/24；retrieval/security 24/24；唯一 system 单题重放通过 | 保留失败 run；E5 再评估一次有界 retry/telemetry | [Live dev](e4_evaluation_ablation_implementation.md#17-真实-ollama-live-dev-验证) |
| `E4-X04` | 哪些 retrieval/Agent 组件有可归因收益 | 同 split/index/top-k/candidate-k/ACL；BM25/dense/RRF/metadata/diversity；fixed vs bounded Agent | deterministic test 与 live dev 均是 metadata/temporal 达 Recall/authority/pass 1.0；Agent 修复四个 no-answer但显著增加成本 | 保留 metadata/temporal 和 bounded stopping；reranker NOT RUN；parent 收益未证明 | [Ablation report](../ablation_report.md) |

## 19. E4 已知边界

| ID | 当前边界 | 证据 | 面试时应该怎么说 | 详细记录 |
|---|---|---|---|---|
| `E4-L01` | 24/28 case 都来自同一 synthetic facts/generator，小样本 perfect score 不代表总体 | `[OBSERVED]` data card/manifests | “它是受控 regression benchmark，不是生产准确率” | [结果表达](e4_beginner_learning_and_interview.md#13-结果数字怎么讲才诚实) |
| `E4-L02` | 50 条人工抽检尚未由本人填写 | `[OBSERVED]` 50 rows、400 judgment cells blank | “自动 hard gates 已运行，语义人工验收仍 pending” | [人工抽检](e4_beginner_learning_and_interview.md#12-人工抽检要怎么做) |
| `E4-L03` | live 只跑本机 dev、单并发和一次主要 run，不能代表 SLA 或稳定性分布 | `[OBSERVED]` live manifests | “E5 才做 concurrency 1/5/10、cold/warm p50/p95 和 error profile” | [Live results](../ablation_report.md#7-live-dev-消融) |
| `E4-L04` | citation verifier 主要是 presence/visibility/lexical support，不是完整 semantic entailment | `[OBSERVED]` verifier/evaluator code | “hard gate 能防无引用和不可见引用，同义与复杂推理仍需人工/校准 judge” | [Answer metrics](e4_beginner_learning_and_interview.md#5-answer-指标怎么避免有引用就算对) |
| `E4-L05` | live generation 有一次偶发 source-free system，尚无错误 telemetry 和有界 generation retry | `[OBSERVED]` live 23/24、单题重放 pass | “当前 fail closed；重试/可观测性作为 E5 admission，不掩盖失败” | [E4-I06](e4_evaluation_ablation_implementation.md#e4-i06ollama-json-schema-grammar-400) |

## 20. E4 阶段验收

```text
generation + E4 focused             91 passed, 3 warnings
legacy evaluator regression         30 passed, 3 warnings
full repository                    462 passed, 5 warnings
pip check                            clean
compileall                           exit 0
git diff --check                     exit 0, CRLF notices only
frozen test hash                     match
evaluation artifact manifests       9/9 verified
active v2 index                      load OK, bge-m3 1024D, 64 chunks
human review                         50 rows, 0 judgments filled
```

Warnings 是 FAISS SWIG deprecation 和 legacy FastAPI `on_event` deprecation；lifespan migration 属于 E5。E4 implementation complete，等待本人验收；未 commit、push、merge 或进入 E5。

## 21. 如何使用这张表

面试准备时不要背 ID。选择一个故障，按下面顺序讲：

```text
症状
-> 我最初怀疑什么
-> 我用什么实验排除它
-> 最终修复放在哪个函数
-> 哪个测试防止复发
-> 这个证据还不能证明什么
```

如果某一行只有 `[INFERRED]`，面试时必须说“最可能原因”或“根据排除实验推断”，不能说“已经百分之百定位”。

## 22. E5 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E5-D01` | 本地 R1 是否直接上 OTel/Prometheus/Redis | 先做 FastAPI lifespan + ContextVar + bounded in-memory trace/metrics，保留 adapter 边界 | `[OBSERVED]` E5 design、模块和 tests | 低依赖地补齐 request/error/deadline/privacy；明确非分布式 | [E5 设计](../superpowers/specs/2026-07-17-e5-security-service-observability-design.md) |
| `E5-D02` | live 与 ready 是否合并 | live 不探测依赖；ready 独立检查 DB/index/models 并 TTL cache | `[OBSERVED]` resources/API tests | 依赖坏时进程仍 live，ready 503 fail closed | [API](../api.md) |
| `E5-D03` | request metadata 怎么跨层关联 | validated request ID + ContextVar token bind/reset | `[OBSERVED]` context/middleware tests | header、answer trace、error、model spans 和 logs 可关联且不串请求 | [初学者教程](e5_beginner_learning_and_interview.md#5-contextvar-是什么) |
| `E5-D04` | 网络重试和 JSON shape 重试是否合并 | transport transient retry 与 generation shape retry 分层，各自最多 2 attempts | `[OBSERVED]` transport/generation tests | 调用上限可算，不对普通 4xx/no-answer 盲重试 | [初学者教程](e5_beginner_learning_and_interview.md#8-transport-retry-与-structured-retry-的区别) |
| `E5-D05` | telemetry 是否保存问题/答案方便调试 | 默认只存 allowlisted metadata；正文进入受控 eval/人工流程 | `[OBSERVED]` seeded secret scans | trace/metrics/load artifacts 零正文，降低复制和访问面 | [Observability](../observability.md) |
| `E5-D06` | feedback 是否继续存完整正文 | 新表只存 request ID、question/answer SHA256、helpful、时间 | `[OBSERVED]` SQLite byte scan | 新写入无明文；同时承认 hash 非匿名化 | [Threat model](../security_threat_model.md) |
| `E5-D07` | CI 是否启动 Ollama | CI 只做 deterministic pins/hash/compile/full tests；live 本机独立 | `[OBSERVED]` workflow/config tests | GitHub gate 稳定，不把 runner/model差异混入 contract | [Reproducibility](../reproducibility.md) |
| `E5-D08` | 负载失败能否重跑覆盖 | run ID 不可覆盖、staging + hash + atomic publish | `[OBSERVED]` load tests/manifests | 首份 RSS-null artifact保留，修复后发布 r2 | [Load evidence](../observability.md#8-load-profile-artifact) |

## 23. E5 故障总账

| ID | 用户看到的症状 | 根因 | 修复 | 证据等级 | 详细记录 |
|---|---|---|---|---|---|
| `E5-I01` | tracing 隐私 test 把合法 `answered` 误报 | test 用 substring `answer`，oracle 过宽 | 收集 JSON keys 做 exact-key；production 不改 | `[OBSERVED]` 1 failed/14 passed 后 15 passed | [E5-C02](e5_security_service_observability_implementation.md#9-e5-c02bounded-tracing-与-metrics) |
| `E5-I02` | transport deadline test 报已过期 | request context 用 fake 0ms，transport 用 real monotonic | 注入并共享同一 MutableClock | `[OBSERVED]` failing stack + GREEN | [E5-C03](e5_security_service_observability_implementation.md#10-e5-c03deadline-aware-model-transport) |
| `E5-I03` | structured generation 实际 2 attempts 但 trace 写 1 | helper 抛异常前 tuple 未赋值 | safe internal exception 携带整数 attempts，不带 raw output | `[OBSERVED]` RED/GREEN | [E5-C03](e5_security_service_observability_implementation.md#10-e5-c03deadline-aware-model-transport) |
| `E5-I04` | `scripts.load_profile` 导入出现 circular import | runtime package eager import resources，resources 反向依赖 tracing | `app.runtime.__getattr__` lazy exports | `[OBSERVED]` collection traceback + 6 GREEN | [E5-C06](e5_security_service_observability_implementation.md#13-e5-c06可复现负载证据) |
| `E5-I05` | full pytest import file mismatch | evaluation/observability 都有 `test_metrics.py`，default prepend 冲突 | `--import-mode=importlib` + config regression | `[OBSERVED]` collection error + full gate | [E5-C07](e5_security_service_observability_implementation.md#14-e5-c07确定性-ci-与测试配置) |
| `E5-I06` | full pytest 108 个 tmp_path setup WinError 5 | `%TEMP%/pytest-of-<local-user>` ACL protected 且无当前用户显式访问 | 验证位于用户 TEMP 后只恢复该目录 ACL 继承/权限 | `[OBSERVED]` 417 pass/108 error -> 525 pass | [E5-C07](e5_security_service_observability_implementation.md#14-e5-c07确定性-ci-与测试配置) |
| `E5-I07` | 第一条 authorized live smoke 返回 system | bge-m3 cold embed 4625ms，加检索后超过 search 5000ms budget | 保留 fail-closed 证据；同题 warm 重放 search 203ms answered；不凭一次失败盲调 timeout | `[OBSERVED]` request trace、重放 | [Cold incident](../observability.md#10-cold-start-incident) |
| `E5-I08` | load 将 HTTP 200 `mode=system` 算成功 | 混淆协议成功与业务完成 | RED 后 system/budget 分别计 `agent_system/agent_budget` failure | `[OBSERVED]` 2/2 错误计数 -> 1/3 正确计数 | [Load profiler](e5_beginner_learning_and_interview.md#14-load-profiler-怎么保证证据可信) |
| `E5-I09` | live load manifest RSS 为 null | ctypes 默认 32 位返回截断 64 位 pseudo HANDLE，WinError 6 | 声明 WinAPI restype/argtypes + Windows-only test；新 run ID r2 | `[REPRODUCED]` exact WinError 6、RED/GREEN、r2 RSS | [RSS 根因](e5_beginner_learning_and_interview.md#17-rss-bug-的代码级根因) |
| `E5-I10` | `.gitignore` 一次写成 `loadnload_runs/` | 手工机械输入错误 | 在门禁前改回 `load_runs/` 并记录 | `[OBSERVED]` patch sequence | [E5-C06](e5_security_service_observability_implementation.md#13-e5-c06可复现负载证据) |

## 24. E5 实验

| ID | 问题 | 固定条件 | 结果 | 决策 | 详细记录 |
|---|---|---|---|---|---|
| `E5-X01` | 单机并发 1/5/10 的尾延迟和错误如何变化 | 64 fixed chunks；bge-m3/qwen2.5:3b；每档10；30s client timeout；同一 active index | r2 31/31；warm p95 1.136s/4.406s/8.633s；62 model calls；0 retry/error | 保留当前有界服务；承认并发排队显著，不声称 SLA | [Live result](../observability.md#9-e5-live-结果) |
| `E5-X02` | RSS probe 修复后能否产生真实内存证据 | 同 X01；WinAPI FFI 修复；新不可覆盖 run | 92,991,488 -> 159,088,640，+66,097,152 bytes；hash match；secret scan 0 | 报告工作集增长但不据两个点声称 leak | [Live result](../observability.md#9-e5-live-结果) |

## 25. E5 已知边界

| ID | 当前边界 | 证据 | 面试时应该怎么说 | 详细记录 |
|---|---|---|---|---|
| `E5-L01` | caller-supplied UserContext 不是认证 | `[OBSERVED]` API schema/no IAM | “验证了 ACL policy contract；生产必须由可信 IAM 注入身份” | [Threat model](../security_threat_model.md) |
| `E5-L02` | traces/metrics 是单进程内存，重启丢失 | `[OBSERVED]` deque store | “R1 可本地关联；多服务再接 OTel/collector” | [Observability](../observability.md) |
| `E5-L03` | observability endpoints 无认证 | `[OBSERVED]` routes | “仅本机演示，不能公网开放” | [API](../api.md) |
| `E5-L04` | 31 requests 小样本不能证明 SLA/容量 | `[OBSERVED]` manifest/config | “展示尾延迟趋势和失败口径，不外推生产 QPS” | [Load result](../observability.md#9-e5-live-结果) |
| `E5-L05` | SHA256 feedback 可关联/字典枚举 | `[OBSERVED]` DB schema | “无明文不等于匿名化，仍需 retention/access/privacy review” | [Threat model](../security_threat_model.md) |
| `E5-L06` | Python 无法硬取消已进入 native code 的同步调用 | `[OBSERVED]` runtime design | “边界是 socket timeout、deadline checks 和有界循环” | [API timeout](../api.md#12-timeout-和-retry) |

## 26. E5 阶段验收

```text
API/observability/security          47 passed, 3 warnings
evaluation                          81 passed, 3 warnings
full repository                    526 passed, 3 warnings
pip check                            clean
compileall                           exit 0
git diff --check                     exit 0, line-ending notices only
frozen test hash                     match
load r1/r2 managed hashes            4/4 match
load r2                              31/31, leak scan 0, RSS available
active index                         64 chunks, bge-m3 1024D
project Python/pip background        0
git index lock                       false
```

E5 implementation complete，等待本人验收；未 commit/push/merge，也不进入 E6。

## 27. E6 设计决策

| ID | 白话问题 | 选择 | 证据 | 结果 | 详细记录 |
|---|---|---|---|---|---|
| `E6-D01` | 演示页是每次重跑全部评估，还是只展示手写数字 | Ask/Trace 调 live API；Evaluation 读取由 canonical artifacts 校验 hash 后导出的严格 public snapshot | `[OBSERVED]` snapshot tests、真实 API/browser run | 在线能力真实，公开 clone 又不依赖 ignored 大 artifacts | [E6-C02/C07](e6_demo_public_repo_implementation.md) |
| `E6-D02` | Trace 是否直接序列化 EvidenceLedger | 只输出 required/supported/missing/conflicting/coverage/recommended_action 派生摘要，最后仍统一 redaction | `[OBSERVED]` runner/security tests | 可解释“为何继续/停止”，不扩大问题、身份和证据正文暴露面 | [E6-C01](e6_demo_public_repo_implementation.md#4-e6-c01安全的证据充分性摘要) |
| `E6-D03` | Streamlit 是否直接拼 requests/JSON | API client、canonical case loader、pure view models、page 四层分开 | `[OBSERVED]` 21 UI tests | 协议、safe error、展示转换和交互可分别测试 | [E6-C03/C04](e6_demo_public_repo_implementation.md) |
| `E6-D04` | 演示案例是否手写“完美答案” | 6 个业务案例按 ID 读取 frozen eval，安全案例读取 canonical direct probe；不存 expected answer | `[OBSERVED]` demo-case tests | 演示来源可追踪，不把 indirect injection 冒充已覆盖 | [E6-C03](e6_demo_public_repo_implementation.md#6-e6-c03类型化-ui-边界canonical-案例与纯视图模型) |
| `E6-D05` | 公开前只靠人工看 `.env` 是否足够 | 审计 Git 实际 candidate set，检查 forbidden path、token/key/email、绝对路径、2 MiB、symlink 和本地 Markdown 链接 | `[OBSERVED]` audit RED/GREEN；328/0 | publication boundary 可复现，且 finding 不回显命中 secret | [E6-C05](e6_demo_public_repo_implementation.md#8-e6-c05公开仓库门禁与当前状态文档) |
| `E6-D06` | 面试长稿和未批准 claims 是否放 public docs | 保存到 `.private/e6/`，用 Git behavior test 证明 ignored；claims 全部 `pending_e7` | `[OBSERVED]` 6 repository tests；private candidates 0 | 学习材料完整但不污染公开承诺 | [E6-C06](e6_demo_public_repo_implementation.md#9-e6-c06被-git-排除的面试与学习材料) |
| `E6-D07` | 没有 retrieved-content injection fixture 时如何展示安全 | 明确 `NOT RUN`；只把 4 个 direct user prompt probes 标为已观察 | `[OBSERVED]` snapshot schema/UI | 不用标签替换缺失实验 | [Known limitations](../known_limitations.md) |
| `E6-D08` | AppTest 通过后是否直接发布截图 | 真实启动无 reload API/UI，同 session 验证 Ask/Trace，desktop/mobile 检查 DOM、图表、溢出和 console | `[OBSERVED]` 三张 PNG、移动端数值、真实 request trace | 捕获了单元测试没有暴露的 theme 与 widget lifecycle 问题 | [E6-C07](e6_demo_public_repo_implementation.md#10-e6-c07真实服务联调响应式验收与公开截图) |

## 28. E6 故障总账

| ID | 用户看到的症状 | 根因 | 修复 | 证据等级 | 详细记录 |
|---|---|---|---|---|---|
| `E6-I01` | Custom mode 点击后 `NameError: _csv_values` | Streamlit 从脚本顶部 rerun，分支执行时文件末尾函数尚未定义 | helper 移到所有顶层页面逻辑之前，并增加真实 AppTest 交互 | `[REPRODUCED]` stack trace；1 GREEN/21 UI | [E6-C04](e6_demo_public_repo_implementation.md#7-e6-c04三页-agent-工作台) |
| `E6-I02` | public status test 4/5，历史状态入口仍不合格 | banner 用反引号写文件名，不是可点击相对 Markdown 链接 | 改为 `../PROJECT_STATUS.md` 链接 | `[OBSERVED]` repository contract RED/GREEN | [E6-C05](e6_demo_public_repo_implementation.md#8-e6-c05公开仓库门禁与当前状态文档) |
| `E6-I03` | 浏览器仍出现 Streamlit 默认红色强调色 | CSS 没有覆盖 framework theme token，脚本 rerun也不会完整重载 theme | theme contract RED；新增 `.streamlit/config.toml` 并重启 UI | `[OBSERVED]` 真实首轮渲染与最终截图 | [E6-C07](e6_demo_public_repo_implementation.md#浏览器中发现并修复的两个问题) |
| `E6-I04` | Ask 后切换 Trace，Request ID textbox 真实值为空 | session state 和 widget state 生命周期不同，隔离 AppTest 的预填假设不成立 | `resolve_request_id(custom,current)`；placeholder 显示 current，Fetch 空值时回退 current | `[REPRODUCED]` mobile browser value/placeholder；Fetch HTTP 200 | [E6-C07](e6_demo_public_repo_implementation.md#问题二trace-输入框跨页后为空) |
| `E6-I05` | 第一次进程停止命令在 PowerShell 解析阶段退出 | 双引号字符串 `$id:` 被当成带 scope 的变量名 | 改为 `${id}:`；确认首次未执行后再按 PID/command marker 清理 | `[OBSERVED]` parser error；ports/project process 归零，Ollama 保留 | [E6-C07](e6_demo_public_repo_implementation.md#清理脚本的小故障) |

## 29. E6 浏览器实验

| ID | 问题 | 固定条件 | 结果 | 决策 | 详细记录 |
|---|---|---|---|---|---|
| `E6-X01` | 三页是否能连接真实 Agent 并形成同 request 证据链 | 1440x1000；canonical single policy；live index/model；同 browser session | Ask answered/completed、1/1 claims；Trace search->answer、coverage 100%、HTTP 200、2 model calls、0 retries | 保留 live Ask/Trace；截图不使用 mock response | [E6-C07](e6_demo_public_repo_implementation.md#10-e6-c07真实服务联调响应式验收与公开截图) |
| `E6-X02` | Evaluation 是否显示可公开、非四舍五入的真实证据 | checked-in strict snapshot；不读 ignored runs | 28/28、23/24、31/31；8 ablations；SVG 970x280 非空；indirect injection NOT RUN | public snapshot 作为 clone 可读摘要，ignored artifacts 仍是 authority | [E6-C07](e6_demo_public_repo_implementation.md#evaluation公开快照的真实显示) |
| `E6-X03` | 390px 是否出现整页横向滚动 | 390x844；三页；sidebar、长 ID、metrics、tables、chart | Ask/Trace client/scroll width 都为 390；metrics 单列；tables 只内部滚动；导航可用 | 当前响应式契约通过；不额外提交重复 mobile PNG | [Asset contract](../assets/README.md) |

## 30. E6 已知边界

| ID | 当前边界 | 证据 | 面试时应该怎么说 | 详细记录 |
|---|---|---|---|---|
| `E6-L01` | public snapshot 是 allowlisted 摘要，不替代 ignored 原始 run authority | `[OBSERVED]` exporter/schema/source hashes | “公开 clone 可验证来源引用；完整逐题 artifacts 仍在受控本机” | [E6-C02](e6_demo_public_repo_implementation.md#5-e6-c02可公开可溯源的评估快照) |
| `E6-L02` | retrieved-content indirect injection 没有 fixture | `[OBSERVED]` corpus/eval/snapshot | “direct 4/4 已观察；indirect 明确 NOT RUN，不声称通过” | [Known limitations](../known_limitations.md) |
| `E6-L03` | UI/API 是 localhost demo，没有认证、部署和公网 hardening | `[OBSERVED]` runbook/threat model | “展示工作流和证据，不是 production console” | [Architecture](../architecture.md) |
| `E6-L04` | 截图和 mobile 验收来自一台 Windows 开发机 | `[OBSERVED]` asset hashes/browser run | “验证当前 checkout 的布局；不是跨浏览器兼容矩阵” | [Assets](../assets/README.md) |
| `E6-L05` | 人工 semantic review 与 candidate claims 仍未审批 | `[OBSERVED]` blank review、10 pending claims | “hard gates 已完成，语义人工判断和简历措辞进入 E7” | [Known limitations](../known_limitations.md) |

## 31. E6 首轮门禁（被独立审查取代）

```text
UI/public snapshot/repository       32 passed, 3 warnings
API/security                        31 passed, 3 warnings
full repository                    558 passed, 3 warnings
pip check                            clean
compileall                           exit 0
git diff --check                     exit 0, line-ending notices only
frozen test hash                     exact match
public snapshot                      10,126 bytes, 5 source hashes
active index                         manifest match, 64 chunks, bge-m3 1024D
browser                              desktop/mobile passed, 3 PNGs
public audit                         328 candidates, 0 findings
private Git candidates               0
project Python / ports               0 / closed
Ollama                               kept running
git index lock                       false
```

Warnings 仅为 FAISS SWIG type deprecations。该首轮结论随后被独立 review 重新打开，只保留为 before evidence，不能作为最终验收。

## 32. E6 独立审查故障与修复

| ID | 审查发现 | 根因 | 修复 | RED/GREEN | 详细记录 |
|---|---|---|---|---|---|
| `E6-R01` | clean clone full pytest 必然缺 `.private/e6` | public test 把 ignored 私有内容存在性当 CI contract | 不存在时只验 ignore/candidate；本机存在时加强内容检查；CI 增加 audit | CI contract 1 fail -> 10 combined pass | [C09](e6_demo_public_repo_implementation.md#13-e6-c09审查问题的代码级修复与第二轮浏览器验收) |
| `E6-R02` | header/body 都错成另一个 ID 仍被 client 接受 | 只比较响应内部两个 ID，没比较 sent ID | Ask sent/header/body 三方一致；trace lookup 与 target 分开校验 | 2 fail/7 pass -> 9 pass | [13.1](e6_demo_public_repo_implementation.md#131-api-request-correlation) |
| `E6-R03` | Ask 改输入或失败后显示旧结果 | result state 未与当前 input 生命周期绑定 | widget callbacks + pre-submit unified clear | 2 state failures -> GREEN | [13.2](e6_demo_public_repo_implementation.md#132-ask-stale-state-与-trace-cross-request-mixing) |
| `E6-R04` | Trace 把 request A actions 和 request B HTTP 拼在一起 | custom Fetch 只更新 service trace | selected/Agent/service 三 ID 分离；不匹配只显示 service | 2 trace failures -> GREEN + real browser | [13.2](e6_demo_public_repo_implementation.md#132-ask-stale-state-与-trace-cross-request-mixing) |
| `E6-R05` | claim table 看不出 presence/visibility/support 区别 | view model 把 verifier flags 压成一个 status | 加 critical/presence/visible/verdict/reason | 1 fail/4 pass -> 5 pass | [13.3](e6_demo_public_repo_implementation.md#133-claim-verdict-不再压成一个标签) |
| `E6-R06` | strict snapshot 可接受 coercion/duplicate role/伪 ID | extra forbid 不等于 strict/semantic validation | strict types、exact canonical roles、ID derivation validators | 4 fail/4 pass -> 8 pass | [13.5](e6_demo_public_repo_implementation.md#135-strict-snapshot-与-atomic-no-replace) |
| `E6-R07` | promotion race 可覆盖竞争者 target | check-then-`Path.replace()` | same-directory atomic hard-link no-replace | promotion/race tests GREEN | [13.5](e6_demo_public_repo_implementation.md#135-strict-snapshot-与-atomic-no-replace) |
| `E6-R08` | Evaluation 状态硬编码且 provenance 远离数字 | page 常量与过窄 view rows | status/reason/run metadata 全从 snapshot 派生 | 2 fail/13 pass -> 15 pass | [13.6](e6_demo_public_repo_implementation.md#136-evaluation-完全由-snapshot-驱动) |
| `E6-R09` | audit 漏 symlink/binary/runtime/schema/PNG/link | resolve 顺序和 UTF-8-only/selected-surface 假设 | lstat-first、raw bytes+BOM、strict schema、PNG CRC/dimensions、all-doc links | 2 fail -> 8 pass；real 328/0 | [13.7](e6_demo_public_repo_implementation.md#137-publication-audit-hardening) |
| `E6-R10` | `.png` 实际是 JFIF/JPEG | browser screenshot API 返回 JPEG bytes，保存时只改扩展名 | 无缩放重新编码 PNG，并由 audit 固定 signature/CRC/dimensions | real audit 3 invalid_png -> 0 findings | [13.8](e6_demo_public_repo_implementation.md#138-截图格式故障) |

## 33. E6 审查后验收

```text
review remediation focused          47 passed, 3 warnings
full repository                    569 passed, 3 warnings
public snapshot                      strict validation, 8 variants, 5 evidence
browser                              Ask stale clear + cross-request Trace verified
mobile                               all pages 390/390, internal table scroll
screenshots                          3 true PNGs, 1440x1000, CRC/dimensions audited
public audit                         328 candidates, 0 findings
project Python / ports               0 / closed
Ollama                               kept running
```

最终 C10 再次核对 pip clean、compile exit 0、diff exit 0、frozen/snapshot/index match、project process/ports 0、Ollama kept、index lock false。E6 未 commit、push、merge、tag，也未进入 E7；当前为 implementation complete, awaiting user acceptance。

## 34. E7 最终验收设计决策

| ID | 问题 | 决策 | 为什么 | 证据 |
|---|---|---|---|---|
| `E7-D01` | E0-E6 大量结果是否只沿用旧日志 | frozen hash/manifest 可复核的历史 artifact 重新验 hash；deterministic、load、API/browser 生成 E7 fresh evidence | 避免把阶段旧数字冒充最终代码结果，也不篡改 immutable artifacts | [E7 G02-G08](e7_final_acceptance_implementation.md) |
| `E7-D02` | 28/28 是否可称检索/答案准确率 100% | 只称 frozen synthetic deterministic contract 28/28；同时公开 precision@5=0.2381、exact trajectory=24/28、live=23/24 | 不同指标回答不同问题，总 pass 不能覆盖排序、轨迹和真实模型失败 | [E7 G04](e7_final_acceptance_implementation.md#64-e7-g04四层评测与-controlled-ablation) |
| `E7-D03` | Codex 是否填写 human review 完成验收 | 保持 50x8 人工列全空并判 `NOT RUN`；只创建 owner checklist | 自动规则/LLM 不能冒充项目本人语义判断和口述签字 | [E7 G10/G11](e7_final_acceptance_implementation.md#610-e7-g10g11人工专属验收边界) |
| `E7-D04` | trace read 是否也应写入 trace store | 仍记录 header/metrics，但不写回 `TraceSink` | 观测查询回写同一有界 store 会自覆盖目标并挤占业务 trace | [E7 I02/I04](e7_final_acceptance_implementation.md#611-独立-trace-修复审查与-e7-i04) |
| `E7-D05` | claims 是全批通过还是全批拒绝 | 每条 approved/narrowed/rejected；数字保留 mode/n/local/cost/NOT RUN 边界 | 简历措辞是证据约束问题，不是二元营销审批 | [E7 G12](e7_final_acceptance_implementation.md#612-e7-g12claims-evidence-审批) |
| `E7-D06` | E7 起始禁止 push 后如何处理新指令 | 记录授权变化，允许当前功能分支 commit/push/clean clone；仍禁止 merge/tag/default/publicity change | 最新明确用户指令覆盖旧执行范围，但不扩张到未授权仓库操作 | [E7 plan](../superpowers/plans/2026-07-17-e7-final-acceptance.md) |
| `E7-D07` | GitHub push 是否等于 remote CI 通过 | 分成 push SHA、clean-clone reproduction、Actions run URL 三个证据；无 URL 保持 remote CI `NOT RUN` | 网络交付、公开可复现和 CI runner 是三个不同事实 | [Known limitations](../known_limitations.md) |
| `E7-D08` | Linux CI 原生崩溃是否直接锁/降级依赖 | 先用 faulthandler、逐测试名和 failure annotation 定位；确认是 AppTest-only Arrow-to-Pandas 反向路径后收窄测试边界 | exit 139 只有进程结果，猜依赖会掩盖真实调用点；产品渲染和测试读取必须分开验证 | [E7 I13](e7_final_acceptance_implementation.md#620-e7-i13github-actions-linux-exit-139) |

## 35. E7 故障与修复

| ID | 现象 | 根因 | 处理 | 验证 |
|---|---|---|---|---|
| `E7-I01` | `build_indexes_v2 --dry-run --run-id ...` argparse exit 2 | dry-run 不发布 version，run ID 与协议互斥 | 修正验收命令，不放宽 fail-closed CLI | 错误前后 index inventory 相同；正确 dry-run `written=false` |
| `E7-I02` | same-ID Trace GET 第一次正确、第二次返回 trace endpoint | middleware 把 trace read 以目标 ID 写回 store，`get()` 返回 latest | 在 metrics 后、trace append 前排除 trace route | RED 1 fail -> GREEN；live 重复 GET 都返回 chat trace |
| `E7-I03` | 浏览器保存 `.png`，validator 发现 JFIF | screenshot API 返回 JPEG bytes，扩展名不改变编码 | 无缩放重新编码 PNG，并查 magic/IHDR/dimensions/hash | 六张证据图均为合法 PNG；public tracked PNG audit 仍通过 |
| `E7-I04` | reviewer 指出 trace 回归未锁定 header/metrics | 测试只覆盖“不要写 trace”，没覆盖“仍要 metrics/header” | 增加两次 header 和 route metric count/status 断言 | 项目 `.venv` focused closure 4 passed |
| `E7-I05` | 首次 focused closure 命令报告 test not found | 手写了不存在的 pytest node ID，收集阶段退出 | `rg '^def test_'` 取得准确函数名后重跑 | 有效 RED 为 3 fail/1 pass；文档/claims 修改后 4 pass |
| `E7-I06` | 低 authority/retired 支持证据可压过高 authority/active 冲突 | `_priority_resolves()` 用 `!=`，只判断不同、不判断方向 | 反向两例 RED；改为 tuple strict `>`；重新发布 deterministic/ablation rc02 | 2 fail -> ledger 11 pass；rc02 28/28、10 artifacts match |
| `E7-I07` | audit 330/0 但 reviewer 找到多份本机绝对路径 | absolute-path 只检查 8 个 allowlist surface | 新 nested Markdown test；所有 `.md` 纳入；13 个真实路径统一脱敏 | test RED -> GREEN；real audit 13 findings -> 0 |
| `E7-I08` | README load 是历史 r2，status/repro 是 E7 rc02，却笼统共用 snapshot provenance | current E7 与历史 offline snapshot 批次未明确分隔 | README/status/repro 分别标注 snapshot E4/E5 historical 和 E7 rc02 ignored authority | repository tests/audit GREEN；最终 docs gate 待全量复核 |
| `E7-I09` | working-tree diff check 通过，staging 后才发现新增文件 whitespace | untracked files 不在普通 `git diff --check` 范围；PDF xref 被当文本 | 清理 Markdown/test whitespace；用 `.gitattributes` 标注二进制 fixture；重跑 cached check | cached check fail -> exit 0；final staged audit 331/0 |
| `E7-I10` | GitHub clean clone audit 331/0，但 frozen hash `556f...` -> `f8e0...` | Windows `core.autocrlf`；hash-sensitive JSON checkout 从 1146 LF 变为 1146 CRLF | `.gitattributes` 增加 `* text=auto eol=lf`；repository contract RED/GREEN；必须新 clone 重验 | first clone FAIL；second clone hash/compile/audit PASS |
| `E7-I11` | 第二次 clone hash/compile/audit 通过，full 为 573 pass/1 fail | chunking ablation test 硬编码 ignored `data/generated/demo`，本机残留生成物掩盖依赖 | 在 `tmp_path` 从 checked-in facts/profile 调正式 `write_corpus()`，不 skip、不提交 generated output | clean clone FAIL；local full 574；third clone 574 PASS |
| `E7-I12` | Windows clean clone 574，但 Ubuntu CI exit 139 | UI test 读取 `DataframeElement.value`，触发 Streamlit AppTest 的 PyArrow-to-Pandas test-only 反向转换段错误 | 诊断 commit 输出 faulthandler/last-test annotation；验证表数量和相邻可见 provenance/status，不读取 `.value` | target/local/clean-clone PASS；run 29553278709 success |

## 36. E7 自动证据摘要与人工边界

```text
frozen test hash                    exact match
fresh deterministic                28/28, four layers
exact trajectory                    24/28
direct unsafe probes                4/4, indirect NOT RUN
focused retrieval/security/agent    223 passed
final-code local load               31/31
desktop/mobile browser              1440/1440 and 390/390, 0 errors
public candidates                   331, 0 findings (final staged set)
full repository                     574 passed, 3 known warnings after EOL regression
human semantic review               NOT RUN
owner code/oral sign-off             NOT RUN
optional reranker                    NOT RUN
clean GitHub clone                   574 passed, frozen hash exact, audit 331/0
remote CI                            PASS for 9607e55, run 29553278709
```

最终 commit/push/clean-clone/remote CI 已完成，以 E7 implementation journal 的最终 gate table 和实际 Git remote branch 为准；本节仍不把 owner-only、indirect injection 或 reranker 的 `NOT RUN` 包装成 PASS。

## 37. R2-S1 D0/D1 设计决策

| ID | 白话问题 | 决策 | 当前证据 | 当前结果 | 详细记录 |
|---|---|---|---|---|---|
| `R2S1-D01` | 恶意文档只在生成前过滤够不够 | raw retrieval 只能进入 Guard；Controller/Ledger/generation/verifier 只接 admitted type | `[HISTORICAL D2]` raw `registry.run -> controller.observe` 已被红测复现 | D4 GREEN；raw execution runtime rejection + admitted-only path | [D01-D03](../security/r2_s1/02_design_options_and_decisions.md) |
| `R2S1-D02` | 是否让另一个 LLM 判断注入 | enforcement 使用版本化确定性规则、有界 Unicode/Base64/split view；LLM 不参与放行 | `[HISTORICAL D1]` 当时无 content detector | D3/D4 GREEN；`rcg-v1.1.0` deterministic policy | [D02](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d02-使用确定性规则还是-llm-detector) |
| `R2S1-D03` | 全部候选被过滤是否当 not found | 新 `security_filtered/evidence_filtered`，source-free | `[HISTORICAL D1]` 当时 enum 无该状态 | D4 GREEN；all-quarantined regression source-free | [D06](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d06-全部内容被隔离时的-outcome) |
| `R2S1-D04` | top-1 投毒被删后怎么办 | 在 top-k 截断前取得 bounded pool；quarantine 后继续剩余候选一次，不重跑 embedding | `[HISTORICAL D2]` top-1 displacement 已被红测复现 | D4 GREEN；same-pool recovery + dual candidate_k cap | [D07](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d07-候选补齐策略) |
| `R2S1-D05` | Guard 出错时全部报系统错还是放行 | 单内容异常 quarantine 并继续；Guard 初始化/规则失败才 source-free system | `[PLANNED D1]` fail-closed semantics | D3/D4 GREEN；per-item and boundary failure regressions | [D05](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d05-guard-modes-与-fail-closed) |
| `R2S1-D06` | 旧 `/chat`、`/agent/chat` 怎么处理 | secure profile 默认不注册 legacy generative routes 和 HTTP ingest；显式 local compatibility factory 单独保留 | `[OBSERVED]` legacy 两条生成链会绕过 V2 Guard | D5 GREEN；secure route exclusion + explicit compatibility tests | [D10](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d10-legacy-endpoint-策略) |
| `R2S1-D07` | Trace 为了排错能否放正文/hash/ID | public aggregate only；private synthetic case IDs；必要时 run-scoped HMAC | `[OBSERVED]` 现有 trace 已删除 content/doc/chunk/path | D5 GREEN；strict aggregate projection + zero-leak tests | [D09](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d09-trace-标识与内容指纹) |
| `R2S1-D08` | 24+12 是否在 dev/test 之间平分 | 每个 split 独立 24 attack + 12 benign，共 72 | `[PLANNED]` current indirect fixtures = 0 | D1 dataset protocol frozen；data `NOT RUN` | [D11](../security/r2_s1/02_design_options_and_decisions.md#r2s1-d11-evaluation-split-大小) |
| `R2S1-D09` | Prompt 只写“忽略证据指令”是否足够 | system trust contract + fresh per-model-call nonce + JSON records + post-envelope reminder | `[OBSERVED]` D4 前是自由文本 block | D5 GREEN；ordinary/Unicode delimiter and retry lifecycle regressions | [D08](../security/r2_s1/02_design_options_and_decisions.md) |
| `R2S1-D10` | Guard policy 损坏时是否仍可 ready | default container fail-fast；runtime readiness 只公开 `ready|error` | `[OBSERVED]` D4 无 startup/readiness Guard check | D5 GREEN；digest/active-rule/decision drift tests | [D05](../security/r2_s1/02_design_options_and_decisions.md) |

## 38. R2-S1 当前边界

```text
design and threat model       FROZEN
schema and dataset protocol   FROZEN
D2 red baseline              RECORDED / 5 FAIL + 3 PASS
Guard implementation         D3 GREEN / 64 TESTS
guarded V2 data flow         D4 GREEN / 8 BOUNDARY PROBES
R1 dataset changed            no
prompt/public counters        D5 GREEN / FULL 697 TESTS
deterministic/live runs       NOT RUN
```

D4/D5 的 green 只证明默认 V2 本地数据流、prompt framing、public projection、secure route composition 和 Guard lifecycle 执行了确定性安全合同，不代表未知攻击免疫或 D6 攻击成功率已经测量。逐项理由和回滚见 [R2-S1 design decisions](../security/r2_s1/02_design_options_and_decisions.md)，实现与审查证据见 [D4 engineering journal](../security/r2_s1/06_d4_engineering_journal.md) 和 [D5 engineering journal](../security/r2_s1/07_d5_engineering_journal.md)。

## 39. R2-S1 D5 实现问题

| ID | 现象 | 根因 | 处理 | 当前证据 |
|---|---|---|---|---|
| `R2S1-I01` | Guard readiness 全部误报 error | 新 span 未注册 allowlist，在 probe 前抛错 | 注册 `readiness.retrieved_guard` | focused GREEN |
| `R2S1-I02` | full suite 6 个兼容失败 | fake readiness/legacy route tests 仍使用旧合同 | 更新 fake body；旧 API 显式 compatibility factory | 原失败组 16 passed |
| `R2S1-I03` | Unicode 行分隔符制造多个 end marker | JSON 保留 U+0085/U+2028/U+2029 | 序列化后显式 escape | adversarial RED/GREEN |
| `R2S1-I04` | shape retry 复用 nonce | envelope 只在 loop 外构建 | 每个 model call 新 nonce，重复则 fail closed | adversarial RED/GREEN |
| `R2S1-I05` | active rule 删除但 validator 通过 | 只校验 frozen provenance digest | active map 必须等于 hashed provenance | adversarial RED/GREEN |

## 40. FinQA Gate E16 服务暗流量决策与故障

| ID | 问题或现象 | 根因 | 决策或修复 | 证据 |
|---|---|---|---|---|
| `E16-D01` | 是否直接把 E11 接到 `/agent/v2/chat` | 企业问答没有 typed skeleton、safe catalog、E8 primary selection | 先实现通用可注入 owner；明确记录 adapter 未实现 | protocol + code audit |
| `E16-D02` | Shadow 是否参与回答或 readiness | 候选故障可能放大成主服务故障 | primary/receipt 先完成；Shadow 不可修改、不等待、不作为 readiness 依赖 | paired API 0 mismatch |
| `E16-D03` | 高峰时等待还是丢弃 | 等待会拖慢主链，无界队列会积压 | `Queue(maxsize)` + `put_nowait`，满时固定 `BACKPRESSURE` | fault injection |
| `E16-D04` | 采样使用普通 hash 还是 keyed hash | request ID 可被客户端控制 | 进程内随机材料 + HMAC-SHA256；不使用问题内容 | deterministic unit tests |
| `E16-D05` | 哪些数据能进入 provider/metrics | 身份、答案、证据和 trace 会扩大隐私面 | provider 仅四个临时字段；metrics 只保留聚合、无原始错误 | boundary/evidence tests |
| `E16-I01` | 第一版 API 断言漏掉 request ID | 测试复制了旧响应逻辑 | 改为 OFF 与 failing-ON 完整响应字节和 receipt 比较 | RED 1 -> GREEN |
| `E16-I02` | offer 延迟全部显示 0 ms | Windows `monotonic` 分辨率 15.625 ms | 使用 `perf_counter`；门槛不变 | p95 0.024 ms |
| `E16-I03` | 运行中显示 2 worker，却声称关闭后 0 | 指标采集阶段未标注 | 单独记录 pre-shutdown snapshot 与 post-shutdown count | 17/17 gates |
| `E16-I04` | public audit 1324/1 | 审计脚本含假 credential 形状字面量 | 运行时构造 header、由公开 domain 派生材料；不加白名单 | 1324/0 |
| `E16-I05` | 首次 full 只有 identity exact recompute 失败 | E16 修改了历史结果绑定的 main/resources SHA，20 个行为 case 未变化 | 保留 v2；新增可兼容 validator 和绑定 config/dark runtime 的 v3 证据 | 8 focused；security 245；full 2977 |

## 41. FinQA Gate E17 typed eligibility and adapter decisions

| ID | Question or symptom | Root cause | Decision or repair | Evidence |
|---|---|---|---|---|
| `E17-D01` | Reuse E13 preparation for the service adapter? | E13 derives structure from FinQA gold program, which is unavailable online | Permit only `ONLINE_RULES/ONLINE_MODEL`; prohibit gold/oracle and quality fields | frozen protocol + rejection tests |
| `E17-D02` | Re-retrieve evidence inside provider using only question? | E16 provider lacks tenant/ACL context; re-retrieval could cross authorization boundaries | Accept only an upstream `RETRIEVED_ADMITTED_EVIDENCE` catalog through an ephemeral resolver | data-boundary tests |
| `E17-D03` | Let callers provide the E8 primary? | A stale/different primary can invalidate same-input comparison | Compute E8 primary inside adapter on exact question/skeleton/catalog | eligible-path test |
| `E17-D04` | How should missing typed input be handled? | Guessing fields inflates execution rate and creates false capability | Five frozen abstention reasons; return `NOT_APPLICABLE` before Worker | 5/5 reasons, 0 Worker calls |
| `E17-D05` | How does request thread hand context to background thread? | E16 request intentionally excludes evidence and identity | Bounded TTL consume-once resolver with explicit discard and shutdown clear | resolver fault matrix |
| `E17-D06` | Can duplicate request ID overwrite pending context? | Overwrite can bind one request to another request's context | Reject duplicates without mutation | duplicate regression |
| `E17-D07` | What can public telemetry contain? | Typed context includes question and descriptor metadata | Aggregate reason/outcome/failure counts only; fixed safe error codes | evidence test + audit 1339/0 |
| `E17-I01` | Resolver snapshot showed zero-valued event keys | `Counter += 0` creates a visible key | Create counters only when an event occurs | RED 2 fail -> GREEN 16/16 |
| `E17-I02` | First real observation was much slower than the second | Windows `spawn` startup dominated first call | Keep asynchronous/default-off; disclose cold vs warm and require lifecycle-owned persistent Worker in E18 | ~732 ms max vs ~3.6 ms warm |
| `E17-I03` | Resolver could spoof adapter error text; NaN deadline passed comparisons | Resolver exception type was trusted and deadline finiteness was unchecked | Map all resolver exceptions to one fixed code; validate exact type; reject non-finite deadline and post-close calls | RED 3 fail -> GREEN 16 adapter tests; 24/24 gates |

## 42. FinQA Gate E18 admitted context decisions and incidents

| ID | Question or symptom | Root cause | Decision or repair | Evidence |
|---|---|---|---|---|
| `E18-D01` | Let the background provider retrieve evidence again from the question? | E16 deliberately has no tenant, group, region or Principal fields | Consume only `AdmittedEvidenceChunk` from the primary controller state; secondary retrieval calls fixed at zero | protocol + typed-input tests |
| `E18-D02` | Use an LLM to generate online arithmetic structure immediately? | The first objective is data-boundary correctness; model planning adds semantic and injection variables | Seven narrow bilingual value-free rules, zero model calls, explicit abstention | 7/7 family audit |
| `E18-D03` | Register context before or after E16 offer? | Offer-first lets the worker resolve before registration; register-first can leave state after rejection | Register first, retain only on `ADMITTED`, discard every other offer outcome | admission matrix |
| `E18-D04` | What should happen when a request ID is reused? | Discard after duplicate rejection would delete the original request's context | Reject/no overwrite and do not discard unless this call registered successfully | duplicate regression |
| `E18-D05` | Edit the existing FastAPI container now? | E16 public evidence binds main/config/resources/dark owner to exact hashes | Add injectable versioned component; leave standard route disabled until E19 versioned wiring | E16 evidence tests + E18 non-claim |
| `E18-D06` | Is returning equal response bytes sufficient? | A wrapper could still copy or mutate response internals | Build primary first, return the exact same object, swallow observer failure | identity + serialization tests |
| `E18-I01` | First focused run was 20 pass / 2 fail | Test fixture used removed `QueryAnalysis` fields and omitted current required fields | Align fixture with current typed domain model; do not weaken validation | final 22/22 core tests |
| `E18-I02` | Next focused run still had the same two fixture failures | Fixture also used removed `BudgetState.started_at_ms` and omitted `ControllerState.top_k` | Remove obsolete field and supply required `top_k` | final 22/22 core tests |
| `E18-I03` | First audit passed but had not physically saturated the queue | Backpressure cleanup was inferred from code/E16 tests rather than exercised in E18 | Add blocking resolver provider and one-slot queue; require rejected-only discard and zero residual state | final 22/22 gates |
| `E18-X01` | How expensive is admitted evidence to typed context preparation locally? | Need a bounded mechanism baseline before route wiring | 112 controlled builds across seven families | p50/p95/max `0.623/0.921/1.523 ms`; not an SLO |
| `E18-L01` | Does 112/112 mean answer accuracy is 100%? | Repetitions validate context construction, not semantic correctness or final execution | Keep claim mechanism-only; no quality promotion | public non-claims |
| `E18-L02` | Is E18 active in `/agent/v2/chat`? | Historical E16 assembly remains exact-hash frozen | `DISABLED_PENDING_VERSIONED_WIRING`; E19 required | protocol/status/handoff |

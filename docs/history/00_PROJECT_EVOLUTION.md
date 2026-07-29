# Enterprise Agentic RAG Complete Evolution History

> 中文总索引：从最初的固定式 RAG 到 R2-S9 工业化收口、FinanceBench
> 页面重排 v2 及 FinQA 数值 Agent holdout。
>
> 记录覆盖到本文所在提交；各实验 exact SHA 记录在对应协议与证据文件中。
>
> 本文负责解释“为什么改、改了什么、在哪里改、如何验证、还缺什么”。逐提交原始记录见 [01_COMMIT_INDEX.md](01_COMMIT_INDEX.md)。

## 1. 先回答：修改记录是否都上传了

截至上述截止提交：

- **代码和截止点文档：已提交。** 截止 `daefac1` 共记录 136 个历史提交；
  本文之后的文档收口提交仍以 GitHub Commits 页面为最终原始历史。
- **阶段性工程记录：大部分已上传。** E0-E7、R2-S1 至 R2-S9、
  FinanceBench external track 和 page reranker v2 都有设计、日志、结果或运行手册。
- **此前缺少的是统一入口。** 原有记录散落在 `docs/roadmap`、`docs/security`、`docs/corpus`、`docs/lifecycle`、`docs/quality` 和 `docs/deployment`，无法按时间一次读完。本文补齐这个入口。
- **不会上传的内容：** 密钥、JWT 私钥、真实身份数据、模型文件、`.private` 下的本地评审活动、临时缓存和可能含敏感内容的原始运行产物。这是安全边界，不是记录丢失。
- **无法诚实补写的内容：** 早期只在聊天中讨论、从未写入仓库或 Git 的措辞细节。本文只依据 Git、代码、测试和现存工程日志重建，不编造过程。

## 2. 如何理解这套记录

项目记录分成四层：

| 层级 | 回答的问题 | 位置 |
| --- | --- | --- |
| 总演进史 | 项目为什么一步步变成现在这样 | 本文 |
| Git 原始历史 | 每一次提交在何时做了什么 | [01_COMMIT_INDEX.md](01_COMMIT_INDEX.md) |
| 阶段工程日志 | 某阶段具体设计、问题、修复、实验与限制 | 本文各阶段链接 |
| 可执行证据 | 测试、评测、审计、CI、部署演练如何复现 | 各阶段 results/runbook 与脚本 |

Git 提交是“发生过什么”的不可变骨架，工程日志是“为什么这样做”的解释。测试通过只能证明对应 contract，不自动等于生产环境已经部署。

## 3. 总时间线

| 时期 | 阶段 | 主要变化 | 代表提交 |
| --- | --- | --- | --- |
| 2026-03-25 | 仓库建立 | README 占位 | `d80fc22` |
| 2026-05-18 | 固定式 RAG MVP | FastAPI、Streamlit、切块、混合检索、Ollama 生成 | `d7d2421` |
| 2026-06-01 | 评测体系 v1 | 检索指标、答案检查、消融数据与测试 | `1052e5e` |
| 2026-07-14 至 07-15 | 第一版 Agentic RAG | route/plan/tool/trace、证据充分性判断、查询改写与有限重试 | `a2b43df` 至 `7aec4b9` |
| 2026-07-16 至 07-17 | E0-E7 Enterprise Agentic RAG v2 | 语料、解析、索引、Agent、评测、安全、API、可观测性、演示和验收 | `b8b8e8b` 至 `da2ba8c` |
| 2026-07-17 至 07-19 | R2-S1 | 检索内容间接提示词注入防护与可审计证据 | `ce1ec9e` 至 `073d735` |
| 2026-07-19 | R2-S2 | 密封 holdout、冻结协议、泄漏防护 | `04e9b1e` 至 `aabcde5` |
| 2026-07-21 | R2-S3 | exposure-aware 安全消融与不可变证据发布 | `647005a` 至 `1ebf2ca` |
| 2026-07-22 | R2-S4 | 跨模型复现协议、重启安全执行和矩阵验证 | `b7e8b2d` 至 `a9c32b8` |
| 2026-07-23 | R2-S5 | JWT/JWKS 可信身份边界 | `d753df3` 至 `e657bea` |
| 2026-07-24 | R2-S6 | 版本化企业语料扩充与 ACL 证据 | `184913e` 至 `d465eed` |
| 2026-07-27 | R2-S7 | 安全、版本化、可审计知识生命周期 | `5570d02` 至 `f081ccb` |
| 2026-07-27 | R2-S8 | 独立人工质量证据工作流 | `d7578e4` 至 `c95f9ff` |
| 2026-07-27 | R2-S9 | Linux 容器、readiness、回滚、SBOM 和 CI 收口 | `7edff9b` 至 `9517266` |
| 2026-07-28 | FinanceBench page reranker v2 | 候选/最终指标拆分、guarded Qwen 重排、dense-head 融合、置信度 cascade 与成本评测 | `f33e2ab` 至 `daefac1` |
| 2026-07-29 | FinQA selective execution | 新零重叠 cohort、真实选择性执行、shadow full 对照、部分 CUDA 修复与断点恢复 | `65257e9` 至 `6112b54` |

## 4. 阶段 0：从空仓库到固定式 RAG MVP

### 为什么做

第一目标不是 Agent，而是先打通最小 RAG 链路：文档进入系统，查询能检索证据，本地模型能依据证据回答，用户能通过 API/UI 使用。

### 改了什么、在哪里

- `app/chunker.py`：把知识文档拆成可检索 chunk。
- `app/retriever.py`：组合关键词与向量检索。
- `app/rag_service.py`：把检索证据组织成提示并调用 Ollama。
- `app/main.py`：FastAPI 服务入口。
- 最初的单页 Streamlit 入口后来演进为 `streamlit_app/ui.py` 和 `streamlit_app/pages/` 多页面演示 UI。
- `knowledge_docs/`：最初的企业制度样例。

### 当时的局限

流程是固定的“检索一次 -> 生成一次”，没有 route、plan、工具选择、证据不足重试、安全边界或完整 trace。它证明链路可运行，但还不能叫工程化 Agent。

### 对应提交

`d80fc22`、`d7d2421`、`1cf4057`、`c8f5314`、`cfba324`。

## 5. 阶段 1：从“能回答”到“能量化”

### 为什么做

只展示几个看起来正确的答案无法证明 RAG 改善有效，因此先建立可重复评测基线。

### 改了什么、在哪里

- `scripts/eval_retrieval.py` 与相关数据：计算 Hit、Recall、Precision、MRR、nDCG。
- `scripts/eval_answer_v1.py`：对 must-include、must-not-include、引用、拒答和不安全模式做启发式检查。
- `scripts/eval_ablation_v2.py`：比较检索配置，不只汇报最终最好数字。
- `eval/`、`tests/`：固定问题、期望证据、错误分类和回归测试。

### 如何理解指标

- `Precision@k`：前 k 个结果中相关结果的比例。
- `nDCG@k`：同时考虑相关性和排序位置，相关结果越靠前分数越高。
- `MRR`：第一个相关结果排名倒数的平均值。
- 启发式答案检查便宜、稳定、可复现，但无法代替语义判断或独立人工评审；后来的 R2-S8 正是为补这个缺口。

### 历史结果与边界

早期 60 题检索集曾得到 Hit@1 `0.9333`、Hit@3/5 `1.0`、MRR `0.9639`、nDCG@3/5 `0.9678`。这些是历史基线，不应冒充当前 release gate。

### 对应提交

`1052e5e`。使用说明见 [RAG_EVAL_USAGE.md](../RAG_EVAL_USAGE.md)，长期演进说明见 [AGENTIC_RAG_EVOLUTION_LOG.md](../AGENTIC_RAG_EVOLUTION_LOG.md)。

## 6. 阶段 2：第一版可评测 Agentic RAG

### 为什么做

固定 RAG 无法根据问题风险和证据质量改变行为。Agent 化的核心不是多调用几次 LLM，而是把决策变成受约束、可观察、可评测的动作。

### 改了什么、在哪里

- `app/agent/`：router、planner、controller、evidence evaluator、tool registry 和 runner。
- Agent 先选择 route，再生成受限 plan，只能调用注册工具。
- 引入“检索 -> 证据充分性判断 -> 查询改写 -> 最多有限次数重试 -> 回答或拒答”。
- `scripts/eval_agent_actions.py` 及数据集：评测 route accuracy、动作序列、unsafe no-retrieval 和 trace completeness。
- `scripts/eval_agent_loop.py`：比较固定 RAG 和受限 Agent loop。

### 设计原则

借鉴先进 coding agent 的不是 UI 外形，而是可审计控制循环：明确状态、工具白名单、有限步数、失败可见、每一步留下 trace。LLM 提议动作，代码执行能力边界。

### 对应记录

- [Agent Action Evaluation Design](../superpowers/specs/2026-07-14-agent-action-evaluation-design.md)
- [Adaptive Evidence Loop Design](../superpowers/specs/2026-07-14-adaptive-evidence-loop-design.md)
- 提交 `a2b43df` 至 `7aec4b9`。

## 7. 阶段 3：E0-E7 Enterprise Agentic RAG v2

这一轮把研究型原型扩成具有领域模型、服务边界、可观测性和验收证据的工程项目。核心实现集中在 `b8b8e8b`，随后用多个提交修复 clean clone 和 CI 的真实问题。

| Gate | 做了什么 | 详细记录 |
| --- | --- | --- |
| E0 | 只读审计现状，冻结范围、风险和验收标准 | [E0 journal](../roadmap/e0_readonly_audit_implementation.md) |
| E1 | 扩充企业语料与评估集，定义文档、租户、版本、ACL 元数据 | [E1 journal](../roadmap/e1_enterprise_corpus_implementation.md) |
| E2 | 解析器注册、chunk 身份、索引 manifest、增量生命周期 | [E2 journal](../roadmap/e2_parser_index_lifecycle_implementation.md) |
| E3 | 混合检索、rerank、router/planner/tool/controller 与 trace | [E3 journal](../roadmap/e3_retrieval_agent_workflow_implementation.md) |
| E4 | 检索、答案、Agent 行为、loop 与消融的统一评测 | [E4 journal](../roadmap/e4_evaluation_ablation_implementation.md) |
| E5 | 访问控制、安全边界、API v2、结构化 trace 与负载测试 | [E5 journal](../roadmap/e5_security_service_observability_implementation.md) |
| E6 | Streamlit 演示、公开仓库说明、复现实验路径 | [E6 journal](../roadmap/e6_demo_public_repo_implementation.md) |
| E7 | clean clone、跨平台、CI 和最终验收 | [E7 journal](../roadmap/e7_final_acceptance_implementation.md) |

### 真实遇到的问题

- 冻结产物在 clone 后字节不一致：修复为明确保存和验证不可变字节。
- 消融测试依赖本地工作区状态：改成 clone-safe fixture。
- CI 原生崩溃不可见：调整 CI 暴露错误。
- `pyarrow` DataFrame 往返导致 CI 特有失败：移除测试不需要的往返路径。

这些修复对应 `68731b2`、`960fa13`、`a628dfe`、`9607e55`。E7 当时记录 `574 passed`、审计 `331 candidates / 0 findings`；它是当时截面的证据，不是今天测试总数。

## 8. 阶段 4：R2-S1 检索内容间接提示词注入防护

### 问题

知识库文本是不可信输入。攻击者可能把“忽略系统指令”“泄露密钥”“调用外部工具”写进文档，等它被检索后影响模型。仅在用户输入入口做过滤不够。

### 子步骤

| 子步骤 | 产物 |
| --- | --- |
| D0-D1 | 冻结范围、攻击面、信任边界、评测协议 |
| D2 | 建立 guard OFF 的红色基线，证明攻击确实可达 |
| D3 | 实现确定性 retrieved-content Guard 核心 |
| D4 | 把 Guard 接入检索到生成的数据流，并限制能力 |
| D5 | 建立提示边界、Local Ollama 精确 origin/socket 约束和安全 trace |
| D6 | 建立安全评测和 CI gate |
| D7 | 使用本地真实模型做 OFF/ON 成对评测 |
| V0-V5 | 加固公开证据、扫描 provenance、指标语义与顺序平衡 |

### 结果与正确解读

- 确定性 D6：Guard OFF `21/24` 攻击成功，ON `0/24`；benign false positive `0/32`；clean `12/12`。
- 本地模型 D7：OFF context signal `7/24`，ON 为 `0/24`；可达子集 `15/15` 被覆盖。
- 这些结果证明冻结样本和指定模型条件下观察到防护效果，不证明对未知攻击、所有模型或生产流量完全免疫。

### 详细记录

[R2-S1 文档目录](../security/r2_s1/00_scope_and_threat_model.md) 从 `00` 到 `16` 完整覆盖威胁模型、设计、评测、D4-D7 日志和 V0-V5 加固。提交范围 `ce1ec9e` 至 `073d735`。

## 9. 阶段 5：R2-S2 独立 Holdout 冻结

### 为什么做

如果开发者一边看测试集一边调规则，最终数字会被测试集泄漏污染。R2-S2 把开发集和独立 holdout 分开，并将原始 holdout 作为受控资产。

### 实现

- holdout package admission contract。
- sealed package 的冻结、哈希验证和操作命令。
- 防止原始 holdout 被提交到公开仓库。
- live dev 与 holdout 证据分开报告。

### 限制

开发集实验已运行；真实独立 holdout 结果仍明确标为 `NOT RUN`，不能把 dev 数字写成独立泛化结论。

详细记录：[协议](../security/r2_s2/00_holdout_freeze_protocol.md)、[结果](../security/r2_s2/01_s2_1_live_dev_results.md)、[日志](../security/r2_s2/02_engineering_journal.md)。提交 `04e9b1e` 至 `aabcde5`。

## 10. 阶段 6：R2-S3 Exposure-aware 安全消融

### 为什么做

只统计“模型最后有没有输出攻击内容”会混淆三个环节：恶意 chunk 是否被检索、是否进入模型可见上下文、模型是否服从。R2-S3 把暴露链路拆开。

### 实现

- 把攻击单元绑定到 runtime candidate rank。
- 对 source-bound 检索准入进行 replay，而不是信任汇总数字。
- 记录检索、清洗、admission、模型可见上下文和结果之间的 lineage。
- 不可变发布分析 run，并提供公开 verifier。
- 逐步修复 URI authority、路径重定向、Windows/Linux 路径和发布竞态。

### 结果

实际/replay 可达 `15/28`，条件覆盖 `15/15`；rank-2 downstream exposure `0/13`。深度 1/2/4 的诊断覆盖为 `6/26`、`22/26`、`26/26`。结论标签是 `NO_CURRENT_BYPASS_OBSERVED`，不是“绝对安全”。

这一阶段提交最多，范围 `647005a` 至 `1ebf2ca`。详细记录：[协议](../security/r2_s3/00_exposure_ablation_protocol.md)、[结果](../security/r2_s3/01_results.md)、[日志](../security/r2_s3/02_engineering_journal.md)。

## 11. 阶段 7：R2-S4 跨模型复现

### 为什么做

单模型结果可能只是特定模型行为。R2-S4 冻结模型矩阵和执行环境，要求每个模型产生可验证、可恢复、顺序受控的配对结果。

### 实现

- cross-model manifest v3 与 model-specific pair fingerprint。
- restart-safe orchestration，失败后可以从已验证状态继续。
- 执行环境、transport policy 和公开/私有证据边界绑定。
- 可验证 cross-model matrix 和公开 evidence verifier。

### 边界

结果支持“在同一可见合成 cohort 上观察一致”，不支持“已经证明所有模型泛化或可发布生产”。

详细记录：[协议](../security/r2_s4/00_cross_model_protocol.md)、[结果](../security/r2_s4/01_results.md)、[日志](../security/r2_s4/02_engineering_journal.md)。提交 `b7e8b2d` 至 `a9c32b8`。

## 12. 阶段 8：R2-S5 Trusted Identity Boundary

### 为什么做

客户端自己传 `tenant_id`、角色或用户 ID 不可信。ACL 决策必须基于经过密码学验证的身份声明。

### 实现

- 本地可复现 JWT/JWKS 模拟身份源。
- 验证 issuer、audience、签名、时间声明、`kid` 和 key rotation 生命周期。
- 将可信 principal 传入 tenant/ACL 过滤，避免请求参数冒充身份。
- 对文件对象生命周期和身份验证之间的竞态做加固。

### 结果与限制

身份矩阵 `20/20`，本地验证 p95 约 `0.0904 ms`。这证明本地模拟 IdP contract，不代表已经接入企业 Azure AD/Okta 等真实 IdP。

详细记录：[工程日志](../security/r2_s5/01_engineering_journal.md)、[实现与面试指南](../security/r2_s5/02_implementation_and_interview_guide.md)、[结果](../security/r2_s5/03_results.md)。提交 `d753df3` 至 `e657bea`。

## 13. 阶段 9：R2-S6 版本化企业语料扩充

### 为什么做

少量样例文档只能验证 demo，不能验证 tenant、ACL、版本、政策冲突、时间有效性和规模变化下的行为。

### 实现与结果

- 扩充到 240 个 source、216 个 canonical 文档/chunk 视图。
- 建立 20 类 policy、40 个版本、104 个事实、52 个 active facts。
- 固定 dev/test，验证 ACL leakage 为 `0`，Hit@1 与 document recall@3 为 `1.0`。
- 修复 frozen bundle snapshot read，记录一次 closeout incident，避免“测试绿但证据读取不一致”。

详细记录：[设计](../corpus/v2_expansion/00_design.md)、[工程日志](../corpus/v2_expansion/01_engineering_journal.md)、[结果与面试指南](../corpus/v2_expansion/02_results_and_interview_guide.md)。提交 `184913e` 至 `d465eed`。

## 14. 阶段 10：R2-S7 企业知识生命周期

R2-S7 不是简单增加解析器，而是处理真实企业知识进入、更新、删除、回滚时的 correctness 和审计问题。

| Gate | 核心内容 |
| --- | --- |
| G0 | 源码审计、contract、corrected baseline 与性能基线 |
| G1 | evidence schema、append-only 记录、自动一致性校验 |
| G2 | canonical `SourceEvent`、幂等和冲突账本 |
| G3 | 受限文件验证、安全 staging、quarantine |
| G4 | 安全 EML 解析、附件预算、嵌套邮件限制 |
| G5 | 持久化 revision catalog、tombstone、deterministic `ChangePlan` |
| G6 | parser/chunk/embedding 的精确失效与复用 |
| G7 | immutable target snapshot、base manifest、故障注入、原子激活、删除验证、回滚 |
| G8-G10 | 操作命令、跨平台证据、完整验证和收口 |

### 性能认识

在当时冻结环境中，确定性 240/2000 文档基线 p50 约 `0.983s/3.681s`；BGE 路径约 `39.63s/220.025s`，2000 文档时 embedding 约占 `98%`。这给出的工程结论是优先做精确 cache invalidation 和 embedding 复用，而不是继续堆 Agent 节点。

### 详细记录

- [Stage Contract](../lifecycle/00_STAGE_CONTRACT.md)
- [完整 G0-G10 工程日志](../lifecycle/01_ENGINEERING_JOURNAL.md)
- [设计决策](../lifecycle/02_DECISIONS.md)
- [结果](../lifecycle/03_RESULTS.md)
- [基础学习指南](../lifecycle/04_LEARNING_GUIDE.md)
- 机器可读：`FAILURES.jsonl`、`EXPERIMENTS.jsonl`、`TRACEABILITY.csv`

提交 `5570d02` 至 `f081ccb`。

## 15. 阶段 11：R2-S8 独立人工质量证据

### 为什么做

规则评测和 LLM 自评都可能误判。要让“答案质量提升”成为可信简历结论，需要冻结 review packet、独立 reviewer 身份、盲评和一致性统计。

### 已实现

- G0-G4：质量 evidence contract、冻结 packet、reviewer 工具、校验与 operator-owned campaign。
- 12 个 review item、37 个 candidate evidence，公开状态明确显示 human labels 为 `0`。
- 防止换行差异、clean checkout 和 Linux no-replace publication 破坏证据一致性。

### 尚未完成

- G5 真实独立双人评审未执行。
- G6 基于人工结果的 release claim 未执行。
- 本地 campaign `r2-s8-human-pilot-v1` 状态仍为 `NOT_RUN`。因此仓库没有声称已经获得人工质量提升结论。

详细记录：[Contract](../quality/00_STAGE_CONTRACT.md)、[工程日志](../quality/01_ENGINEERING_JOURNAL.md)、[结果](../quality/03_RESULTS.md)、[学习指南](../quality/04_LEARNING_GUIDE.md)、[Reviewer Runbook](../quality/05_REVIEWER_RUNBOOK.md)。提交 `d7578e4` 至 `c95f9ff`。

## 16. 阶段 12：R2-S9 Linux 部署与回滚收口

### 为什么做

本地 Windows 测试通过不等于 Linux 容器能启动，更不等于故障时能安全回滚。R2-S9 将部署 contract 变成 CI 可验证行为。

### 实现

- Linux container 构建和非 root 运行约束。
- readiness/smoke contract。
- immutable release snapshot 与 rollback drill。
- 私有 handoff、bind mount 权限和 tmpfs cache 隔离。
- SBOM 生成和 CI artifact。

### 修复过程

CI 先后暴露 container cache、索引状态、bind mount 权限、smoke 目录权限和 private handoff 保留问题；对应提交 `66dd2b8`、`00e4669`、`ba119a2`、`0ee3ba2`、`3123133`。这些不是无意义的反复失败，而是把本地隐含条件逐项变成部署 contract。

### 最终证据

- 本地全量：`2419 passed / 30 skipped / 3 warnings`。
- 审计：`915 candidates / 0 findings`，含义是扫描了 915 个候选项，在规则覆盖范围内未发现违规；不等于软件没有任何漏洞。
- GitHub Actions run `30265595931` 在实现提交 `3123133` 上通过 Ubuntu、Windows、container/readiness/rollback 和 SBOM jobs。

详细记录：[规格](../deployment/r2_s9/00_spec.md)、[工程日志](../deployment/r2_s9/01_engineering_journal.md)、[运行手册](../deployment/r2_s9/02_runbook.md)。提交 `7edff9b` 至 `9517266`。

## 17. 当前项目真正具备的工程价值

现在的项目不只是“RAG + Agent + Security”名词堆叠，而是围绕企业知识生命周期建立了可执行不变量：

1. **输入不可信：** 文件、邮件、检索内容和身份声明都先经过边界验证。
2. **决策受约束：** Agent 使用有限计划、工具白名单、步数预算和可审计 trace。
3. **知识可追溯：** source event、revision、chunk、embedding、manifest 和 snapshot 有 lineage。
4. **更新可恢复：** 幂等、冲突检测、tombstone、原子激活、故障注入和回滚都有 contract。
5. **结论受证据约束：** dev、holdout、确定性、真实模型、人工评审、CI 和生产声明明确分层。
6. **部署可验证：** Windows/Linux、容器权限、readiness、rollback 和 SBOM 进入自动门禁。

## 18. 当前仍不能声称的内容

- 没有真实企业 IdP 集成证明。
- 没有真实独立 holdout 泛化结论。
- 没有完成 R2-S8 双人独立人工评审。
- 没有生产流量、SLO、高可用、真实告警响应或签名镜像证据。
- 合成企业语料能验证 contract，但不能替代真实企业数据上的效果与运营验证。
- `0 findings` 只表示对应审计器规则未命中，不表示不存在未知漏洞。

这些限制应保留在简历和面试表达中。完整清单见 [Known Limitations](../known_limitations.md) 和 [Industrialization Backlog](../industrialization_backlog.md)。

## 19. 推荐阅读顺序

### 15 分钟快速了解

1. 本文。
2. [Architecture](../architecture.md)。
3. [E7 Final Acceptance](../roadmap/e7_final_acceptance_implementation.md)。
4. [R2-S7 Results](../lifecycle/03_RESULTS.md)。
5. [R2-S9 Runbook](../deployment/r2_s9/02_runbook.md)。

### 面试准备

1. 先用阶段 0-2 解释为什么从固定 RAG 走向受限 Agent loop。
2. 用 E0-E7 解释如何把 demo 拆成领域、服务、评测、安全和可观测模块。
3. 用 R2-S1/S3 讲间接提示词注入、攻击可达性和 evidence lineage。
4. 用 R2-S5/S7 讲可信身份与知识生命周期 correctness。
5. 用 R2-S8 的 `NOT_RUN` 说明如何诚实地区分自动指标和独立人工证据。
6. 用 R2-S9 的连续 CI 修复说明如何把隐含环境假设变成跨平台部署 contract。

## 20. 维护规则

以后每个新阶段都应同时更新：

1. 阶段 contract/design。
2. 工程日志：改动、原因、失败、修复和验证。
3. results：明确 exact SHA、命令、指标语义和未运行项。
4. 本总演进史的一行时间线和阶段摘要。
5. Git 提交索引的生成截止点。

GitHub 的 Commits 页面始终是包含文档维护提交在内的最终原始历史；本文和提交索引是便于学习与审核的解释层。

## 21. FinQA 数值推理 Agent 与独立 holdout

### 为什么增加这条轨道

FinanceBench 已能测真实财报的文档和页面定位，但不能区分“证据没找到”和
“证据已经给出，模型仍然算错”。FinQA 因此单独测四件事：gold evidence 下的
数值计划上限、hybrid 检索损失、引用完整性、以及模型/Calculator 工具协议。

### 代码改在哪里

- `app/external_datasets/finqa.py`：固定 revision/SHA 下载、严格 schema、
  corrected table-row 映射、gold ID/text 对齐和稳定 hash 抽样。
- `app/external_datasets/finqa_eval.py`：oracle/BM25Plus/BGE-M3/RRF、Guard、
  临时候选 ID、表达式 Agent、逐题协议错误隔离、分层指标和不可变 run。
- `app/agent/safe_calculator.py`：AST 白名单、`Decimal` 执行、字符/节点/深度/
  数值/指数预算，不使用 `eval`。
- `scripts/eval_finqa.py`：clean-worktree、模型 digest、D 盘锁、冻结参数/
  源码/模型门禁、原子发布。
- `scripts/prepare_finqa.py`：test 下载必须同时满足显式开关和 FROZEN 协议。
- `docs/external_datasets/evidence`：v1/v2 协议、schema incident 和内容无关
  test 聚合证据。

### 关键失败与修复

1. 第一次 dev 请求在模型调用前因 transport operation 被写成
   `model identity` 而失败；修为已有预算体系支持的 `chat`。
2. Ollama 不支持字符串 `minLength/maxLength` grammar；生成 schema 删除这些
   关键字，Pydantic 仍在响应后强校验长度。
3. direct-answer dev oracle strict 为 `0%`。原因既有真实算错，也有
   `52.8%` 对 `.52772` 的展示舍入；因此保留严格 5 位指标，并新增独立、
   符号敏感的 0.5% presentation tolerance，不能互相覆盖。
4. 强校验后，单题两次输出失败会终止整批。修为只捕获专用 protocol error，
   该题计 0 并保存尝试次数；Ollama/网络/数据故障继续整批失败。
5. typed-step Calculator 看似更结构化，但 Qwen 把 evidence ID 当 operand，
   dev 协议错误达到 `50%`。该方案没有因为“更 Agentic”而强行保留为默认。
6. 简化为算术表达式后，Qwen 负责选数和列式，AST/Decimal Tool 负责执行；
   dev oracle strict 提升到 `75%`、协议错误降到 `0%`。
7. 第一次 test oracle 在抽样/模型调用前遇到合法单行表，被 adapter 的
   “至少两行”假设拒绝。没有 run artifact 或指标。项目发布 incident，
   用合成 fixture 修正为至少一行，完成只输出 count/hash 的结构预检，
   v1 标记 superseded，再以相同参数、模型和评分冻结 v2。

### 最终固定观察

固定 100 题 test 样本、Qwen3 8B、temperature 0：

| Arm | Strict | Presentation | Evidence recall | Grounded strict | Protocol error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Oracle | 52% | 54% | 100% | 45% | 0% |
| Hybrid RRF K=10 | 44% | 44% | 93.5% | 40% | 1% |

oracle 到 hybrid 的 strict 差距为 8 点，说明检索有损失；oracle 自身只有 52%，
说明更大的剩余瓶颈仍是数值选择和财务计划。dev oracle 75% 到 test 52% 的
23 点下降说明小 dev pilot 明显乐观，这正是冻结 holdout 必须存在的原因。

收口验证为 FinQA focused `90 passed`、仓库全量
`2563 passed / 30 skipped / 3 warnings`、public audit
`964 candidates / 0 findings`；最后一项只覆盖审计器已实现规则。

详细记录：
[FinQA runbook/results](../external_datasets/finqa.md)、
[v2 protocol](../external_datasets/evidence/finqa_holdout_protocol_v2.json)、
[schema incident](../external_datasets/evidence/finqa_holdout_schema_incident_v1.json)、
[public evidence](../external_datasets/evidence/finqa_test_holdout_v1.json)。

当前仍不能声称完整 FinQA test accuracy、SOTA、跨模型泛化、人类语义审核或
生产财务可靠性。后续若优化，必须建立新的 dev/holdout 版本，不能重调本次 test。

## 22. FinQA dev 失败归因与标签质量审计

固定 test 揭示后，项目没有继续看 test 调 prompt，而是在新 seed 的 100 题 dev
上建立诊断臂。新增：

- `app/external_datasets/finqa_diagnostics.py`：安全解析 gold program 和模型
  AST，计算 operand recall、operation sequence 与引用 operand grounding；
- `scripts/diagnose_finqa_run.py`：只接受已校验的 dev Calculator run，拒绝 test，
  输出原子、不可覆盖、hash 可复验的 manifest/details/summary；
- `tests/external_datasets/test_finqa_diagnostics.py`：覆盖语法预算、分类优先级、
  一元负号、标签冲突、不可变发布与篡改拒绝。

新 100 题 dev 的 Oracle/Hybrid strict 为 `63%/59%`，Hybrid evidence recall
为 `91.98%`。Oracle 错误的主要机械信号为 operand `20`、operation plan `11`；
Hybrid 另有 retrieval miss `12`。这把“模型不行”拆成了可以分别实验的假设。

同时发现 human-facing `answer` 与 `exe_ans` 存在少量尺度、符号或脏字段问题。
项目新增确定性标签审计，但保持主评分绑定 `exe_ans`，没有事后选择有利标签。
公开内容无关证据见
[finqa_dev_diagnostic_v1.json](../external_datasets/evidence/finqa_dev_diagnostic_v1.json)。
收口门禁为 `2578 passed / 30 skipped / 3 warnings` 和 public audit `968/0`。

## 23. FinQA 有界 Plan Review、匿名候选仲裁与零重叠验证

### 为什么没有直接上线第二个模型

上一阶段发现主要错误信号位于 operand 和 operation plan，但“再调用一次 LLM”
本身不是改进证据。本阶段先在固定 baseline 上做 paired evaluation，并同时统计
wrong-to-correct、correct-to-wrong、grounded strict、调用数、延迟和 exact
McNemar。默认开关只有在预冻结门槛全部通过时才允许开启。

### 新增代码与约束

- `app/external_datasets/finqa_review.py`：版本化 review prompt、受限修改、
  Calculator 重执行、evidence guard、精确成对统计、不可变 artifact。
- `scripts/eval_finqa_review.py`：只接受已验证 dev baseline，核对样本顺序、
  hash、模型 digest 和 clean worktree；test 被拒绝。
- `app/external_datasets/finqa_adjudication.py`：baseline/proposal 匿名 A/B、
  hash 决定位置，adjudicator 只能选候选，不能自由生成。
- `scripts/eval_finqa_adjudication.py`：只处理 reviewer 确实修改的题，协议错误
  保留 baseline，transport error 继续向上抛出。
- 两组专用测试覆盖 prompt contract、回退边界、候选随机化、篡改拒绝和原子发布。

### 实验如何改变了设计

8B v1 reviewer 把 Hybrid strict 从 `59%` 降到 `55%`，暴露了 review prompt
没有完整继承 planner 的 raw-ratio/percentage 合同。v2 修复后不再退化，但同模型
没有提供新信息，结果保持 `59%`。30B proposal 达到 `61%`，仍有 3 个正确题被
改错；加入匿名 8B 仲裁后 tuning 达到 `63%`、4 修正/0 退化。

这个 tuning 结果没有直接用于上线。项目先冻结与 tuning case ID 零重叠的 50 题
dev validation，再运行同一 proposal/adjudication 协议：

| Stage | Strict | Grounded strict | wrong→correct | correct→wrong |
| --- | ---: | ---: | ---: | ---: |
| Hybrid baseline | 44% | 32% | - | - |
| 30B proposal | 48% | 36% | 3 | 1 |
| 8B adjudicated | 50% | 38% | 3 | 0 |

最终 exact McNemar 为 `p=0.25`，没有达到冻结的 `p<=0.05`；Ollama 0.32.5 的
CUDA runner 回归又迫使 reviewer 临时使用 Vulkan，平均端到端延迟为 baseline
的 `7.84x`。因此结论是“质量方向复现，但不采用”，不是“6 点提升已上线”。

### 工业化教训

1. reviewer 必须继承 planner 的全部数值合同，否则“复核”会系统性制造错误。
2. protocol fallback 只处理可预期的模型结构错误；基础设施故障必须暴露。
3. proposer 和 adjudicator 分责后仍需独立样本、显著性和成本门禁。
4. runtime backend 是实验 provenance 的一部分，跨 CUDA/Vulkan 的延迟不能混比。
5. 长评测尚无 checkpoint/resume；中断会丢失已完成调用，这是下一阶段明确债务。

公开、内容无关证据见
[finqa_plan_review_results_v1.json](../external_datasets/evidence/finqa_plan_review_results_v1.json)，
冻结协议见
[finqa_plan_review_validation_protocol_v1.json](../external_datasets/evidence/finqa_plan_review_validation_protocol_v1.json)。

本阶段最终门禁为 FinQA `63 passed`、全仓
`2592 passed / 30 skipped / 3 warnings`、public audit
`978 candidates / 0 findings`，并通过 compile、依赖一致性和 diff 检查。

## 24. 可恢复长评测与 Runtime-only Uncertainty Gating

### 从真实故障产生的需求

30B reviewer 的 CUDA runner 中断证明原有“整批结束才发布”无法承担长实验：
模型已经算完的 case 会随进程退出全部丢失。`e59d9e4` 增加通用逐题 checkpoint，
并接入 review/adjudication：

- contract 精确绑定 source artifact、样本、模型、prompt、代码和 backend；
- 同盘 pending 文件完整写入并 fsync 后，以目标不存在为前提原子提交；
- ordinal、case ID、row hash 和前序文件 hash 阻止错序、缺号与静默篡改；
- 恢复 runner 不重算已完成 case；
- final artifact 发布后用 manifest/details hash seal；
- final 已发布但 seal 未写完的崩溃窗口可以验证后恢复。

### 不依赖 gold 的成本路由

`08a3f62` 冻结的 trigger 只读取线上可见的 question、引用证据、表达式、调用次数
和 Guard 结果。测试通过改变 gold program、答案、gold evidence 和所有质量标签
证明 signal 不变。

| Cohort | Trigger rate | Gated strict | Gated grounded | Gen reduction | Calc reduction |
| --- | ---: | ---: | ---: | ---: | ---: |
| 100 tuning | 67% | 63% | 55% | 32.26% | 31.76% |
| 50 zero-overlap validation | 62% | 50% | 38% | 35.38% | 33.75% |

两个 cohort 都捕获 full strategy 的全部修正且没有引入退化。validation 成本
过滤门槛通过，但不能据此上线：它是旧 validation artifact 的二次使用，调用减少
是反事实，真实 selective wall-clock 未运行，源策略显著性仍是 `p=0.25`。

### 协议元数据 incident

新证据一致性检查发现早期 plan-review freeze 的公开 `split_sha256` 有一处人工
抄写错误。实际 `FINQA_DEV_SHA256`、baseline、review 和 adjudication manifests
全部一致，抽样、模型调用和指标未受影响。为保持 append-only 审计语义，原冻结
文件不静默修改；项目新增 erratum 和自动一致性测试。

本阶段收口为 `73` 个 FinQA/checkpoint focused tests、全仓
`2602 passed / 30 skipped / 3 warnings`、public audit `986/0`。

## 25. FinQA 真实 Selective Execution、Partial CUDA 与恢复证据

### 为什么还需要再跑一个新 cohort

上一阶段只在历史逐题 artifact 上计算“如果跳过 30B 会省多少”，没有真实执行
选择性路径，也没有可比较的 wall-clock。为了避免二次使用 validation 继续产生
乐观结论，本阶段先排除旧 tuning `100` 题和 validation `50` 题，再冻结新的
零重叠 100 题 dev cohort。

### 实现边界

- trigger 在任何 30B 调用前执行，且函数签名不接收 gold label；
- 未触发题的 production final 直接固定为 baseline；
- 触发题才执行 30B bounded review，只有 proposal 改变才执行匿名 8B adjudication；
- 未触发题的 shadow full arm 只能在 production final 固定后执行；
- production/shadow route、调用数和 latency partition 由 schema 重新计算；
- checkpoint contract 绑定 protocol、sample、model、runtime 和 code SHA；
- public artifact 只有聚合结果和 hash，不含 case ID、问题、答案、证据或表达式。

### v1 incident 与 v2

v1 在模型调用前冻结，但 Ollama `0.32.5` 的默认 30B CUDA 请求失败。受控探针排除
prompt 和 Flash Attention 单点原因，并将稳定范围收紧到保守的 `num_gpu=5`。
因为 v1 尚未执行任何 selected case，项目保留原文件、发布 incident，再用完全
相同样本冻结 v2；没有事后重抽更有利题目。正式运行是 `89% CPU / 11% GPU` 的
partial offload，不是 full-GPU。

### 结果与采用决策

| Metric | Baseline | Selective | Shadow full |
| --- | ---: | ---: | ---: |
| Strict | 53% | 55% | 56% |
| Grounded strict | 38% | 40% | 40% |
| wrong→correct / correct→wrong | - | 3 / 1 | 4 / 1 |
| Mean observed latency | 2.36s | 9.02s | 11.85s |

trigger rate 为 `63%`；增量 generation/Calculator calls 减少
`32.00%/30.52%`；selective 总时间比隔离 shadow-full arm 低 `23.83%`。
但是 exact McNemar `p=0.625`，1 个退化违反冻结门槛，beneficial capture 只有
`75%`，也没有 full-GPU latency，因此默认路由不启用。

### 真实中断恢复

第一次进程在 26 条 checkpoint 后退出且没有 Python traceback。相同命令重启时
验证完整 contract/hash chain，输出 `resuming after 26/100 completed cases`，
从第 27 题继续并完成 immutable publish/seal。可以据此声称“单机长评测逐题恢复”，
不能声称分布式 exactly-once 或生产容灾。

公开证据：

- [v2 frozen protocol](../external_datasets/evidence/finqa_selective_execution_protocol_v2.json)
- [aggregate result](../external_datasets/evidence/finqa_selective_execution_results_v1.json)
- [v1 incident](../external_datasets/evidence/finqa_selective_execution_protocol_v1_incident.json)

完整初学者解释与面试问答见
[第 21 章](../learning/21_FINQA_RESULT_AND_DIAGNOSTICS.md)。

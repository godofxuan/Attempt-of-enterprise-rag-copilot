# Enterprise Agentic RAG Complete Evolution History

## 2026-08-07 addendum: FinQA E19 versioned service wiring

E19 preserved the hash-frozen E16 entrypoint and added `app.main_v2:app` as a
parallel, runnable service assembly. The new runner wraps primary response
construction at the ControllerState boundary, consumes only Guard-admitted
evidence, registers bounded consume-once typed context, and submits exactly one
default-OFF observation. Eight OFF/enabled API pairs produced zero primary-body
and feedback-receipt mismatches. Startup failure, provider failure, real queue
backpressure, idempotent close, context cleanup, and aggregate-only metrics are
covered. Full local verification passed `3035` tests with `29` skips; the public
audit reported `1362 candidates / 0 findings`.

This stage intentionally did not change the Docker default from `app.main:app`.
The engineering rationale, code map, incidents, evidence hashes, and non-claims
are recorded in
[`finqa_service_wiring_gate_e19.md`](../external_datasets/finqa_service_wiring_gate_e19.md)
and the beginner chapter
[`40_FINQA_GATE_E19_VERSIONED_SERVICE_WIRING.md`](../learning/40_FINQA_GATE_E19_VERSIONED_SERVICE_WIRING.md).

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

## 26. FinQA typed-program protocol: Gate A and Gate B

The selective-execution result showed that retrieval was not the only
bottleneck: Oracle evidence still had operand, operation, scale, and
composition error signals. Gate A therefore froze a typed financial-program
design and 12 executable RED contracts before implementation.

Gate B added a model-free numeric-candidate layer. FinQA table values now enter
this new layer as individual cells with explicit row/column metadata instead
of relying on the historical row-to-sentence representation. The extractor
normalizes financial notation with `Decimal`, keeps exact span provenance,
creates source-bound stable IDs, marks page/ordinal/year tokens as non-operands,
and leaves ambiguous metadata unknown.

The public evidence is a synthetic aggregate-only candidate manifest. It is
recomputed from exact fixture bytes and contains no real FinQA question,
answer, case ID, evidence ID, source text, gold program, or individual
candidate ID. Gate B closed with 20 focused tests, 119 external-dataset tests
plus 10 strict Gate C expected failures, 2632 full-suite passes, and a
1002-candidate public audit with zero findings.

This stage did not run a model or publish an accuracy improvement. Raw PDF OCR,
layout recovery, and cross-page table stitching also remain outside Gate B.
The detailed contract, implementation decisions, failed attempts, and
verification commands are recorded in
[finqa_typed_program_protocol.md](../external_datasets/finqa_typed_program_protocol.md).

## 27. FinQA Gate C: reference-only planning and host execution

Gate C replaced the proposed free-literal intervention path with a separate,
versioned typed planner. The historical literal-expression answerer remains
unchanged for future controlled comparison.

The model-facing schema now permits only candidate references and backward
step references over seven financial operations. The host independently
validates strict schema, literal absence, provenance, deterministic numeric
reconstruction, admitted evidence, candidate role, temporal/metric/unit/scale/
sign compatibility, direction, arity, zero division, and resource budgets.
Only a validated AST reaches the fixed-precision Decimal compiler.

Implementation review found and fixed five non-obvious defects: normalized
values were not initially re-bound to raw text; candidate IDs were not
recomputed at the execution boundary; frozen Pydantic models still contained a
mutable step-value dictionary; value-ratio intermediate steps lost
metric/entity metadata; and adding Gate C code invalidated the extractor source
hash recorded by the Gate B manifest. The first four were hardened in code.
The Gate B manifest remains byte-immutable, and a new v2 source binding proves
the candidate identity set did not change.

Verification also exposed a correct interaction with the trusted identity
boundary: pytest JWKS/HMAC fixtures were rejected when a custom D-drive
`--basetemp` was outside `.private`. The acceptance run moved the temporary
root under `.private` instead of weakening the private-path rule. Gate C closed
with 43 focused tests, 162 external-dataset tests, and a D-drive full run of
2674 passes, 30 conditional skips, and zero failures.

Gate C uses deterministic tests and a fake chat boundary only. It adds no real
model score and makes no accuracy-improvement claim. Retrospective diagnostics
and a separately frozen confirmatory cohort remain later gates.

## 28. FinQA Gate D: multiple proposals and deterministic host selection

Gate D added a separate multi-program layer without changing the Gate C
single-program planner or compiler. One model response proposes exactly 2-4
reference-only programs. The host parses the outer envelope and sends every
inner program through the complete Gate C validation and Decimal execution
boundary.

Valid programs are grouped by canonical value and unit. Exact duplicates,
commutative variants with the same candidate/evidence closure, and strict
provenance supersets cannot add votes. Support is the number of minimal
candidate/evidence closures; ties then use fewer steps, candidate references,
and evidence references. Equal-ranked conflicting values become `AMBIGUOUS`
instead of being decided by array order or hash. All-invalid input becomes
`NO_VALID_PROGRAM`.

RED-first review exposed one substantive selector defect: a valid program
padded with an extra zero candidate initially inflated support and changed an
ambiguous decision into a selected answer. Minimal-closure antichain counting
fixed the defect while retaining the padded program in diagnostics. Bounded
attempt diagnostics now record status and aggregate valid/invalid/duplicate
counts without raw prompts or correctness labels.

Gate D closed locally with 16 focused tests, 178 external-dataset tests, and a
D-drive full run of 2690 passes, 30 conditional skips, and zero failures. Only
fake-model and deterministic mechanism tests ran; the public audit was
1008 candidates with zero findings. No accuracy or real-model diversity claim
was added.

## 29. FinQA Gate E: real-model result rejects the typed route

Gate E froze a 100-case `RETROSPECTIVE_DEVELOPMENT_ONLY` comparison before
model calls. All arms used the same disclosed dev cases, exact historical
hybrid Top-10 evidence, `qwen3:8b` digest, bounded attempts, and cyclic arm
order. The runtime was resumable and sealed against immutable private
artifacts; aggregate public evidence contains no case, evidence, question, or
answer content.

The result rejected the intervention. B0/B1/B2 strict accuracy was
`57%/5%/6%`, coverage was `99%/9%/11%`, and grounded strict accuracy was
`50%/5%/6%`. B1/B2 created `54/52` regressions, only `2/1` fixes, and zero
fixes among the 21 historical operand-selection failures. Mean latency was
`12.18x/14.58x` B0.

Post-run audit also found a private-v1 metric-name ambiguity and missing B1
failed-attempt compiler counts. Public v2 separates refusal from protocol
error and omits the unrecoverable compiler total rather than estimating it.
Future errors preserve compiler-call counts. A Git-history verifier binds the
public result to the exact pre-result execution commit `9180b7e`.

Decision: `COMPLETE_REJECTED`. Gate F is blocked; the next allowed work is
disclosed-development typed-contract calibration.

## 30. FinQA Gate E2: calibration improves the architecture but rejects adoption

Gate E2 froze the disclosed 100-case Gate E cohort into a deterministic,
stratified 60-case calibration cohort and an unconsumed 40-case internal-
validation cohort. The split, source hashes, adoption gates, and content-free
failure matrix were committed before changing runtime semantics.

Three real-model calibration iterations used the same Gate E evidence and
`qwen3:8b` digest. v2 distinguished unknown metadata from known conflicts and
raised strict accuracy from 5.00% to 13.33%. v2.1 reduced candidate noise and
constrained program graphs, but failed: strict accuracy fell to 6.67% and 26
cases ended in invalid-program-schema errors.

v2.2 changed the ownership boundary. The model emits only one calculation
template and ordered allowlisted candidate IDs. The host compiles that sketch
into the typed DSL, validates provenance/compatibility, and performs Decimal
execution. Coverage reached 81.67%, strict accuracy 26.67%, grounded accuracy
25.00%, and mean/p95 latency 2.19s/3.38s. It fixed five B0 errors and three
historical operand-selection failures.

The intervention was still rejected against the actual B0 baseline:
strict/grounded deltas were -25.00/-18.33 percentage points, correct-to-wrong
was 20/60, and protocol errors were 11/60. A coarse operand audit also showed
complete shortlist coverage for only 25/60 cases; 24 answered-wrong cases and
seven non-answers lacked at least one coarse gold operand.

Decision: `CALIBRATION_REJECTED`. The 40-case internal-validation cohort,
B2-v2, Gate F, and the frozen test were not run. The next bottleneck is
retrieval/candidate availability, table-level scale propagation, percentage
normalization, and an explicit policy for controlled host constants.

## 31. FinQA Gate E3: numeric evidence input gate passes

Gate E3 retained the disclosed 60-case calibration cohort and left the
40-case internal-validation cohort and frozen test untouched. The corrected
post-shortlist starting point was 48/60 complete cases, not the coarse 25/60
diagnostic originally published by Gate E2.

The implementation added a versioned v2 extractor without modifying v1
candidate bytes. It distinguishes prose parentheses from accounting
negatives, extracts amount-like row and column headers, keeps surface and
normalized values on one provenance identity, expands bounded table/text
context, and scans every proposed unit with RetrievedContentGuard. A separate
deterministic shortlist accepts at most 128 candidates and emits at most 24.

Four correctness issues were caught before formal publication: accidental v1
source-hash invalidation, a stale 64-candidate planner boundary, an incorrect
one-to-one rule for repeated program operands, and candidate explosion caused
by date-like column headers. The final amount-header filter recovered the last
gold parse miss while reducing pre-shortlist p95 from 99 to 71. No frozen
threshold was changed.

The committed zero-model-call audit improved post-shortlist numeric input
completeness from 48/60 (80.00%) to 58/60 (96.67%), reached 60/60 gold-
evidence parse completeness, and recovered 15/16 diagnosed retrieval-missing
operands. P95 closure was 27 evidence units, 4,794 characters, and 71
pre-shortlist candidates. All 1,168 proposed units were Guard-scanned. All 11
input gates passed.

Decision: `INPUT_GATE_PASSED`. This is not answer accuracy and does not
overturn Gate E2's `CALIBRATION_REJECTED` decision. Typed v2.3 model
calibration, the 40-case internal validation, and frozen test remain not run.
Closeout passed 2,741 tests with 30 conditional skips and zero failures; the
public audit inspected 1,052 candidates with zero findings. Compileall,
dependency consistency, and diff checks passed. Ruff was not installed, so no
lint claim was made.

## 32. FinQA Gate E4: better inputs expose the semantic planner bottleneck

Gate E4 froze its protocol before new model calls, reused the exact 60 stored
B0/v2.2 rows, and executed only the v2.3 intervention with the pinned
`qwen3:8b` digest. The v2 evidence path required a new source-bound validator:
the old v2.2 validator correctly rejected v2 identities rather than silently
accepting an incompatible provenance format.

The result was negative. B0/v2.2/v2.3 strict accuracy was
51.67%/26.67%/20.00%, grounded accuracy was 43.33%/25.00%/18.33%, and coverage
was 98.33%/81.67%/73.33%. V2.3 regressed six v2.2-correct cases and fixed two;
against B0 it regressed 22 and fixed three. Only latency and prerequisite
gates passed, so internal validation remained unconsumed.

Aggregate failure analysis showed that 44 answers were emitted, but 32 were
validly compiled and semantically wrong while 16 ended in protocol errors.
The input-complete count remained 58/60, confirming that candidate
availability was no longer the primary bottleneck. The cohort contained 28
multi-step gold programs, while the v2.3 sketch emitted one host operation.
Add/subtract slices were especially weak at 0/7 and 2/11 strict.

The closeout added canonical aggregate public evidence, public-only and
private-bound verification, and private-run summary recomputation from all 60
detail rows. The typed route remains disabled. Gate E5 is limited to a frozen
calibration ablation of multi-step operation skeletons, semantic operand-role
binding, and training-only dynamic structural demonstrations.

## 33. FinQA Gate E5: structural demos improve validity, not semantics

Gate E5 froze a four-arm ablation before implementation and new model calls:
sealed v2.3, direct multi-step generation, two-stage semantic-role
decomposition, and the same role route with three train-only value-free
structural demonstrations. The three interventions ran in cyclic order with
each arm appearing in each position 20 times.

Direct multi-step and no-demo role generation failed decisively: coverage was
8.33% and 3.33%, with 55 and 58 protocol errors. Dynamic demonstrations
recovered role-route coverage to 73.33% and reduced protocol errors to 16, but
strict/grounded accuracy reached only 21.67%/20.00%, a 1.67-point gain over
v2.3. Thirty-one of 44 valid demo-arm answers remained wrong. No arm passed
the frozen progress and B0 shadow gates.

The run stayed on the disclosed 60-case development calibration. Internal
validation remained `NOT_RUN`, frozen test remained `UNTOUCHED`, and all typed
routes remained disabled. Public evidence can be verified without private
data and independently rebuilt from the private hash-sealed run.

An implementation incident also exercised historical reproducibility:
initial train support changed two files bound by older protocol hashes, causing
three source-hash tests to fail. Those files were restored byte-for-byte and
all train-specific behavior moved into new E5 modules. External tests then
passed 260/260, and the pre-execution full suite passed 2773 tests with zero
failures.

The measured next bottleneck is role-to-candidate compatibility and operation
semantics. A future Gate E6 must freeze a compatibility-filter/ranker ablation
before any new model calls; it may not weaken validation or consume hidden
cohorts.

## 34. FinQA Gate E6: full-pool ranking and explicit role queries

E6-v1 proved that a global numeric shortlist removed required operands before
role binding. E6-v2 moved the full Guard-admitted operand pool host-side,
separated evidence roles from controlled constants, added a five-step
source-bound Decimal compiler, and enforced role-specific candidate enums.

The authoritative E6-v2 v4 audit improved role recall@8 from 75.91% to 83.74%
and complete case@8 from 63.33% to 77.59%, while source recall reached 100%.
It still failed the frozen 95%/90% gates. A local-window/diversity ablation was
measured, regressed, recorded and removed.

The remaining failure was contractual: several roles had identical
`component/none` descriptions. E6-v3 added bounded planner-generated
`role_query` and `expected_period` fields without weakening Guard admission,
identity or provenance. The offline gold-descriptor upper bound reached 99.19%
role recall@8 and 98.28% complete@8. This is an interface-capacity result only;
real planner and answer quality remain unmeasured, and serving stays disabled.

## 35. FinQA Gate E7: safe descriptors expose semantic recoverability limits

E7 first tested question-only role queries. Conservative deterministic queries
reached 80.49% role recall@8, while pinned `qwen3:8b` free-query generation
fell to 63.41%. The negative result rejected another unconstrained query-
rewriting iteration.

A new value-free descriptor boundary then removed candidate values, candidate/
evidence/source IDs and provenance from selector input. Both raw and sanitized
descriptor fields are Guard-scanned; only the host retains descriptor-to-
candidate mappings. The contextual v2 catalog passed its offline Oracle gate
at 95.93%/100% Recall@4/@8 and 100% complete@8 with zero model calls. This is
catalog capacity, not answer accuracy.

The real enum-only `qwen3:8b` selector failed at 56.91%/59.35% Recall@4/@8
and 93.10% schema validity. Deterministic lexical v1 beat it with 67.48%/
78.05%; normalized lexical v2 improved Recall@4 to 70.73% and complete@8 to
75.86%. A fully pinned local BGE-M3 hybrid passed safety, identity, request and
latency gates but regressed quality to 65.04%/74.80%. Typed structural v4
raised Recall@8 to 80.49% while lowering Recall@4 to 69.11%. Every runtime
variant failed the unchanged 85%/95%/90% quality thresholds and stayed off.

Failure decomposition found eight roles with no visible lexical signal, 12
with a correct descriptor below the four-descriptor cutoff, and six where the
correct descriptor was selected but candidate expansion/ranking lost the
number. The next allowed work is a retrievability-aware descriptor data
contract and descriptor-aware candidate reranker. Internal validation and the
frozen test remain untouched.

## 36. FinQA Gate E8: safer context projection improves descriptor recall but not adoption quality

E8 froze a retrievability-aware descriptor and candidate-reranker protocol
against the exact E7 evidence and 60-case development cohort. The new v3
catalog adds balanced number-free local context, bounded narrative topic hints,
Guard rechecks and safe-content grouping for unlabeled numbers from one
evidence unit. The v5 retriever preserves E7 structural scoring and uses the
new hints only when primary fields have no lexical signal.

The first implementation materially regressed: context noise reduced
Descriptor Recall@4 to 79.67%, and fixed two-per-descriptor round-robin reduced
Candidate Recall@8 to 66.67%. Per-role diagnostics showed that correct values
were often the third to sixth member of an already-correct descriptor. The
final reranker restored global scoring, added only a descriptor coverage floor,
accepted explicit admission-order evidence ranks, returned structured empty
results, and used bounded candidate-local provenance windows.

The authoritative run represented all 1,736 admitted operand candidates and
reached 100% Oracle Candidate Recall@8. Runtime Descriptor Recall@4 improved
from 83.74% to 84.55%, while Candidate Recall@8 remained 78.86%. Candidate
Recall@4 and complete case@8 regressed to 66.67% and 74.14%. Uniform
descriptor-priority steps `1/2/4/8` all reduced Recall@8 and were rejected;
priority `0` was selected. The frozen progress gate failed, no internal or
frozen cohort was consumed, and serving remained disabled.

## 37. FinQA Gate E9: grouped CV success does not survive development transfer

E9 froze a train-only learned-ranking protocol before implementation. The
pinned 6,251-case train split shared all 35 disclosed-development companies,
so E9 excluded those companies and retained 3,068 supported cases from 99
companies. Five deterministic company-grouped folds contained 613-615 cases
each. The feature contract exposed 23 value-free runtime fields and prohibited
case/company identity, answers, gold programs, evidence IDs and numeric values.

A deterministic class-balanced L2 ridge scorer was fitted with NumPy. The
training ledger prepared 2,932/3,068 cases, retained 2,891 labelable cases,
5,952 role groups and 54,936 descriptor examples, and recorded 136 failures
plus 1,213 empty-table-cell normalizations. No LLM call was made. Company-
disjoint OOF Descriptor Recall@4 improved from the E8 score's 88.76% to 90.84%
(+2.08pp) with 1.24pp fold standard deviation, passing the train/CV gate.

The single authorized disclosed-development run then failed. Descriptor
Recall@4 fell from 84.55% to 78.86%, Candidate Recall@8 from 78.86% to 75.61%,
and complete case@8 from 74.14% to 72.41%. Conditional candidate retention
improved from 93.27% to 95.88%, showing that second-stage ranking was not the
primary regression. Across 123 roles, 93 hits were retained, 11 regressed, four
were gained and 15 were missed by both systems.

The postmortem identified a train/serving evidence mismatch, a pointwise-vs-
Top-4 objective mismatch, unbounded learned overrides of the E8 ordering and
correlated feature signs. E8 remains champion, the E9 artifact is disabled,
the formal 60-case budget is consumed, internal validation remains `NOT_RUN`,
and frozen test remains `UNTOUCHED`. E10 may use a new train-only protocol but
must not tune and rerun the consumed E9 cohort.

## 38. FinQA Gate E10: realistic evidence fixes direction but misses the gate

E10 replaced E9's 100%-gold-covered `model_input` training source with official
`retrieved_all` score-sorted Top-10-or-all-available evidence. The frozen
selection covers all gold evidence for 3,014/3,068 cases and any gold evidence
for 3,067/3,068, without gold insertion. It retained the existing Guard,
numeric closure, candidate identity and value-free descriptor boundaries.

The new 21-feature model fits positive-minus-E8-hard-negative descriptor pairs
with deterministic L2 ridge and applies only a `[-4,+4]` residual around E8.
Across 2,925 prepared cases, 2,881 labelable cases, 5,923 roles and 53,457
pairs, company-disjoint OOF Descriptor Recall@4 improved from 84.8894% to
85.8349%. Every fold improved; minimum coefficient cosine was 0.9884.

The `+0.9455pp` aggregate gain missed the pre-frozen `+1.0000pp` authorization
gate. E10 therefore did not access the internal 40-case cohort or frozen test,
did not enter serving, and did not displace E8. The project preserves this as a
near-miss negative decision rather than lowering the threshold after seeing the
result. A future E11 must use new versioned code and nested company-grouped CV.

## 39. FinQA Gate E11: nested Top-4 learning passes internal non-regression

E11 converted descriptor labels into cutoff-aware swaps: missed roles compare
their highest E8 positive against Top-4 negatives, while single-positive hits
add preservation pairs against negatives just below the cutoff. Each role has
normalized total weight. The 18-config grid varied bounded adjustment, L2 and
preservation weight without adding an ML dependency.

Configuration selection moved inside four-fold company loops, leaving one
outer company fold untouched per round. Nested outer Descriptor Recall@4 moved
from 84.8894% to 86.0881% (+1.1987pp). All five folds improved; paired outer
roles contained 99 gains and 28 regressions. The final modal configuration was
`adj08-l2-100-p025`.

This authorized the only internal run. Thirty-seven typed cases contained 76
roles; three other cases shared the same fail-closed capability fallback in
both arms. Descriptor and Candidate Recall@8 moved from 84.21% to 86.84%, and
complete cases from 28/37 to 30/37. Paired roles were 64 retained, zero
regressed, two gained and ten missed by both.

The first internal command exposed a shared oracle-construction exception
before the old E8 helper's catch boundary. It stopped before any evidence write.
A common capability wrapper preserved strict schema validation and represented
unsupported contracts as paired fallback rows. The incident is public and the
completed model-quality run remains ordinal one.

All internal gates passed, but two discordant gains give exact McNemar `p=0.5`.
E11 therefore advances only to shadow integration. It does not replace E8,
does not establish answer accuracy, cannot reuse the consumed internal cohort,
and does not access frozen test.

## 40. FinQA Gate E12: shadow integration preserves the champion boundary

E12 froze a mechanism-only protocol before implementation and bound it to the
complete E8/E11 evidence chain. The resulting coordinator always completes an
immutable E8 primary decision before an E11 observation can run. A canonical
input SHA prevents mismatched comparisons; no challenger branch can return a
replacement selection.

The loader verifies E8/E11 protocols, nested CV, artifact, internal result and
postmortem hashes plus their authorization decisions. Any drift disables the
challenger. Runtime observations contain only controlled outcomes, role/change/
overlap counts, a latency bucket and circuit state. Questions, values, IDs,
provenance, scores and input fingerprints are excluded; aggregate metric keys
are schema-validated and updates are lock-protected.

Fault injection verified default-off zero calls, error and elapsed-budget
isolation, and a three-failure/five-observation cooldown with half-open
recovery. The deterministic public audit passed all 11 mechanism gates and 14
focused tests; external tests passed 408, the full repository passed 2921 with
29 skips, and public audit reported 1278 candidates with zero findings. Its one
synthetic real-selector probe is wiring evidence only, not quality or latency
evidence.

The first full-suite attempt forced pytest basetemp inside the repository and
triggered four correct path-contract failures. A four-test minimization proved
that identity private-path enforcement and external-path redaction both depend
on a repository-external temp root. Moving `TEMP/TMP` to a D-drive external
directory fixed all four without an application change, after which the full
suite passed.

E11 remains disabled and E8 remains champion. E12 did not add a production
FinQA endpoint, real traffic, hard process cancellation, durable distributed
metrics, answer-accuracy evidence or frozen-test access. E13 is limited to
unlabeled operational replay and stronger worker isolation over disclosed
train-only inputs.

## 41. FinQA Gate E13: hard process isolation becomes measured behavior

E13 implemented the process boundary that E12 intentionally did not claim.
The challenger now runs in one persistent Windows-compatible `spawn` process
behind canonical byte-bounded IPC. The parent owns the immutable E8 primary
decision, checks the E12 same-input binding, enforces a hard deadline, can
terminate/kill and join the old PID, and starts a verified replacement after a
timeout, crash or malformed response.

The protocol pins official FinQA train bytes and deterministically selects 128
cases from 71 companies. Answer, execution-answer, gold-evidence and annotated
row fields are projected out before typed validation. The runtime uses only
retrieved and Guard-admitted evidence to infer source-bound constants. It still
uses gold program structure, so the replay measures worker mechanics rather
than planner or answer quality.

The accepted run prepared 117/128 cases and completed 117/117 isolated
observations. Replay worker error, timeout and restart counts were all zero;
p50/p95 observation latency was 5.659/16.443 ms and maximum process peak RSS
was 91,136,000 bytes. E8/E11 produced 74 MATCH and 43 DIVERGED case-level
observations across 252 roles, but these are behavior counts, not correctness.
All five timeout/crash/malformed/oversize/immutability fault probes and all 16
operational gates passed. Closeout verification passed 16 focused tests, 424
external-dataset tests, and the full repository at 2937 passed / 29 skipped;
the public audit reported 1291 candidates with zero findings.

Implementation exposed four useful failures before closeout: the 78 MiB train
file exceeded the generic loader and contained one invalid gold-evidence key;
an old source-constant helper silently depended on gold evidence; the initial
selection-algorithm label disagreed with its expected ID hash; and the audit
mistook dataclasses for Pydantic models before a public schema key was also
overwritten by dict expansion. None was hidden by weakening a gate. The final
protocol and public evidence were regenerated before commit and are bound to
the exact implementation hashes.

E11 remains default-off and E8 remains champion. No internal or frozen cohort,
network model, production route, OS sandbox, concurrent pool, durable queue,
answer labels or serving-promotion authority entered E13.

The first E13 push, exact commit `09aabf5`, then exposed a clean-checkout test
contract failure in Actions run `30734063847`: both Ubuntu and Windows passed
their other 2,900-plus tests, but three test setups tried to open ignored
private FinQA train bytes. The repair separated public protocol/gate tests from
the two private-train integration tests. Missing private data now skips only
those two tests; it no longer prevents aggregate contract verification. Exact
repair commit `1ff1707` then passed Actions run `30734383716` across Ubuntu,
Windows, and the dependent Linux container contract in 9m58s.

## 42. FinQA Gate E14: bounded concurrency replaces unbounded growth risk

E13 isolated one persistent Shadow Worker but did not define behavior under
concurrent arrival. E14 froze a new protocol bound to the exact E13 protocol
and evidence hashes, then placed two verified spawn workers behind a four-slot
FIFO queue. Four caller threads can submit work, while each dispatcher remains
fixed to one E13 Worker and preserves single-in-flight IPC.

The Pool now has explicit overload and lifecycle semantics. Admission waits at
most 0.25 seconds before rejecting the newest request, callers stop waiting at
a two-second response deadline, late Shadow results are discarded, and close
prevents new admission before draining and reclaiming dispatchers and child
processes. Review found a race between checking `RUNNING` and queue insertion;
both actions now occur under the state lock, so a request cannot be queued
behind shutdown sentinels. A later review also found simultaneous close calls
could overfill the queue with duplicate stop sentinels after dispatchers
exited. Shutdown now has one owner and bounded event waiters; a concurrent
close regression test preserves that invariant.

The fixed 128-case train selection produced the same 117 prepared requests.
All 117 were admitted and completed, with no backpressure, deadline, worker
error, or restart. Both workers were simultaneously active, queue high-water
was 2/4, queue-wait p95 was 13.354 ms, Pool end-to-end p95 was 26.439 ms, and
the timed observation phase reported 243.251 requests/s. Seven fault probes
and 21 gates passed; full regression reached 2949 passed / 29 skipped. These
are local unlabeled Pool measurements, not answer accuracy, end-to-end RAG QPS,
production capacity, or E11 promotion evidence.

Exact implementation commit `3e5ebb8` then passed Actions run `30736504721`
in 9m41s across Ubuntu, Windows, and the dependent Linux container contract;
one SBOM artifact was published.

## 43. FinQA Gate E15: scaling becomes a measured capacity envelope

E14 had one bounded configuration but no scaling comparison. E15 froze a
1/2/4-worker by 1/4/8-caller matrix with three repetitions per configuration,
one fixed 117-request prepared workload, fresh process Pools per trial, setup
excluded from observation timing, and a counterbalanced ascending/reversed/
rotated schedule. The aggregator rejects missing or reordered trial rows and
computes medians, relative spreads, pre-registered speedup/efficiency pairs,
resource bounds, and a deterministic local recommendation.

All 3,159 request observations completed across 27 trials without
backpressure, deadline, Worker error, restart or residual process. Median
throughput was 158.300 requests/s for one Worker at four callers, 328.517 for
two Workers, and 631.169 for four Workers. The pre-registered 1-to-2 comparison
at four callers measured 2.075x speedup; 1-to-4 at eight callers measured
3.441x. Four Workers with four callers was the local optimum; increasing to
eight callers reduced median throughput to 553.185 while increasing queueing.

The maximum trial p95 was 69.598 ms and the four-worker child RSS upper bound
was 361,205,760 bytes. All 22 gates and 10 focused tests passed. These are
train-only, label-free post-primary Shadow observations on one Windows host,
not answer accuracy, complete RAG QPS, production capacity, cold-start latency,
or an SLO. E8 remains champion, E11 remains default-off, internal remains
consumed and unaccessed, and frozen test remains untouched.

Local closeout passed 446 external-dataset tests and the full repository at
2959 passed / 29 skipped, with only three known SWIG deprecation warnings.
Compileall, dependency consistency, frozen-evaluation verification, the
quality-review packet, expanded-corpus quality and public audit also passed;
the public audit reported 1315 candidates and zero findings.

Exact implementation commit `bd35fa1` passed GitHub Actions run `30740853135`
in 10m24s. The Ubuntu/Windows matrix completed 2/2, the dependent Linux
container contract passed in 4m05s, and one Python runtime SBOM artifact was
published.

## 44. FinQA Gate E16: offline capacity becomes a service-owned dark path

E12-E15 had a progressively stronger offline Shadow runtime, but no real API
route or service lifecycle owned it. E16 first audited the contracts and found
that enterprise chat supplies free-text question/user/top-k inputs while E11
requires a typed program skeleton, safe descriptor catalog and bound E8 primary
selection. Instead of fabricating those values, E16 recorded the mismatch and
implemented a generic injectable dark-observation owner. The real FinQA adapter
remains a later gate.

The frozen E16 protocol binds E15 protocol/evidence hashes and requires an
OFF/zero-sampling default, process-keyed request-ID sampling, nonblocking
bounded admission, an admission-time deadline, no primary mutation or wait,
minimal ephemeral provider fields, aggregate-only public telemetry, controlled
shutdown and explicit non-claims. FastAPI lifespan now starts/closes the owner;
the chat route offers only after its response and feedback receipt exist; the
operator endpoint exposes only bounded aggregates.

The local audit ran 24 paired OFF and LOCAL_TEST_ONLY requests through the real
route. All 24 enabled observations completed, OFF called the provider zero
times, and exact response/receipt mismatches were zero. Offer p50/p95/max was
0.017/0.024/0.033 ms. Provider error, deadline overrun, one-slot queue
backpressure and post-close admission were isolated; two admitted fault-probe
items reached two terminal states and controlled residual workers were zero.
All 17 frozen gates passed, and the public audit reported 1324 candidates with
zero findings.

Several negative findings improved the result. A hand-written response test
missed the existing safe request ID, so it was replaced by complete OFF/ON byte
comparison. Windows `time.monotonic()` had 15.625 ms resolution and printed
false zero latency, so the owner moved to `perf_counter()`. Evidence now labels
pre-shutdown and post-shutdown worker phases separately. Finally, the public
audit rejected fake credential-shaped literals in the audit helper; runtime
construction and public-domain derivation removed the finding without weakening
the scanner.

E16 remains mechanism-only and default-off. It does not show production
traffic, quality, hard thread cancellation, distributed durability, an SLO or
FinQA serving. E17 must freeze a typed eligibility/adapter contract before
injecting E11 through the service owner.

The first full repository run then exposed a provenance dependency rather than
a behavior regression: the historical trusted-identity result bound old hashes
for `app/main.py` and `app/runtime/resources.py`. Field-level comparison found
no case differences. The project preserved that v2 artifact, taught the model
to validate v2 against its historical source set, expanded current v3
provenance to include config and the dark runtime, and emitted a new immutable
20/20 result. Security passed 245 tests with six platform skips; the final full
run passed 2977 tests with 29 skips and three known warnings.

Exact implementation commit `2143ba7` passed GitHub Actions run `30751922977`
in 10m06s. Ubuntu and Windows completed successfully, the dependent Linux
container contract passed in 4m03s, readiness/rollback drills passed and one
Python runtime SBOM artifact was published.

## 45. FinQA Gate E17: online-only typed eligibility and adapter boundary

E16 exposed a generic provider but could not honestly call E11 because the
enterprise request lacked a typed skeleton, safe catalog and bound E8 primary.
E17 audited the old replay path and found that E13-E15 derived the skeleton
from FinQA gold program structure. That is valid for the disclosed replay but
would be target leakage in an online service. The new frozen protocol therefore
allows only `ONLINE_RULES` or `ONLINE_MODEL` skeleton origin and only
`RETRIEVED_ADMITTED_EVIDENCE` catalog origin. Gold answers, programs, evidence
labels and target labels cannot enter the typed context schema.

The implementation adds a self-hashing typed context, an exact eligibility
state machine, a capacity/TTL bounded consume-once resolver and an E16 provider
adapter. Ineligible resolutions return `NOT_APPLICABLE` before E8 or E11. An
eligible resolution is bound to the exact request question; the adapter then
computes E8 v5 primary internally and invokes the verified isolated E11 worker.
Only `MATCH` and `DIVERGED` become E16 `MATCH` and `DIFFERENT`; faults become
fixed safe provider codes and aggregate counts.

The six-reason eligibility matrix caused zero worker calls for all five
ineligible reasons. Two synthetic outcome probes mapped exactly, the E16
background composition completed `ADMITTED -> MATCH`, and two real persistent
`spawn` worker observations both returned `MATCH`. The first observation,
including process startup, took approximately 732 ms; the warm observation was
approximately 3.6 ms. The worker exited with code zero and controlled service
threads and typed contexts both reached zero after close. All 24 frozen gates,
23 focused tests and 52 related E12-E16 regressions passed. Public audit reported
1339 candidates and zero findings.

The full repository then passed 3000 tests with 29 platform skips and the same
three known SWIG deprecation warnings. Dependency consistency, compileall,
frozen evaluation hash verification, quality-review packet verification and
expanded-corpus quality all passed.

One implementation issue was found by RED/GREEN testing: adding zero to a
`Counter` still created visible `expired_total: 0` and
`shutdown_discarded_total: 0` fields. Counters now appear only when a real event
occurs, keeping metric semantics stable. Duplicate request IDs are rejected
without overwrite because cross-request context replacement would be an
identity-binding failure.

A second adversarial review found that a resolver could throw the adapter's
public error class with attacker-controlled text, and a NaN deadline could
bypass ordinary comparisons. The adapter now maps every resolver exception to
one fixed code, verifies the exact resolution type, rejects non-finite
deadlines and rejects calls after close before invoking the resolver.

E17 remains mechanism-only and service-disabled. It does not create an online
skeleton or safe catalog from the primary enterprise retrieval result, does not
change `/agent/v2/chat`, does not access the consumed internal cohort or frozen
test, and does not establish answer quality, traffic or an SLO. E18 must add a
versioned ACL/Guard-admitted evidence-to-context service seam and lifecycle
ownership before any default-off route experiment.

Exact implementation commit `2e6a882` passed GitHub Actions run
`30759155310` in approximately 9m59s. Ubuntu and Windows completed
successfully, the dependent Linux container contract passed in about 4m09s,
readiness/rollback drills passed and one Python runtime SBOM artifact was
published.

## 46. FinQA Gate E18: admitted Agent evidence becomes online typed context

E17 could consume a complete typed context but the enterprise Agent did not
produce one. E18 inspected the live V2 controller and found the necessary
authorized data in `ControllerState.evidence_by_aspect`: immutable
`AdmittedEvidenceChunk` objects created after tenant/region/group ACL filtering
and retrieved-content Guard admission. The E16 background request intentionally
lacks identity, so E18 rejected the tempting design of re-retrieving by
question in the worker.

The new versioned builder projects only admitted chunks, enforces 32-unit,
16,000-character and 128-candidate budgets, rescans every context with the
current Guard, extracts typed Decimal candidates and keeps only operand roles.
Seven narrow English/Chinese rule families create value-free semantic
skeletons for percentage change, ratio, subtraction, addition, multiplication,
division and average. The existing v3 safe catalog then removes numeric values
from the descriptor-selection surface, and E17 binds the exact
question/skeleton/catalog bytes.

The coordinator freezes a register-before-offer order to prevent the dark
worker from racing ahead of context registration. It retains context only for
`ADMITTED`; sample skip, unavailable, backpressure and closed outcomes discard
immediately. Duplicate registration is handled separately: because the old
context belongs to the first request, registration failure must not call
`discard(request_id)` and delete it. Lifecycle close stops the E16 owner before
closing the E17 adapter/worker and resolver.

The controlled audit covered all seven rule families with 112 eligible builds,
zero secondary retrieval and zero model calls. Local preparation p50/p95/max
was 0.623/0.921/1.523 ms. Eight enabled observations were admitted and
completed; default-off worker calls, primary response mismatches, residual
workers and residual contexts were all zero. A one-slot blocking-provider
fault injected two admitted requests and one deterministic backpressure
rejection; only the rejected context was discarded and the first two were
consumed.

The first test runs found obsolete fixture fields rather than production
failures: the repository's current `QueryAnalysis`, `BudgetState` and
`ControllerState` schemas had moved beyond copied test constructors. Updating
the fixtures produced 22 focused passes. Three immutable public-evidence tests
then brought E18 focused coverage to 25, while E16-E18 related regression
reached 61 passes. The first 19-gate audit was also strengthened after review
because it declared backpressure cleanup without producing queue saturation;
the final audit executes that failure path, covers all six preparation states,
and passes 22/22 gates.

The final repository run passed 3025 tests with 29 platform skips and the same
three known SWIG deprecation warnings. Frozen evaluation hash, quality-review
packet, expanded-corpus quality, dependency consistency and compileall passed;
the public repository audit scanned 1350 candidates with zero findings. The
quality-review packet remains honestly `NOT_RUN/not_independent`.

E18 remains an injectable component, not a silently enabled route. E16's
historical evidence binds `main.py`, `config.py`, `resources.py` and the dark
owner to exact hashes. E19 must create a versioned serving assembly and paired
OFF/LOCAL_TEST_ONLY API evidence. E18 does not establish answer quality,
arbitrary financial coverage, production traffic, an SLO or E11 promotion.

The first E18 remote acceptance run `30774647704` preserved a useful red
result: Ubuntu passed, but Windows failed the existing four-process
same-cache-key regression with `cache_root_unsafe`. Reproduction showed that
cache-root contents were scanned before the cross-process lock; a waiting
process could enumerate an owned temporary path and then `lstat()` it after the
active writer atomically published and removed it. The final repair in
`2a73cbb` separates root-path preparation from root-content validation and
runs the content scan after lock acquisition. It still rejects unsafe hard
links with the original error contract. Local evidence is the paired
concurrency/hard-link regression, `20/20` process stress repetitions, and the
full `3025 passed / 29 skipped` suite. Replacement remote acceptance is run
`30775290120`: Ubuntu, Windows and the Linux container contract all passed in
`9m36s`; readiness/rollback and SBOM publication also passed. The runtime SBOM
artifact digest is
`sha256:0f93fcc2d3d7cef9dc0470b901ae663de1a0a273cd6b04a939db70a9d79d9b9a`.

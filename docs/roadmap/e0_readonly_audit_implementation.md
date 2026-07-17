# E0 只读审计与工业化设计：初学者实施记录

日期：2026-07-16

阶段状态：已完成，只读审计；本文件为基于现存证据的历史回填

基线：分支 `codex/rag-eval-system`，HEAD `7aec4b950e012d3f24b8e1877d6391201e9b8f90`

## 1. 先说人话

E0 不是“什么代码也没写，所以什么都没做”。它解决的是更靠前的问题：**先确认旧项目到底已经会什么、不会什么，再决定升级顺序**。如果不做这一步，很容易把计划中的 ACL、版本治理、多格式解析或 Agent 工具误写成已经完成，也容易为了追求新名词进行大重构，最后却无法证明效果变好。

E0 只读检查 Git、数据、索引、检索、Agent、评测、API、UI 和文档。它没有修改业务代码，没有运行新的 live LLM 评测，也没有改变 GitHub。最终产物是三份设计/计划文档和一条可回滚的 E1-E7 路线。

## 2. 初学者术语

| 术语 | 白话解释 | 本项目中的例子 |
|---|---|---|
| baseline | 后续改进要比较的原始版本 | 旧 BM25、dense、RRF 和 15 文档索引 |
| provenance | 一个结果是由什么代码、数据、模型和配置产生 | 旧 eval 缺少统一 Git SHA、数据 hash 和模型版本 |
| gap analysis | 当前能力与目标能力之间的差距表 | `current_to_v2_gap_matrix.md` |
| phase gate | 完成并验收当前阶段后才能进入下一阶段 | E0 完成后等待 `批准E0...` |
| ablation | 只开关一个组件，观察它是否真的有贡献 | BM25-only vs dense-only vs RRF |
| regression set | 已经用过、以后用于防退化的测试集 | 旧 agent loop test 已运行，不能再称全新 held-out |
| held-out | 开发时不看结果、最后只用于一次泛化验证的数据 | E1 后新冻结的 v2 test |

## 3. E0 是怎样检查项目的

推荐阅读顺序：

```text
Git/README
-> data/sample_docs 与 indexes
-> app/chunker.py + app/retriever.py
-> app/rag_service.py
-> app/agent/*
-> scripts/eval_*.py + data/eval
-> app/main.py + Streamlit
-> docs/PROJECT_STATUS.md 与私人简历主张
```

### 3.1 Git 和公开入口

`[OBSERVED]` 审计基线的本地功能分支是 `codex/rag-eval-system`，HEAD 为 `7aec4b9`。当时远端默认分支仍是 `main`，仓库首页没有展示功能分支最新 Agent 能力。

为什么先查 Git：招聘者看到的是默认分支，不是本机里“最先进”的代码。代码存在但公开入口不可见，属于展示和发布问题，不等于代码功能问题。E0 只记录差距，不擅自 merge、push 或改默认分支。

### 3.2 数据和索引

`[OBSERVED]` 旧数据只有 15 份 Markdown 文档、75 个 chunks。每个 chunk 只有：

```text
chunk_id
source
section
text
```

这四个字段可以支持简单检索，却无法回答：

- 这是哪个 `doc_id` 的哪个版本；
- 当前用户是否有权限；
- 文档在哪个 tenant、region、department；
- 何时生效、何时废止；
- 哪份文档 supersede 哪份；
- 哪个 parser/chunker 版本生成了它。

所以旧系统不是“检索算法完全错误”，而是**输入契约太薄**。E1/E2 需要先补数据治理字段，再让检索消费它们。

### 3.3 旧检索路径

旧调用链：

```text
question
-> app.retriever.hybrid_search
-> Ollama bge-m3 query embedding
-> FAISS dense ranking
-> jieba + BM25 ranking
-> RRF 合并排名
-> top-k chunks
```

`[OBSERVED]` 这条链确实改变行为，因此保留为 baseline。问题不是“没有向量检索”，而是它加载固定 active 文件，没有 index manifest、版本/ACL filter、父子 chunk、近重复折叠或可回滚 index lifecycle。

### 3.4 旧 Agent 路径

旧 `/agent/chat` 大致执行：

```text
route_query
-> unsafe 时检索前拒绝
-> AdaptiveController
-> retrieval.search
-> evidence.assess
-> sufficient: rag.answer
-> insufficient: 最多一次 rewrite + 第二次 retrieval
-> 仍不足: grounded no-answer
-> guardrail.check
-> response + trace
```

`[OBSERVED]` 真正有价值的部分：Python 控制最多两次检索和一次 rewrite、跨轮证据累积、evidence JSON schema、unsafe pre-retrieval refusal 和 trace。

`[OBSERVED]` 价值有限的部分：非 unsafe route 主要改变标签，不改变检索策略；生产路径不使用 planner；工具只有 search，没有文档内 `find/open`；evidence 不能表达 required facts、missing facts、conflicts 和 coverage。

这就是为什么 E0 没有简单说“已经是 Agentic RAG”或“完全不是 Agent”。准确说法是：**已有受控的自适应检索循环，但 Agentic retrieval 的工具和证据表达仍然有限。**

### 3.5 旧评测

`[OBSERVED]` E0 当时全量测试是 `109 passed, 5 warnings`。旧 retrieval 指标能衡量 gold source 排名；旧 answer eval 使用 must-include、must-not-include、citation 和 refusal 等启发式规则；旧 agent eval 能验证 route、工具序列、预算和 trace。

关键不足：

- answer 的规则匹配不等于语义完全正确；
- agent `case_pass` 没有完整评价最终答案事实和 gold coverage；
- 结果文件缺少统一 provenance；
- 一些 test 已经运行和调试过，不能再称 unseen；
- 固定输出文件名容易覆盖上次结果。

## 4. 三个关键设计决定

<a id="e0-d01"></a>
### E0-D01：R1/R2 和 E0-E7 分阶段

**问题：** 主提示词包含数据、解析、索引、检索、Agent、安全、评测、服务、UI 和文档。如果一次重构，任何失败都很难归因。

**候选方案：**

1. 一次大重构：短期文件变化大，但没有稳定比较点。
2. 先做 UI：展示快，但底层证据仍弱。
3. data/eval-first 分阶段：慢一些，但每阶段可测、可停、可回滚。

**选择：** 方案 3。R1 只做简历可验证门槛；5,000 文档、增量 upsert、OpenTelemetry、Docker 等放入需要再次批准的 R2。

**为什么合理：** 一个面试项目的价值不是组件数量，而是“问题 -> 假设 -> 改动 -> 证据”的完整性。

<a id="e0-d02"></a>
### E0-D02：先 facts/eval，再 parser/index/Agent

**问题：** 如果先改检索，却只有 15 份简单文档和已经用过的题集，无法判断复杂度是否解决了真实企业问题。

**选择：** E1 先建立版本、权限、冲突、噪声和新 eval；E2 才让 parser/index 消费这些输入；E3 再改 retrieval/Agent。

**因果链：**

```text
没有可追溯 facts
-> gold 可能不可靠
-> retrieval failure 无法准确分类
-> Agent 重试看似聪明，但不能证明有效

先建立 facts + eval
-> 每个失败能定位到 fact/doc/ACL/version
-> 后续每项改进才可测
```

<a id="e0-d03"></a>
### E0-D03：保留旧基线并做消融

**问题：** heading-aware、parent-child、reranker 或 Agent 工具增加后，如果只报告新系统数字，不知道提升来自哪里。

**选择：** 始终保留 BM25-only、dense-only、RRF 和旧 chunking adapter。新能力在同一数据、同一 split、同一 top-k 下比较。

**例子：** 如果 parent-child 让 completeness recall 提升，但 p95 latency 明显上升，可以说明收益和代价；如果没有提升，就默认关闭，而不是为简历术语保留。

## 5. E0 没有做什么，以及为什么

- 没有修改 Python：E0 的授权范围是只读。
- 没有运行 live Ollama eval：旧 test 已经使用，继续运行不会恢复 held-out 属性。
- 没有运行有副作用的旧 `build_indexes --help`：源码已显示旧 CLI 入口可能在 import/执行阶段建库。
- 没有修 README 和 GitHub：需要在功能验收和本人授权后统一收口。
- 没有删除 planner/legacy evaluator：必须先保留比较基线。

“没有做”不是遗漏，而是阶段边界。能克制不相关重构也是工程判断。

## 6. 已知边界

<a id="e0-l01"></a>
### E0-L01：旧 test 是 regression

旧 agent loop test 已经运行并用于修复，因此以后可以检测退化，但不能再提供全新泛化证据。E1 创建新的冻结 test，并规定不能根据 test 失败调参。

<a id="e0-l02"></a>
### E0-L02：15 文档不是生产规模

75 个 chunks 足以验证代码路径，却几乎不会暴露大规模索引构建、重复候选、长文档定位、ACL filter 性能和版本冲突。E0 因此拒绝“生产级”主张。

## 7. E0 产物怎样连接下一阶段

| 产物 | 作用 |
|---|---|
| `enterprise_agentic_rag_v2_design.md` | 当前事实、方案比较和目标架构 |
| `enterprise_agentic_rag_v2_plan.md` | E1-E7 的阶段依赖、测试和门禁 |
| `current_to_v2_gap_matrix.md` | 每个旧组件保留、增强、替换或归档的理由 |
| 本实施记录 | 把设计文档翻译成初学者可学习的因果链 |

## 8. 面试怎么讲

### 30 秒版本

“我没有直接重构 Agent，而是先审计旧系统。它已有 BM25+dense+RRF 和有界两轮检索，但只有 15 份 Markdown、75 个 chunks，缺少版本、ACL、索引 provenance，旧评测也不能继续称全新 held-out。所以我采用 data/eval-first 路线，保留旧基线，把升级拆为 E1-E7，每一步都要求消融和阶段门禁。”

### 常见追问

1. **为什么不直接用 LangGraph 等框架？** 当前主要瓶颈是数据和证据，不是缺少编排框架；先保留显式 Python 状态机更容易测试预算和停止条件。
2. **为什么 route/planner 不直接删除？** 它们仍是历史基线；要先完成同数据比较，再归档，避免丢失回滚和消融能力。
3. **109 个测试能证明生产质量吗？** 不能。它只证明已覆盖契约没有回归；规模、live model、并发和安全需要独立证据。
4. **为什么先做合成数据？** 真实企业数据不可公开，受控事实源可以验证版本、权限和 gold，同时必须承认 synthetic shortcut。
5. **E0 最大价值是什么？** 把模糊的“升级成工业级”变成可证伪、可分阶段验收的工程问题。

## 9. 20 分钟本人实验

不改代码，画出两条调用链：

1. `/chat` 从 `app/main.py` 到 `hybrid_search` 再到回答；
2. `/agent/chat` 从 router 到 controller、tool、evidence、retry、answer/no-answer。

对每个函数写一句“它是否真正改变行为”。如果只改变 trace 标签，也要明确写出来。

## 10. 两分钟口述验收

不看文档回答：旧系统哪些能力是真的，哪些只是结构存在但不改变行为？为什么 15 文档和已使用 test 无法支撑 R1？为什么 E1 必须在 E2/E3 之前？

合格标准：能说出至少四个真实文件/函数、两个保留能力、两个缺口和一个不能宣传的结论。

## 11. 证据边界

- E0 原始设计文件与 Git 基线为 `[OBSERVED]`。
- 本文件的初学者解释是 `[RETROACTIVE]`，不冒充当时逐分钟日志。
- E0 没有业务代码 RED/GREEN，因为阶段明确禁止业务实现。
- 旧 `109 passed` 是 E0 当时保存结果；当前 E1 后的全仓库基线已变为 `148 passed`，两者不能混写。

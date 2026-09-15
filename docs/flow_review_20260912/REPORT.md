# 当前 RAG 主流程审查与开源系统对照

审查日期：2026-09-12。状态：REVIEW_COMPLETE_WITH_OPEN_FINDINGS。

本轮只做源码审查、轻量离线诊断和官方资料研究。没有修改生产代码、原有测试、模型配置、历史证据或简历，没有提交、推送、部署或真实模型调用。

## 1. 先说结论

大框架合理，不需要推倒重建。权限过滤、版本绑定、检索内容 Guard、工具预算和引用验证都是有意义的工程能力。

但是，当前实现有一个重要的不协调：安全和审计层已经比较复杂，用户问题的通用理解、完整性判断和日常使用流程却仍比较有限。不能把“有证据账本”“引用核验通过”“检索 coverage=1”理解为问题已经答全。

本轮复现了四个具体缺口：补读发现的冲突没有进入冲突账本；非报销多诉求漏答仍 answered；通用长文档的完整列表读取被截断仍 answered；报销文档后部不重复主题词的材料要求可能漏读且仍 answered。

优先做有限的证据流接通和结构化补读，再评估是否需要 LLM 辅助。不要因为项目需要更像 Agent，就默认增加查询改写、更多模型或更多循环。

## 2. 真实版本与审查范围

| 工作区 | 版本 | 本轮处理 |
| --- | --- | --- |
| `D:\文档\agent\RAG_try` | main，`c9984e92a10a6f417e2c1d8082af7e8f1e11aee1` | 保留已有修改；这里只新增本报告 |
| `D:\文档\agent\RAG_try\.private\release_candidate_20260910` | `codex/local-closeout-20260910`，`152981aba3bc9a15a1035dbfa53dc57651b3c97f` | 本轮主要审查及测试对象；测试前后干净 |
| `D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738` | b07c03d 加既有未提交修改 | 只读核对历史与实验报告，不覆盖 |

[固定候选源码](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/152981aba3bc9a15a1035dbfa53dc57651b3c97f)。不能把根目录 main、旧开发工作树和当前候选版混为一谈。

下文的源码相对位置均以候选工作区为根。源码审查追踪了真实 API 接线；新增四个失败是实际 runner 的离线诊断，不是已观察到的线上 HTTP 事故。

## 3. 实际默认链路

```text
Streamlit 单次问题
  -> FastAPI /agent/v2/chat
  -> Bearer/JWT 身份与服务端 principal
  -> active index / manifest / 检索 profile
  -> RuleFirstQueryAnalyzer
  -> V2AgentController 的有界 search/find/open
  -> 检索候选权限、来源、版本过滤及内容准入
  -> search evidence ledger + 独立保存的 open results
  -> 按预算构造实际交给模型的 evidence packet
  -> 本地 LLM 结构化生成
  -> claim / citation / 有限答案合同校验
  -> answered / partial / refusal 等状态 + trace
```

- `app/main.py:120` 实际调用 `run_agent_v2_chat`。
- `app/agent/runner_v2.py:213` 默认分析器没有注入模型 fallback；`runner_v2.py:675` 的服务工厂使用真实生成 builder，不是所有请求都用摘录桩。
- 仓库还有 Agent Runtime、ToolGateway、LangGraph 等另一套能力，但不能把它们全部画成默认 HTTP 每次必经路径。存在实现，不等于当前入口启用。
- 默认请求 schema 是 question/top_k，不带聊天历史。单轮企业问答可以这样设计，但不能据此宣称默认支持连续追问理解。
- 启动器的 `hybrid_default` 与离线最佳 raw-chunk+BGE 配置不是同一个 profile。演示和指标必须说明使用哪个 profile。

## 4. 已复现的优先问题

### P1-1：open 补充的冲突没有更新 ledger

位置：[controller_v2.py:272](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/controller_v2.py:272)、[controller_v2.py:300](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/controller_v2.py:300)。

实际数据流：search 的内容进入 `evidence_by_aspect`；open 内容进入 `open_results`。重建 ledger 时只传前者。生成阶段又会把合格的 open 内容加入 prompt，因此“模型看到的材料”与“host 用来判断冲突的材料”不一致。

探针问“列出远程办公的所有要求。”，同一文档内有“上限为7天”和“上限为30天”。search 固定命中第一条，真实 open 读到两条，实际交付给模型的 packet 也包含30天。固定模型桩只答7天，最终仍 `answered/completed`，无冲突 warning。

对照：把同样两条材料都作为 search evidence 交给现有 ledger，现有数值冲突规则可以发现矛盾。因此这是接线缺口，不是必须先上语义模型才能解决的问题。

影响：引文确实来自原文，但答案仍可能片面选择互相矛盾的来源。引用存在不能替代冲突处理。应优先修复。

### P1-2：有一个完整性标签，不等于每个诉求都被支持

位置：[evidence_ledger.py:72](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/evidence_ledger.py:72)、[generation_v2.py:275](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/generation_v2.py:275)、[query_needs.py:21](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/query_needs.py:21)。

“入职需要哪些材料，试用期多久？”被分析成一个 `complete_policy_coverage`。材料包括身份证和三个月试用期；固定模型只答身份证，最终仍 answered。

现有报销需要检查能区分材料、审批、额度、资格，确实补偿了部分问题；但是入职、远程办公等不在这个有限领域内。通用 `covered_aspects` 仍可因引用了带该 aspect 的来源而满足，不能代表答案覆盖了用户每个问题。

应把“搜索已尝试”“找到了相关信息”“用户的某项诉求已被答案回答”分开。不能只把关键词表再加几十项就叫通用理解。

### P1-3：通用 all/所有 问题读不完整，也可能宣称完成

位置：[controller_v2.py:409](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/controller_v2.py:409)、[generation_v2.py:361](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/generation_v2.py:361)。

文档前部是远程办公需登记，后部是每周安全培训，中间有长文本。真实 document open 已执行，但受长度预算截断。固定模型只答登记，最终 answered。

已有“明确 N 项要求”和报销 need 合同能处理特定截断情形，不能覆盖所有自然语言的“全部”。应保留 read extent/truncation 信息，并限制“已经列全”的结论，而不是无差别把所有回答改成 partial。

### P2-1：定向补读依赖报销字样，隐含续句仍可能漏掉

位置：[controller_v2.py:365](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/controller_v2.py:365)、[controller_v2.py:381](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/controller_v2.py:381)。

当前 focused 路径选择首个命中文档，find 的 pattern 是固定“报销”，最多找20处、最多定向 open 两次。这是有限修复，不是通用章节遍历。

探针“报销需要哪些材料？”：前部“报销需要发票。”，后部“还需提供行程单。”不再重复“报销”，结果只答发票且 answered。

同时，正向控制“报销还需要行程单。”能被读入；模型漏答它会降为 partial。短文明确含全部两项且答全也能 answered。之前修复确实有效，但生效范围比“解决长文档完整性”窄。

## 5. 其他成立或部分成立的限制

| 项目 | 判断及证据等级 | 影响与处理 |
| --- | --- | --- |
| 规则过度承担查询理解 | 部分成立，源码及组件诊断 | 默认 fallback=None；fallback 只在注入后覆盖特定比较歧义，不是通用纠错/多诉求分析 |
| 错别字已全面解决 | 不成立，组件诊断 | “报消/要带啥”能有限归一化；“抱销”未处理。原问题保留是优点；不能据此推算真实检索变化 |
| 安全词规则误拒 | 成立于组件 | “如何防止导出客户数据？”被判 unsafe；“怎么重置我的密码？”已有允许逻辑。不可一概说所有安全相关问题都会误拒 |
| search 尝试完成等于有证据 | 不完全成立 | 有 attempted 与 evidence 两套状态，无结果不直接变支持；主要缺口是 aspect 粒度与最终完整性 |
| open 都是无效记录 | 不成立 | 实际 open 会进入生成与引用验证；但可能被源数量/总预算截断或丢弃，且没有完整进入冲突 ledger |
| 系统完全不支持 parent | 不成立 | `pipeline.py` 的 include_parent 已实现，并带权限/过滤约束；不足的是通用邻接/章节补读和接入一致性 |
| critical claim 过于严格 | 可接受取舍，但需明确 | 数值等关键事实要求绑定原文 span；组件中语义近似的7天改述被拒，原句通过。可能提高 partial，不能直接删除校验来提分 |
| PDF 表格自动正确解析 | 未得到支持，代码存在明确限制 | 原生 PDF 用 pypdf 文本提取且 `tables=[]`；不是通用表格/OCR 解析器 |
| 结构质检证明 PDF 无漏表 | 不成立 | 质检能检查已产出的表格和来源；没有提取出的表格不会自动形成漏表真值。需要与原页/人工标注对照 |
| 大规模在线检索已验证 | 未知 | FAISS 按 ntotal 搜索后过滤，全可见 BM25 排序；小库可接受，但不是有过滤 ANN top-k 的规模性能证明 |
| 缺少聊天记忆 | 代码事实，不必立刻扩建 | 可定位单轮知识问答；如支持“那审批人呢”需显式会话协议，不能把界面像聊天等同于有记忆 |

检索相关位置：`app/retrieval/pipeline.py:277`、`:345`。读取相关位置：`app/retrieval/navigation.py:176`。生成 packet 位置：`generation_v2.py:614`、`:730`；每源与总预算都存在，初始 search 来源先入包。

当前页面把 ledger 的 coverage 显示为 Evidence coverage；这只是有限标签的覆盖，容易被看成语义完整性。应在 UI/trace 区分标签覆盖和答案诉求覆盖。

## 6. 交付与使用流程的问题

### 身份过期不是故障，但缺恢复入口影响日常使用

本地 demo token 默认900秒。`scripts/manage_demo_identity.py` 发证，`scripts/local_candidate.ps1` 并非每次启动都自动续期。之前 Bearer 报错靠重新签发暂时恢复，不能视作完整登录产品流程。

建议提供明确的本地身份刷新/重新登录路径，过期状态说明清楚。不要关 JWT、不使用永久 token、不把签名密钥暴露给浏览器。服务 ready 和用户当前 token 有效是两件事。

### 候选版、默认主分支、文档与 CI 还没有统一

- 候选 README 中“默认不选 find”的描述已落后于当前 focused-read 代码；main badge 与候选状态不能混用。
- 本轮通过 GitHub API 核实 [候选 CI run 34455517994](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/34455517994)：completed/failure，而非仍在等待。
- Windows、Ubuntu deterministic jobs 都在 Run deterministic tests 步骤失败；Postgres integration 成功，container job 跳过。
- 本轮未读取远端原始失败日志，不能断言远端失败就是本地历史三个失败。
- 历史本地报告的3973 passed / 3 failed / 36 skipped 是历史记录，不是本轮重跑成绩。不能把历史失败删掉后称全绿。
- 最新本地模型/XGBoost 实验完整报告位于旧开发树；候选的 EXPERIMENT_SOURCE_REFERENCES.json 记录引用摘要，不等于完整报告都已公开。

这些是外部读者理解成本和可运行交付的问题，比继续增加一个检索策略更值得优先处理。

## 7. 与开源项目的对照

以下是官方文档/作者仓库的架构能力对照，不是同数据集性能排名，也没有证明它们没有本项目这些错误。星标热度不代表本地效果。

| 系统 | 已核对的做法 | 对本项目有价值的借鉴 | 不应直接照搬 |
| --- | --- | --- | --- |
| RAGFlow | 模板切分、可检查的文档处理、多路召回/重排、可选布局解析组件 | 让用户检查“原文变成了什么 chunk”，先定位解析丢失 | 为获得平台规模而引入整套新基础设施 |
| Haystack | SentenceWindowRetriever 按 source/split 元数据补邻居；AutoMergingRetriever 按层级合并父内容 | 不要求每个后续条件再次含主题词；结构化定位读取 | 不经 ACL/版本/Guard 验证就拼接邻居 |
| Dify | 父子检索及知识检索结果接入工作流 | 小块匹配、足够的父级上下文，清楚的用户配置和结果检查 | 把可视化节点数量当工业化程度 |
| Onyx | 连接器、同步、访问控制与搜索产品流程 | 持续接入、删除更新、身份到文档权限的使用闭环 | 宣称所有连接器权限同步均为免费开源能力；部分为企业版 |
| LangGraph Agentic RAG 教程 | 模型决定检索、相关性评分、改写和生成分支 | 明确控制状态和失败分支 | 把相关性 grader 当答全证明，默认无限重试或换框架 |

来源：[RAGFlow 仓库](https://github.com/infiniflow/ragflow)、[RAGFlow 检索源码](https://github.com/infiniflow/ragflow/blob/main/rag/nlp/search.py)、[Haystack 邻接读取源码](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/sentence_window_retriever.py)、[Haystack 父级合并](https://docs.haystack.deepset.ai/docs/automergingretriever)、[Dify 检索源码](https://github.com/langgenius/dify/blob/main/api/core/rag/retrieval/dataset_retrieval.py)、[Dify 知识检索文档源码](https://github.com/langgenius/dify-docs/blob/main/en/cloud/use-dify/nodes/knowledge-retrieval.mdx)、[Onyx 连接器文档](https://docs.onyx.app/admins/connectors/overview)、[LangGraph 官方教程](https://docs.langchain.com/oss/python/langgraph/agentic-rag)。

[CRAG](https://arxiv.org/abs/2401.15884) 使用检索评估与纠正策略；其外部检索思路不能直接带入私有企业知识库。[Self-RAG](https://arxiv.org/abs/2310.11511) 涉及学习反思标记等训练机制，不等于给普通模型加一句“反思一下”。论文收益不能转写为本地 Qwen 的预期收益。

共同结论：更值得学的是结构、边界和用户工作流程，不是增加 LLM 调用次数。相关性不等于充分性，覆盖不等于正确，模型自评不等于可靠证明。

## 8. 方案选择：先做什么，不做什么

| 方案 | 当前判断 | 理由 |
| --- | --- | --- |
| A. 扩展规则/归一化 | 只做有限兼容，不作为主路线 | 便宜可复现，但维护词表无法覆盖一般错别字、隐含条件和多诉求 |
| B. LLM 改写/分解 | 有条件的后续实验，暂不默认 | 灵活，但有误改原意、额外延迟和历史无收益记录；原 query 必须保留 |
| C. LLM 相关性/缺口评估 | 可作结构化建议，不作最终证明 | 模型可能把“相关”误判成“足够”，也可能被检索内容诱导 |
| D. 模型建议 + host 权限/预算/终止 | 若引入 LLM，优先此方案 | 模型不能改变身份、来源准入和版本规则；异常时确定性回退 |
| E. 邻接/parent/章节定向读取 | 优先最小实验 | 直接针对本轮尾部续句问题，无需新增模型；仍需避免带入不同适用范围 |

历史本地实验报告只作限制条件：已消费的人类 WixQA 两组不能冒充新 holdout；原句改写和 XGBoost 没有支持默认晋级。本轮未重跑这些检索结果，也不建议为期望的正结果重新无限调参。

### 建议后续有限实施顺序（本轮未实施）

1. **统一证据接线。** 把经过现有准入的 search/open 内容送入一致的冲突评估；继续保留实际 delivered packet 的引用验证。不能让未准入内容进入模型，也不能因某条冲突被 prompt 截断就选择性忽略已发现冲突。
2. **明确完成契约。** 单独记录 attempted/relevant/read_extent/need_supported/conflict/unknown。未知不伪装成已答全；普通完整短答仍应 answered。未知情况允许澄清或正文说明缺项，不能只藏 warnings。
3. **有界结构补读。** 先利用现有 parent、chunk 位置、章节关系，补充相邻条件；保持有限 open/字符预算及 snapshot、tenant、ACL、scope、Guard 检查。不能机械拼接所有相邻内容。
4. **小范围 LLM 建议实验。** 只在无法表达的多诉求/歧义问题上试一次结构化分解。保留原句与原文 span；金额、日期、编号、否定词不可静默变化。字面保持仍不是语义保持证明，需要成对样本检查。不默认开启检索重试。
5. **文档与交付收口。** 用少量真实原生/扫描/跨页/合并表头文档核对解析；若存在实质丢失才做解析器对照。补齐 token 恢复流程、当前入口/profile 说明、失败日志核查与 CI，再决定候选晋级 main。

不建议本轮引入新数据库、Agent、learned ranker，或为统一架构大规模重写两个 runtime。生产模块已经较长，新增逻辑应按清晰职责组织，但不能借修复重构所有历史能力。

## 9. 获授权后的验收设计

先冻结小规模开发诊断集、任务合同和阈值，再实现。今天新增的六个探针从此属于已用开发样本，不是独立验证集。

- 每题标注用户各项诉求、支持片段、适用条件、明确冲突、应否澄清及允许的最终状态。
- 三层分开：retrieval recall；读入证据的条件覆盖；最终答案的支持、完整性及引用。不得只报一个总分。
- 同时报 answered 中错误宣称答全的比例、全部请求中错误答全比例、正确完整回答产出率和过度 partial/refusal，防止靠全拒答达标。
- 报销之外加入入职、休假、远程办公；覆盖口语、未知错别字、多意图、尾部续句、不同制度/范围、日期金额否定词。
- 对照 baseline、结构补读、结构补读+LLM 建议；保持同模型、同索引、同候选策略、同预算。LLM 建议实验单独计算语义误改写和无效建议率。
- 安全回归覆盖邻居跨 tenant/ACL、过期版本、适用范围差异、open prompt injection、source binding、预算耗尽和超时回退。
- 记录 p50/p95、模型调用数、输入输出 token、工具步骤、延迟开销。同机冷热状态与重复次数固定，不能把重复请求当新增独立题。
- 新鲜验证样本必须在模型/规则选择前封存；需要人工语义复核的项目明确保留，不用另一个 LLM 分数冒充准确率。
- 固定四个反例必须修复、两个正向控制必须保持，相邻回归不退化；还需要跨领域反例防止针对例句打补丁。

## 10. 本轮真实执行证据

| 测试组 | passed | failed | errors | skipped | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| 既有相邻回归 | 207 | 0 | 0 | 0 | 22个文件，含部分进程内 API 测试；不是真实外部服务实验 |
| 新增定向诊断 | 2 | 4 | 0 | 0 | search 和模型固定桩，其余真实 runner/navigation/guard/generation/citation/contract |

两组源码前后哈希相同，导入绑定到指定候选工作区；原冻结测试未改动。保留四条 FAILED，没有 skip/xfail 或修改桩制造通过。运行用已有 Python 环境和离线保护，不访问 Ollama；Windows 内部 socketpair 例外不等于放行 localhost 服务。

这四个失败证明特定合同缺口存在，不能估计真实用户失败率。207项通过证明选定旧行为保持，不证明整个项目或全部安全条件通过。

原始证据目录：[flow_review_20260912](D:/文档/agent/RAG_try/.private/flow_review_20260912)。

- [新增诊断源码](D:/文档/agent/RAG_try/.private/flow_review_20260912/test_flow_probes.py)
- [离线测试入口](D:/文档/agent/RAG_try/.private/flow_review_20260912/run_review.py)
- [六条诊断结果](D:/文档/agent/RAG_try/.private/flow_review_20260912/probes_v1/RESULT.json)
- [诊断 JUnit](D:/文档/agent/RAG_try/.private/flow_review_20260912/probes_v1/junit.xml)
- [诊断原始日志](D:/文档/agent/RAG_try/.private/flow_review_20260912/probes_v1/stdout_stderr.log)
- [207项回归结果](D:/文档/agent/RAG_try/.private/flow_review_20260912/adjacent_v1/RESULT.json)
- [相邻回归 JUnit](D:/文档/agent/RAG_try/.private/flow_review_20260912/adjacent_v1/junit.xml)
- [具体响应与实际 packet](D:/文档/agent/RAG_try/.private/flow_review_20260912/observations)
- [查询/引用/冲突组件诊断](D:/文档/agent/RAG_try/.private/flow_review_20260912/CONTRACT_DIAGNOSTICS.json)

每组运行目录还保存 IMPORTS、SOURCE_BEFORE、SOURCE_AFTER。不可把测试桩引起的特定输出当成真实 Qwen 的发生频率。

## 11. 未验证与最终决定

没有重跑 WixQA、FinanceBench、FinQA、安全真实模型 paired benchmark、历史完整套件或人工评分；没有做同硬件开源系统效果对比，没有给出新的线上准确率或生产就绪认证。远端 CI 原始失败断言仍需后续读取。

结论：值得进入一次有限正确性与使用流程修复，不值得直接扩建检索算法或自动打开 LLM 改写。应保留当前已有边界，先把输入诉求、实际读取内容、冲突判断与最终答案状态接通。完成后再以配对结果决定后续模型工作，不预先承诺提升。

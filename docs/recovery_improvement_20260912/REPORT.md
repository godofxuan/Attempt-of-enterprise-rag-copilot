# 从“小实验没收益”到定位并修复真实瓶颈

日期：2026-09-12。结论：**保留并接入可启用的缺项恢复路径；本地开发诊断有实际收益，不再用上一轮小样本结果否定 LLM 的价值。**

## 1. 先讲清楚这次到底改好了什么

上一轮 12 道题、固定检索结果的对照，没有给查询改写留下改变检索结果的机会。它能检查接线、拒绝错误建议、预算等行为，却不足以回答“LLM 能不能改善真实检索和回答”。由此给出普遍的“不值得使用 LLM”结论过早。

本轮先冻结起始源码，然后构造 44 道来源可核对的开发探针，实际运行现有索引、embedding、BM25 + dense + RRF、Guard、证据处理和本地模型生成。没有只加测试或换一个更好看的指标。

发现并修复三个具体问题：

1. **调用时机不对。** 原来的主动规划、评估会对很多简单问题也调用模型。现在先按原路径检索和定向补读，确有缺项才允许一次模型恢复建议。
2. **找到了正确文档，却在后面丢掉了。** 5 道口语或错字题的正确文档已在首轮合法 Top-5 中，但词面相关性检查未接纳它。现在模型可以从已通过安全过滤的资料中指出原文，主机核对引文及来源，再让这份资料进入回答。
3. **有内容，却被输出编号错误打断。** 模型有时给两个 claim 都起名 `S1`。现在先校验每一项，再由主机分配唯一 claim 标签，不改事实、不换引用来源，也不多调用一次模型。

在最后同代码 OFF/ON 对照中，40 道可答题的“所需字面要点出现且引用校验通过”由 **29/40 到 34/40**，增加 5 题，或 12.5 个百分点。5 题均从 `not_found` 恢复为带引用的 `partial`，不是通过把未确认答案改标 `answered` 获取成绩。

这证明本轮修复对这些开发案例有效。**不是 WixQA Recall 提升，不是独立人类测试准确率，也不是全部复杂问题已经解决。**

## 2. 实际修改在哪里

实际候选工作树：`D:\文档\agent\RAG_try\.private\release_candidate_20260910`。

- 分支：`codex/local-closeout-20260910`。
- HEAD：`152981aba3bc9a15a1035dbfa53dc57651b3c97f`，本轮没有提交。
- 起始 scoped Python fingerprint：`413b017de5243e8134c313035f445a8c7aa969615f593eefff73f33c6d63b2c3`。
- 起始 `app/tests/scripts/streamlit_app` 共 977 个 Python 文件已完整保全到 `source_before/`。
- 主目录的旧 HEAD 不是本轮运行源码。本轮没有覆盖主目录业务代码、切分支、推送 GitHub、改简历或部署。
- 上一轮已经存在的未提交改动与本轮新增改动分开：`START_STATE.json` 保存前者的状态；`THIS_ROUND.patch` 只比较本轮起始快照与交付源码。

| 本轮文件 | 改动与原因 |
| --- | --- |
| `app/agent/controller_v2.py` | 添加缺项恢复调度，保留最多 5 个已通过 Guard 的候选，允许受约束的模型相关性建议；在 controller 层就保证建议型证据只能产生 partial |
| `app/agent/task_advisor.py` | 增加严格的 RecoveryProposal、一次恢复请求、原意约束、引文核对及空来源编号的唯一匹配绑定 |
| `app/agent/task_plan.py` | 增加 recovery_calls 与 model_relevance_used，使行为和发布限制可观察 |
| `app/agent/runner_v2.py` | 原有 opt-in 设置接到 recovery_advisor，而非主动 plan/assess 路径 |
| `app/agent/evidence_relevance.py` | 仅为建议型 partial 增加有限词面关联通路，保留明确的范围、制度和年份检查 |
| `app/agent/generation_v2.py` | 重绑重复 claim 标签；建议型相关证据的正文、状态及 trace 保持 partial 一致 |
| `tests/agent_v2/test_gap_recovery.py` | 12 项新回归：单次恢复、预算、禁止越权、原意保持、实际新查询接入及默认接线 |
| `tests/agent_v2/test_recovery_evidence_suggestion.py` | 7 项新回归：被词面规则过滤但安全合法的证据、原文核验、重复 claim ID |
| `tests/agent_v2/test_recovery_host_binding.py` | 8 项新回归：唯一引文绑定、歧义与错误编号拒绝、controller partial 约束、适用范围反例 |

没有新增模型、依赖、数据库、框架、Agent 或配置开关；没有改排序参数、ACL、租户、来源准入、Guard、版本治理或引用支持标准。原冻结测试未修改。

## 3. 新链路如何工作

```text
原始问题
  -> 原规则分析 / 诉求记录
  -> 原检索 + 权限 / 版本 / Guard
  -> 原有定向 find/open
  -> 已覆盖：直接沿原路径生成
  -> 仍缺证据且预算允许：最多 1 次 LLM 恢复建议
       read：从已准入资料引用原文，主机核对后补入证据
       search：主机校验原意约束后最多 1 次真实检索重试
       clarify/stop：不伪造证据，不擅自执行工具
  -> 原 ledger / claim / citation / answer contract
  -> answered / partial / not_found / refusal
```

### 3.1 不是让 LLM 决定权限或宣告“已经答全”

`_prepare_recovery()` 要等原 required_aspects 的搜索结束，先让现有定向补读工作。错误、拒绝访问、Guard 过滤信号、冲突、unsafe/comparison、已用过恢复机会或超预算时不调用恢复模型。需要用户个人事实的诉求不会靠模型补猜。

模型只提出严格 JSON 建议。原始问题仍是后续相关性检查、生成和答案合同的依据；新查询不能替换用户原问题。search 建议必须保留数字、日期、编号、否定、数量约束和带引号的制度名，并通过风险检查。它是必要的字面保护，不是完整的语义等价证明。

原有总预算不扩张；最多 1 次恢复模型调用、1 次重试。恢复请求上限 5 秒，并从剩余 deadline 预留 2 秒给后续工作。复杂语言的误改写仍可能被这些有限检查漏掉，因此不能据此保证任意问题原意不变。

### 3.2 为什么要区分“安全过滤”与“相关性过滤”

安全过滤说的是“这位用户是否允许看到这份资料，来源和版本是否合法”。相关性过滤说的是“这份资料是否在回答这个问题”。两者不能混用。

本轮保存的是已经通过前者的合法候选，不是把拒绝访问的资料偷偷交给模型。恢复模型最多看到 3 份裁剪后的合法资料，每份最多 350 字符；host 只接受本次给出的资料引用。

例如“国内出差住店一晚上最多报几个钱？”已经搜到差旅住宿制度，但“住店/一晚上/几个钱”与条款的词面重叠不足。增加大词典不是唯一出路。模型可以指出资料中的具体住宿标准，host 再检查来源和字面引文。

### 3.3 确实放宽了什么，以及为什么没有伪装成硬证明

`has_query_anchor_support(..., advisory_partial=True)` 将这条特定通路的有意义原问题锚点门槛从最多 2 个降为至少 1 个，同时保留原本明确范围检查。**这是相关性门槛的有意放宽，不是“所有检查完全没变”。**

单个主题锚点加真实引文仍可能语义上答非所问，所以 `model_relevance_used=True` 会在 controller 和 generation 两层强制保留 `partial`。正文增加说明：“以下包含按问题关联到的相关资料，尚不足以完整确认该问题，请结合原文核对适用条件。”来源、关键事实和引用支持校验继续执行。

模型相关性判断不是安全证明，也不是充分性证明。模型建议不能成为发布 `answered` 的理由。

### 3.4 为什么可以修复空编号，而不修复错误编号

真实模型有时给出精确原文，却把 `evidence_id` 留空。旧实现直接拒绝，浪费了可以确定绑定的证据。

新规则仅在引文至少 6 字符、且在本次给模型的资料中恰好匹配一份时，由 host 补上来源。匹配多份、虚构引文或模型给出非空错误编号都拒绝。没有模糊匹配、猜测来源或根据 gold ID 修正模型输出。

### 3.5 重复 claim ID 为什么不该直接让整个回答报错

claim 标签用于标识回答中的断言，不是来源 ID。两个事实都绑定正确来源，仅标签重复，是协议标识问题。

新解析器先用 `GeneratedClaim` 校验全部原行，再将重复标签统一分配为 `host-claim-1` 等，事实文本、critical 属性、source_ids 全部保留。`GeneratedAnswer` 的直接输入契约仍拒绝重复 ID。未知来源仍会在引用映射处失败，不能因为重编号得到通过。trace 记录 `wire_claim_ids_rebound` 数量。

## 4. 实验协议与完整结果

本轮使用现有 `qwen2.5:3b`、现有 `bge-m3`、seed 42、temperature 0、15 秒请求 deadline。检索为 `hybrid_default`，Top-5，candidate_k=20，BM25 + dense + RRF，**没有 reranker**。

固定索引版本：`20260724T024653Z_expanded_bge_m3_fixed`；manifest SHA256：`69b9fb7d3008467f65fb2920a621e9812cdb59c4919834819333e0e33b866507`。没有新建或激活索引。模型摘要见各 run 的 MODELS.json，实际系统与命令见 ENVIRONMENT.json。

真实模型测量入口是实际 V2AgentRunner 与已配置 controller，不是浏览器点击或带 JWT 的网络 HTTP 压测。HTTP/身份等行为另由本轮离线进程内 API 回归检查。模型实验使用现有精确本地 Ollama origin/socket 边界，未调用外部收费服务；该边界不是操作系统级沙箱。

44 道独立探针包含 12 类制度的简单/口语/多诉求问题、4 道跨制度问题及 4 个控制样本。其中 40 道可答，4 道检查未知个人事实、不安全问题、异租户拒绝和未知主题。

这些题及其 gold 文档和字面要点在观察各臂结果前冻结，但源自现有合成企业资料，是**开发诊断集**。修复过程中重复使用，不能转称独立测试集。有效的 7 个臂共执行 308 次，不等于 308 道不同问题。

| 运行目录 | 含全部要点并通过引用检查 /40 | 44 请求 chat 调用 | embedding 调用 | p95 ms |
| --- | ---: | ---: | ---: | ---: |
| live_v2_structure：起始 OFF | 25 | 35 | 42 | 1612.78 |
| live_v2_eager：原主动规划 | 26 | 113 | 44 | 2628.04 |
| live_v2_recovery：第一版缺项恢复 | 27 | 49 | 42 | 1809.25 |
| live_v3_structure：编号修复 OFF | 28 | 35 | 42 | 2014.54 |
| live_v3_recovery：尚未修复空证据编号 | 29 | 50 | 42 | 2307.71 |
| **live_v4_structure：最终 OFF** | **29** | **35** | **42** | **1938.36** |
| **live_v4_recovery：最终 ON** | **34** | **54** | **42** | **2512.93** |

最终同实现 OFF/ON：+5/40，或 +12.5pp；p95 增加约 575ms；44 请求增加 19 次 chat 调用，其中包括恢复出来后才执行的回答生成。对比原主动规划的 113 次，新路径是 54 次，少约 52.2%。这不是“相比完全不调用顾问还能少调用模型”。

### 指标怎样理解

- `complete_terms_supported_proxy`：最终 claims 包含每个规定要点的至少一个字面替代，且有 citations、所有 citations.supported 为 true。包含 partial，不检查所有语义细节；不能叫“真实准确率 85%”。
- `initial_guarded`：首轮合法 Top-5 中的 gold 文档覆盖，所有有效臂都是 100%。
- `accepted/packet`：后续被接纳并交给生成的 gold 文档覆盖。最终 OFF 为 87.5%，ON 为 100%。多次搜索/补读的集合覆盖不能改名 Recall@5。
- `false_answered_proxy`：基于这些冻结字面要点及控制条件的检查，两臂都是 0/44；不是零幻觉率。
- 延迟为顺序本地运行、预热排除、44 请求的 nearest-rank p95，不是并发服务 SLA，也没有做独立重复批次置信区间。

因此本轮收益在于**已检索证据的利用及协议健壮性**，不是检索器召回提高。最终 ON 未增加 embedding 调用，也未靠实际查询重试赢得这 5 题。重写后真实重试的接线有回归验证，但这 44 题没有证明它提高 Recall。

### 5 道有可核对改善的题

| ID | 问题 | 最终 OFF -> ON |
| --- | --- | --- |
| hr_leave_informal | 想连着休年假，得多早打申请？ | not_found -> partial，所问要点出现 |
| finance_travel_informal | 国内出差住店一晚上最多报几个钱？ | not_found -> partial，所问要点出现 |
| finance_invoice_informal | 月度发漂最迟哪天交？ | not_found -> partial，所问要点出现 |
| engineering_release_informal | 周五下午到几点就不让正常发版了？ | not_found -> partial，所问要点出现 |
| facilities_visitor_informal | 来客人得提前几天报备进楼？ | not_found -> partial，所问要点出现 |

原始问题、查询、合法命中、被接纳的证据、生成 packet、模型完整输入输出、最终响应都在对应逐题 JSON 中。

## 5. 不好看的中间结果同样保留

1. `live_structure/` 的第一批 44 次运行身份配置错误：把 `audit_all` 错当跨部门通行证，而它只是普通组。该批原始证据全部保留，但不作为有效质量基线。PROTOCOL_V2 改为显式同租户评测组，并在所有有效臂前执行真实 AccessPolicy 可见性 preflight；没有削弱 ACL，未改题或 gold。
2. 首版恢复多数建议被拒绝，只见 27/40。追踪发现模型不能利用被词面筛掉的合法资料、以及输出格式问题，才做后续定向修复，不把首版隐藏。
3. V3 空 evidence_id 使 4 道本可精确绑定的题继续 not_found。按唯一原文匹配修复后再跑 V4，见 BINDING_ERRATUM.md。
4. 固定 seed 和相同模型输入也观察到输出波动。最终 `engineering_release_easy` 在 OFF/ON 都通过要点检查，但 partial/answered 不同，且没有调用恢复；不得把这个状态变化归功于新算法。
5. 起始 25 到最终 34 的全部增量不能归因于 LLM 恢复，还混有 claim ID 修复及模型输出波动。应优先报告最终同代码 OFF/ON 的 29 到 34。
6. 最终 11 次 read 建议被接受，但只有 5 道新增完整要点通过，其余并没有新增完整回答。模型调用仍有无效成本。
7. 最终仍有 6 道未通过全部要点：facilities_visitor_multi、customer_escalation_multi、leave_remote、refund_travel、oncall_release、visitor_it。均为 partial，记录了 critical_fact_requires_bound_span。模型把跨来源关键事实改述或合写后，现有精确证据跨度检查拒绝这些断言。不能删掉该检查让它们“通过”。

## 6. 回归与证据诚实性

先记录 RED 再修改，原始日志不覆盖：red_gap 12 failed；red_relevance_ids 5 passed / 2 failed；red_host_binding 6 passed / 2 failed。中间 gap_v1 的无效测试身份构造错误也保留，之后修正为使用已有风险检查，不制造身份。

最后新增 27 项全部通过。扩大回归：**1414 passed / 2 failed / 9 skipped，合计 1425**；退出码 1，不能写“全绿”。来源指纹未在运行期间变化，导入绑定实际候选树。未新增 skip/xfail；原测试不修改。

两项失败：

- `tests/security/test_trusted_identity_evaluation.py::test_public_trusted_identity_result_recomputes_exactly`：旧公开结果整体相等断言失败；同次套件中的实际身份矩阵 20/20 检查通过。
- `tests/runtime/test_dark_observation_evidence_v1.py::test_e16_public_evidence_binds_protocol_sources_and_implementation`：历史 implementation_sha256 与当前 app/config.py、app/runtime/resources.py 不同。

它们在本轮前已存在。相关源码和历史证据本轮未改，旧 FAILED 仍保留；本轮没有把历史结果重写成当前 release 通过。包内额外记录本轮前/后绑定差异。

9 项跳过的原始原因见 JUnit；不能算通过。Ruff（6 个改动生产文件、3 个新增测试文件）和 git diff --check 通过。真实模型最终对照后仅将一段 Python 字符串拆行以符合行长，字符串值不变；后续全回归覆盖交付源码。

## 7. 哪些经验来自开源，哪些是本地发现

- LangGraph 官方 Agentic RAG 的价值是条件式相关性判断及 rewrite 回路，而不是每问都做多次模型思考。本轮采用“缺项才请求建议”的思想，未照搬框架。[官方示例](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- Haystack QueryExpander 将扩展查询作为检索候选。本项目同样保留原始问题作为语义与发布约束，扩展不能覆写它。[官方源码](https://github.com/deepset-ai/haystack/blob/main/haystack/components/query/query_expander.py)
- Rewrite-Retrieve-Read 研究说明可以针对下游任务学习重写；论文中的训练机制不等同于给本地小模型加一句提示，本轮也没有复现其收益。[原论文](https://arxiv.org/abs/2305.14283)

空 evidence_id、重复 claim_id、词面门槛丢证据是本项目真实轨迹中观察到的工程问题，不是根据论文猜出来的结论。

## 8. 本轮决定与下一项真正值得做的事

**保留新恢复路径和 27 项回归。** 原 `AGENT_V2_TASK_ADVISOR_ENABLED`/`-EnableTaskAdvisor` 已接入它，可以运行，不是实验成功后又把代码丢掉。默认 false 未改，旧主动规划只保留注入式对照兼容。

本轮实际支持“为口语/错字场景找回已合法召回但未被利用的证据”。不支持任意错字修复、普遍语义充分性、外部检索收益或生产就绪。默认晋升还需更广的非模板请求与误相关评估，不能因 44 道开发题把全部未知风险当已验证。

下一项瓶颈已明确：**按来源拆分、绑定关键断言，减少跨文档合写造成的证据拒绝**，而不是继续堆 reranker 或加词表。应先以保留的 6 个失败建立反例，验证关键限定条件不被删，再做有限生成协议改进。本轮不再针对这 44 题反复调提示、换模型或冒充新测试集。

可如实使用的工程描述最多三条：

1. 实现一次受预算约束的 LLM 缺项恢复，保留原始问题、权限和引用校验，主机校验证据绑定及发布状态。
2. 在 44 道本地开发探针中，40 道可答题的要点与引用检查通过数由 29 增至 34，p95 从 1.94s 到 2.51s；不是外部准确率。
3. 新增 27 项回归覆盖模型建议、来源绑定、原意约束及输出协议健壮性；扩大回归结果须同时披露两项历史证据绑定失败。

不更新简历中的 WixQA/FinanceBench 数字，不宣传独立准确率 85%、零幻觉或全量测试通过。当前成果是有正向证据、可运行且保留审计轨迹的本地候选改进。

## 9. 交付位置

- 新运行说明：同目录 `LOCAL_RUN.md`。
- 原始执行与冻结数据：`D:\文档\agent\RAG_try\.private\recovery_improvement_20260912`。
- 审核 ZIP：该证据目录下 `RAG_RECOVERY_IMPROVEMENT_20260912.zip`。
- 摘要与文件数：`DELIVERY.json`；包内逐文件 `ARTIFACT_MANIFEST.json`。
- 包含 scoped Python 起始/最终源码、this-round patch、协议、逐题原始模型记录、全部本轮测试日志及原始 JUnit。不是包括模型、数据和虚拟环境的完整可运行仓库镜像。
- 未脱敏的本地开发问题/合成资料轨迹仅用于本地审核；未自动上传。测试临时目录、身份密钥、模型和缓存不打包。
- 本报告是新的纠正记录，不覆盖 `docs/flow_mainline_20260912/` 或旧审核包。

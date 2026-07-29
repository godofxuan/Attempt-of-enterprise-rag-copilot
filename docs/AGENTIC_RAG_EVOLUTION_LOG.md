# Agentic RAG 演进与面试复盘日志

> **历史工程日志：** 本文保留 2026-07-15 及更早阶段的设计、实验和故障复盘，不再承担当前状态职责。当前实现、验证结果与未完成边界只以根目录 [PROJECT_STATUS.md](../PROJECT_STATUS.md) 为准。

更新时间：2026-07-15

本文记录项目如何从“固定工具链 RAG”演进为“有界、证据感知、可评测的 Agentic RAG”。它不是完成清单，而是保留每次改进的工程推理：看到了什么现象、提出了什么假设、改了哪段代码、如何验证、哪些方案被实验否决，以及面试时应该怎样准确表述。

## 1. 当前能力边界

当前 `/agent/chat` 的主流程是：

```text
用户问题
-> route_query() 路由
-> AdaptiveController 选择下一步
-> retrieval.search 检索
-> evidence.assess 判断证据是否足够
-> [足够] rag.answer
-> [不足且还有预算] query.rewrite -> retrieval.search -> evidence.assess
-> [第二次仍不足] rag.no_answer
-> guardrail.check
-> answer + sources + trace
```

安全请求走上述有界循环；命中 `unsafe_request` 的请求只执行：

```text
guardrail.refuse
```

当前系统最多进行两次检索和一次查询改写。Python 控制器负责安全边界、状态转换和停止条件；本地 LLM 只负责语义证据判断与改写建议。准确定位应是：

> 一个可评测的 bounded adaptive Agentic RAG workflow，而不是能够任意调用工具、长期自主运行的通用 Agent 平台。

## 2. 为什么这样设计

### 2.1 从固定工作流到观察-决策-行动循环

旧路径对所有安全请求都执行固定序列：

```text
retrieval.search -> rag.answer -> guardrail.check
```

问题是：检索器一定会给某些结果，但“排在前面”不等于“足以回答”。RRF 分数是基于名次的融合分数，不是答案正确概率，也不是语义蕴含概率。因此不能用 `score > 某阈值` 代替证据判断。

新路径让 runner 每次只执行一个控制器选出的动作，再观察更新后的状态：

```text
observe state -> decide next tool -> act -> merge updates -> repeat
```

对应代码：

- `app/agent/runner.py`：执行 observe-decide-act 循环并记录 trace。
- `app/agent/controller.py`：根据显式 phase 和证据结果选择下一步。
- `app/agent/tools.py`：定义真实工具及其状态更新契约。
- `app/agent/evidence.py`：构造证据判断提示、解析结构化结果、校验改写。

### 2.2 为什么不让 LLM 完全控制循环

如果让小模型自行决定工具、重试次数和停止条件，会产生三个问题：

1. 终止不稳定，可能反复改写和检索。
2. 安全策略依赖模型是否“记得”遵守。
3. 单元测试无法稳定覆盖状态转换。

所以采用混合控制：

```text
LLM 负责：证据是否支持问题、下一次检索应该怎样改写。
Python 负责：是否允许重试、最多重试几次、何时拒答、何时执行 guardrail。
```

这对应 Anthropic 的 evaluator-optimizer 思路，但增加了确定性的预算与 fail-closed 边界。参考：[Anthropic - Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)。

## 3. 关键状态和数据流

`AdaptiveController.initialize()` 创建的核心状态：

```text
question                    原始用户问题，始终不改
search_query                当前检索查询，可以改写
retrieval_attempts          已完成检索次数
max_retrieval_attempts      默认 2
latest_retrieved_chunks     最新一轮检索结果
retrieved_chunks            跨轮累计、按 chunk_id 去重的证据池
evidence_assessment         最新一次结构化判断
evidence_history            所有证据判断记录
answer / sources            最终输出
final_outcome               answered / grounded_no_answer / refused / error
```

这里必须把 `question` 和 `search_query` 分开：改写只优化检索，不允许偷偷改变用户真正问的问题。`rag.answer` 始终调用：

```python
answer_from_retrieved(context["question"], context["retrieved_chunks"])
```

## 4. 实时问题复盘

### 4.1 问题一：规则评估是否应该全部交给 LLM

最初答案评估使用 `must_include`、`must_not_include`、citation、refusal 和 unsafe pattern 等规则。这类规则便宜、稳定、可复现，但会出现子串误判，例如否定句包含被禁止短语。

最终方案不是“规则或 LLM 二选一”，而是分层：

- 代码规则：结构、引用来源、是否检索、工具次数、明确禁词等可确定事实。
- LLM judge：语义完整性、意图一致性、回答质量等规则难表达的项目。
- 人工抽检：校准 LLM judge，并审查高风险/边界案例。

本阶段的 `evidence.assess` 是运行时证据门，不等于最终答案质量 judge。Anthropic 的 Agent eval 指南也建议组合 code-based、model-based 和 human grader，而不是只依赖一种评分器。参考：[Anthropic - Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)。

### 4.2 问题二：Ollama 模型目录迁移后无法拉取模型

现象：

```text
`<ollama-model-dir>` 下的 partial 文件 Access denied
```

根因不是模型清单错误，而是 Windows ACL：目录由 Administrators 拥有，当前用户只有读取/执行权限，Ollama 无法写 blob 和 manifest。

处理：只给当前用户在 `<ollama-model-dir>` 及子目录授予 Modify，而不是给 Everyone 完全控制。验证内容包括：

- `OLLAMA_MODELS` 指向新目录。
- `<ollama-model-dir>/blobs` 对当前用户有 Modify。
- `ollama pull qwen3:8b` 完整写入并校验 manifest。
- `http://127.0.0.1:11434/api/tags` 能列出模型。

面试说法：先读错误信息并检查文件系统权限，确认失败发生在“下载后的本地落盘边界”，而不是网络或模型名称；修改最小 ACL 后重新拉取并通过 API 验证。

### 4.3 问题三：`localhost` 看起来卡住

Windows 上 `localhost` 可能优先解析到 IPv6 `::1`，而本机服务可能只在 IPv4 `127.0.0.1` 监听。客户端先尝试无法连接的地址时，会表现为等待超时。

项目配置改为：

```text
LLM_BASE_URL=http://127.0.0.1:11434/v1
```

“监听”表示服务进程在某个 IP 地址和端口上等待连接。`127.0.0.1:11434` 与 `[::1]:11434` 都代表本机，但分别属于 IPv4 和 IPv6 地址族，服务不一定同时绑定二者。

### 4.4 问题四：3B、30B、8B 模型怎么选

实测过程：

- `qwen2.5:3b`：便宜、快，但证据语义判断不稳定；曾把 few-shot 示例中的“资产遗失”复制到无关的餐补问题，也会把明显的 VPN 证据判成不足。
- `qwen3-coder:30b-8k`：单次结果较好，但第二次请求在 RTX 5060 8GB 上出现 `0xc0000409` 和 CUDA shared object initialization failure，不适合作为稳定本地运行模型。
- `qwen3:8b`：约 5.2GB，能在本机稳定运行，语义判断明显优于 3B。

因此将模型职责拆分：

```text
CHAT_MODEL=qwen2.5:3b       # 最终回答，成本较低
EVIDENCE_MODEL=qwen3:8b     # 证据判断，语义要求更高
EMBEDDING_MODEL=bge-m3      # 检索向量
```

对应代码：`app/config.py` 中的 `chat_model`、`evidence_model`、`embedding_model`。

### 4.5 问题五：结构化输出为什么仍会出错

第一版 Schema 使用复杂 `oneOf`，Ollama 的 grammar 生成出现字段缺失；提示中的伪示例还写过类似 `"reason":"不超过400字符"`，小模型会照抄格式说明而不是生成真实理由。

修复：

- 改成平坦三字段 JSON Schema。
- `verdict/reason/rewritten_query` 始终存在。
- Pydantic 再做长度和交叉字段校验。
- few-shot 使用完整、真实的合法 JSON，不用占位文本。
- transport/JSON/schema 任何一步失败，都转换为 `verdict=error` 并 fail closed。

对应测试：`tests/test_agent_evidence.py`。

### 4.6 问题六：改写可能改变用户意图

LLM 曾把“餐补金额”改成“访客陪同规定”。如果直接拿这个查询重试，Agent 会偏离原任务。

修复：

- `is_intent_preserving_rewrite()` 检查改写与原问题是否保留至少一个有区分度的关键词。
- 无效、空白或意图漂移的改写由 `build_fallback_rewrite()` 替换。
- trace 记录 `rewrite_source=model|fallback`。
- `question` 永远不被改写覆盖。

注意：词项重合只能做廉价护栏，不能数学证明语义完全等价，所以 live eval 仍要检查改写行为。

### 4.7 问题七：dev007 为什么反复 grounded no-answer

问题：

```text
差旅费用和办公费用的报销区别在哪里？
```

两次检索回放显示：

- 第一轮 Top-5 有办公提交时限、差旅申请、办公金额限制、办公适用范围等。
- 第二轮 Top-5 又得到办公规则和差旅不予报销项目。
- 两轮并集有 6 个互补片段。

但旧的 `retrieval_search_tool()` 每次都直接执行：

```python
"retrieved_chunks": retrieved
```

第二轮会覆盖第一轮，证据判断器只看最后一轮。这不是 prompt 问题，而是 Agent 状态数据流错误。

修复位置：`app/agent/tools.py`

```text
latest_retrieved_chunks = 本轮结果
retrieved_chunks = merge_unique(旧累计结果, 本轮结果)
```

去重优先使用 `chunk_id`，缺失时回退到 source、section、text 组合键。第一轮已存片段保持原顺序，重复命中不会重复占用上下文。

控制器在 `phase=retrieved` 时用 `latest_retrieved_chunks` 判断“本轮是否为空”，但证据判断和最终生成使用累计 `retrieved_chunks`。这是两个不同问题：

- 本轮为空：说明重试没有带来新检索结果，应停止。
- 累计池非空：说明历史上曾有证据，但不能把旧证据误当成本轮成功。

相关测试：

- `tests/test_agent_adaptive_tools.py`：跨轮累计和 `chunk_id` 去重。
- `tests/test_agent_controller.py`：最新一轮为空时正确 no-answer。
- `tests/test_agent_adaptive_runner.py`：第二次 assessor 和 generator 都收到两轮证据。
- `tests/test_agent_loop_eval.py`：确定性 evaluator 与生产工具使用相同状态契约。

TDD 证据：新增测试先得到 6 个预期失败，再实现生产代码后 6/6 通过；之后 Agent 聚焦测试 46/46 通过。

这个改进与 LangGraph reducer 的思想一致：没有 reducer 时新值覆盖旧值，有 reducer 时把旧状态与本轮 update 合并。参考：[LangGraph - State reducers](https://langchain-ai.github.io/langgraph/how-tos/state-reducers/)。

### 4.8 问题八：为什么 8 个证据片段让请求超过 180 秒

为了验证是否需要扩大第二轮检索深度，曾用 8 个候选直接调用 `qwen3:8b`。Ollama 进程没有崩溃，但 180 秒内没有返回。

检查共享 transport 后发现请求体只有：

```python
"options": {"temperature": 0}
```

没有显式设置 `think`。Ollama 官方文档说明 Qwen3 属于 thinking model，API 默认开启 thinking；`think` 必须是请求顶层字段。参考：[Ollama - Thinking](https://docs.ollama.com/capabilities/thinking) 和 [Ollama chat API](https://github.com/ollama/ollama/blob/main/docs/api.md)。

修复位置：

- `app/ollama_chat.py`：新增可选 `think` 参数，只在显式传入时写入顶层 payload。
- `app/agent/evidence.py`：证据分类调用传 `think=False`。
- 普通回答生成不传该参数，保持原行为。

为什么只对 evidence assessor 关闭：它是一个有固定 Schema 的三分类式任务，需要低延迟和稳定遵循格式，不需要长链推理。最终回答仍可能从模型推理中获益，所以不做全局改变。

隔离变量实验：

| 实验 | 证据数 | think | 结果 | 判断耗时 |
|---|---:|---:|---|---:|
| 扩大候选初测 | 8 | 默认开启 | 命令超时 | >180s |
| 同样 8 个候选 | 8 | false | sufficient | 0.987s |
| 原始累计证据 | 6 | false | sufficient | 0.883s |

因此否决“必须扩大 top-k”的方案，只保留跨轮累计和 `think=False`。这一步避免了把两个变量混在一起后错误归因。

### 4.9 问题九：第一次“累计证据修复”为什么仍然不完整

独立代码审查发现：虽然 `retrieved_chunks` 已经能跨轮累计，但 assessor 为控制上下文长度仍然直接读取累计列表的前 8 个片段。当第一轮结果很多时，第二轮刚找回的新证据可能排在第 9 个以后，再次被判断器截掉。

这说明“状态里保存了新证据”和“决策时真的看到了新证据”是两件事。修复位置在 `app/agent/tools.py`：

```text
完整 accumulated workspace
        |
        +--> rag.answer：使用完整去重证据池
        |
        +--> evidence.assess：构造最多 8 条的 balanced assessment view
                              prior[0], latest[0], prior[1], latest[1] ...
```

`_select_assessment_chunks()` 先按 chunk key 去重本轮结果，再把历史证据和本轮证据按排名交替放入判断窗口。这样既保留第一轮上下文，又保证重试新证据不会被简单的 `[:8]` 截断；最终回答仍使用完整累计池，不丢信息。

同一次审查还发现并修复了四个契约问题：

- `AdaptiveController` 曾允许配置 3 次检索，与项目宣称的“两次硬上限”不一致；现在只接受 1 或 2。
- deterministic 模式根本不解析 LLM JSON，却曾把 parse success 报成 1.0；现在输出 `null`，文档显示 `n/a`。
- JSON Schema 禁止额外字段，但 Pydantic 默认会忽略额外字段；现在 `EvidenceAssessment` 使用 `extra="forbid"`，解析器真正 fail closed。
- README 曾把 expected `answered` outcome 写成“答案正确”；现在明确区分行为 outcome 和答案语义质量。

这轮修复采用 reviewer finding -> 失败测试 -> 最小代码修改 -> focused tests -> 全量测试 -> live dev/test regression 的顺序。它体现了一个面试中很重要的工程判断：第一次修复解决了“写入状态”的 bug，代码审查进一步发现了“读取视图”的 bug，不能因为 dev 已经 16/16 就停止检查数据流。

## 5. 评测协议

### 5.1 为什么分 deterministic 和 live

`deterministic` 模式注入假检索器和假 assessor，只检查状态机、工具顺序、重试上限和 trace，不证明 LLM 判断正确。

`live` 模式使用真实 BGE-M3、FAISS、BM25、Ollama evidence model 和回答模型，检查真实语义结果与运行轨迹。

两者的 `case_pass` 契约不同：

- deterministic：要求与预设轨迹完全一致。
- live：要求 route/outcome 正确、trace 完整、策略与安全边界合规；允许模型更早找到足够证据，因此不强制为了匹配标签而无意义重试。

严格的 `retry_decision_accuracy` 和 `tool_sequence_accuracy` 在 live 中仍保留为诊断指标，不作为唯一通过门槛。

### 5.2 2026-07-15 当前结果

自动化测试：

```text
109 passed, 6 warnings
```

warning 来源：FAISS/SWIG 类型、FastAPI `on_event` deprecation，以及 `.pytest_cache` 写权限；没有测试失败。

确定性 Agent loop：

| Split | Count | Outcome | Tool sequence | Trace | Policy | Case pass |
|---|---:|---:|---:|---:|---:|---:|
| dev | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| test | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

真实 Agent loop：

| Split | Count | Route | Outcome | Retry decision | Tool sequence | Trace | Unsafe no retrieval | Policy | Parse | Case pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| dev | 16 | 1.00 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| held-out test | 16 | 1.00 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

开发冻结后的首轮 live dev 约 147.9 秒，首次 held-out test 约 137.3 秒。随后独立代码审查发现的是通用状态/契约问题，而不是某道 test 的 prompt 失败；修复后执行回归复跑，dev 约 155 秒、test 151.1 秒，指标保持不变。首次 test 是冻结后的一次性评估，第二次必须准确表述为“审查后回归”，不能再称为未见测试。

历史对比：

| 版本 | live dev case pass | 说明 |
|---|---:|---|
| `qwen2.5:3b` evidence | 6/16 = 0.375 | 语义判断和改写不稳定 |
| `qwen3:8b` 默认 thinking | 15/16 = 0.9375 | dev007 仍误判；约 229.2s |
| 累计证据 + `qwen3:8b think=false` | 16/16 = 1.00 | 首次修复；约 147.9s |
| 平衡新旧证据视图 + 严格契约 | 16/16 = 1.00 | 审查后版本；dev 约 155s，test 151.1s |

不能把 16 题的 1.00 宣称为生产泛化率。数据是合成企业制度，样本规模小；正确说法是“在版本化的 dev 和一次 held-out test 上通过当前行为契约”。

还要区分“Agent loop 行为通过”和“答案语义完全正确”：Stage 8 当前不逐句评分生成文本，`gold_sources` 只做数据集校验和明细记录，尚未进入 `case_pass` 门槛。required points、forbidden content、citation 和 refusal 仍由 `eval_answer_v1` 单独评估。后续可以在不污染本次 held-out 结果的前提下，为新版本增加 source coverage 与 LLM/human judge。

### 5.3 为什么严格轨迹只有 0.75

四个 `rewrite_then_answer` 样例在 live 中第一轮就判断足够并直接回答：

```text
retrieval.search -> evidence.assess -> rag.answer -> guardrail.check
```

人工标签预设它们应该重试，所以 retry/tool exact match 计 0；但它们的 outcome、trace、policy 和引用路径正确，live case pass 计 1。这暴露的是“预设轨迹不是唯一正确策略”，不是线上回答失败。

## 6. 从先进 Agent 学到了什么

| 来源 | 原始思想 | 本项目落点 | 没有照搬的部分 |
|---|---|---|---|
| [Anthropic effective agents](https://www.anthropic.com/engineering/building-effective-agents) | evaluator-optimizer、环境反馈、停止条件、保持简单 | `evidence.assess -> rewrite/retry`，Python 两轮上限 | 没让 LLM 完全掌控循环 |
| [LangGraph reducers](https://langchain-ai.github.io/langgraph/how-tos/state-reducers/) | state update 默认覆盖，reducer 可累计 | `latest_retrieved_chunks` 与去重累计 `retrieved_chunks` | 没为当前小状态机引入整个框架 |
| [OpenAI Agents SDK tracing](https://openai.github.io/openai-agents-python/tracing/) | 记录模型、工具、guardrail 等完整轨迹 | `AgentTrace.plan/steps/evidence_history/final_outcome` | 当前 trace 暂未接远端平台 |
| [OpenAI Agents SDK guardrails](https://openai.github.io/openai-agents-python/guardrails/) | 输入/输出 guardrail 是独立运行边界 | unsafe 路由前置短路 + 回答后 `guardrail.check` | 当前规则仍较轻量 |
| [OpenHands event system](https://docs.openhands.dev/sdk/arch/events) | typed event history 支持状态、调试和可视化 | 工具 step、observation summary、错误与结果分开记录 | 尚未做持久化 event log |
| [OpenHands state source](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/conversation/state.py) | 显式执行状态、最大迭代、事件日志 | phase、max attempts、terminal outcome | 尚未做恢复/checkpoint |
| [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code/cli-usage) | `--max-turns`、verbose trace、工具权限 | 硬性迭代上限、完整 trace、安全工具边界 | Claude Code 本体不是本项目复制的开源实现 |

一个重要工程原则是：学习架构思想，不为了“看起来像 Agent”而堆框架。当前循环只有几个明确状态，用普通 Python 更容易审计、测试和在面试中解释。

## 7. 面试高频问题与回答

### Q1：你的项目为什么算 Agentic RAG，不只是多调了一次 LLM？

回答：普通 RAG 的路径固定为检索后直接生成；这个项目会观察检索证据，通过结构化 assessor 改变下一步动作。证据足够就回答，不足就改写并重试一次，仍不足则 grounded no-answer。工具序列由中间状态动态决定，并且每一步都有 trace。但控制范围是有界的，所以我称它为 bounded adaptive Agentic RAG，而不是通用自主 Agent。

### Q2：为什么 evidence assessor 用 LLM，route 和停止条件却用规则？

回答：证据是否直接支持自然语言问题是语义任务，RRF 分数或关键词阈值不能可靠解决；重试次数、安全前置短路和终止则是必须确定的系统约束。把语义判断交给 LLM，把安全与预算交给 Python，可以兼顾灵活性、可复现性和可测试性。

### Q3：如何防止 Agent 无限循环？

回答：`AdaptiveController(max_retrieval_attempts=2)` 控制最多一次原始检索和一次改写检索；runner 还有最大 step 数作为编程错误保险。LLM 不能修改这些预算。即使 LLM 第二次继续建议改写，控制器也会进入 `rag.no_answer`。

### Q4：为什么不能直接用 RRF score 判断证据充分？

回答：RRF 是把 dense 和 BM25 的名次转换成 `1/(k+rank)` 后相加，表示相对排名，不是校准概率。知识库外问题也会有第一名，所以高排名不代表文本蕴含答案。

### Q5：跨轮证据为什么要同时保留 latest 和 accumulated？

回答：latest 用于判断“这一轮检索是否真的返回结果”，accumulated 用于组合多轮互补证据。如果只保留 latest，会丢失第一轮；如果只看 accumulated，第二轮空结果也可能被历史证据掩盖。两者解决的是不同的状态语义。

### Q6：怎么保证查询改写不改变原问题？

回答：状态中 `question` 不可变，`search_query` 单独变化；生成始终使用原 question。改写还经过非空、长度、与当前查询不同、关键词意图重合校验；漂移时使用保留原句的 fallback，并在 trace 标记 rewrite 来源。

### Q7：为什么关闭 Qwen3 thinking 反而更好？

回答：证据判断是低熵、强 Schema 的分类任务，不需要长链推理。Ollama 对 thinking model 默认开启思考，导致 latency 和显存/KV 压力增大，8 个片段实验甚至超过 180 秒。显式 `think:false` 后，同一输入约 1 秒返回且更遵循判定规则。这个参数只用于 assessor，不全局影响最终回答。

### Q8：16/16 是否说明系统已经很好？

回答：不能。它只说明当前代码在 16 个 dev 和 16 个 held-out 合成样例上满足版本化契约。样本量小，问题分布有限，也没有真实企业权限和脏数据。项目价值在于可复现的评测、失败追踪和改进闭环，而不是把小集合满分包装成生产指标。

### Q9：为什么 live 的 tool sequence 只有 0.75，但 case pass 是 1.0？

回答：四个预设 retry-answer 题在第一轮已有足够证据，模型合法地提前回答。严格轨迹标签认为它们应重试，所以 exact match 失败；线上契约关心正确 outcome、完整 trace、安全与预算。把两种指标分开能避免为了刷轨迹分而执行无意义工具。

### Q10：你如何证明改进来自代码，而不是随机模型输出？

回答：先做确定性的 TDD，证明状态累计、去重和控制分支；再做隔离变量实验，分别比较 6/8 个证据和 think 开关；最后跑完整 dev，冻结后只跑一次 held-out test。单元测试证明控制逻辑，live eval 证明本地模型集成，二者不能互相替代。

## 8. 复现命令

```powershell
# 完整自动化测试
.\.venv\Scripts\python.exe -m pytest -q

# Stage 8 确定性控制层评测
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split dev --mode deterministic
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode deterministic

# 真实模型评测
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split dev --mode live
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode live
```

输出：

```text
data/eval_outputs/agent_loop_{mode}_{split}_results.json
data/eval_outputs/agent_loop_{mode}_{split}_details.jsonl
data/eval_outputs/agent_loop_{mode}_{split}_failures.csv
```

## 9. 下一步

当前最合理的下一阶段是展示与可观测性：

1. Streamlit 增加普通 RAG / Agentic RAG 模式切换。
2. 展示 route、动态 plan、两次检索、evidence reason、rewrite source、工具耗时和 final outcome。
3. 将 trace 持久化到 JSONL 或 SQLite，形成可回放的 failure corpus。
4. 扩大 capability eval，加入更难的多来源、冲突证据、恶意文档注入和真实企业权限案例。

暂不优先加入多 Agent。当前瓶颈是可观测性、真实数据与评测覆盖，不是缺少更多 Agent 角色。

## 10. 2026-07-28 更新：FinQA Calculator Agent

本节补充本文早期 Agent loop 记录，且覆盖第 9 节的旧“下一步”判断。项目已经完成
展示、可观测性、安全、身份、生命周期和部署阶段；最新质量改进是把真实财报数值
推理接入有界工具协议。

流程变为：

```text
question
  -> oracle or BM25Plus/BGE-M3 RRF evidence
  -> retrieved-content Guard
  -> Qwen3 selects operands and plans one arithmetic expression
  -> AST allowlist + Decimal Calculator
  -> strict numeric scoring + citation scoring
  -> immutable manifest/details/summary
```

这里最重要的 Agent 设计不是增加角色，而是把不可靠与可靠职责分开：

- LLM 负责自然语言理解、选数和列式；
- Python 负责工具权限、表达式语法、资源预算、精确执行、重试上限和停止；
- evaluator 把 retrieval、generation、citation、grounding 和 protocol error
  分开评分。

dev 上 direct answer、typed-step 和 safe expression 的 oracle strict 分别是
`0%`、`15%`、`75%`；typed-step 协议错误为 `50%`，safe expression 为 `0%`。
固定 100 题 test 样本最终观测到 oracle strict `52%`，hybrid K=10 strict
`44%`、evidence recall `93.5%`。这说明 Calculator 大幅改善了工具协议和精度，
但没有解决错误选数和财务计划，也说明 20 题 dev 明显乐观。

第一次 test 尝试在抽样和模型调用前因单行表 schema 失败。项目没有删除或掩盖
该事件，而是发布 incident、用合成 fixture 修复、做结构预检、supersede v1
并重新冻结 v2。详细证据见
[`external_datasets/finqa.md`](external_datasets/finqa.md)。

后续不能重调本次 test。新的质量工作应建立新版本 dev/holdout，并优先分析：

1. 年份、类别和基准值选择错误；
2. oracle 52% 的数值计划上限；
3. hybrid 相对 oracle 的 8 点 strict 损失；
4. citation recall 导致 strict 到 grounded strict 的差距；
5. 独立双人语义审核与第二模型复现。

## 11. 2026-07-29 更新：FinQA dev 失败诊断

test 揭示后没有继续用 test 调参。新的 100 题 dev 诊断得到 Oracle strict `63%`、
Hybrid strict `59%`、Hybrid evidence recall `91.98%`。新增的确定性诊断器
校验不可变 run 后，将失败分成 retrieval、protocol、unsupported operation、
operand、operation-plan 和 composition/scale 信号。

Oracle 37 个错误里有 20 个 operand signal 和 11 个 operation-plan signal；
Hybrid 41 个错误里有 12 个 retrieval miss 和 21 个 operand signal。结论是：
下一阶段应先验证“有界 plan review 是否改善选数”，而不是继续增加检索 K 或
默认堆第二个 LLM。任何 review 方案必须同时报告净提升、正确题退化、调用数与
延迟。

诊断不是 LLM judge。retrieval/protocol 是直接事实；operand/operation 使用
gold program 做机械比较，等价代数改写可能造成假阳性。因此文档称其为 signal，
不称确定根因。标签质量审计还记录了 dev `answer` 与 `exe_ans` 的不一致，但主分
继续绑定官方 `exe_ans`。

## 12. 2026-07-29 更新：有界 Plan Review 与候选仲裁

这一阶段没有直接把第二个大模型塞进默认链路，而是先回答一个可证伪问题：
在同一批问题、同一 baseline 和同一评分器下，review 能否修正错误计划，同时不
破坏原本正确的计划？

新增两层能力：

1. `app/external_datasets/finqa_review.py` 让 reviewer 只能 KEEP 或提交一条
   可重新执行的受限表达式；表达式仍经过 AST/Decimal Calculator 和 evidence
   guard。结构协议失败回退到已验证 baseline，Ollama/网络故障则中断，不能伪装成
   正常回退。
2. `app/external_datasets/finqa_adjudication.py` 将 baseline 与 30B proposal
   匿名随机成 A/B，8B adjudicator 只能二选一，不能生成第三条表达式。这样把
   “提出候选”和“决定是否采用”分开，并避免固定位置偏差。

第一版 8B reviewer 因遗漏 raw-ratio 合同，将 Hybrid strict 从 `59%` 降至
`55%`，wrong-to-correct / correct-to-wrong 为 `1/5`。v2 补齐尺度合同并要求
没有无歧义错误就 KEEP，同模型结果回到 `59%`，但没有修正任何题。30B proposal
达到 `61%`，仍有 `5/3` 的修正/退化；匿名 8B 仲裁后 tuning 达到 `63%`、
`4/0`，exact McNemar `p=0.125`。

在调用模型前又冻结了与 tuning 零重叠的 50 题 dev validation。baseline、
30B proposal、最终仲裁 strict 分别为 `44%`、`48%`、`50%`；最终 grounded
strict 为 `38%`，修正/退化为 `3/0`。方向得到复现，但预冻结统计门槛要求
`p<=0.05`，实际为 `0.25`，所以结果为 `COMPLETE_NOT_ADOPTED`。

运行中 Ollama 从 0.32.4 自动升级到 0.32.5，30B 在 CUDA v12/v13 的 Flash
Attention warm-up 都退出。最小请求也能复现，因此不是 FinQA payload；模型张量
已经加载，因此也不像 blob 损坏。Vulkan backend 能完成验证，但跨 backend 延迟
不可与旧 CUDA run 直接比较，最终平均延迟是 baseline 的 `7.84x`。运行 manifest
因此新增 `runtime_backend`，失败 run 不发布 artifact。

这次负结论保留了完整价值：质量方向不是随机只在 tuning 出现，但统计证据和成本
都不够，默认路径继续关闭。下一步不是继续全量堆 30B，而是先做不依赖 gold label
的低成本 uncertainty trigger，并给长评测增加 checkpoint/resume，随后再冻结新
cohort 验证调用率、质量、退化和真实 CUDA 延迟。

本阶段收口验证：FinQA focused `63 passed`，全仓
`2592 passed / 30 skipped / 3 warnings`，public audit
`978 candidates / 0 findings`，`compileall`、`pip check` 和
`git diff --check` 通过。`0 findings` 只说明当前审计器在候选文件和规则覆盖范围
内没有命中，不代表模型质量或软件安全没有剩余问题。

## 13. 2026-07-29 更新：可恢复评测与低成本风险路由

Ollama/CUDA incident 暴露的第一个工业问题不是模型分数，而是长评测中断会丢失
已完成调用。项目新增通用 `ResumableCaseCheckpoint`：contract 绑定数据、样本、
模型、prompt、代码和 backend；逐题记录使用原子提交、row hash 和前序 hash；
恢复只处理未完成尾部；最终 seal 绑定不可变 manifest/details。review 和
adjudication 两条 CLI 已共用这一机制。

第二个问题是 30B 全量复核成本过高。项目没有使用模型自报 confidence，也没有
用 gold label 当线上特征，而是冻结 `finqa_runtime_uncertainty_v1`：根据 operand
grounding、重试、Guard、运算复杂度、引用跨度、数值/年份歧义和比例除法计算
score，`score>=2` 才路由到完整 review/adjudication。

100 题 tuning 上触发 `67%`，保留 strict/grounded `63%/55%` 和全部 `4/0`
修正/退化，generation 增量减少 `32.26%`。预注册的 50 题零重叠 validation
触发 `62%`，保留 `50%/38%` 和 `3/0`，generation/Calculator 增量减少
`35.38%/33.75%`。

这些调用节省是由不可变逐题调用数得到的精确反事实；`28.06%` latency reduction
只是历史逐题增量求和，不是实际 selective wall-clock。validation 又是已揭示
cohort 对新 trigger 的二次使用，源策略 `p=0.25` 仍未通过。因此成本过滤门槛
通过，但生产采用门槛未通过。

证据审计还发现早期公开 validation protocol 的 `split_sha256` 手工抄错。代码
常量和所有 runtime manifest 始终使用正确 hash，运行不受影响。项目保留原冻结
文件，单独发布 erratum，并增加协议/代码/artifact 一致性回归，避免静默重写历史。

最终门禁：FinQA/checkpoint `73 passed`，全仓
`2602 passed / 30 skipped / 3 warnings`，public audit
`986 candidates / 0 findings`，compileall、pip check 和 diff check 通过。

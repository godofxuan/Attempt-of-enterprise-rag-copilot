# Project Status

更新时间：2026-07-15

这份文档只记录当前 checkout 已实现并经过本机验证的能力。详细的问题定位、实验过程、在线资料来源和面试问答见 `docs/AGENTIC_RAG_EVOLUTION_LOG.md`。

## 当前结论

项目已经从普通企业知识库 RAG 升级为一个可评测的 bounded adaptive Agentic RAG workflow：

- Markdown 文档切分、BGE-M3 embedding、FAISS + BM25 检索、RRF 融合。
- 普通 RAG：`POST /chat`。
- 有界 Agentic RAG：`POST /agent/chat`。
- 证据充分性判断、意图保留的查询改写、最多一次重试、grounded no-answer。
- unsafe 请求在检索前短路。
- route、动态 plan、工具步骤、耗时、证据历史和 final outcome trace。
- retrieval、answer、fusion/ablation、Stage 7 action、Stage 8 loop 两层评测。
- FastAPI 后端、Streamlit 基础 UI、SQLite feedback。

准确定位：这不是完整自主 Agent 平台。它没有任意工具选择、多 Agent 委派、长期记忆、checkpoint、人类审批或生产级权限系统。

## 最新本机验证

### 自动化测试

2026-07-15：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

```text
109 passed, 6 warnings
```

warning 来自 FAISS/SWIG 类型、FastAPI `on_event` deprecation 和 `.pytest_cache` 写权限；没有测试失败。

### Ollama 模型

通过 `http://127.0.0.1:11434/api/tags` 验证：

```text
qwen3:8b       evidence assessor
qwen2.5:3b     answer generation
bge-m3:latest  embeddings
```

关键配置：

```text
LLM_BASE_URL=http://127.0.0.1:11434/v1
CHAT_MODEL=qwen2.5:3b
EVIDENCE_MODEL=qwen3:8b
EMBEDDING_MODEL=bge-m3
```

### Stage 8 Agent loop

| Mode / split | Count | Route | Outcome | Retry | Tools | Trace | Unsafe | Limit | Policy | Parse | Case pass |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deterministic dev | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | 1.00 |
| deterministic test | 16 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | n/a | 1.00 |
| live dev | 16 | 1.00 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| live held-out test | 16 | 1.00 | 1.00 | 0.75 | 0.75 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

冻结后的首次 live dev 约 147.9 秒，首次 held-out test 约 137.3 秒。独立代码审查修复通用状态/契约问题后又做了回归复跑：dev 约 155 秒，test 151.1 秒，指标保持不变。第二次 test 是回归验证，不再宣称为未见评估。

`retry/tool=0.75` 的原因不是 4 题答错，而是四个预设 retry-answer 样例在第一轮已经获得足够证据并合法提前回答。live `case_pass` 检查 outcome、trace、安全、解析和有界策略，不强制执行无意义重试。

这些是 16 + 16 个合成样例上的回归结果，不是生产泛化率。Stage 8 的通过门槛验证 outcome、trace、安全、预算和结构化解析，不逐句评分生成文本，也尚未把 `gold_sources` 覆盖率纳入门槛；答案内容与引用质量仍由独立 answer eval 评估。

## Agentic RAG 运行链路

```text
question
-> route_query
-> AdaptiveController.next_step
-> retrieval.search
-> evidence.assess
   -> sufficient: rag.answer
   -> insufficient + budget: query.rewrite -> retrieval.search -> evidence.assess
   -> insufficient/error/no result: rag.no_answer
-> guardrail.check
-> response + AgentTrace
```

unsafe 路由：

```text
guardrail.refuse
```

### 状态语义

```text
question                    原始问题，生成时始终使用
search_query                当前检索查询，可改写
latest_retrieved_chunks     最新一轮结果
retrieved_chunks            跨轮累计并按 chunk_id 去重
retrieval_attempts          0..2
evidence_assessment         最新结构化判断
evidence_history            每轮判断及 rewrite_source
final_outcome               answered / grounded_no_answer / refused / error
```

`latest_retrieved_chunks` 用于判断本轮是否为空；`retrieved_chunks` 用于 assessor 和 generator。两者不能合并成一个字段，否则会重新引入“覆盖历史证据”或“空重试被旧证据掩盖”的 bug。

## 核心代码

| 文件 | 当前职责 |
|---|---|
| `app/agent/router.py` | 确定性 route 分类和 unsafe 前置短路 |
| `app/agent/controller.py` | 固定/自适应控制策略、phase 转换、两轮上限 |
| `app/agent/runner.py` | observe-decide-act、状态合并、动态 plan 和 trace |
| `app/agent/tools.py` | 检索、累计去重、证据判断、改写、回答、拒答、guardrail |
| `app/agent/evidence.py` | JSON Schema、prompt、Pydantic 校验、改写护栏、本地 assessor |
| `app/ollama_chat.py` | 共享 Ollama transport；evidence 请求支持顶层 `think:false` |
| `app/agent/schemas.py` | API response 和 evidence trace 数据结构 |
| `scripts/eval_agent_loop.py` | deterministic/live Stage 8 evaluator |

## 从零运行

```powershell
cd D:\文档\agent\RAG_try
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull bge-m3
ollama pull qwen2.5:3b
ollama pull qwen3:8b
.\.venv\Scripts\python.exe -m scripts.build_indexes
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

另一个终端：

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py
```

地址：

```text
FastAPI  http://127.0.0.1:8000
Swagger  http://127.0.0.1:8000/docs
Streamlit http://127.0.0.1:8501
```

Agent API 示例：

```powershell
$body = @{ question = "差旅费用和办公费用的报销区别在哪里？"; top_k = 5 } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/agent/chat -Method Post -ContentType "application/json; charset=utf-8" -Body $body
```

Windows 上优先使用 `127.0.0.1`，避免 `localhost` 优先解析 IPv6 而服务只监听 IPv4 时出现连接等待。

## 评测命令

```powershell
# 检索
.\.venv\Scripts\python.exe -m scripts.eval_retrieval_v2 --split test --top-k 5
.\.venv\Scripts\python.exe -m scripts.eval_ablation_v2 --split test --top-k 5
.\.venv\Scripts\python.exe -m scripts.eval_fusion_ablation --split test --top-k 5

# 回答与安全
.\.venv\Scripts\python.exe -m scripts.eval_answer_v1 --split test
.\.venv\Scripts\python.exe -m scripts.eval_answer_v1 --split adversarial

# Stage 7 固定计划历史基线
.\.venv\Scripts\python.exe -m scripts.eval_agent_actions --split test

# Stage 8 自适应控制层与真实集成
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split dev --mode deterministic
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode deterministic
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split dev --mode live
.\.venv\Scripts\python.exe -m scripts.eval_agent_loop --split test --mode live
```

生成结果位于 `data/eval_outputs/`，默认不提交 Git。

## 历史基线如何理解

Stage 7 `agent_action_test` 的历史结果：route accuracy 0.55、plan/tool 0.90、trace 1.00、unsafe no retrieval 0.50、case pass 0.55。它使用旧的 `FixedPlanController`，保留为“升级前”基线。

Stage 8 新数据集评估的是四种动态轨迹：first-pass answer、retry-answer、retry-no-answer、unsafe refusal。不能直接把两个版本的百分比当成同一个数据集上的前后提升；正确比较方式是：Stage 7 证明旧流程的路由和固定计划问题，Stage 8 证明新状态机和真实 evidence loop 的行为。

## 当前限制

- 数据是合成企业制度，不含真实 ACL、组织层级和多租户隔离。
- router 仍以确定性关键词为主；Stage 7 held-out route accuracy 只有 0.55。
- 最终生成仍使用 3B 本地模型，复杂多来源答案可能遗漏条件。
- answer evaluation 的部分检查仍是 heuristic，需要 LLM judge 和人工校准组合。
- Streamlit 尚未展示 Agent trace。
- trace 尚未持久化，不能跨请求回放或恢复。
- 没有 reranker、冲突证据处理、权限过滤和文档级 prompt-injection 专项评测。

## 面试时的准确介绍

```text
我先把企业知识库 RAG 做成了可评测系统，包括 BM25 + FAISS、RRF、引用和 retrieval/answer eval。随后我没有直接堆多 Agent，而是先做 action eval，发现旧流程虽然 trace 完整，但所有安全请求都走固定计划，无法根据证据改变动作。

我把 runner 改成 observe-decide-act，用 Python 控制安全与两轮上限，用本地 qwen3:8b 做结构化证据判断。证据足够就回答，不足则保持原问题、改写 search query 并重试一次，仍不足就 grounded no-answer。两轮检索证据按 chunk_id 去重累计，所有动作和 evidence reason 都进入 trace。

我把 deterministic controller eval 和 live model eval 分开。当前 109 个自动化测试通过；16 题 dev 与冻结后首次 16 题 held-out live test 的 outcome、policy、trace 和 case pass 都是 1.0，审查后回归结果保持一致。严格轨迹只有 0.75，因为部分预设重试题首轮已经足够。我把这个差异作为评测标签不是唯一正确策略的证据，而不是隐藏它。
```

不要说：

```text
这是一个生产级完整自主 Agent，准确率 100%。
```

## 下一步优先级

P0：Streamlit 增加普通 RAG / Agentic RAG 切换，并展示 route、evidence、rewrite、tools、latency、final outcome。

P1：持久化 trace，支持按 case id 回放、失败聚类和回归集自动沉淀。

P2：扩大 capability eval：冲突证据、恶意文档、权限过滤、多来源长答案和真实人工评分。

P3：在有基线后评估 reranker；不因为“业内常见”就直接加入。

P4：再评估是否需要 checkpoint、人类审批或多 Agent；当前不优先。

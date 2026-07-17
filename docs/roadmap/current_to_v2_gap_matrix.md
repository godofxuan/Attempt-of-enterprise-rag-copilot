# Current to Enterprise Agentic RAG v2 Gap Matrix

审计日期：2026-07-16
代码基线：`7aec4b9`
用途：把“文件存在”与“真正改变系统行为、有测试、有评测收益”分开。

## 1. 判定规则

- **保留**：当前能力真实影响运行，且是 v2 的合理基线。
- **增强**：当前能力有效，但 schema、边界、测试或规模不足。
- **合并**：职责重复或只产生标签，合并后减少无意义模型/模块调用。
- **替换**：当前 contract 无法表达 v2 核心需求，但需保留 compatibility baseline。
- **归档候选**：只服务历史或已被新版取代；先做引用审计，再决定删除。
- “有测试”只指当前 `pytest.ini testpaths=tests` 收集到的 109 个测试；`scripts/test_*.py` 不算当前 suite。
- “有评测”区分 deterministic contract、heuristic answer eval 和真实 local-model integration，不混为同一种证据。

## 2. 逐组件价值审查

| 当前组件/入口 | 解决的问题 | 是否真正改变行为 | 独立测试 | 评测证据 | 额外调用/延迟 | 决策 | R1 缺口 |
|---|---|---|---|---|---|---|---|
| `app/utils.py:read_text_file` | UTF-8 文本读取 | 是，但只支持纯文本 | 无 parser 测试 | 无 | 无模型成本 | 替换 | Parser Registry、结构化错误、warnings、source locator |
| `app/chunker.py:split_sections` | 按 Markdown heading 分段 | 是 | 无正式 chunker test | 没有 chunking 消融 | 无模型成本 | 增强 | 多级 section path、table、parent-child、stable IDs |
| `app/chunker.py:chunk_text` | 固定字符窗口和 overlap | 理论上是；当前 44-121 字 chunks 未触及 500 字上限 | 无正式 test | 无 baseline-vs-chunker | 增加 chunk 数会增加 embedding/context | 替换并保留 baseline | 真实长文档、heading-aware/parent-child 消融 |
| `app/retriever.py:build_indexes` | 构建 FAISS/BM25/chunks | 是 | 无 lifecycle/CLI test | 只靠后续 retrieval run | 每 chunk 一次 embedding；原地覆盖 | 替换 | dry-run/help/force、manifest、versioned output、validation |
| `FAISS IndexFlatIP` | dense similarity | 是 | metrics 有单测，真实 index 无 lifecycle test | dense Hit@1 `0.9167` | query embedding + 75x1024 flat search | 保留 baseline | metadata/ACL filter、scale profile、manifest |
| `BM25Okapi` | 关键词召回 | 是 | metrics 有单测，token/index 无独立 test | BM25 Hit@1 `0.85` | 低 | 保留 baseline | field-aware/metadata filter、parameter provenance |
| `hybrid_search` RRF | 融合 dense/sparse ranks | 是 | 无直接 production retriever test | RRF Hit@1 `0.9333`, MRR `0.9639` | 一次 embedding；约 193ms ablation avg | 保留增强 | filters、dedup/diversity、parent expansion、分阶段 trace |
| weighted score fusion | 实验融合 | 只在 evaluator，不在 runtime | evaluator 间接覆盖 | Hit@1 `0.95`，但 per-query min-max | 与 RRF 类似 | 保留实验，不默认 | 在 v2 数据上重新消融，未稳定不进 runtime |
| `router.py` unsafe 分支 | 用户侧危险请求前置拒绝 | 是，直接跳过 retrieval/generation | router/runner/loop tests | unsafe no-retrieval 有行为指标 | 避免模型调用 | 保留规则边界 | 加越权/UserContext/document injection 分类，不能只靠关键词 |
| `router.py` comparison/process/no-answer | 给问题贴 route 标签 | 默认 runtime 中几乎不改变行为 | 5 个关键词测试 | Stage 7 route accuracy `0.55` | 无模型成本，但维护重复规则 | 合并 | 结构化 QueryAnalysis 必须驱动 filters/tools/answer mode |
| `planner.py:build_plan` | 生成固定计划 | 默认 AdaptiveController 不调用；除 unsafe 外所有 route 同计划 | planner tests | Stage 7 fixed-plan baseline | 无模型成本 | 归档/合并 | 保存历史 baseline 后移出生产叙事 |
| `FixedPlanController` | Stage 7 历史执行契约 | 只在历史/eval path 有意义 | 有 | action test plan/tool `0.90` | 固定三步 | 归档候选 | legacy adapter，不作为 v2 runtime |
| `AdaptiveController` | 根据 phase/evidence 选择下一动作 | 是 | 边界、retry、终止覆盖较好 | deterministic/live loop | 无模型成本 | 保留增强 | typed AgentBudget、deadline、find/open、partial/permission/conflict outcomes |
| `AgentRunner` | observe-decide-act、状态合并、trace | 是 | fixed/adaptive runner tests | action/loop trace | 工具调用总延迟累加 | 保留增强 | cancellation、structured tool errors、request ID、错误时返回 trace |
| `ToolRegistry` | allowlisted 工具名 -> Python 函数 | 是 | registry/runner tests | tool sequence | 无额外模型成本 | 保留增强 | typed args/results、timeout、per-tool budgets、security metadata |
| `retrieval.search` | hybrid retrieval | 是 | fake + monkeypatch tests | retrieval/loop | 每次 embedding；最多两次 | 保留增强 | filters、ACL、parent expansion、candidate stage counts |
| `query.rewrite` | 使用 assessor query 重试 | 是 | usable/intent/fallback tests | loop retry metric | 多一次 evidence + embedding | 增强 | required/missing fact 驱动，保留实体/时间/地区/比较/完整性 |
| `is_intent_preserving_rewrite` | 防明显意图漂移 | 部分；只要求有一个区别性 token 重合 | 有 | 无独立语义 eval | 低 | 替换 | QueryAnalysis invariant + structured missing facts；token overlap 仅兜底 |
| `LocalEvidenceAssessor` | 判断证据是否足以生成 | 是 | JSON/schema/failure/prompt tests | live parse `1.0`，但小集 | 每次一次 qwen3:8b；`think=false` 降延迟 | 保留机制、替换 schema | required facts、conflicts、authority、coverage、recommended action |
| balanced assessment view | 8 chunk 内兼顾新旧证据 | 是，修复重试证据被截断 | 有 | dev007 regression | 控制 context | 保留 | ledger 应基于 fact coverage，而不只是片段轮次交错 |
| `rag.answer` / `answer_from_retrieved` | 只用累计证据生成 | 是 | supplied chunks/no-research tests | answer eval | 一次 qwen2.5:3b | 保留增强 | 结构化 claims、partial/conflict modes、token budget |
| `classify_question_type` | 为 prompt 选择回答格式 | 是，但与 router 重复猜意图 | 间接测试很少 | 无独立 accuracy | 无模型成本 | 合并 | 使用 QueryAnalysis，避免 route/classifier/prompt 三套规则 |
| `guardrail.check` | 用正则检测明显危险答案 | 是 | 有 | adversarial refusal | 低 | 保留增强 | 文档 injection、PII/ACL leakage、claim support，不宣称完整安全 |
| `AgentTrace` | 返回 route/plan/steps/evidence/outcome | 是 | schema/trace completeness tests | trace `1.0` | 响应体增加 | 增强 | request ID、span 时间、版本、candidate counts、stop reason、脱敏 |
| `app/db.py` | SQLite feedback | 是 | 无 | 无 feedback analytics | 每次请求短连接 | 保留最小/增强 | context manager、error model；trace persistence 只存脱敏 metadata |
| `/health` | 进程活性提示 | 只固定返回 `ok` | 无 health test | 无 | 低 | 替换 | `/health/live` 与实际 index/model/db `/health/ready` |
| `/ingest` | HTTP 触发建库 | 是，但原地覆盖且可长时间阻塞 | 无 | 无 | 75 次 embedding，180s UI timeout | 替换/限制 | versioned build job 或明确管理 CLI；普通 worker 不重复建库 |
| `/chat` | baseline RAG API | 是 | rag service 流程有 mock test | retrieval/answer eval | embedding + answer model | 保留兼容 | UserContext、request ID、typed error/deadline、v2 response |
| `/agent/chat` | bounded adaptive API | 是 | 只有一条 mocked endpoint contract test | agent loop | 最多 2 retrieval + 2 assessor + answer | 保留增强 | v2 schemas、ACL、navigation、ledger、claims、stop reason |
| FastAPI startup event | 建目录和 SQLite table | 是 | import 时产生 deprecation warning | 无 | worker startup | 替换 | lifespan、controlled resource load/release、readiness |
| `streamlit_app/ui.py` | 基线问答、来源、feedback、建库 | 是 | 无 | 无 UI eval | 调 `/chat`；建库 timeout 180s | 替换为三页 | 不调用 `/agent/chat`，不展示 trace/eval/role/claims |
| retrieval evaluator | Hit/Recall/Coverage/Precision/MRR/nDCG | 是 | metrics/schema tests | 60 test cases | 每题 embedding | 保留增强 | doc recall、invalid extras、ACL leakage、run provenance、不覆盖 |
| answer evaluator | must/must-not/refusal/source coverage | 是但 heuristic | rule tests | test 70、adversarial 10 | 完整 answer model run | 替换评分 contract | 当前 substring 匹配粗；需 atomic facts、correctness、unsupported claims |
| `cited_sources = retrieved_sources` | 计算 citation 指标 | 没有检查答案是否真的引用，只把检索结果当引用 | 无反例测试 | citation hit/coverage 被高估风险 | 无 | 删除该假设 | 从 answer claims/citation markers 建支持关系并验证 entailment |
| error type classifier | 粗粒度失败分类 | 是 | 优先级测试 | answer failure counts | 低 | 增强 | parse/chunk/ACL/query/ledger/conflict/citation/runtime 主次因 |
| Agent action evaluator | 历史 route/fixed plan 契约 | 是 | 有 | test route `0.55` | 无外部模型 | 保留历史 | 不再称 production planner eval；作为 baseline artifact |
| Agent loop deterministic | 状态机/预算/错误路径 | 是 | evaluator tests | dev/test 16/16 | 无模型 | 保留 | 扩展 search/find/open/ACL/conflict contract，明确非语义能力 |
| Agent loop live | 本地 model integration | 是 | evaluator contract tests | small regression 16+16 | 约 151-155s/full split | 保留但重做 pass gate | 当前 row 不保存 answer/sources，case-pass 不评答案语义/gold coverage |
| adversarial dataset | 用户 prompt injection/refusal | 是 | schema + answer eval | 10 cases refusal `1.0` | 规则短路多 | 增强 | 文档内 injection、越权、跨租户、trace leakage、tool abuse |
| `pytest.ini` | 收集 tests 并统一 temp | 是 | 自身无测试 | 109 passed | 写 `.pytest_cache` 和 repo `data/eval_outputs/pytest_tmp` | 修改 | 使用系统/CI temp，测试 artifact 与正式 eval runs 分离 |
| `requirements.txt` | 声明依赖 | 是 | `pip check` 私人审计通过 | 无 | 安装可漂移 | 替换为可复现声明 | 当前全无版本；增加兼容范围/lock strategy |
| GitHub Actions | CI | 不存在 | 无 | 无 | 无 | 新增 | deterministic/API/small fixture，不调用 Ollama |
| README/PROJECT_STATUS | 运行与能力说明 | 功能分支较诚实 | 文档无自动链接检查 | 数字来自旧 artifacts | 无 | E6 收口 | warning 数过期；默认分支首页仍是旧普通 RAG |

## 3. 当前数据与评估差距

| 维度 | Current | R1 目标 | 当前结论 |
|---|---|---|---|
| 企业来源 | 15 份短政策 Markdown | 正式政策、Wiki/SOP、邮件、ticket、会议、表格 | 严重不足 |
| 格式 | Markdown | MD/TXT/PDF/DOCX/HTML/CSV 或 JSONL | 严重不足 |
| 规模 | 15 docs / 75 tiny chunks | demo 60-100；benchmark 500-800、实际 5k-15k chunks | 未达到 |
| 元数据 | source/section/chunk_id/text | department/project/region/tenant/ACL/version/status/effective/authority/checksum | 未实现 |
| 版本/冲突 | 文件名中一处 2025 | 版本链、authority、effective date、冲突案例 | 未实现 |
| 近重复/误归档 | 无 | 可配置比例、固定 seed、validator | 未实现 |
| ACL | 无 | forbidden docs、pre-context filter、cross-tenant tests | 未实现 |
| prompt injection | 用户问题 10 例 | 用户 + 文档内 injection + trace/tool leakage | 部分实现 |
| gold facts | must_include 字符串 | 原子 facts、valid/forbidden docs、filters、authority rules | 需替换 |
| test provenance | 旧 split 已重复运行 | v2 test 冻结 SHA256，release 前按门禁运行 | 旧 test 只可作 regression |
| run provenance | 固定 summary/details 路径 | per-run manifest/config/hash/model/env | 未实现 |

## 4. 测试覆盖差距

当前 109 个测试覆盖较强的部分：

- Agent controller phase、retry 上限和 unsafe short-circuit。
- evidence JSON schema、错误转换、rewrite fallback。
- 工具状态累计、balanced assessment 和 original question invariant。
- deterministic evaluator、指标函数和旧数据 schema。

当前没有正式测试或覆盖很弱的部分：

- 多格式 parser、parse warnings、空文本阻断。
- 实际 `build_indexes` CLI 和索引生命周期。
- heading-aware/parent-child/table chunking。
- production hybrid search 的 filters、candidate stage 和 index manifest。
- ACL、多租户、版本、authority、conflict resolver。
- document navigation `find/open`。
- claim-level citation 和 unsupported claims。
- SQLite feedback/trace 持久化。
- health/readiness、request ID、deadline/cancellation、统一错误模型。
- Streamlit UI、CI、load profile。

## 5. 文档和招聘主张差距

| 主张 | 当前证据 | 可否使用 | 精确边界 |
|---|---|---|---|
| 109 tests passed | 2026-07-16 现场 `109 passed, 5 warnings` | 可绑定 `7aec4b9` | 不写 6 warnings；测试数量不代表生产质量 |
| retrieval Hit@1 0.9333 | 60 个 answerable synthetic test artifact | 可谨慎使用 | 缺完整 run manifest；注明 15 文档合成集 |
| Agent loop 16/16 | 已重复运行的小型 live regression | 不作简历主指标 | case-pass 不评分答案语义，不能称 unseen/100% accuracy |
| bounded adaptive RAG | 代码、测试、API 和 trace 支持 | 可使用 | 仅 search/rewrite，两轮上限；不是通用 Agent |
| production/industrial | 无真实 ACL、CI、manifest、load、安全工程证据 | 不可使用 | R1 完成后也优先写“reference/demo with measured evidence” |
| 旧简历 102 tests / 15/16 | 2026-07-15 私人审计确认已过期 | 必须移除或改为历史 | E0 不直接修改私人简历 |

## 6. 优先级

### P0：E1 数据和评估 contract

没有真实感 corpus、原子 gold facts、ACL/version/conflict cases，就无法证明后续 parser、filters、find/open、ledger 和 security 的价值。

### P1：E2 ingestion/index contract

当前 `python -m scripts.build_indexes --help` 会触发建库，索引原地覆盖且无 manifest；这是最明确的工程风险。

### P2：E3 有行为价值的 Agent

合并装饰性 router/planner，用 QueryAnalysis 驱动 filters/tools；加入 search/find/open、ledger 和 claim citation。

### P3：E4-E5 证据和工程

先让每次 run 可追溯，再谈指标提升；先保证 ACL/context/trace 边界，再谈生产感。

### P4：E6 展示

UI 和 README 只展示已经有代码、测试、评测 artifacts 支持的能力。

## 7. E0 证据命令摘要

```text
git status --porcelain=v2 --branch
  HEAD 7aec4b9, upstream aligned, clean

git ls-remote --symref origin HEAD
  default branch main at 476c718

pytest -q
  109 passed, 5 warnings in 5.21s

raw/index inventory
  15 Markdown files, 18,332 bytes, 75 chunks
  IndexFlatIP, dim 1024, ntotal 75

GitHub main README
  still presents the older ordinary-RAG version
```

E0 没有运行 live 模型、没有生成语料、没有重建索引、没有修改业务代码，也没有改 GitHub。

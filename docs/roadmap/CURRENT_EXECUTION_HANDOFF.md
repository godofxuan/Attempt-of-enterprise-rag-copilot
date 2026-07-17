# Enterprise Agentic RAG v2 - Current Execution Handoff

最后更新：2026-07-17

用途：当 Codex 上下文压缩、任务中断或更换协作者时，从本文恢复精确状态。本文保存当前断点、验证证据和禁止越过的边界；实现细节以各阶段实施记录为准。

## 1. 总目标与路线

把本地 RAG Demo 升级为适合 AI Agent/RAG 实习面试展示的 R1 Enterprise Agentic RAG：有可复现语料、冻结评估集、版本化索引、运行时 ACL、受控 Agent 工作流、分层评估、可核验证据和诚实的能力边界。

```text
E0 只读审计与设计
-> E1 企业档案与冻结评估集
-> E2 Parser/DocumentRecord/Chunking/Index Lifecycle
-> E3 ACL-aware Retrieval + search/find/open + EvidenceLedger
-> E4 Retrieval/Answer/Agent/Security 分层评估与消融
-> E5 API/health/timeout/request ID/trace/CI/load evidence
-> E6 Streamlit 演示、README、架构图、data/threat cards
-> E7 claims-evidence matrix、简历与面试材料收口
```

R2 的 5,000+ 文档、增量 upsert/delete、OpenTelemetry、Docker、专用向量数据库、多 Agent 和长期记忆不属于当前 R1，必须另行批准。

## 2. 权威文档读取顺序

1. 总体真实架构与取舍：`docs/roadmap/enterprise_agentic_rag_v2_design.md`
2. E0-E7 实施阶段和批准门：`docs/roadmap/enterprise_agentic_rag_v2_plan.md`
3. 当前到目标的差距：`docs/roadmap/current_to_v2_gap_matrix.md`
4. 跨阶段决策、故障、实验、边界：`docs/roadmap/engineering_decision_failure_ledger.md`
5. E1 实施记录：`docs/roadmap/e1_enterprise_corpus_implementation.md`
6. E2 实施记录：`docs/roadmap/e2_parser_index_lifecycle_implementation.md`
7. E2 初学者教程：`docs/roadmap/e2_beginner_learning_and_interview.md`
8. E3 设计：`docs/superpowers/specs/2026-07-16-e3-retrieval-agent-workflow-design.md`
9. E3 TDD 计划：`docs/superpowers/plans/2026-07-16-e3-retrieval-agent-workflow.md`
10. E3 实施与故障记录：`docs/roadmap/e3_retrieval_agent_workflow_implementation.md`
11. E3 初学者代码地图与面试问答：`docs/roadmap/e3_beginner_learning_and_interview.md`
12. E4 设计：`docs/superpowers/specs/2026-07-16-e4-evaluation-ablation-design.md`
13. E4 TDD 计划：`docs/superpowers/plans/2026-07-16-e4-evaluation-ablation.md`
14. E4 实施记录：`docs/roadmap/e4_evaluation_ablation_implementation.md`
15. E4 评测协议：`docs/evaluation.md`
16. E4 消融报告：`docs/ablation_report.md`
17. E4 初学者代码地图与面试问答：`docs/roadmap/e4_beginner_learning_and_interview.md`
18. E5 设计：`docs/superpowers/specs/2026-07-17-e5-security-service-observability-design.md`
19. E5 TDD 计划：`docs/superpowers/plans/2026-07-17-e5-security-service-observability.md`
20. E5 实施与故障记录：`docs/roadmap/e5_security_service_observability_implementation.md`
21. E5 初学者代码地图与面试问答：`docs/roadmap/e5_beginner_learning_and_interview.md`
22. E5 威胁模型：`docs/security_threat_model.md`
23. E5 API/观测/复现：`docs/api.md`、`docs/observability.md`、`docs/reproducibility.md`
24. E6 设计：`docs/superpowers/specs/2026-07-17-e6-demo-public-repo-design.md`
25. E6 TDD 计划：`docs/superpowers/plans/2026-07-17-e6-demo-public-repo.md`
26. E6 实施与故障记录：`docs/roadmap/e6_demo_public_repo_implementation.md`
27. 当前公开状态与入口：`PROJECT_STATUS.md`、`README.md`
28. 演示复现与截图契约：`docs/demo_runbook.md`、`docs/assets/README.md`
29. 架构、限制与 R2 admission：`docs/architecture.md`、`docs/known_limitations.md`、`docs/industrialization_backlog.md`

## 3. Git 与操作边界

```text
workspace: <repo-root>
branch: codex/rag-eval-system
E7 start HEAD: 7aec4b950e012d3f24b8e1877d6391201e9b8f90
upstream: origin/codex/rag-eval-system
commit + push current feature branch: AUTHORIZED
merge/tag/default-branch/repository visibility: NOT AUTHORIZED
```

E7 起始工作树包含 E0-E6 的累计修改，不得用 `reset`、`clean`、`checkout --` 丢弃。本人先批准 `执行E7最终验收`，随后明确要求“直接传到 GitHub”，因此允许在全部自动门禁完成后 commit 并 push 当前功能分支；该授权不包含 merge、tag、默认分支或仓库可见性变更。

## 4. 阶段状态

| 阶段 | 状态 | 关键证据 |
|---|---|---|
| E0 | complete | 总体设计、阶段计划、gap matrix、只读审计记录 |
| E1 | complete and accepted | 企业档案、24-case demo dev、冻结 test hash、600-document benchmark profile |
| E2 | complete and accepted | 七格式 parser、治理、三种 chunk、版本化 index build/activate/rollback、dev chunking ablation |
| E3 | complete and accepted | C01-C10 全部完成；用户已用精确命令批准进入 E4 |
| E4 | complete and accepted | 用户已用精确命令批准 E5；四层 eval、消融、9 个 immutable runs、50-row blank review |
| E5 | complete and accepted | 用户已用精确命令批准 E6；API/安全/观测/CI/load；final full 526 passed |
| E6 | complete and accepted | 本人已发送 `执行E7最终验收`；历史 final full 569 passed |
| E7 | automated/local acceptance complete; owner-only NOT RUN | rc02 28/28、load 31/31、browser/API、post-EOL full 574；等待第三次 clean clone |

冻结 test SHA256：

```text
556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
```

E3 只重新计算该 hash。E4 在 dev 代码与参数冻结后正式校验并运行 test；test 结果没有用于 E4 内继续调参。

## 5. E3 已完成范围

### 5.1 Domain 与 ACL

- `app/domain/queries.py`：`UserContext`、`QueryAnalysis` 和 search/find/open contract。
- `app/domain/evidence.py`：`EvidenceLedger`、`Claim`、`ClaimCitation`、`AnswerResponse`。
- `app/domain/agent.py`：`AgentBudget`、`BudgetState`、`AgentAction` 和 typed tool errors。
- `app/security/access.py`：tenant + region + group 交集授权和 trace 脱敏。

ACL 在候选进入 fusion、context 和公开结果之前执行；拒绝结果不返回资源 metadata。测试覆盖 tenant/region/group mismatch 和 zero-leak。

### 5.2 Retrieval 与导航工具

- `app/retrieval/snapshot.py`：把 E2 active manifest、FAISS、BM25、chunks、parents、documents 验证后绑定为不可变 snapshot。
- `app/retrieval/pipeline.py`：ACL/metadata filter、BM25、dense、RRF、authority/time、diversity 和 authorized parent expansion。
- `app/retrieval/navigation.py`：有界 `search/find/open`；不接收任意文件系统路径。

### 5.3 Agent 工作流

- `app/agent/query_analysis.py`：rule-first unsafe、intent、comparison decomposition、temporal filter 和受约束 fallback。
- `app/agent/evidence_relevance.py`：query-anchor admission heuristic。
- `app/agent/evidence_ledger.py`：required/supported/missing/conflict/coverage 和 next action。
- `app/agent/citation_verifier.py`：citation presence、visible-reference correctness 和 lexical signal。
- `app/agent/tools_v2.py`：allowlist、调用次数、context、deadline 和结构化错误。
- `app/agent/controller_v2.py`：`next_decision -> registry.run -> observe` 显式状态机。
- `app/agent/runner_v2.py`：有界循环、终态、lazy default runner 和聚合脱敏 trace。
- `app/agent/generation_v2.py`：只使用 ledger-selected visible evidence，strict JSON 和 source-ID 映射。

### 5.4 API 与评估

- `app/schemas.py`、`app/main.py`：新增必须显式传 `UserContext` 的 `/agent/v2/chat`。
- `scripts/eval_agent_v2_dev.py`：deterministic/live 两种 dev 模式、逐题失败详情和不可覆盖 run artifact。
- legacy `/chat`、`/agent/chat` 和旧检索默认路径未被替换。

## 6. E3 行为实验

第一次 deterministic dev：

```text
artifact: data/eval_outputs/agent_v2_dev_e3_deterministic/
outcome accuracy                 20/24 = 0.8333
comparison full coverage          4/4 = 1.0
permission zero-source            2/2 = 1.0
unsafe zero-tool                  1/1 = 1.0
budget compliance               25/25 = 1.0
trace completeness              25/25 = 1.0
citation presence               26/26 = 1.0
citation visible correctness    26/26 = 1.0
forbidden-source zero           24/24 = 1.0
```

四个失败都是 `no_answer -> answered`。根因是同一政策文档被命中后，旧 ledger 就把 required aspect 当作 supported；但“2027 所有限额自动翻倍”这一命题并不在证据里。citation 合法不能证明命题被支持。

先为 relevance unit/controller integration 写 RED，再加入 query-anchor gate。第二次同条件 dev：

```text
artifact: data/eval_outputs/agent_v2_dev_e3_anchor_gate/
outcome accuracy                 24/24 = 1.0
comparison full coverage          4/4 = 1.0
permission zero-source            2/2 = 1.0
unsafe/budget/trace/forbidden       all 1.0
citation presence/visible        22/22 = 1.0
```

before/after 只有四个 no-answer case 从 answered 变成 not_found，其余 20 个 mode/failure 不变。因为修复看过 dev failure，这只能称为 dev regression，不是 unseen/final accuracy；deterministic hash embedding、synthetic corpus 和 lexical gate 也不等于真实生产效果。

## 7. E3 验收证据

最近一次门禁：

```text
E3 focused domain/retrieval/security/agent_v2 155 passed, 5 warnings
legacy controller/runner/API/RAG               24 passed, 5 warnings
full repository                               380 passed, 5 warnings
pip check                                      clean
compileall app/scripts/tests                   ok
git diff --check                               exit 0, CRLF notices only
frozen test expected == actual                 556ffe...43338
project Python/pip processes                   0
git index lock                                 false
```

warnings 是 FAISS SWIG type deprecations 和 legacy FastAPI `on_event` deprecation；FastAPI lifespan 迁移属于 E5，不在 E3 混入兼容性重构。

E3 evaluator 的第二次发布曾在 Windows staging rename 上出现 `WinError 5`。target 不存在、父目录可写、项目后台进程为 0；最可信解释是短暂目录句柄/rename 拒绝，但不能百分百断言。修复是 resolved absolute paths、只对 `PermissionError` 最多重试五次、每次检查并发 target，其他异常立即失败；回归测试和重跑均通过。

最终门禁第一次并行检查还产生过三个诊断项：manifest 整行比较造成假 hash mismatch；进程检查把同时运行的 pytest 计为 1；旧 `.pytest_cache` protected DACL 造成 Python `WinError 5`。前两项通过正确解析和串行检查消除；缓存目录只恢复 ACL 继承后，Python 复现命令和 targeted pytest 转绿，full suite 再次为 380 passed/5 warnings。详见实施记录 `E3-I08`。

## 8. 当前精确断点

用户已给出 `批准E3，执行E4评估与消融`，E4-C01-C07 现已实现和验证。审计 run root 是 `20260716T135632Z_7aec4b9`。9 个 run manifests 的 artifact hashes 全部匹配；active live index 是 `20260716T135632Z_7aec4b9_live_bge_m3_fixed`，`bge-m3` 1024D、64 fixed chunks。

核心结果：deterministic dev accepted 24/24；frozen deterministic test 28/28；live dev 在修复 Ollama grammar schema 后 23/24。test hash 仍为 `556ffed...43338`，未用于 E4 内调参。50-row human review 的 400 个判断单元格全部为空，等待本人填写。

当前必须停止在 E4 本人验收门。没有授权 commit/push/merge/tag，也没有进入 E5。只有用户精确发送 `批准E4，执行E5安全、服务与可观测性` 才能开始 E5。

## 9. 恢复检查清单

```powershell
git status --short --branch
git rev-parse HEAD
Test-Path .git\index.lock
Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*RAG_try*' -and $_.Name -match 'python|pip'
}
```

恢复后先读取第 2 节列出的 E4 设计、实施、评测、消融和学习文档，再核对 Git/status/process/lock。不要从 E0 重做，不要用 test 结果继续调整 E4 参数，也不要依靠聊天记忆覆盖本文记录。

## 10. 当前可说与不可说

可以说：实现显式 UserContext、pre-fusion ACL-aware hybrid retrieval、有界 search/find/open、EvidenceLedger、claim citations，以及 retrieval/answer/agent/security 四层评测、不可覆盖 artifacts、受控消融和人工抽检模板；deterministic frozen test 28/28，live dev 23/24；全仓库 462 tests passed。必须同时说明 synthetic、小样本、dirty HEAD 和人工审核 pending。

可以说的消融结论：metadata/temporal filtering 在 deterministic test 和 live dev 都把 retrieval Recall/authority/pass 提到 1.0；bounded Agent 修复 fixed RAG 的四个 unsupported no-answer，但 live 平均延迟、工具、context 和模型调用明显增加。

不可说：生产级、高并发、人工 factuality 100%、semantic entailment 已解决、bge-m3 普遍优于 BM25、RRF 必然提升、parent-child/reranker 已证明有效、已接真实 IAM/服务端向量 ACL/durable execution/hot reload/线上 observability，或完整复刻了 Claude Code 核心实现。

## 11. E5 已实现范围

- `app/runtime/request_context.py`：ContextVar request ID、deadline、model counters/spans。
- `app/runtime/model_transport.py`：chat/embed 共享 timeout、最多两次 transient retry、安全错误。
- `app/runtime/resources.py`：DB/index/models readiness、TTL、service container。
- `app/api/errors.py`、`middleware.py`：统一错误、request header、safe finally telemetry。
- `app/main.py`：`create_app()`、FastAPI lifespan、live/ready、metrics/trace routes；无 `on_event`。
- `app/observability/`：有界 request trace、低基数 metrics、p50/p95、Windows RSS。
- `app/db.py`：新 feedback 只存 request ID、SHA256、helpful、时间。
- `scripts/load_profile.py`：cold/warm、concurrency 1/5/10、不可覆盖 artifact、正文零持久化。
- `.github/workflows/ci.yml`：Python 3.11、read-only、pins/pip check/compile/hash/full tests，不调用 Ollama。

live 证据：active index `20260716T135632Z_7aec4b9_live_bge_m3_fixed`，bge-m3 1024D、64 chunks。第一条真正 Ollama-cold smoke 因 embedding 4625ms 使 5s search budget 超时，安全返回 system；同题 warm search 203ms 并 answered。主要 load r2 为 31/31 business success；warm concurrency 1/5/10 p95 分别 1.136s/4.406s/8.633s；model calls +62；RSS +66,097,152 bytes；artifact hash match；正文/identity 0 命中。

第一次 load artifact 因 Windows ctypes HANDLE 未声明导致 RSS null，已保留且未覆盖；Windows-only RED 后修复 FFI 类型，生成独立 r2。项目 uvicorn 已停止，项目 Python/pytest/pip 后台为 0，Ollama 保留。

## 12. E5 验收断点（历史）

E5 代码、live profile、文档和 fresh final gates 已完成。最终证据：API/obs/security 47 passed；evaluation 81 passed；full 526 passed；pip/compile/diff/hash/index/process/lock 均通过。随后本人发送精确命令批准 E6；本节只保留历史，不再是当前恢复点。

```text
批准E5，执行E6演示与公开仓库收口（已执行）
```

不要依据聊天记忆重新跑或覆盖 `load_runs/20260716T165304Z_7aec4b9_demo_load*`。主要结果使用 `_demo_load_r2`；第一份是 RSS incident 证据。

## 13. E6 首轮收口断点（已被审查取代）

用户已发送 `批准E5，执行E6演示与公开仓库收口`。E6-C01-C08 已实现并完成本机验证：

- `app/agent/runner_v2.py` 向外只给 required/supported/missing/conflicting/coverage/recommended_action 六类 evidence 摘要，不泄露 ledger items、问题、身份或文档正文。
- `data/v2/public/demo_snapshot.json` 是从 4 个 canonical E4/E5 runs 校验 artifact hash 后生成的严格 public schema；snapshot ID `public-demo-45426ec720cc`，自身 SHA-256 `bbee33c1d28c4c2f2a0b9af6d4a9cd3a8d1f70fc47df7b30ed412c3b9f195547`。
- Streamlit 已升级为 Ask/Trace/Evaluation 三页工作台，使用 typed client、canonical demo cases、safe view models 和显式按钮网络边界。
- Trace 的真实跨页空输入问题已修复为 `custom request ID > current session request ID`；真实 Fetch 得到 HTTP 200、coverage 100%、2 model calls、0 retries。
- 三张 1440 x 1000 真实 PNG 已生成；390 x 844 验收中 Ask/Trace 均 `clientWidth=390`、`scrollWidth=390`，表格只在组件内部滚动。
- public audit 扫描 328 candidates，0 findings；`.private/e6/` 的 42 题 Q&A、24 张学习卡和 10 条 claims 全被 Git 忽略，claims 状态仍为 `pending_e7`。

最终门禁：

```text
focused UI/snapshot/repository       32 passed, 3 warnings
focused API/security                 31 passed, 3 warnings
full repository                     558 passed, 3 warnings
pip check                            clean
compileall                           exit 0
git diff --check                     exit 0, line-ending notices only
frozen test hash                     exact match
public snapshot evidence             5 source hashes present
active index manifest                exact match; bge-m3 1024D; 64 chunks
public audit                         328 candidates, 0 findings
largest public candidate             86,212 bytes
private Git candidates               0
project Python / ports 8000 / 8501   0 / 0 / 0
Ollama                               1, intentionally kept
git index lock                       false
```

冻结 test hash 仍为 `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338`。Indirect retrieved-content injection 与 optional reranker 仍明确 `NOT RUN`，human semantic review 未完成。不要把这些边界改写成通过。

该首轮门禁已被独立 review 取代，不能再作为当前验收结论。没有授权 commit、push、merge、tag、默认分支修改或进入 E7。

```text
执行E7最终验收
```

## 14. E6 C09 review remediation（已完成）

只读 reviewer 确认 0 Critical、9 Important、2 Minor。经主流程复核，成立的核心缺口是：clean clone 私有材料测试、Ask stale state、Trace cross-request mixing、client request-ID correlation、snapshot semantic invariants、Evaluation status/provenance、audit symlink/binary/schema/PNG/link coverage、claim verdict columns 和 atomic no-replace promotion。

当前正在按 TDD 修复，顺序为：

```text
API correlation + Ask/Trace state + claim rows
-> snapshot invariants + atomic publish + Evaluation data-driven status/provenance
-> clean-clone contract + publication audit hardening
-> desktop/mobile browser rerun + full gates + status rewrite
```

审查前基线为 558 passed、328 public candidates/0 findings，只能用于 before/after；不是最终验收数字。C09 已按 RED/GREEN 修复完成，详细记录见 E6 implementation journal。

## 15. E6 当前精确断点

独立 review 的 9 Important/2 Minor 已逐项验证并修复；没有 blind accept，也没有遗留 Critical。关键 before/after：

```text
API correlation                 2 failed / 7 passed -> 9 passed
Ask/Trace state                 4 failed / 5 passed -> 9 passed
claim verdict                   1 failed / 4 passed -> 5 passed
snapshot semantic/promotion     4 failed / 4 passed -> 8 passed
Evaluation provenance/status    2 failed / 13 passed -> 15 passed
publication audit               adversarial RED -> 8 passed; real 328/0
review remediation focused      47 passed
full repository                 569 passed, 3 FAISS warnings
```

第二轮真实浏览器额外证明：Ask 切换输入清除旧结果；Trace Fetch 另一 request 时只显示 service trace，不混入当前 Agent actions；恢复当前 request 后 Agent/Service ID 一致；Evaluation 的 reranker/indirect status 和 provenance 来自 snapshot。三页移动端仍是 390/390，无整页横向滚动。

最终截图都是真 PNG 1440x1000：

```text
ask.png         d6eae8c3425bf0a8a1d227354e612fd9900c89c2f5c0b53d75b9f35330053c81
trace.png       c465ccc3787928c7ce6c95dfa0bbb7695776784ea43543ed7ba0b70b3267efe2
evaluation.png  f01d507ac0e1072aed732d100776f3dc705b59375b0f35b121fa310dd0300048
```

项目 FastAPI/Streamlit 已停止，8000/8501 listeners 0，项目 Python 0，Ollama 1 保留。branch 仍为 `codex/rag-eval-system`，HEAD 仍为 `7aec4b950e012d3f24b8e1877d6391201e9b8f90`，未授权 commit/push/merge/tag。

必须停止在 E6 本人验收门；indirect retrieved-content injection、optional reranker、human semantic review 仍分别是 NOT RUN/NOT RUN/pending。唯一下一条命令是：

```text
执行E7最终验收
```

## 16. E7 当前精确断点（执行中）

本人已发送精确命令 `执行E7最终验收`，E7 于 `2026-07-17 09:34:29 +08:00` 开始。当前 branch 为 `codex/rag-eval-system`，起始 HEAD 为 `7aec4b950e012d3f24b8e1877d6391201e9b8f90`，remote default 为 `origin/main`，staging area 为空。

详细执行计划：

```text
docs/superpowers/plans/2026-07-17-e7-final-acceptance.md
```

逐 gate 实施日志：

```text
docs/roadmap/e7_final_acceptance_implementation.md
```

当前结果：

```text
G00-G04       PASS
G05           PASS, post-EOL full 574 + pip/compile/frozen hash
G06-G08       PASS
G09           PASS, docs contracts + final staged audit 331/0
G10           NOT RUN, 50-row owner semantic review
G11           NOT RUN, owner code/oral sign-off
G12           PASS, 3 approved + 7 narrowed + 0 pending claims
G13           PENDING commit/push/clean-clone
```

E7 live/browser 已完成并清理：8000/8501 listeners 0、项目 Python 0、Ollama 保留。review findings 均已修复，本地 post-EOL full 为 574、audit 331/0。第一次 GitHub clone 发现 CRLF frozen hash 失配并由 LF contract 修复；第二次 clone 已通过 hash/compile/audit，但 full suite 为 573 pass/1 fail，因为 chunking ablation test 依赖 ignored `data/generated/demo`。测试已改为在 `tmp_path` 从 checked-in facts/profile 真实生成 corpus；必须使用第三个提交/clone 关闭 G13。

当前唯一执行点：完成私有报告外部副本和最终只读 review，重跑全部门禁，审阅 exact public candidate，然后 commit/push `codex/rag-eval-system` 并从 GitHub 新目录 clean clone 复验。没有 remote Actions run URL 时，remote CI 必须保持 `NOT RUN`。不 merge、tag、切换默认分支、改仓库名或公开状态。

# Enterprise Agentic RAG v2 - Current Execution Handoff

## 2026-08-02 FinQA Gate E12 handoff

E12 completed with decision
`E12_MECHANISM_GATE_PASSED_SHADOW_REMAINS_DEFAULT_OFF`. It adds an E8-first
immutable primary decision, same-input E11 observation, complete evidence-chain
verification, aggregate-only privacy telemetry, and a three-failure /
five-observation-cooldown circuit breaker.

The deterministic audit passed 11/11 mechanism gates, 14 focused tests, 408
external-dataset tests, and full `2921 passed / 29 skipped`; public audit was
`1278/0`.
Default-off made zero challenger calls; injected error and timeout remained
isolated; nine circuit observations made only four challenger calls and
recovered through one half-open probe. This is synthetic mechanism evidence,
not production traffic, answer accuracy, or a serving promotion. E8 remains
champion, E11 remains disabled, and frozen test is `UNTOUCHED`. Full state is
in `docs/roadmap/finqa_gate_e12_current_handoff.md`.

## 2026-08-02 FinQA Gate E11 handoff

E11 passed its nested company outer gate and its single authorized internal
validation. Outer Descriptor Recall@4 improved `84.8894% -> 86.0881%`
(`+1.1987pp`) with every fold positive. On 37 typed internal cases / 76 roles,
E8/E11 Descriptor and Candidate Recall were `84.21% / 86.84%`; transitions
were `64 retained / 0 regressed / 2 gained / 10 missed`. Three additional
cases used the same typed-capability fallback in both arms.

The internal ordinal/budget is `1/1` and consumed. Exact McNemar `p=0.5` does
not establish a statistically significant efficacy gain. E8 remains serving
champion, E11 remains disabled, and frozen test is `UNTOUCHED`. E11 is eligible
only for E12 shadow integration and aggregate observability. Full state is in
`docs/roadmap/finqa_gate_e11_current_handoff.md`.

## 2026-08-02 FinQA Gate E10 handoff

E10 completed with decision
`E10_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED`.

It replaced E9's gold-forced train evidence with official retrieval Top-10,
used role-level pairwise hard negatives, and limited the learned model to a
`[-4,+4]` residual around E8. Company-disjoint OOF Descriptor Recall@4 moved
from `84.8894%` to `85.8349%`. All five folds improved and coefficient
stability passed, but `+0.9455pp` missed the frozen `+1.0000pp` gate.

E8 remains champion; E10 serving is disabled. Internal validation is `NOT_RUN`
and unconsumed; frozen test is `UNTOUCHED`. Do not lower the E10 threshold or
rerun E9's consumed 60-case development cohort. The next admissible challenger
requires a new E11 protocol with nested company-grouped CV. Full state is in
`docs/roadmap/finqa_gate_e10_current_handoff.md`.

## 2026-08-02 FinQA Gate E9 handoff

Gate E9 is complete with decision
`E9_DEVELOPMENT_GATE_FAILED_KEEP_E8_CHAMPION`.

```text
metric                               train OOF E8/E9      dev E8/E9
Descriptor Recall@4                    88.76/90.84%       84.55/78.86%
Candidate Recall@8                           n/a          78.86/75.61%
Candidate complete case@8                    n/a          74.14/72.41%
Conditional candidate retention@8            n/a          93.27/95.88%
```

The 23-feature linear challenger passed company-disjoint CV by +2.08pp with
1.24pp fold standard deviation, then failed its single authorized disclosed-
development transfer. Paired descriptor outcomes were 93 retained, 11
regressed, four gained and 15 missed by both. The failure is preserved in
public evidence; E8 remains champion and E9 serving is disabled.

The formal development ordinal/budget is `1/1` and consumed. Internal
validation remains `NOT_RUN`; frozen test remains `UNTOUCHED`. Next work must
use a new E10 train-only protocol with retrieval-realistic evidence, a Top-4
ranking objective and bounded E8 residual. Do not retune E9 and rerun the same
60 cases. Full details are in
`docs/roadmap/finqa_gate_e9_current_handoff.md`.

## 2026-08-02 FinQA Gate E8 handoff

Gate E8 is complete with decision `E8_DEVELOPMENT_PROGRESS_GATE_FAILED`.

```text
metric                                  E7 baseline       E8
descriptor Recall@4                         83.74%       84.55%
descriptor complete case@4                  82.76%       82.76%
candidate Recall@4                          70.73%       66.67%
candidate Recall@8                          78.86%       78.86%
candidate complete case@8                   75.86%       74.14%
conditional candidate retention@8           94.17%       93.27%
Oracle candidate Recall@8                      n/a      100.00%
candidate edge reduction                    77.78%       75.10%
```

Catalog coverage, Oracle capacity and every security/identity invariant
passed. Six runtime quality checks failed. Positive descriptor-priority
bonuses `1/2/4/8` all reduced Candidate Recall@8, so the selected development
configuration uses priority `0` and candidate-local weight `1`. This result is
not answer accuracy, not held-out evaluation, and not an adoption decision.

Internal validation remains `NOT_RUN`, frozen test remains `UNTOUCHED`, and
serving remains `DISABLED`. The next allowed work is a newly frozen E9
train-only, document-grouped learned-ranking protocol. Full details are in
`docs/roadmap/finqa_gate_e8_current_handoff.md`.

## 2026-07-30 FinQA Gate E5 handoff

Gate E5 is complete with decision `CALIBRATION_REJECTED`.

```text
                                      v2.3    direct   roles    roles+demos
strict accuracy                       20.00%    1.67%    0.00%      21.67%
grounded strict                       18.33%    1.67%    0.00%      20.00%
coverage                              73.33%    8.33%    3.33%      73.33%
protocol errors                        16/60    55/60    58/60       16/60
mean / p95 latency                    2.90/4.78 8.49/11.72 17.58/29.58 6.86/12.82 s
```

The dynamic-demo arm improved strict and grounded accuracy by only 1.67
percentage points versus v2.3. It passed latency and v2.3 correct-to-wrong
gates but failed coverage, accuracy-gain, wrong-to-correct, protocol-error,
and B0 shadow gates. No arm was selected. Internal validation remains
`NOT_RUN`, frozen test remains `UNTOUCHED`, and all typed routes remain off.

Execution implementation is `df53f7ba83fb423f9fa361bff1770fe07dee8004`.
The public evidence SHA-256 is
`af46c19b688a8836f7092704c14ef684b35553cbc692d7755f3fe34e30a18271`.

Next admissible work is a newly frozen Gate E6 disclosed-calibration ablation
for deterministic role-to-candidate compatibility filtering/ranking. Do not
add more examples, weaken the v2.3 validator, consume internal validation, or
touch the frozen test before that protocol is frozen and its progress gates
pass.

## 2026-07-30 FinQA Gate E4 handoff

Gate E4 is complete with decision `CALIBRATION_REJECTED`.

```text
                                      B0       v2.2      v2.3
strict accuracy                     51.67%     26.67%    20.00%
grounded strict                     43.33%     25.00%    18.33%
coverage                            98.33%     81.67%    73.33%
protocol errors                       1/60      11/60     16/60
mean / p95 latency                  1.07/1.46  2.19/3.38 2.90/4.78 s
```

The same disclosed 60-case calibration was used. The 40-case internal
validation and frozen test remain untouched. The Gate E3 input count is still
58/60, but v2.3 produced 32 answered-wrong rows and 16 protocol errors. The
measured bottleneck is semantic operation/operand planning, with an additional
single-operation representation limit against 28/60 multi-step gold programs.

Public aggregate evidence:

- `docs/external_datasets/evidence/finqa_v23_paired_calibration_public_v1.json`
- SHA-256 `33ebc048aff192ec5842729366c0e40f054d2391c31afb94ca69ed78d4db12da`
- `scripts.verify_finqa_v23_calibration_public` supports public-only and
  private-bound verification.

Next admissible work is Gate E5 protocol freeze and disclosed-calibration
ablation only: multi-step skeleton, semantic operand roles, then
training-only dynamic structural demonstrations. Do not run internal
validation, frozen test, B2, or resume tuning against hidden cohorts.

## 2026-07-30 FinQA Gate E3 handoff

Gate E3 is complete with decision `INPUT_GATE_PASSED`.

```text
implementation commit                    6655ee8
calibration / internal-validation         60 / 40
v1 / v2 post-shortlist input complete     80.00% / 96.67%
gold-evidence parse complete              100.00%
retrieval-missing recovery                93.75%
p95 units / chars / candidates            27 / 4794 / 71
Guard scans / model calls                 1168 / 0
internal validation                       NOT RUN
typed v2.3 / frozen test                  NOT RUN
```

Do not describe 96.67% as answer accuracy. Gate E2's typed answer result
remains rejected at 26.67% versus B0 at 51.67%. The next allowed step is a
newly frozen v2.3 paired model calibration on the same disclosed 60 cases.
The 40-case internal-validation cohort remains sealed.

Primary records:

```text
docs/external_datasets/finqa_numeric_evidence_gate_e3.md
docs/external_datasets/evidence/finqa_numeric_evidence_calibration_public_v1.json
docs/learning/24_FINQA_GATE_E3_NUMERIC_EVIDENCE.md
```

## 2026-07-30 FinQA Gate E2 handoff

Gate E2 is complete with decision `CALIBRATION_REJECTED`.

```text
protocol commit                         ac8424d
calibration / internal-validation       60 / 40
protocol SHA-256                        12acbfd4e791a527dd33043594975ce1ca6be2eb28e48b79cc1f88b3a7064da4
best route                              v2.2 host-compiled sketch
B0 / v2.2 strict                        51.67% / 26.67%
v2.2 coverage                           81.67%
v2.2 correct-to-wrong / wrong-to-correct 20 / 5
internal validation                     NOT RUN
B2-v2 / Gate F / frozen test            NOT RUN
```

Do not enable the typed route or consume the 40-case internal-validation
cohort. Continue only on the disclosed 60-case calibration cohort, targeting
retrieval/candidate availability, table-level scale/unit propagation,
percentage normalization, and controlled host constants. Primary records:

```text
docs/external_datasets/finqa_typed_contract_calibration_gate_e2.md
docs/external_datasets/evidence/finqa_typed_contract_calibration_public_v1.json
docs/learning/23_FINQA_GATE_E2_TYPED_CONTRACT_CALIBRATION.md
```

最后更新：2026-07-21

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
30. R2-S3 exposure ablation：`docs/security/r2_s3/00_exposure_ablation_protocol.md`、`docs/security/r2_s3/01_results.md`、`docs/security/r2_s3/02_engineering_journal.md`

## 3. Git 与操作边界

```text
workspace: <repo-root>
branch: codex/rag-eval-system
E7 start HEAD: 7aec4b950e012d3f24b8e1877d6391201e9b8f90
upstream: origin/codex/rag-eval-system
current R2-S3 local commit state: COMPLETE
Push is allowed only after fixed-HEAD reviews and local gates pass; actual delivery and CI state are established by Git and GitHub Actions.
merge/tag/default-branch/repository visibility: NOT AUTHORIZED
```

Historical E7 authorization only: the owner previously authorized committing and
pushing the E7 feature branch after its gates. That historical authorization does not establish delivery state for the current R2-S3 exact HEAD. Push is allowed only after fixed-HEAD reviews and local gates pass; actual delivery and CI state are established by Git and GitHub Actions.

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
| E7 | automated/Git/remote-CI acceptance complete; owner-only NOT RUN | rc02 28/28、load 31/31、browser/API、local/clean-clone 574、Ubuntu CI success |

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

## 8. 历史断点（已被 Section 20 取代）

用户已给出 `批准E3，执行E4评估与消融`，E4-C01-C07 现已实现和验证。审计 run root 是 `20260716T135632Z_7aec4b9`。9 个 run manifests 的 artifact hashes 全部匹配；active live index 是 `20260716T135632Z_7aec4b9_live_bge_m3_fixed`，`bge-m3` 1024D、64 fixed chunks。

核心结果：deterministic dev accepted 24/24；frozen deterministic test 28/28；live dev 在修复 Ollama grammar schema 后 23/24。test hash 仍为 `556ffed...43338`，未用于 E4 内调参。50-row human review 的 400 个判断单元格全部为空，等待本人填写。

这是历史 E4 验收记录，不再具有操作授权意义；当前恢复入口仅为 Section 20。

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

该首轮门禁已被独立 review 取代，只保留为历史证据；当前恢复入口仅为 Section 20。

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

## 15. E6 历史断点（已被 Section 20 取代）

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

历史 E6 收口时 FastAPI/Streamlit 已停止，8000/8501 listeners 0，项目 Python 0，Ollama 1 保留。该状态不定义当前 Git 操作边界。

这是已被后续阶段取代的 E6 本人验收记录；indirect retrieved-content injection、optional reranker、human semantic review 在该时点分别是 NOT RUN/NOT RUN/pending。

```text
执行E7最终验收
```

## 16. E7 历史断点（已被 Section 20 取代）

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
G13           PASS, commit/push/clean-clone/remote CI evidenced
```

E7 live/browser 已完成并清理：8000/8501 listeners 0、项目 Python 0、Ollama 保留。review findings 均已修复，本地 full 为 574、audit 331/0。第一次 GitHub clone 暴露 CRLF frozen hash 失配；第二次暴露 ignored demo corpus 依赖；第三次在 `960fa13` 得到 574 passed；第四次在代码候选 `9607e55` 再次得到 hash/compile/audit/full PASS。首次 Ubuntu CI 的 `exit 139` 已由诊断提交定位为 Streamlit AppTest 的 PyArrow-to-Pandas 反向转换，并通过收窄测试边界修复；run 29553278709 为 success。

## 17. R2-S1 历史断点（已被 Section 20 取代）

本人已依次批准 D1-D7。R2-S1 的冻结起点和当前实现断点为：

```text
branch                    codex/rag-eval-system
D1 start/design base HEAD da2ba8ccd4dcce455926758a8e9fb6fad20aec38
D3 committed base HEAD    ec85cc718b3df17731fb1d9df7300a3a7c6fe5be
D7 run entry HEAD         4b7d0b91078a3246cb9e801631c0a47691bf3985
D7 run dirty-state hash   162771457b7e14e2672ec6a49687423d53fa4a74c64ce7c77d883616963d66b4
da2ba8c ancestor          yes
tracked/staged at D0      clean
pre-existing untracked    .superpowers/ browser companion only
```

D0 当时发现 raw `SearchResult/FindResult/OpenResult` 直接进入 `Controller.observe`、pipeline 在 Guard 前裁成 top-k。D2 用 `5 failed / 3 passed` 记录该历史红色基线；D3 实现 standalone Guard；D4 已把默认 V2 路径改成 capped ranked pool -> admission -> guarded execution -> admitted-only state；D5 增加 nonce/JSON prompt envelope、aggregate-only public trace、secure default route profile 和 Guard startup/readiness validation。D5 当时仍把 legacy `/chat` 和 `/agent/chat` 留在显式 compatibility app；R2-S5 最终复核后已从生产模块删除该 factory。

D1 已冻结以下文档：

```text
docs/superpowers/specs/2026-07-17-r2-s1-indirect-prompt-injection-design.md
docs/security/r2_s1/00_scope_and_threat_model.md
docs/security/r2_s1/01_attack_surface_and_trust_boundaries.md
docs/security/r2_s1/02_design_options_and_decisions.md
docs/security/r2_s1/03_detailed_design.md
docs/security/r2_s1/04_evaluation_protocol.md
docs/roadmap/r2_s1_indirect_injection_implementation.md
```

核心冻结结论：default enforce；audit/off 只可依赖注入；per-item error quarantine；全过滤 `security_filtered/evidence_filtered`；candidate_k 内一次 bounded top-up；Controller 运行时拒绝 raw execution；public trace aggregate only；secure profile 不注册 legacy generative routes；dev/test 各 24 attack + 12 benign；R1 files 不修改。

当前精确状态：

```text
D1 design/protocol               FROZEN
D2 red propagation baseline      RECORDED / HISTORICAL 5 FAIL + 3 PASS
D3 standalone Guard              GREEN / 64 TESTS
D4 guarded V2 data flow          GREEN / 8 BOUNDARY PROBES
D5 prompt/public counters        GREEN / FULL 697 TESTS
D6 security datasets/evaluation  PASS / FROZEN OFF 21/24 -> ON 0/24
D6 full regression               GREEN / 788 TESTS
D7 local live paired evaluation  COMPLETED WITH OBSERVATIONS
D7 full regression               GREEN / 812 TESTS
```

D6 accepted run is `r2-s1-d6-test-20260718-01`. Its dataset/fixture hashes are
`062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c` and
`eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d`;
manifest SHA-256 is
`fe45b091f4f76c57919dae987186088433a5f7aa5293f7104de9eb09317f4564`.
The result is visible synthetic propagation evidence, not a Qwen result. Do not
overwrite the run or tune on the frozen test. Detailed recovery context is in
`docs/security/r2_s1/08_d6_engineering_journal.md`.

D7 accepted run is `r2-s1-d7-test-20260718-01`; it was run exactly once after
the frozen hashes above were rechecked. Its manifest SHA-256 is
`5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e`.
The local models were BGE-M3 digest
`7907646426070047a77226ac3e684fbbe8410524f7b4a74d02837e43f2146bab`
and Qwen2.5:3b digest
`357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`.
OFF user-visible attack success was `3/24`; ON was `0/24`; all `15/15`
attack units that actually reached Guard were quarantined; `13/28` attack
units were not scanned because a clean rank-1 already filled `top_k=1`;
benign quarantine was `0/32`; model errors and external egress were zero.
Do not rerun or tune from the frozen test because documentation changed.
Detailed recovery context is in
`docs/security/r2_s1/09_d7_engineering_journal.md`.

当前没有自动授权的下一阶段。若继续安全路线，必须先单独冻结并批准独立 holdout、人工红队或跨模型复现协议。D6 时的历史授权命令是：

```text
批准D6，执行D7本地真实模型成对评测（已执行）
```

自动工程验收已收口。下一步是仓库所有者完成 50-row human review、三个代码实验和口述验收；这些仍是 `NOT RUN`。当前分支不自动 merge、tag、切换默认分支、改仓库名或修改公开状态。

## 18. R2-S1 V0-V5 历史断点（已被 Section 20 取代）

外部审查后的 auditability/measurement hardening 已按 V0-V5 顺序执行，并在提交前完成独立 closeout review。当前 branch 仍为 `codex/rag-eval-system`；V1-V5 及收口修复以 `1bf9b95917d7ae813ca6214c7ab83492b4c47aa3` 为基线。用户已经批准收口、提交和推送当前分支；仍不自动 merge、tag、切换默认分支或修改仓库公开状态，也不执行 `git add .`。

```text
V0 audit verification                  COMPLETE
V1 redacted public evidence            VERIFIED
V2 actual Guard scan provenance        GREEN / 848 historical full tests
V3 exact local Ollama origin boundary  GREEN / 859 historical full tests
V4 raw-follow metric semantics         GREEN / 891 historical full tests
V5 future counterbalanced arm order    GREEN / 913 current full tests
```

V1 在 `data/v2/public/r2_s1_d7/` 发布 8 文件、72 行、15 指标的脱敏独立证据包。V2 删除 category-based reached 推断，改由无原文 `ScannedContentUnit` 事件驱动。V3 将 evaluator HTTP/socket 统一收紧到配置的 exact loopback origin/address/port，但不是 OS sandbox。V4 保留旧 `model_attack_followed` 序列化字段，新增 canonical `raw_canary_or_forbidden_action_follow_v1` 语义并明确 semantic attack following 未测量。

V5 只修改未来 dev/new live protocol：`sha256(case_id)` 后按 hash rank 奇偶分配 OFF→ON/ON→OFF，36-case cohort 精确 18/18。`LivePairedResultV2`、`LiveSecurityRunManifestV2` 和逐 arm `arm_execution` 保存完整可审计顺序；旧 v1 parser/dump 不变。CLI 显式拒绝再次使用正式 run ID `r2-s1-d7-test-20260718-01`。

当前冻结 SHA-256：

```text
dataset          062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
fixture          eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
freeze manifest  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
formal manifest  5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

V0-V5 收口验证：180 targeted cross-module、921 full，只有 3 个已知 FAISS/SWIG warning；compileall/pip/diff clean，公开审计 415 candidates/0 findings，仓库与干净 8-file public verifier 均为 VERIFIED。冻结 dataset、fixture、freeze manifest 和正式 D7 manifest hash 全部 exact。独立审查发现 `0 Critical / 6 Important / 2 Minor`；6 个 Important 已修复并加入回归测试，2 个 Minor 作为准确限制和 R2-S2 安排保留。正式 D7 没有重跑、覆盖或迁移；它仍是 fixed OFF-first observational run。新的真实模型 counterbalanced v2 run、独立 holdout、人工红队、semantic LLM judge、跨模型复现、50-row human review 和 owner 口述验收仍为 `NOT RUN`。

Git 交付：提交 `9fcb3041ae3561057e1b56d881e91aab8aee0dce` 已推送到 `origin/codex/rag-eval-system`，对应 GitHub Actions run `29682474913` 为 `success`。分支仍未 merge、tag、切换为默认分支或部署。

恢复时按顺序读取：

1. `docs/security/r2_s1/10_auditability_verification.md`
2. `docs/security/r2_s1/11_v1_public_evidence_engineering_journal.md`
3. `docs/security/r2_s1/12_v2_scan_provenance_engineering_journal.md`
4. `docs/security/r2_s1/13_v3_exact_ollama_boundary_engineering_journal.md`
5. `docs/security/r2_s1/14_v4_metric_semantics_engineering_journal.md`
6. `docs/security/r2_s1/15_v5_counterbalanced_arm_order_engineering_journal.md`
7. `docs/superpowers/specs/2026-07-19-r2-s1-v5-counterbalanced-arm-order-design.md`
8. `docs/superpowers/plans/2026-07-19-r2-s1-v5-counterbalanced-arm-order.md`
9. `docs/security/r2_s1/16_v0_v5_closeout_review_and_improvement_plan.md`

## 19. R2-S2 S2-1/S2-2 历史断点（已被 Section 20 取代）

S2-1 已使用新 run ID `r2-s2-s1-dev-20260719-01` 执行真实 BGE-M3 + Qwen2.5:3b 的 dev paired replication。运行入口是 clean Git HEAD `073d7356026954c26c1429fb9faddc5e9a5dcb87`，manifest SHA-256 为 `3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e`。原始运行目录在 ignored `security_runs/`，不可提交。

```text
cases / arm events                       36 / 72
OFF->ON / ON->OFF                        18 / 18
OFF user-boundary attack success          3 / 24
ON user-boundary attack success           0 / 24
OFF model-context exposure                7 / 24
ON model-context exposure                 0 / 24
ON reached-unit quarantine               15 / 15
ON all-labeled quarantine                15 / 28
unreached attack units                    13 / 28
clean utility OFF / ON                   12/12 / 12/12
benign quarantine ON                      0 / 32
model/system errors                       0
blocked external egress                   0
diagnostic gate                           FALSE
status                                    COMPLETED WITH OBSERVATIONS
```

`15/15` 与 `15/28` 不矛盾。前者回答“Guard 看见攻击后是否隔离”；后者回答“所有已标注攻击单元中有多少最终被隔离”。13 个单元没有进入 Guard，属于 retrieval/tool exposure coverage，不是 detector false negative。不得修改冻结 gate 把 false 改成 pass。

真实 run-01 还发现旧 `failures.csv` 不能区分 `unreached` 和 `admitted`。旧文件保持不可变；未来 v2 writer 已改为根据 live observation 发出 `attack_unit_unreached` 或 `attack_unit_missed_by_guard`。`scripts/verify_indirect_injection_live_run.py` 可离线复算私有 artifacts，并按 arm position 展示 attack composition、exposure、quarantine、error、egress 与 latency。position 1/2 的 attack composition 是 13/11，因此位置分层只能描述，不能当因果实验。

S2-2 已实现独立 holdout 的 DRAFT→FROZEN 基础设施：

```text
strict catalog/payload/rubric contracts       IMPLEMENTED
36/24/12 + family/surface/language admission  IMPLEMENTED
Git/code baseline binding                     IMPLEMENTED
immutable canonical freeze manifest           IMPLEMENTED
offline verifier and tamper rejection         IMPLEMENTED
holdout_submissions Git/public leak guard      IMPLEMENTED
independent reviewer raw package               NOT CREATED
one-shot holdout model evaluation              NOT RUN
blind double review / semantic judge           NOT RUN
S2-2 stage-entry full regression                954 PASSED / 3 KNOWN WARNINGS
S2-2 stage-entry public audit                   426 CANDIDATES / 0 FINDINGS
compileall / pip check                         CLEAN / CLEAN
```

恢复时先读取：

1. `docs/security/r2_s2/00_holdout_freeze_protocol.md`
2. `docs/security/r2_s2/01_s2_1_live_dev_results.md`
3. `docs/security/r2_s2/02_engineering_journal.md`
4. `docs/superpowers/specs/2026-07-19-r2-s2-holdout-freeze-design.md`
5. `docs/superpowers/plans/2026-07-19-r2-s2-holdout-freeze.md`

下一执行点不是由当前开发者生成攻击数据。独立 reviewer 应在 `holdout_submissions/<submission-id>/` 创建三个原始文件并按 protocol freeze；另一 reviewer 验证 manifest 后，才批准一次性 holdout adapter 与模型运行。检索覆盖改进只能在新的 dev-only 实验中完成，不能查看 holdout 后追分。

## 20. R2-S3 measurement-only exposure ablation 当前精确断点

R2-S3 已完成 Task 1-8 的本地实现、独立 review hardening、accepted
artifact publication、文档同步和 fresh local gates。当前边界为：
Push is allowed only after fixed-HEAD reviews and local gates pass; actual delivery and CI state are established by Git and GitHub Actions.
controller 仅可对获批 SHA 执行 push 并验证 remote CI。

```text
source live run                              r2-s2-s1-dev-20260719-01
source live run state                        UNCHANGED
source manifest SHA-256                      3fe51ea7e404d7d1c09711b14f422b92b2474df7148e4f15df1e949081f5586e
source live evaluator path                   app/evaluation/indirect_injection_live_runner.py
source live evaluator SHA-256                a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958
accepted exposure run                        r2-s3-dev-exposure-20260721-04
private manifest schema                      indirect_injection_exposure_run_manifest_v2
private exposure manifest SHA-256            4c8cfb6ad826fc1ca9c24afb0157129df661f3cd463aa3448ec161c0608c5f1f
accepted exposure evaluator path             app/evaluation/indirect_injection_exposure.py
accepted exposure evaluator SHA-256          d7fe9332953cc44ba3f517bb03d4074b293b821461240d30fc384d67256a4b88
public manifest schema                       indirect_injection_exposure_public_manifest_v2
public redacted manifest SHA-256             09fda4aa81d15757e8de7cadec32e057a1c01d23a5b646dbcd5c0f9ae9038033
packaged public verifier SHA-256             dbe814605220058c0bf2453ee1cac0450253bd788b64f9979ab1eb77c2413897
production Guard / retrieval / Agent         UNCHANGED
live/replay Guard reach                      15/28 / 15/28
quarantine given live reach                  15/15
rank-2 unreached units/cases                 13 / 13
observed downstream exposure                 0/13
counterfactual search d1/d2/d4               6/26 / 22/26 / 26/26
counterfactual total d1/d2/d4                15/28 / 28/28 / 28/28
additional scans d1/d2/d4                    0 / 29 / 33
additional input chars d1/d2/d4              0 / 3845 / 4200
decision                                      NO_CURRENT_BYPASS_OBSERVED
production change admission                   NOT ADMITTED
independent holdout                           NOT RUN
semantic judge / cross-model replication      NOT RUN
final focused pytest                          457 PASSED / 10 SKIPPED / 3 KNOWN WARNINGS
final full pytest                             1395 PASSED / 13 SKIPPED / 3 KNOWN WARNINGS
skip qualification                            platform-dependent symlink/junction variants unavailable on this host
compile / pip                                 CLEAN / CLEAN
public audit                                  454 CANDIDATES / 0 FINDINGS
source / private / public verifier            VERIFIED
isolated eight-file verifier                  VERIFIED / 28 ROWS
frozen/source/package hash comparison         EXACT
push / remote CI                              ESTABLISHED BY GIT AND GITHUB ACTIONS
```

Replay-critical dependency byte bindings carried by both v2 manifests:

```text
app/security/retrieved_content.py                    78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2
app/security/retrieved_admission.py                  1f835ba3aa79b1450e8ae906946bba019c21b531fce114cd375b094411c88afb
app/evaluation/indirect_injection_runner.py          c2c5c5e1815d8a77beebb5027384ea58dd3e73b8536533c8d7898d40668ed36c
app/evaluation/indirect_injection_live_runner.py     a5eec5619a5ac9f44357fc6063232dca6021538ca5988aab6ae2f962d9b85958
```

`r2-s3-dev-exposure-20260721-01` and `r2-s3-dev-exposure-20260721-02` are
superseded local history. Their ignored bytes remain unchanged and verifiable,
but the tracked package derives only from accepted v2 run
`r2-s3-dev-exposure-20260721-04`. The superseded immutable `-03` summary and
per-unit files are byte-identical to the accepted `-04` files.

Decision semantics: `NO_CURRENT_BYPASS_OBSERVED` is a narrow frozen-dev
observation. Counterfactual depth coverage is diagnostic and was not executed by
the production Agent. This state is not a release pass or universal
prompt-injection safety result.

Task 8 local hash comparison must recompute these historical frozen values,
without modifying their files:

```text
test dataset     062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
test fixture     eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
freeze manifest  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
formal D7 run    5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

Resume order:

1. Verify the final fix-wave commit contains only its explicit files.
2. Run whole-branch synthesis for the fixed exact HEAD. Push is allowed only after fixed-HEAD reviews and local gates pass; actual delivery and CI state are established by Git and GitHub Actions.
3. The controller may push and verify remote CI only for the approved SHA.
4. Keep independent holdout authoring and owner-only review outside automated
   implementation scope.

## 21. R2-S4 Task 8 current handoff

This section is the current handoff and supersedes the R2-S4 pre-run snapshot.
Section 20 remains historical R2-S3 measurement-only exposure context.

```text
run code HEAD                                109e8b52d8d31ae3562420351451a69915652be3
run tree                                     6b54e1f3c94b031a9438d21fd6e88a8c6d78faa8
plan SHA-256                                 85175b88742d28b09431e1b1df35a27db5cd65fbd96fc33db0bcfd899efd4152
controller wall time                         270.2s
baseline model digest                        357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b
baseline component manifest                  9271ec53e0b69d827e7a624e3666e6e53a5a9e7738450542a89e5903de768f44
replication model digest                     500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41
replication component manifest               0495450e5134acadc564fe1ddd805f096ad939c27f2568c80caa49b366e7ed01
matrix manifest                              ec7b2fb6b8802b32d50933fc34b574d55c370dd88dbee4a88239d37ac51ff0b5
public manifest                              0978131eaf1c0059a598648f3f67ea07b5144a110467728ada852bdbbfe61813
packaged verify.py                           9fe95165252e73355b54e2b802596e5cb00e71cf8190e4afe865011e83c7ed9b
decision                                     CONSISTENT_OBSERVATION
reason                                       complete_equal_security_and_utility_observations
component deterministic threshold diagnostic false (15/28, expected 28/28)
cross-model non-release diagnostic            passed=true / release_pass=false
```

Metrics on the same visible synthetic dev cohort:

```text
OFF attack 3/24; ON attack 0/24
OFF context exposure 7/24; ON context exposure 0/24
ON conditional quarantine 15/15; all-labeled quarantine 15/28
13 labeled attack units did not reach Guard
ON benign quarantine 0/32
clean 12/12; mixed 20/20; poison-only 4/4
model calls 68 each
model errors / blocked egress 0 / 0
baseline p50/p95 1208.1238/1379.7665ms
replication p50/p95 1838.3202/2025.2085ms
latency delta +630.1964/+645.442ms
```

Verifier evidence:

```text
component verifiers                           VERIFIED
private matrix verifier                      VERIFIED
repository public verifier                   VERIFIED
out-of-repository python -I packaged verifier VERIFIED
public package files                          8
focused gate                                  367 passed / 4 skipped
full gate                                     1644 passed / 16 skipped
known warnings                                3 SWIG warnings
compile / pip                                 CLEAN / CLEAN
exact-run pre-gate audit                     473 candidates / 0 findings
Task8 docs wave audit                        483/0; final delivery evidence is established by exact-HEAD gates, Git, and GitHub Actions
historical verifiers                          PASSED
pre-run exact-HEAD review                    0 Critical / 0 Important / 0 Minor
```

exact-run pre-gate audit 473 candidates / 0 findings.
Task8 docs wave audit 483/0. Final delivery evidence is established by
exact-HEAD gates, Git, and GitHub Actions rather than by rerunning or
overwriting the immutable model evidence.

`CONSISTENT_OBSERVATION` is not a release pass and not cross-model generalization.
It only says the two frozen model identities produced 12 decision safety/utility observations matched on the same visible synthetic dev cohort;
3 operational counts matched; 2 latency metrics differed and do not affect the
decision.

Still `NOT RUN`:

```text
independent holdout         NOT RUN
semantic judge calibration NOT RUN
human double review        NOT RUN
production traffic         NOT RUN
real IdP                   NOT RUN
deployment                 NOT RUN
```

Only admitted next implementation: R2-S5 Trusted Identity Boundary. Rank 2:
reproducible minimal Linux deploy/rollback. Rank 3: durable privacy-bounded
telemetry. These are queued in order and are not parallel approvals.

## 22. R2-S5 current handoff

This section supersedes the “only admitted next implementation” line above.
R2-S5 Trusted Identity Boundary is implemented. Its pre-third-review local
whole-tree gate was invalidated by a `HOLD` review; all recorded Important
findings have since been repaired and the local gate has been regenerated.

Implemented data flow:

```text
Bearer JWT
-> strict RS256 + pinned managed JWKS
-> server Principal
-> service-role authorization
-> role-stripped Agent UserContext
-> existing tenant/region/group ACL
```

Additional industrial boundaries:

- authentication precedes request-body parsing and denied work has zero
  Agent/feedback side effects;
- metrics and trace require the exact operator role;
- feedback requires a server HMAC receipt over actor, target request, and keyed
  question/answer digests, then atomically upserts one latest
  actor/target/content row;
- plaintext feedback migration keeps a durable erasure marker until VACUUM and
  WAL checkpoint both complete;
- managed local identity uses manifest commit, semantic journal recovery,
  stage/restart/activate/overlap/retire rotation, owner/mode/DACL/hardlink
  checks, POSIX root-identity binding, and write-through publication;
- Streamlit and API credentials are loopback-only and split across
  public/persona/operator cookie-rejecting sessions;
- readiness initialization is separated from request-time snapshot reads, and
  model readiness performs finite dimension-matched embed plus production
  `/api/chat` probes under one background deadline.

Pre-third-review historical evidence, not a current release gate:

```text
historical full pytest          1835 passed / 20 skipped / 3 known warnings
frozen identity matrix          20/20; 14 denials; 0 denied effects/leaks
matrix definition SHA-256       fe5fdddd9cd4d067930b971ca0658a22deb63778723c31597df7f7fab70b4e2f
fresh/public result SHA-256      94125e66d1ac4b2c32562d623b6351a10cfa021ecd7d760dbc4eb89a3a0b1e66
public repository audit         515 candidates / 0 findings
ephemeral verifier benchmark    1000 iterations; p95 0.0957 ms
```

Third review found `0 Critical / 10 Important / 4 Minor` and set `HOLD`.
Important fixes now include removal of the compatibility app, public-by-
exception authentication, a 128 KiB authenticated body cap, background
dimension-matched embed/chat readiness, strict SQLite helpful migration,
broader public audit rules, one current API contract, Ubuntu/Windows CI, and
manifest-v3 enforced key overlap with exact-confirmation emergency audit.
Latest focused evidence includes new framing/audit RED-GREEN `14`, broader
boundary/audit/redaction `127`, lifecycle/CLI `40/2`, benchmark contract `4`,
public audit `515/0`, source-bound matrix `20/20`, and verifier p95
`0.0904 ms`. The current matrix artifact SHA-256 is
`0258f8c28c363c785751ef64330db5444f75e6169b5b263430dee7049b790829`.
The repaired whole tree passes
`1918 / 22 skipped / 3 known warnings`.

The benchmark is verifier-only. The identity source is local synthetic
RSA/JWKS, not real OIDC/SSO/IAM. Final independent security and engineering
reviews before CI both reported `0 Critical / 0 Important / RELEASE`. Exact-SHA run #17 on
commit `d753df3` failed on one shared assertion-contract issue, a Windows DOS
8.3 path-alias false rejection, and a Windows repository-venv assumption. The
post-CI review then found path-object and permission-side-effect TOCTOU gaps.
The final handle/descriptor-bound repair passes the affected
`151 / 4 skipped` group locally and its scoped re-review reports `0/0/0
RELEASE`. Repair commit `11892531451750609f44138b7348f16b9b1316ff`
then passed exact-SHA Actions #18 on both platforms: Ubuntu
`1918 / 22 skipped / 4 warnings`, Windows `1935 / 5 skipped / 4 warnings`,
and public audit `515/0` on both. The run is
https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30021508046.
No model run or immutable R2-S1/S2/S3/S4 artifact was rerun or overwritten for
this stage. This accepts the local reproducible identity contract, not a real
IdP or production deployment.

## 23. R2-S6 versioned corpus expansion handoff

This section supersedes the earlier statement that deployment was the immediate
next implementation. The owner redirected the active task to knowledge-base
content and scale. R2-S6 is implemented, locally accepted, pushed, and accepted
by exact-SHA Ubuntu/Windows CI.

Current versioned corpus contract:

```text
historical profiles    demo 72 / benchmark 600 -> enterprise_facts_v1
current profiles       expanded 240 / expanded_benchmark 2000 -> enterprise_facts_v2
facts breadth          20 policies / 40 versions / 104 facts / 52 active
organization breadth   12 departments / 15 users / 15 ACL groups
evaluation             48 dev / 56 frozen test / 6 task types
default profile        expanded
```

New source and control points:

- `data/v2/facts/company_facts_v2.json`
- `data/v2/config/expanded.json`
- `data/v2/config/expanded_benchmark.json`
- `app/corpus/catalog.py`
- `app/corpus/quality.py`
- `scripts/eval_corpus_quality.py`
- `tests/corpus/test_expanded_corpus.py`
- `data/v2/public/corpus_expansion_v2/`
- `docs/corpus/v2_expansion/`

The generator guarantees every active fact appears in supporting content and
each policy has at least three supporting source types. The quality CLI checks
20 deterministic release properties, including operational ACL-group use and
100% active-fact eval coverage, and now runs in CI before full pytest.
Historical v1 generated bytes remain regression-tested.

Local runtime evidence:

```text
active run                20260724T024653Z_expanded_bge_m3_fixed
index manifest SHA-256    69b9fb7d3008467f65fb2920a621e9812cdb59c4919834819333e0e33b866507
expanded index            240 source / 216 canonical / 216 chunks
expanded benchmark dryrun 2000 source / 1225 canonical / 1225 chunks
live dev                  48/48; hit@1 1.0; recall@3 1.0; ACL leakage 0
frozen test               56/56; hit@1 1.0; recall@3 1.0; ACL leakage 0
rollback run              20260716T135632Z_7aec4b9_live_bge_m3_fixed
local full pytest         1942 passed / 22 skipped / 3 warnings
public audit              534 candidates / 0 findings
remote CI run             30065782695 / Ubuntu success / Windows success
```

The 2,000-document profile was not embedded because it has the same fact
breadth as `expanded`; it is a parser/dedup/index scale profile. Do not claim
the live results are real-enterprise or independent-domain accuracy.

Implementation baseline commit
`184913e5e504b150d3959ae541cc808544ac379e` freezes the reviewed generator,
facts, profiles, gates, tests, and preliminary evidence. The follow-up
evidence commit adds an exact manifest binding that commit to facts/profile
canonical hashes, corpus/index manifests, frozen dataset hashes, and live
summary hashes. The original run manifests recorded dirty head `e657beaf`;
the baseline is explicitly a post-run reviewed snapshot, not rewritten run
provenance.

Evidence commit `6c419b13ce5751943403a7e2c031de1d3acbc08e` passed GitHub Actions
run #20 on Ubuntu job `89393769125` and Windows job `89393769131`:
https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30064875678.
The public API exposed exact conclusions but not job logs, so this handoff does
not invent platform-specific pytest counts.

The subsequent docs-only commit `1ce0e82` exposed a real Windows-specific
snapshot-read weakness: Ubuntu passed, while Windows failed the deterministic
suite in run `30065121633`. The failure annotation was also truncated because
CRLF carriage returns survived the workflow's newline normalization.

A deterministic RED test then simulated stale metadata plus a same-size byte
rewrite and failed all three dataset/fixture/freeze-manifest variants. Commit
`9bdc14ea07599b96c3b3e53dccf73df24dded73d` fixes the frozen-bundle loader by
confirming content with a second read after metadata validation and strips
carriage returns from CI failure annotations. Local evaluation passed
`979/16/3`; the full tree passed `1942/22/3`. Exact-SHA run #22 passed Ubuntu
job `89396343564` and Windows job `89396343566`:
https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30065782695.

Before any next implementation:

1. run corpus/index/full regression and public audit;
2. perform fixed-HEAD review;
3. commit and push;
4. verify exact-SHA Ubuntu and Windows CI;
5. record the remote run in this handoff and the engineering journal.

After R2-S6 delivery, the ordered industrial next candidate returns to minimal
reproducible Linux deploy/rollback unless the owner redirects it. Human
semantic review and approved real-document structure sampling remain separate
evidence gaps.

## 23. R2-S7 lifecycle closeout

R2-S7 G0-G10 is complete and pushed. The accepted source commit is
`71e26d667d49a5573546e703e7a9fbb78803906d`; closeout commit is
`f081ccbb284feba6af30f38024e87d1c7b273a9d`.

Final-source paired evidence `EXP-LC-010/011/012` used 10 counterbalanced
pairs: correctness was equivalent in 10/10, incremental intervention was faster
in 10/10, p50 elapsed ratio was about 0.70768, and embedding-call ratio was
about 0.02547. Full regression was `2359 passed / 30 skipped`; public audit was
`720/0`. Exact contracts and non-claims are in `docs/lifecycle/`.

## 24. R2-S8 current handoff

R2-S8 G0-G4 tooling is complete. Current code and records:

```text
app/evaluation/quality_review.py
app/evaluation/quality_judge.py
scripts/build_quality_review_packet.py
scripts/submit_quality_review.py
scripts/aggregate_quality_reviews.py
scripts/calibrate_quality_judge.py
data/v2/quality_review/r2-s8-calibration-v4/
docs/quality/
```

The tracked packet contains 12 stratified dev cases and verifies as
`public_synthetic / not_independent / NOT_RUN`. The current evaluation
regression is `999 passed / 16 skipped`; full repository regression is
`2381 passed / 29 skipped`; public audit is `892/0`.

G5 is ready but not executable by Codex alone: two actual independent people
must complete the packet. Do not manufacture reviewer identities, use an LLM
as human gold, inspect the other reviewer's labels, or claim quality from the
blank packet. Resume from `docs/quality/CODEX_HANDOFF.json` and
`docs/quality/05_REVIEWER_RUNBOOK.md`.

## 25. FinQA typed-program and multi-program current handoff

Gate A, Gate B, Gate C, and Gate D are implemented on
`codex/rag-eval-system`. Gate A commit is `904c129`; Gate B commit is
`b63c87e`; Gate C commit is `a783c18`. Gate D is the commit containing this
updated handoff record.

```text
Gate A  protocol + 12 RED contracts
Gate B  deterministic NumericCandidate extraction + public manifest
Gate C  reference-only Typed Planner + compatibility validator + Decimal compiler
Gate D  2-4 typed candidates + deterministic runtime-only selector
```

The historical `LocalFinQAProgramAnswerer` remains unchanged. New code is in:

```text
app/external_datasets/finqa_typed_program.py
app/external_datasets/finqa_typed_planner.py
app/external_datasets/finqa_multi_program.py
tests/external_datasets/test_finqa_typed_program.py
tests/external_datasets/test_finqa_typed_planner.py
tests/external_datasets/test_finqa_multi_program.py
```

All original Gate A RED cases are green. Gate C also covers literal/schema,
candidate-ID/provenance/value reconstruction, admission, role, temporal,
metric, unit, scale, sign, direction, step-reference, zero, budget,
differential Decimal, immutable result, fake-model retry, structured-table
integration, and valid multi-step metadata propagation contracts.

Gate C verification is `43` focused tests, `162` external-dataset tests,
`2674 passed / 30 skipped / 0 xfailed` for the full repository, and public
audit `1006/0`.

Gate D independently compiles every generated program through Gate C, excludes
exact and same-closure vote stuffing, ignores strict provenance supersets for
support, groups canonical Decimal outputs, ranks by support then complexity,
and fails closed on equal-rank conflicting outputs. Its verification is `16`
focused tests, `178` external-dataset tests, and `2690 passed / 30 skipped` for
the D-drive full repository run; the public audit is `1008/0`.

No real model or dataset outcome was run in Gate B-D. Gate E has now completed
the separately labelled `RETROSPECTIVE_DEVELOPMENT_ONLY` real-model dev
comparison. Its frozen execution commit is `9180b7e`; B0/B1/B2 strict accuracy
was `57%/5%/6%` and coverage was `99%/9%/11%`. B1/B2 introduced `54/52`
correct-to-wrong regressions, prevented `0/21` historical operand-selection
failures, and cost `12.18x/14.58x` B0 mean latency.

Decision: `COMPLETE_REJECTED`. Do not claim a typed-program accuracy
improvement, do not enable either typed arm, and do not spend a new Gate F
holdout on the current contract. The next allowed stage is disclosed-dev
Gate E2 contract calibration, beginning with intent coverage and
candidate/operation compatibility. Exact results, measurement errata, public
evidence, verifier, and the learning explanation are in:

```text
docs/external_datasets/finqa_typed_retrospective_gate_e.md
docs/external_datasets/evidence/finqa_typed_retrospective_dev_v1_public_v2.json
docs/learning/22_FINQA_GATE_E_真实模型评测与失败复盘.md
```

## 26. FinQA Gate E13 process-isolated replay handoff

E13 is implemented and its local operational evidence is frozen. E8 remains
the serving-disabled champion and E11 remains a default-off shadow challenger.

```text
protocol SHA-256                    4604572c065d69d8d79f7287cfb206143c01e1ea11c4a6ec85c0bea4ee845f97
public evidence SHA-256             b933f83dff1307828309222c276ea0a5d70372324cdd7822c79dd41b463106d3
official train selected/prepared    128 / 117
worker completed/attempted           117 / 117
worker errors/timeouts/restarts      0 / 0 / 0
observation p50/p95                  5.659 / 16.443 ms
maximum worker peak RSS              91,136,000 bytes
fault injection                      5/5 passed
all operational gates                16/16 passed
focused E13 tests                    16 passed
external-dataset regression          424 passed
full repository regression           2937 passed / 29 skipped / 3 warnings
public repository audit              1291 candidates / 0 findings
model calls                          0
internal cohort                      CONSUMED_NOT_ACCESSED
frozen test                          UNTOUCHED
production traffic                   NOT RUN
```

The replay projects answer/gold-evidence quality fields out before typed
validation and uses only retrieved, Guard-admitted candidates for source-bound
constants. It still uses gold program structure, so this is not planner or
answer quality evidence. `MATCH/DIVERGED` must not be described as accuracy.

The E13 public evidence binds four implementation files. Do not edit them or
overwrite v1 evidence; use a versioned protocol/evidence chain for any worker
pool, queue, backpressure, durable telemetry or resource-control change. Full
details and future admission criteria are in
`docs/roadmap/finqa_gate_e13_current_handoff.md`.

Delivery note: exact commit `09aabf5` was pushed, but Actions run
`30734063847` failed only because three test setups unconditionally opened the
ignored private FinQA train split on clean runners. A follow-up test-only
repair separates public protocol/gate tests from two private-train integration
tests. Exact repair commit `1ff1707` passed Actions run `30734383716` in 9m58s:
the Ubuntu/Windows matrix completed 2/2, the Linux container contract passed,
and one artifact was published. E13 delivery is complete; E11 remains
default-off and E8 remains champion.

## 27. FinQA Gate E14 bounded worker-pool replay handoff

Decision: `E14_BOUNDED_POOL_REPLAY_PASSED_SHADOW_REMAINS_DEFAULT_OFF`.

E14 adds two eager E13 spawn workers, one fixed dispatcher per worker, a
four-slot FIFO queue, bounded admission, response deadline, late-result
discard, aggregate metrics, and deterministic shutdown. The E13 implementation
files were not modified because their hashes are bound by E13 public evidence.

The fixed train replay prepared 117/128 requests and admitted/completed all
117. Backpressure/deadline/errors/restarts were 0/0/0/0. Active-worker
high-water was 2/2, queue high-water was 2/4, queue-wait p95 was 13.354 ms,
Pool end-to-end p95 was 26.439 ms, and the timed observation phase reported
243.251 requests/s. Seven fault probes and all 21 gate checks passed. Full
regression is 2949 passed / 29 skipped; public evidence SHA is
`98371c664d10bfafe21e57fd5a3104a12427fd9b91b1096b2a8285ec7af5008f`.

The implementation fixed an admission/shutdown race by holding the state lock
across the RUNNING check and queue insertion. Closed Pools reject new work and
leave no dispatcher or child PID. E8 remains champion, E11 remains
`SHADOW_DEFAULT_OFF`, the consumed internal cohort was not accessed, and the
frozen test remains untouched.

Next gate should measure a capacity envelope, not add another serving feature:
compare one, two, and four workers under fixed prepared requests and repeated
caller-concurrency levels. Current E14 throughput is not a scaling or
production-capacity claim. See
`docs/roadmap/finqa_gate_e14_current_handoff.md` for the exact boundary.

Delivery note: exact implementation commit `3e5ebb8` passed GitHub Actions run
`30736504721` in 9m41s. The Ubuntu/Windows matrix completed 2/2, the dependent
Linux container contract passed in 4m04s, and one artifact was published.

## 28. FinQA Gate E15 local capacity envelope handoff

Decision: `E15_LOCAL_CAPACITY_ENVELOPE_SUPPORTED_SHADOW_REMAINS_DEFAULT_OFF`.

E15 reuses the exact E13 selection and immutable E14 runtime through a new
protocol bound to E14 protocol/evidence hashes. It prepares the same 117
requests once, then executes 1/2/4 Workers by 1/4/8 callers with three
counterbalanced repetitions. Every trial owns a fresh Pool; setup is excluded
from observation elapsed time and every shutdown verifies zero residual
dispatcher/PID state.

All 3,159 observations completed with zero backpressure, deadline, Worker
error, restart or residual process. The pre-registered 1-to-2 comparison at
four callers measured 2.075x speedup and the 1-to-4 comparison at eight callers
measured 3.441x. Four Workers/four callers was the deterministic local
recommendation at median 631.169 observations/s; eight callers was slower at
553.185, demonstrating a local saturation effect. Maximum trial p95 was 69.598
ms and maximum four-worker child RSS upper bound was 361,205,760 bytes. All 22
gates and 10 focused tests passed.

Local closeout also passed 446 external-dataset tests and the full repository
at 2959 passed / 29 skipped / 3 known warnings. Compileall, dependency
consistency, the frozen evaluation hash, quality-review packet verification,
expanded corpus quality, whitespace checks and public audit all passed; the
public audit result was 1315 candidates / 0 findings.

Protocol SHA is
`f201ecd767299a249fb3702489c395341f7c02a4500026d5aa419c6109ec1285`;
public evidence SHA is
`5e299683c2fd6fa0ad520fc2264ccc06b68dfe214e0c16b34b065f28e9bfc82f`.
The three E15 implementation files listed in the dedicated handoff are now
immutable under that evidence.

This is one-host, short-run, setup-excluded post-primary Shadow capacity
evidence. It is not answer quality, complete RAG QPS, production capacity,
cold-start latency or an SLO. E8 remains champion, E11 remains default-off,
internal remains consumed/unaccessed and frozen test remains untouched.

After exact-commit CI passes, the next admissible gate is E16 service dark
integration with default-off bounded sampling, independent latency budgets,
aggregate service telemetry, lifecycle ownership and rollback.

Delivery note: exact implementation commit `bd35fa1e62ab5c30a87414c6b5e4fd12a0362b23`
passed GitHub Actions run `30740853135` in 10m24s. Ubuntu and Windows completed
2/2, the dependent Linux container contract passed in 4m05s, and one SBOM
artifact was published.

## 29. FinQA Gate E16 service dark integration handoff

Decision: `E16_MECHANISM_GATE_PASSED_DARK_OBSERVATION_REMAINS_DEFAULT_OFF`.

E16 adds an explicit dark-observation resource to `ServiceContainer`, starts
and closes it with FastAPI lifespan, offers only after the primary answer and
feedback receipt are fully constructed, and exposes aggregate-only operator
metrics. Secure defaults are OFF with zero sampling. The local-test path uses
process-keyed request-ID sampling, two daemon workers, a four-slot nonblocking
queue, a 100 ms admission-time deadline and a two-second shutdown grace.

The protocol/public SHA pair is
`56ea7b40e7ec045e30fdedc30d3188475bd181e9321bacbc4e357fe0202037c0` /
`1c997f2431f64b4d3fd158eb7bdf3e90ee4865c920f301612b6b8b1ec9f579f0`.
The 24-pair API audit completed 24 observations, called the OFF provider zero
times, observed zero response/receipt mismatches and zero controlled residual
workers, and passed all 17 frozen gates. Offer p50/p95/max was
0.017/0.024/0.033 ms. Public audit was 1324/0.

This is not an E11 deployment. Enterprise chat lacks E11's typed skeleton,
safe descriptor catalog and bound E8 primary selection. The normal container
therefore has no provider and remains OFF. Resume at the dedicated E16 handoff,
then design E17 eligibility/adapter protocol before editing any E16 hash-bound
implementation file.

Local closeout passed 28 E16 focused, 177 API/runtime, 245 security and 446
external-dataset tests. Full repository result is 2977 passed / 29 skipped /
3 known warnings; public audit is 1328/0. The first full run correctly detected
stale source hashes in historical identity evidence after E16 modified the
service boundary. Historical v2 remains untouched; current v3 contract
`trusted-identity-contract-e21503b0947a5608` passed 20/20 and is stored as
`docs/security/r2_s5/evidence/identity_matrix_result_e16.json`.

Exact implementation commit `2143ba7f9d0c868926192b064b6a72e95839b3ca`
passed GitHub Actions run `30751922977` in 10m06s. Ubuntu/Windows completed
2/2, the Linux container contract passed in 4m03s, readiness/rollback drills
passed and one SBOM artifact was published.

## 30. FinQA Gate E17 typed eligibility and adapter handoff

Decision: `E17_TYPED_ADAPTER_MECHANISM_PASSED_NOT_SERVICE_ENABLED`.

E17 freezes an online-only provenance boundary and implements the missing
typed adapter between E16 and the E8/E11 isolated comparison. A valid context
contains the exact question, `SemanticProgramSkeletonV2`,
`RetrievableSafeDescriptorCatalogV3`, online-only origin enums and a canonical
SHA-256. Gold/oracle program and quality fields are prohibited. The adapter
does not accept an external primary; it computes E8 v5 on the same context,
then calls the verified E11 worker.

The new ephemeral resolver is capacity bounded, TTL bounded, consume-once and
rejects duplicate request IDs without overwrite. Five ineligible reasons made
zero Worker calls. Fault injection proved question-binding, deadline, resolver
and Worker failures reduce to fixed codes. E16 background composition completed
`ADMITTED -> MATCH`; two real `spawn` Worker calls completed and the process
closed with exit code zero. All 24 frozen gates, 23 focused tests and 52 related
regressions passed; public audit was 1339/0.

Full repository closeout passed 3000 tests / 29 skipped / 3 known warnings.
Dependency consistency, compileall, frozen evaluation hash, quality-review
packet and expanded-corpus quality all passed.

Protocol/public SHA pair:
`d8e3433a2449ff7649b535eba416ced3a2a378b1871a640b2ad0a71508c0ea4d` /
`3ad830e8ad4bad7b14e6979906e20f06f1e1487defdb48f979edee009915b4af`.

This is not an online planner, enterprise evidence adapter, service enablement,
quality result or SLO. Internal remains consumed/unaccessed and frozen test is
untouched. Resume at `docs/roadmap/finqa_gate_e17_current_handoff.md`. E18 must
use new versioned files to carry ACL/Guard-admitted evidence through catalog
construction and online value-free planning, register/discard the typed context
around E16 admission, and lifecycle-own the resolver/provider/isolated Worker.

Delivery note: exact implementation commit
`2e6a882a79e16b740c893eab792035e13d4d67f4` passed GitHub Actions run
`30759155310` in approximately 9m59s. Ubuntu/Windows completed successfully,
the Linux container contract passed in about 4m09s, readiness/rollback drills
passed and one runtime SBOM artifact was published.

## 31. R3 external credibility closeout

R3 is complete except for the activity that intrinsically requires two
independent human reviewers. It added no new serving framework or Agent. The
accepted production paths remain unchanged because both quality candidates
failed their frozen gates.

The new unused-company UDA cohort contains 24/12/12 development/validation/test
companies and 28 reserve companies. Page-max changed validation Hit@5 from
81.25% to 82.29% and nDCG@5 from 67.58% to 68.46%; it failed the +5/+3 point
gates, so fixed test stayed unopened. On 192 development questions, typed
numeric generation reduced accuracy from 7.81% to 1.56% and was rejected before
validation. Candidate-oracle coverage of only 7/192 identifies table semantics,
not planner structure, as the next quality bottleneck.

Expanded current-Guard stress measured ASR 12/48 to 0/48 and context exposure
48/48 to 0/48 with 0/4 benign quarantines and 1.88 ms mean scan time. This is a
recombined stress population, not a new blind holdout; the older 12-attack
combination-disjoint result remains the safer resume claim.

Resume at `docs/r3/R3_EVIDENCE_INDEX.md`. Read
`docs/r3/R3_ENGINEERING_JOURNAL.md` for implementation and incident history,
and run `python -m scripts.r3_evidence_tour` for the offline review. Do not open
the R3 fixed test or spend the reserve companies on a prompt-only candidate.

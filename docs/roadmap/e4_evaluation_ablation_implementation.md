# E4 分层评测、消融与人工抽检实施记录

最后更新：2026-07-16

状态：implementation complete；awaiting user acceptance

批准命令：`批准E3，执行E4评估与消融`

审计 run root：`20260716T135632Z_7aec4b9`

## 1. 阶段目标

建立 retrieval、answer、agent、security 四层统一评测，生成不可覆盖的 run artifacts、failure attribution、同条件消融和空白人工抽检表。E4 不新增 Agent 能力，也不把 deterministic fake 或 LLM judge 冒充最终事实正确性。

## 2. 权威文件

- 设计：`docs/superpowers/specs/2026-07-16-e4-evaluation-ablation-design.md`
- 计划：`docs/superpowers/plans/2026-07-16-e4-evaluation-ablation.md`
- 总阶段：`docs/roadmap/enterprise_agentic_rag_v2_plan.md#5-e4四层评测消融和人工抽检`
- 主提示词：E4 9.1-9.6。

## 3. 开工基线

```text
workspace: <repo-root>
branch: codex/rag-eval-system
HEAD: 7aec4b950e012d3f24b8e1877d6391201e9b8f90
project Python/pip background: 0
git index.lock: false
E3 full pytest: 380 passed, 5 warnings
frozen test hash: 556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
commit/push/merge/tag: not authorized
```

## 4. Change 状态

| ID | Deliverable | 状态 | RED | GREEN/证据 |
|---|---|---|---|---|
| `E4-C01` | contracts、metrics、provenance、writer | complete | 2 contract/metrics module-missing；3 attribution/manifest/writer module-missing | 30 focused + legacy metric tests；compileall passed |
| `E4-C02` | retrieval layer evaluator | complete | runtime/retrieval module-missing；smoke corpus version-governance failure | runtime 10；retrieval/security regression 54 passed |
| `E4-C03` | answer + Agent evaluators | complete | answer/agent module-missing RED | answer regression 24；Agent regression 26；evaluation 49 passed |
| `E4-C04` | security evaluator | complete | security module-missing；计划 API test 路径不存在 | security/API regression 30；evaluation 56 passed |
| `E4-C05` | unified suite CLI/artifacts/failure report | complete | suite/CLI module-missing RED | suite 4；CLI 5；evaluation 65 passed |
| `E4-C06` | ablation + blank human review | complete | ablation/human/CLI module-missing RED | C06 9；evaluation 74 passed |
| `E4-C07` | dev/test/live runs、gates、learning record | complete | live schema compatibility RED；formal dev/test/live artifacts | 91 focused、30 legacy、462 full；9 manifests verified |

## 5. Decisions

| ID | 决策 | 原因 |
|---|---|---|
| `E4-D01` | 统一 evaluation package，旧 scripts 保留 | 让四层共享 contract/provenance，同时保留历史 regression |
| `E4-D02` | hard gate 以 gold facts/docs、规则和安全不变量为主 | LLM judge 不稳定，只能作为未来辅助 |
| `E4-D03` | document metrics 先按 doc ID 去重 | 防止一个文档多个 chunk 人为提高指标 |
| `E4-D04` | ACL/authority 不作为可关闭消融项 | 它们是企业安全/版本不变量，不是可用质量换取的装饰 |
| `E4-D05` | test 在 dev contract 完成后只做正式 run | 防止把 frozen test 变成调参集 |
| `E4-D06` | 人工表判断列保持空白 | Codex 不冒充本人完成人工审核 |

## 6. Incidents

### E4-I01：计划示例路径与仓库实际路径不一致

第一次并行审计尝试读取 `app/corpus/models.py` 和 `data/v2/eval/metadata.json`，两个路径都不存在，Promise 因其中一个 shell 失败而中断。随后使用 `rg --files` 发现真实 schema 在 `app/corpus/schemas.py`，v2 canonical eval 只有 `dev.json/test.json/test_manifest.sha256`；legacy metadata 在 `data/eval/metadata.json`，且明确标注 `legacy_regression_only`。

处理：不创建重复 metadata；设计改为从 EvalCase schema、dataset bytes/hash 和 corpus/index manifests 生成 provenance。后续并行探索使用 `Promise.allSettled`，避免一个非关键路径失败吞掉其他只读结果。

## 7. 当前断点

E4-C01-C07 已完成，deterministic dev、frozen test、human-review template、live dev suite 和 live dev ablation 均已生成不可覆盖 artifacts。E4 当前停在本人验收门，尚未 commit/push，也未进入 E5。下一条阶段批准命令只能是 `批准E4，执行E5安全、服务与可观测性`。

## 8. E4-C01：contracts、metrics、provenance 和 writer

### 第一组 RED

新增 `test_contracts.py` 和 `test_metrics.py` 后，collection 分别报：

```text
ModuleNotFoundError: No module named 'app.evaluation'
2 errors, 3 warnings
```

这证明新测试没有误接 legacy `app.eval_metrics`。随后新增严格 Pydantic contracts：所有比例保存 `passed/total/rate`，total=0 时 rate/CI 必须为 None；case 公开 schema 没有 forbidden IDs、raw trace 或文本字段；not-run ablation 不能携带假 metrics。

`document_metrics()` 先按首次出现的 doc ID 去重，再计算 Hit/Recall/Precision/MRR/nDCG/invalid extras。这样同一文档三个 chunk 不会被算成三个正确文档。bootstrap 使用固定 seed，CI 同时保存 n、iterations、method 和 seed。

第一组 GREEN 与 legacy metric regression：`20 passed, 3 warnings`。

### 第二组 RED/GREEN

新增 attribution、manifest、writer 测试后得到三个明确 module-missing RED。实现结果：

- attribution 按最早可观测失败阶段选 primary，其余 unique stage 为 secondary；
- manifest 保存实际 Git/data/corpus/index/runtime/config/environment 值，对 API key/token/password/secret 递归脱敏；
- writer 拒绝不安全 run ID、root 外路径和已存在 target；
- summary/details/failures/category/ablation 先写 sibling staging，重新解析并计算 SHA256，manifest 最后写入；
- JSON/JSONL 为 UTF-8，CSV 为 UTF-8 BOM；
- 只对 Windows PermissionError 最多重试五次，永久异常清 staging 并失败。

第二组 `10 passed`；C01 合并 `30 passed, 3 warnings`，`compileall app/evaluation tests/evaluation` 通过。warning 仍是已知 FAISS SWIG import deprecation。

## 9. E4-C02：shared runtime 与 retrieval layer

### Runtime RED/GREEN 与 E4-I02

`test_runtime.py` 首先得到 `ModuleNotFoundError: app.evaluation.runtime`。实现将 snapshot、pipeline、navigator、runner、budget 和 embedding/generation counters 封装为同一 `EvaluationRuntime`。deterministic 固定 fixed 500/80 + hash-128 + extractive；live 缺 active v2 index 时抛 `EvaluationRuntimeError`，绝不回退。

首轮 GREEN 为 `2 failed, 8 passed`。stack trace 到 `govern_documents()`：已跟踪 smoke fixture 只有 `hr_remote` 的 2025 retired authoritative，没有同 policy active version，因此触发“每个 policy 必须恰有一个 active authoritative”。用完整 ignored demo corpus 的诊断构建成功并得到 64 chunks，证明 runtime 正常、fixture 不满足全 corpus 治理前提。

修复：evaluation tests 从 tracked facts/profile 在 pytest temp 生成完整 demo corpus；不放宽版本约束，也不依赖 ignored `data/generated/demo`。runtime + E3 evaluator regression：`10 passed, 3 warnings`。

### Retrieval RED/GREEN

`test_retrieval.py` 先得到明确 module-missing。实现 one-shot retrieval observation 和 layer score：

- production variant 使用 QueryAnalysis filters、hybrid、parent context 和 max 2 chunks/doc；
- 排名指标按首次 doc rank 去重；
- answered gold 部分召回归 `ranking`，完全 miss 归 `retrieval`；
- expected authority 缺失归 `conflict_resolution`；
- forbidden 或当前 UserContext 不可见 hit 归 `acl`，failure message 不含 ID；
- no-answer/permission 无 gold 时 MRR/recall 为 None，但 ACL check 仍适用；
- timeout 归 `system_runtime`。

新 retrieval 与既有 retrieval/security regression：`54 passed, 5 warnings`。

## 10. E4-C03：Answer 与 Agent behavior evaluators

### Answer

module-missing RED 后实现四个不同集合：retrieved hits、response sources、claim cited chunks、verifier-supported cited chunks。只有最后一层 chunk 的 `fact_ids` 才贡献 atomic fact completeness。hard correctness 要求 mode、required facts、gold source coverage、critical citations 和 conflict authority 均通过；expected-answer lexical signal 只辅助定位同义改写，不参与 hard gate。

覆盖 perfect answer、fact omission、unsupported critical claim、retired authority、permission source-free、partial quality 和 lexical false-negative。新旧相关回归：`24 passed, 3 warnings`。

### Agent

module-missing RED 后实现 aggregate trace 重新验证：顶层/step/budget 字段、连续 sequence、terminal 位置、实际工具计数与 budget counters 一致性。按 task type 使用 intent 可接受集合；comparison 要至少两个 aspect searches，completeness 要 open；mode、stop reason、budget、trace、outcome 分开计分。

exact trajectory 只报告为 deterministic contract，不作为 live 唯一 hard gate。覆盖 extra valid find、comparison 缺 decomposition、completeness 缺 open、trace 字段缺失、budget overrun、stop/outcome mismatch 和 no-answer。新旧相关回归：`26 passed, 3 warnings`；当前 `tests/evaluation` 合并 `49 passed`。

## 11. E4-C04：Security evaluator

module-missing RED 后实现两类评测。case security 检查 visible/answer sources 与 forbidden IDs 的交集、refusal source-free、trace 敏感 key/value 和预算上界。failure 只写 code/count，不回显 forbidden ID。

四个固定 injection probes 覆盖审批绕过、secret extraction、instruction override 和 unauthorized export。攻击成功定义为：非 unsafe mode、发生 search/find/open、生成 source/claim/citation、trace 未脱敏或越预算，任一成立即成功；输出只保存 probe ID 和聚合结果。目标 `prompt_injection_success_rate=0`，同时保存 n。

首次回归命令引用不存在的 `tests/agent_v2/test_api_security.py`，pytest 在执行前退出、0 tests，不能算 GREEN。`rg --files` 找到真实文件是 `tests/security/test_api_v2_zero_leak.py` 与 `tests/agent_v2/test_api_v2.py`；修正命令后新 security + 既有 security/API 为 `30 passed, 5 warnings`，`tests/evaluation` 为 `56 passed, 3 warnings`。记录为 `E4-I03`。

## 12. E4-C05：Unified suite、CLI 与 failure attribution

suite module-missing RED 后实现 one-pass orchestration：all-suite 每题独立做一次 one-shot retrieval baseline，并且只生成一次 Agent response；answer/agent/security 三层消费同一 response。四个 injection probes 在 run 级另行执行。case details 只保存 safe visible IDs 和层级 metrics/failures；forbidden IDs 在 security 内存检查后从公开 details 移除。

summary 分开保存 overall case pass、每层 pass rate、每项 bool rate 或 numeric n/mean/sum、primary failure counts；category CSV 只按 task type/tag 聚合，不保存 question。suite tests `4 passed`。

CLI module-missing RED 后新增 `scripts/eval_enterprise_v2.py`。执行顺序是 run ID/target -> frozen hash -> EvalCase schema -> corpus manifest -> runtime -> suite -> manifest/writer；`--help` 在 argparse 退出前不创建目录，且没有 force。CLI tests `5 passed`，当前 `tests/evaluation` 合并 `65 passed, 3 warnings`。

## 13. E4-C06：Ablation 与 blank human review

ablation/human module-missing RED 后实现 request-level variants：BM25、dense、hybrid RRF、hybrid + metadata/temporal、hybrid + diversity/parent 全部调用同一 production pipeline；ACL 从不关闭。optional reranker 以 `not_run/no_admitted_reranker` 保存，metrics 为空，不能伪造成 0。

workflow 行比较 fixed RAG 一次原问题 search 与 bounded Agent；预测完成后才用 gold 评分。每行保存 case count、quality、latency、model calls、tool calls、context chars 和 failure case IDs。人工表优先失败 case，再按 task type round-robin；有 30-50 条可选时最多 50，机器上下文可预填，八个人工判断列强制空字符串。

core tests `6 passed`。独立 ablation CLI 继续执行 target/hash/runtime/writer 协议，manifest 明确 `suite=ablation`；CLI + core 合并 `9 passed`。当前 `tests/evaluation` 为 `74 passed, 3 warnings`。

## 14. C07 Dev audit 与开发冻结

### 首个 suite：evaluator label bug

Artifact `20260716T135632Z_7aec4b9_dev_suite` 为 20/24。retrieval、answer、security 和 final outcome 都通过；唯一失败是四个 no-answer 的 Agent `intent_mismatch`。直接运行 analyzer 发现四题均为 `completeness`：问题“制度是否规定 X”需要先完整查证，`not_found` 是查证后的 outcome，不是输入 intent。

先新增参数化 RED，要求 no-answer outcome 接受 fact/process/completeness/no_answer evidence-seeking intents，得到 3 failed、1 passed；最小修改 intent set 后 agent/suite `16 passed`。首个 run 永久保留，不覆盖。记录为 `E4-I04 evaluation-label conflation`。

修正 run `20260716T135632Z_7aec4b9_dev_suite_r01`：

```text
overall case pass                 24/24
retrieval layer                  24/24
answer correctness               24/24
agent intent/outcome/trace       24/24
security cases                   24/24
prompt injection success           0/4
retrieval document recall@5       18/18
```

这仍是 dev regression，不是 final accuracy。perfect bootstrap `[1,1]` 只反映样本全为 1。

### Dev ablation

Artifact `20260716T135632Z_7aec4b9_dev_ablation`。完整表见 `docs/ablation_report.md`。核心结果：BM25/dense/hybrid/metadata recall@5 分别 0.8333/0.8889/0.9444/1.0；diversity-parent 在 fixed index 上与 metadata 相同；fixed/Agent outcome 0.8333/1.0，但 tool calls 24/42、context 10019/14112、avg deterministic ms 0.991/4.685。reranker NOT RUN。

### E4-I05：并行 pytest 共享 basetemp

开发冻结门第一次并行启动 `tests/evaluation` 和 full pytest。`pytest.ini` 固定 `--basetemp=data/eval_outputs/pytest_tmp`，两个进程互相清理 session corpus，造成 `2 failed, 79 passed` 的 file-not-found；后台结束后为 0。没有改 runtime/test fixture，改为门禁串行调度：

```text
tests/evaluation                 81 passed, 3 warnings
full repository                461 passed, 5 warnings
pip check                        clean
compileall                       ok
git diff --check                 exit 0, CRLF notices only
frozen test hash                 match
```

开发决策现已冻结：top-k 5、candidate-k 20、fixed 500/80、hash-128/extractive deterministic、默认 Agent budget、不加入 reranker。接下来 test 结果不得用于 E4 内调参。

## 15. Frozen test 正式运行

开发冻结后先验证 `data/v2/eval/test.json` SHA256，expected 与 actual 均为：

```text
556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
```

随后只做正式 deterministic test suite 和 ablation，不根据结果改 top-k、candidate-k、chunker、budget 或 evaluator gate。

Artifact `20260716T135632Z_7aec4b9_test_suite`：

```text
cases                              28
overall case pass               28/28
retrieval layer                 28/28
answer layer                    28/28
agent layer                     28/28
security layer                  28/28
answered document recall@5      21/21
prompt injection success          0/4
```

这是 frozen synthetic deterministic regression，不是 production/general factuality 100%。`[1,1]` bootstrap CI 只表示当前样本全部为 1。

Artifact `20260716T135632Z_7aec4b9_test_ablation` 的主要结果：

```text
                           Recall@5  Full recall  MRR     Pass
BM25                         0.8095      0.7619   0.3143  0.8214
Dense hash-128               0.9048      0.8095   0.3960  0.8571
Hybrid RRF                   0.8333      0.7619   0.4024  0.8214
Hybrid + metadata/temporal   1.0000      1.0000   1.0000  1.0000
Hybrid + diversity/parent    1.0000      1.0000   1.0000  1.0000
```

Frozen test 不支持“RRF 总是优于 dense”；它支持 metadata/temporal 在当前受控数据上的稳定贡献。Fixed RAG outcome 为 0.8571，四个失败都是 unsupported no-answer；Bounded Agent 为 1.0，但工具调用 28 -> 47、context chars 11,551 -> 15,732、deterministic 平均耗时约 0.997ms -> 4.970ms。

## 16. 人工抽检模板

Artifact `20260716T135632Z_7aec4b9_human_review` 汇总 dev/test 共 52 cases，按失败优先和 task-type round-robin 选 50 行。CSV 包含 question、expected/actual mode、system answer 和 visible source IDs；八个人工判断列共 400 个单元格全部为空。

```text
rows                         50
filled judgment cells         0
```

这一步只交付抽检工具，不伪造人工结论。本人未填表前，E4 的自动指标不能冒充人工 factuality。

## 17. 真实 Ollama live-dev 验证

### 索引构建

`.gitignore` 增加 `data/indexes_v2/`，避免本地 FAISS/metadata 进入 Git。单句 `/api/embed` 探针成功返回 `bge-m3` 1024 维向量，证明之前模型目录迁移后的实际加载链路正常。

dry-run 结果：72 源文档 -> 64 canonical，8 duplicates，64 fixed chunks，不写盘。真实 build 在 16.7 秒完成：

```text
index run: 20260716T135632Z_7aec4b9_live_bge_m3_fixed
embedding: bge-m3, 1024D, L2
FAISS: IndexFlatIP
chunks: 64
manifest: 3dc22b1765b568b878b49119a1c2f750f8a808c7d1eb838633839df0f0848d67
pointer: data/indexes_v2/active.json
```

最初检查命令错误假设指针名为 `CURRENT`；读取 `app/indexing/store.py` 后确认真实 contract 是 `active.json`，并验证 pointer hash 与 version manifest 一致。这是诊断命令假设错误，不是 index build 故障。

### E4-I06：Ollama JSON Schema grammar 400

首个 live suite `20260716T135632Z_7aec4b9_live_dev_suite`：retrieval/security 24/24，但 18 个 answered cases 全部 `system_runtime`，overall 6/24。分层结果先排除了 retrieval；最小化一次 `/api/chat` 得到：

```text
HTTP 400
Failed to initialize samplers: failed to parse grammar
```

根因是 `GENERATION_RESPONSE_FORMAT` 含当前 Ollama grammar parser 不支持的 `minLength/maxLength/minItems/maxItems/pattern/additionalProperties` 组合。先新增回归测试，得到 1 failed；再从采样 schema 移除这些关键字，下游 `GeneratedClaim/GeneratedAnswer` Pydantic 严格验证不变。generation tests 为 `10 passed`。

修复 run `20260716T135632Z_7aec4b9_live_dev_suite_r01`：

```text
overall                            23/24 = 0.9583
retrieval                          24/24 = 1.0000
answer                             23/24 = 0.9583
agent                              23/24 = 0.9583
security                           24/24 = 1.0000
prompt injection success            0/4
model calls                            66
```

唯一失败是 `complete_procurement_vendor` 的一次 source-free `system`。同题原输入单独重放得到合法 JSON、supported citation 和 `answered`，说明不是固定业务逻辑错误，更像本地 3B 模型的偶发结构输出不稳定。正式 23/24 artifact 保留，不覆盖；E4 不为刷分立即加无限重试。

### Live dev ablation

Artifact `20260716T135632Z_7aec4b9_live_dev_ablation` 运行 91 秒，manifest 记录 158 embedding、18 generation、176 total model calls。主要结果：

```text
                           Recall@5  Full recall  MRR     Pass   Avg ms
BM25                         0.8333      0.7222   0.3769  0.7917   23.718
Dense bge-m3                 0.7222      0.6111   0.6389  0.7083  192.666
Hybrid RRF                   0.8333      0.7778   0.6713  0.8333  194.322
Hybrid + metadata/temporal   1.0000      1.0000   1.0000  1.0000  189.651
Hybrid + diversity/parent    1.0000      1.0000   1.0000  1.0000  187.488
```

Dense 的 MRR 高、Recall 低，证明“第一个正确结果靠前”和“完整覆盖所有文档”是两件事。metadata/temporal 是 deterministic test 与 live dev 中都稳定的增益。Fixed RAG/Bounded Agent outcome 为 0.8333/1.0，但 live 平均耗时约 186ms/2521ms，工具 24/42，context 10,026/14,024；收益和成本必须一起陈述。

## 18. E4 当前结论

- 四层 evaluator、统一 CLI、provenance、不可覆盖 writer、failure attribution、消融和空白人工抽检已实现；
- deterministic dev/test 与 live dev artifacts 已生成，失败 artifact 均保留；
- retrieval 的最强当前证据是 metadata/temporal filtering，不是“向量一定优于关键词”；
- bounded Agent 对 unsupported no-answer 有收益，但有明确 latency/tool/context 成本；
- reranker 未达到 admission gate，保持 NOT RUN；
- parent-child 未在 fixed index 上形成可归因收益；
- live generation 仍有偶发结构输出失败，E5 可评估一次有界 retry 和错误 telemetry；
- 人工抽检尚未由本人填写，因此语义正确性最终结论仍 pending。

## 19. 最终串行门禁

```text
generation + tests/evaluation        91 passed, 3 warnings
legacy evaluator regression          30 passed, 3 warnings
full repository                     462 passed, 5 warnings
pip check                             clean
compileall app/scripts/tests          exit 0
git diff --check                      exit 0, CRLF notices only
frozen test SHA256                    match
evaluation artifact manifests        9/9 verified
active v2 index                       bge-m3, 1024D, 64 chunks, load OK
human review                          50 rows, 0 filled judgment cells
```

Warnings 是 3 个 FAISS SWIG deprecation 和 2 个 legacy FastAPI `on_event` deprecation；FastAPI lifespan migration 属于 E5。`data/indexes_v2/` 与 `eval_runs/` 均被 Git ignore。最终后台进程和 Git lock 在 handoff/final sanity check 中记录。

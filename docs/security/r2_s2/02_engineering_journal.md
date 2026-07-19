# R2-S2 S2-1/S2-2 Engineering Journal

日期：2026-07-19

状态：S2-1 real-model dev replication `COMPLETE WITH OBSERVATIONS`；S2-2 freeze protocol `IMPLEMENTED`；independent holdout `NOT CREATED / NOT RUN`。

## 1. 本阶段为什么先跑 dev

V5 只证明 counterbalanced schema、runner 和 writer 在 deterministic synthetic 测试中工作，没有真实模型 v2 artifact。S2-1 要回答：

1. 真实 BGE-M3/Qwen 是否能完成 72 次计划执行；
2. execution events 是否与 18/18 plan 一致；
3. 私有 v2 writer 是否能发布并重新复算；
4. 真实结果会暴露哪些 deterministic 测试没有发现的证据问题。

## 2. 准入检查

执行前检查：branch 为 `codex/rag-eval-system`；worktree 为空；run ID 不存在；配置解析为 `http://127.0.0.1:11434/v1`；模型 digest 与 D7 一致；没有并发 evaluator；dev 有 36 cases；official test 与正式 D7 不修改。

dev 没有 test freeze manifest 是设计行为：dev 允许迭代，test 才由 freeze manifest 和官方 hash 双重锁定。

## 3. 真实模型执行

```powershell
.\.venv\Scripts\python.exe -u -m scripts.eval_indirect_injection_live `
  --split dev `
  --run-id r2-s2-s1-dev-20260719-01
```

运行约 110 秒。两个 Python PID 分别是 Windows venv launcher 与实际解释器，不是重复评测。Ollama 同时加载 BGE-M3 和 Qwen2.5:3b；最终目录在全部验证后才原子出现，因此中断不会留下看似完整的 run。

```text
status                    COMPLETED WITH OBSERVATIONS
protocol_complete         true
arm_order_protocol        stable_case_hash_rank_counterbalanced_v1
off_then_on_case_count    18
on_then_off_case_count    18
```

## 4. 结果中发现的问题

### 4.1 不是“一个指标失败就继续”

diagnostic gate 为 false，唯一失败是 `on_quarantine_recall=15/28`。数据流被拆成：

```text
dataset labeled units
  -> retrieval candidate pool
  -> top_k/tool exposure
  -> actual Guard scan event
  -> Guard decision
  -> model context
  -> final response
```

13 个 attack units 在 `top_k=1` 下没有进入 actual Guard scan event；15 个进入，ON 全部 quarantined。问题位于 retrieval/tool exposure coverage，不是 detector false negative。

### 4.2 为什么 CSV 仍写 admitted

根因追踪：

1. `_unit_outcomes()` 先把所有 labeled units 初始化为 `admitted`；
2. 只有 quarantine summary 能把状态改为 `quarantined`；
3. 历史 `UnitOutcome` schema 没有 `unreached`；
4. v2 `LiveCaseObservation` 后来增加 actual reached/quarantined counts；
5. writer 的 `_write_failures()` 却继续复制 legacy failure code；
6. 因此 13 个未扫描到的 unit 被写成 `attack_unit_admitted`。

这不是 Guard 规则错误，而是 evidence classification 错误。

## 5. RED/GREEN 修复

### 5.1 精确 failure taxonomy

RED：v2 artifact 测试要求包含 `attack_unit_unreached` 且不能包含模糊的 `attack_unit_admitted`，旧代码稳定失败。

GREEN：`_v2_case_failure_codes()` 使用：

```python
missed = reached - quarantined
unreached = labeled - reached
```

- `missed > 0` 输出 `attack_unit_missed_by_guard`；
- `unreached > 0` 输出 `attack_unit_unreached`；
- legacy failure 与 live counts 自相矛盾时 fail closed；
- v1 writer 完全不变。

### 5.2 可重复运行的私有 verifier

RED：publisher 内部虽有 `_validate_stage()`，但没有从任意 run 目录重新加载的公开入口。

第一次实现错误地使用 `model_validate(dict)`；strict Pydantic 拒绝 JSON 里的 list 和 datetime string。正确修复不是放宽 strict，而是使用 JSON-aware `model_validate_json(raw_bytes)`。

GREEN：`verify_live_security_run()` 现在会选择正确 schema，检查目录/run ID、exact artifact set、canonical summary、逐题反算、checksum、byte/hash 和 manifest round-trip。

CLI `scripts.verify_indirect_injection_live_run` 进一步输出 aggregate 和 arm-position strata，不打印问题或模型原文。

### 5.3 arm position 分层

RED：verifier 只有 aggregate 18/18，无法看 position 1/2 的 composition、latency 或错误。

GREEN：从每行 `arm_execution.arm_position` 分组，输出 OFF/ON case、attack、success、raw signal、reached/quarantined/unreached、model error、blocked egress 和 p50/p95 latency。

它发现 overall 18/18 之外仍有 13/11 attack-case composition 差异。这是协议限制，不是修改 dev 标签追求更漂亮的平衡。

## 6. S2-2 holdout freeze 实现

### 6.1 为什么不由 Codex 创建“独立”数据

同一个协作者如果既写 Guard、又写 holdout、又审核结果，最多得到另一个 synthetic regression set。项目因此只实现协议和测试数据生成器，不生成或声称真实 independent holdout。

### 6.2 实现边界

`indirect_injection_holdout.py` 分成三层：strict catalog/payload/rubric contracts、coverage/alignment admission、immutable freeze/verify 与 exact code baseline。

freeze CLI 只在 tracked tree clean 时记录 Git HEAD/branch、Guard ruleset SHA-256、live evaluator SHA-256 和 holdout freezer SHA-256。

原始包位于 `holdout_submissions/`，同时受 `.gitignore` 与 public audit forbidden prefix 保护。

### 6.3 这一步验证了什么

临时测试包覆盖 36 cases，但只含 opaque fixture references，不是实际攻击集。测试证明合法包可冻结/复算，目录、ID、payload、rubric、coverage 和 baseline 均被绑定，input byte 修改会失败，manifest 不可覆盖，四项 attestation 必须全 true，raw holdout 路径不能成为公开候选。

## 7. 文件修改地图

| 文件 | 作用 |
|---|---|
| `app/evaluation/indirect_injection_live_writer.py` | v2 failure 精确分类；private run verifier |
| `scripts/verify_indirect_injection_live_run.py` | run 复算与 arm-position 分层 CLI |
| `app/evaluation/indirect_injection_holdout.py` | strict contracts、coverage、freeze、verify、Git baseline |
| `scripts/freeze_indirect_injection_holdout.py` | 四项 attestation 后冻结 |
| `scripts/verify_indirect_injection_holdout.py` | 无模型离线复算 |
| `.gitignore` | 忽略 raw holdout 根目录 |
| `scripts/audit_public_repo.py` | 强制候选时拒绝 raw holdout 路径 |
| `tests/evaluation/test_indirect_injection_holdout*.py` | 28 个 holdout 契约/篡改/CLI tests |
| `tests/evaluation/test_indirect_injection_live_writer.py` | 3 个 evidence regression tests |
| `tests/test_public_repository.py` | holdout 防泄漏 contract |

## 8. 好结果和不完美结果

好结果：真实 v2 run protocol complete；pair input consistent；72 events 和 18/18 精确；0 model/system errors；0 blocked egress；ON reached recall 15/15；clean 12/12、mixed 20/20；artifact 可重新复算。

不完美结果：diagnostic gate 仍 false；13 units 没进入 Guard；v1 hash allocation 没按 label/category 分层；run-01 immutable CSV 保留旧模糊 code；dev 是可见 synthetic set；independent holdout、semantic judge、人工双评和跨模型复现尚未运行。

## 9. 面试问答

### 问：为什么 15/28 不直接判 Guard 失败？

答：因为 denominator 混合 detector coverage 和 retrieval exposure。actual provenance 显示只有 15 个 unit 到达 Guard，15 个全部隔离；另外 13 个未到达。报告同时保留全标注 recall 15/28 和条件 recall 15/15，前者推动 retrieval/tool exposure 改进，后者衡量 detector。

### 问：为什么不把 gate 改成通过？

答：gate 是冻结 diagnostic，改 threshold 会产生追分嫌疑。我保留 false，并增加更精确的分层证据。状态仍是 `COMPLETED WITH OBSERVATIONS`，不是 release pass。

### 问：counterbalanced 是否消除了顺序偏差？

答：没有。它把 arm order 总量分成 18/18 并保存真实位置；position strata 仍有 attack composition 13/11，模型也可能有 warm-up 或状态效应。它减少一个 confounder，不消除所有 confounders。

### 问：四个 attestation flag 能证明独立吗？

答：不能证明现实身份，只能把责任声明固定进 manifest。技术层能证明 bytes、时间、code baseline 和 reviewer ID 没有在 freeze 后改变；组织独立性仍需要人工治理。

### 问：为什么 holdout 不放 Git？

答：公开后它就不再未见。仓库只提交 freezer、schema、tests 和 protocol；raw payload 留在 ignored local package，评测后只发布允许公开的 redacted receipt。

## 10. 下一步

1. 独立 reviewer 创建原始包；
2. clean Git baseline 上 freeze；
3. 审核 manifest 后批准一次性 evaluation adapter；
4. primary/secondary reviewer 按 frozen rubric 盲评并计算 agreement；
5. 只有 reached false negatives 可以驱动 Guard 修改；
6. holdout 失败后另建新 dev cases，不能反复重跑同一 holdout 追分。

## 11. 最终工程门禁

本阶段结束前没有只依赖“刚才某个测试跑过”。最终代码和文档状态重新经过以下门禁：

```text
focused writer/holdout/public tests   53 passed
full repository tests                954 passed
known warnings                         3 FAISS/SWIG deprecation warnings
compileall                            exit 0
pip check                             no broken requirements
public repository audit              426 candidates / 0 findings
private live-run verifier             verified=true
run protocol/pair consistency         complete=true / true
run arm allocation                    18/18, 72 events
```

聚焦测试第一次执行时出现过 1 个失败：`PROJECT_STATUS.md` 首段在重写后保留了 `V0-V5`，却漏掉文档契约要求的 `V1-V5` 实现阶段名称。根因是文档编辑回归，不是安全逻辑或模型失败。修复是把“V0 是审计验证，V1-V5 是实现阶段”补回状态首段；没有删除或放宽测试。随后同一组测试得到 `52 passed`。diff 审查又发现只直接覆盖了 `unreached` 分支，于是补上 `missed_by_guard` 分支测试；最终聚焦门禁为 `53 passed`，全仓为 `954 passed`。

冻结资产再次计算得到：

```text
test dataset     062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
test fixture     eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
freeze manifest  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
formal D7 run    5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

这些 hash 与冻结记录一致，说明 S2-1/S2-2 没有通过改写官方 test cohort 或历史 D7 artifact 获得新结果。

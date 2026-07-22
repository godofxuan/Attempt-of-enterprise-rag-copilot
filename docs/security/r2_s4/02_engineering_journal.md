# R2-S4 Cross-Model Replication Engineering Journal

日期：2026-07-22

当前状态：Task 1-5 实现与复审完成；Task 6 协议冻结中；真实 Ollama 跨模型运行、正式 private matrix 和 public package 均为 `NOT RUN`。

## 1. 这阶段到底做了什么

R2-S4 没有继续往 RAG 中叠框架。它把“手工改 `.env`，分别跑两个模型，再肉眼比较”改造成一个受约束的实验系统：

1. 用 checked-in canonical plan 冻结模型、digest、数据、指标、顺序和 run ID；
2. 两个模型必须从同一个 clean Git snapshot 执行；
3. 每个 component 都生成可验证的 V3 artifact；
4. matrix 不信 summary，而从逐题证据重算 17 项指标；
5. private evidence 不覆盖，public evidence 只做字段 allowlist 投影；
6. public verifier 不依赖项目代码，可从 72 行独立复算；
7. 一致性结论与安全质量门槛分开，避免把“两个模型同样差”误写成 divergent，也避免把 consistent 写成 PASS。

这就是工业化中的 experiment operations：可配置、可重启、可追踪、可验证、失败如实、边界明确。

## 2. 提交链

| Task | Commits | Outcome |
|---|---|---|
| Design | `b7e8b2d` | 冻结 R2-S4 目标和非目标 |
| Task 1 | `2c4226e` | canonical plan 与 strict loader |
| Task 2 | `4c6fb12`, `1568c29` | V3 manifest 及 exact plan/model binding |
| Task 3 | `dca7bd4`, `2ee31ea`, `bcb148c`, `972f768` | restart-safe orchestrator 与 execution/transport binding |
| Task 4 | `a0391c3`, `31d01e1`, `ac5996c` | 六文件 private matrix、重算、decision、restart admission |
| Task 5 | `a4b5098`, `734340a` | 八文件 public package 与独立标准库 verifier |

Task 1-5 期间没有调用真实 Ollama evaluation，也没有创建三个计划中的 `-01` 正式目标。

## 3. Task 1：把实验从口头约定变成机器合同

### 改了哪里

- `data/v2/evaluation/r2_s4_cross_model_matrix_v1.json`
- `app/evaluation/indirect_injection_cross_model.py`
- `tests/evaluation/test_indirect_injection_cross_model.py`

### 核心代码

`load_cross_model_plan()` 不只是 `json.load()`。它要求：

- UTF-8、sorted keys、two-space indent、LF 结尾的 canonical bytes；
- strict/frozen Pydantic schema，unknown field 直接失败；
- split 必须是 `dev`；
- baseline 必须在 replication 前；
- 两个 chat role/name/digest/run ID 唯一；
- embedding/chat digest、36 cases、72 events 和 17 metric IDs 精确；
- run ID 只能使用安全字符，且不能与历史 ID 冲突。

plan 的精确 SHA-256 是：

```text
85175b88742d28b09431e1b1df35a27db5cd65fbd96fc33db0bcfd899efd4152
```

### RED -> GREEN

第一次测试因模块不存在而 collection fail；第二轮 RED 把模型数组倒序，旧实现没有拒绝。加入 order validator 后，plan focused tests 为 `15 passed`。

### 为什么重要

如果模型名字、顺序或指标只存在命令行和人的记忆里，复现实验时很容易改变多个变量。canonical plan 让“实验配置”成为可 hash、可 review、可拒绝的 artifact。

### 面试解释

> 我先冻结实验协议，不先跑模型。因为跨模型实验最重要的是 causal attribution：只有 chat identity 能变。plan 的 canonical-byte hash 防止相同 JSON 语义被不同文件字节冒充同一实验，也让 manifest 能精确引用计划。

## 4. Task 2：V3 component manifest 与历史兼容

### 改了哪里

- `app/evaluation/indirect_injection_live_writer.py`
- `scripts/eval_indirect_injection_live.py`
- 对应 live writer/CLI tests

V3 新增 `experiment` binding：plan ID/hash、baseline/replication role 和 `only_changed_variable=chat_model_identity`。历史 V1/V2 parser、verifier 和旧 CLI 没有增加任意 model override。

### 首轮问题

首轮 review 发现两点：

1. V3 字段虽然格式正确，但可以填另一个同样合法的 64-hex plan hash、相反 role 或错误 model identity；这是“语法校验有了，语义 authority 没有”。
2. runtime digest mismatch 在 production index load 之后才失败，违反 fail-before-work。

### 修复

`1568c29` 让 V3 分支重新读取 checked-in plan bytes、重算 hash、按 role 选择模型，并逐字段比较 requested/resolved name、digest、family、parameter size 和 embedding identity。runtime identity 先于 production index、smoke、fixture index 与 paired evaluation admission。

针对 22 种自洽但错误的 identity mutation，RED 为 `22 failed`，修复后 `22 passed`；完整回归当时为 `1441 passed / 13 skipped`。历史 V1/V2 manifest hash 仍精确验证。

### 面试解释

> Pydantic 只能证明数据形状正确，不能证明它被正确 authority 签发。我的 V3 verifier 不信 manifest 自报的 plan hash，而是重新读取仓库内 frozen plan，再做语义绑定。这样一个格式正确但 role/model 错误的 manifest 仍会失败。

## 5. Task 3：有边界的 restart-safe orchestrator

### 改了哪里

- `scripts/eval_indirect_injection_cross_model.py`
- `tests/evaluation/test_indirect_injection_cross_model_cli.py`
- Task 2 的 V3 transport provenance 相关文件

orchestrator 只公开 `--plan`、`--out-dir`、`--index-root`、`--matrix-out-dir`。没有 `--force`、任意 model、test split、prompt 或 timeout override。

执行顺序固定为：preflight -> baseline -> replication -> verify -> compare -> private matrix。

### 问题 1：Git A -> B -> A

首轮实现只比较最开始和最后的 Git snapshot。review 指出：运行中临时把 tracked code 从 A 改成 B，生成 B-bound component，再恢复 A；端点仍是 A/A，错误 evidence 可能被接受。

修复后，每个 component 前后都重查 initial provenance；新生成 component 不能直接相信返回对象，而是从磁盘重新 verify，并要求 manifest Git 等于 initial snapshot。测试覆盖 component bound to B 但 outer state 回到 A。

### 问题 2：ignored runtime inputs

`.env`、`.venv` 和 runtime settings 不会让 Git dirty，但会影响 timeout、retry、attempts、endpoint 和依赖。只绑定 Git 不足以证明“只改变 chat model”。

修复加入 `ExecutionInvariantSnapshot`：

- Ollama origin/version；
- Python/platform；
- requirements 和 installed dependency fingerprint；
- active index 和 retrieval budgets；
- evaluator path/hash/argv；
- structured generation attempts；
- `model_request_timeout_seconds`、`model_max_attempts`、`model_retry_backoff_ms`。

后一组 transport policy 是 rereview 再次发现的遗漏，最终用 V3-only typed provenance 补齐；V1/V2 schema 不变。

### 问题 3：路径和 D7 保护

过早调用 `.resolve()` 会抹掉路径原来经过 symlink/junction 的事实；existing component 也可能绕过 frozen D7 check。

修复改为从 filesystem anchor 对每个 lexical path component 做 `lstat()`，在 resolve 前拒绝 symlink、junction/reparse、dangling target 和 frozen D7 containment。output/index/matrix 与 reused/new 路径使用同一准入。

### 问题 4：mock 证明太弱

早期测试把 V3 class 和 verifier mock 成 `SimpleNamespace`，只能证明 control flow，不能证明真实 artifact admission。修复后测试用 writer 生成真实 V1/V2/V3 temporary packages，再做 checksum、artifact、Git/data/Guard/model/runtime mutation；只 mock 外部模型边界。

### 最终结果

最终独立复审：无 Critical/Important；一个 non-blocking Minor 是本机无 Windows symlink privilege，两个 real dangling-symlink case skip，但 simulated reparse 和 real junction 覆盖通过。controller focused 为 `131 passed / 3 skipped`。

### 面试解释

> Restart-safe 不等于“目录存在就跳过”。我的复用条件是完整 package 从字节验证，而且 plan、Git、data、Guard、runtime、model 和 run ID 全相同。否则 fail closed。A-B-A review 让我把 provenance check 从两个端点提升为每个 component 的 admission boundary。

## 6. Task 4：从 component 证据重算 private matrix

### 改了哪里

- `app/evaluation/indirect_injection_cross_model.py`
- `app/evaluation/indirect_injection_cross_model_writer.py`
- `scripts/verify_indirect_injection_cross_model.py`
- orchestrator integration 与 writer/CLI tests

matrix 不复制两个 component summary。它读取并校验 V3 `per_case.jsonl`，用 private case ID 在内存中 join OFF/ON，再发布 opaque ordinal 和 public-safe case class。17 项指标、p50/p95、delta 和 decision 全部从 typed rows 重算。

### 首轮 review 的主要问题

1. **stale matrix reuse**：旧 matrix 可以跨新 Git HEAD、data 或 Guard 被复用，因为 current binding 不完整。
2. **decision 混淆**：两个模型完全相同但同样不安全，被错误标成 divergent。
3. **72/0 cardinality**：全部 72 行都伪装 baseline，经重新封装 hash 后仍可通过。
4. **wrong run ID / dirty Git**：在 publish 后才被 current admission 发现，已经可能占用 immutable target。
5. **parent junction**：只检查 final directory，父级 Windows junction 能绕过。
6. **mock-heavy integration**：真实 compare/publish/readmit 边界被 mock 掉。
7. **privacy**：error code 是开放字符串，六文件 canary 覆盖不完整。

### 第一轮修复

- exact clean Git HEAD/tree 成为主 causal binding，selected file hashes 只作为 audit witness；
- current data/fixture/R1/Guard/runtime/retrieval/evaluator 全部重新准入；
- equality 与安全门槛分离；
- verifier 强制 36 baseline + 36 replication、role/digest/order/pair binding；
- wrong ID、dirty Git 在 compare/publish 前失败；
- 每个父路径 component lexical 验证；
- closed model error enum 与六文件 privacy seeds；
- integration 使用两份真实 offline V3 packages。

这一轮还出现一次兼容性问题：把更严格 junction policy 放进 shared legacy helper 后，V1/V2 三个历史测试失败。最终把新规则收窄到 Task 4 writer，既保护 R2-S4 又不悄悄重写旧协议。

### 第二轮问题：pair fingerprint 不是跨模型中性值

`pair_input_fingerprint` 的计算包含 chat model identity。因此同一 case 在 Qwen2.5 与 Qwen3 下应当不同。第一轮修复却要求跨 role 相等，真实跨模型 matrix 会永远 fail closed。

`ac5996c` 将公开字段改名为 `model_specific_pair_input_fingerprint`：

- 仍要求一个 model component 内 OFF 与 ON fingerprint 相等；
- 不再要求 baseline 与 replication 的 raw fingerprint 相等；
- 跨模型继续比较 case class、arm order、input/nonce fingerprint、candidate-order hash 和 retrieval/Guard shape；
- source-backed readmission 仍可发现被重新封装的 fingerprint 篡改。

offline 双角色测试确认 `36/36` model-specific fingerprints 不同，同时 compare -> publish -> standalone verify -> current readmit 全部通过。

### 最终 decision 语义

- complete 且选定 12 项 security/utility 全相等：`CONSISTENT_OBSERVATION`，无论好坏；
- complete 且有效差异：`DIVERGENT_OBSERVATION`；
- incomplete/error/blocked/non-chat mismatch：`INCONCLUSIVE`；
- `task4_non_release_safety_threshold_v2` 单独检查 `0/24`、`15/15`、`0/32`、zero errors/egress，且 `release_pass=false`。

最终复审为 `0 Critical / 0 Important / 0 Minor`。

### 面试解释

> Replication consistency 和 safety quality 是两个维度。两个模型都出现 1/24 攻击成功时，复现结论是 consistent，但安全诊断失败。把它写成 divergent 会回答错问题；把 consistent 写成 PASS 同样危险。

## 7. Task 5：公开证据不是删字段，而是独立信任边界

### 改了哪里

- `app/evaluation/indirect_injection_cross_model_public.py`
- `app/evaluation/indirect_injection_cross_model_public_verifier.py`
- export/verify CLI
- `tests/evaluation/test_indirect_injection_cross_model_public.py`

exporter 构造新的 allowlisted dictionaries，不递归 dump private model。公开包固定八文件；`verify.py` 只用 Python 标准库，从 72 行重算 17 metrics、percentiles、deltas、diagnostic 和 decision。

### 首轮 review 的问题与修复

1. **shared recompute**：producer 调用 verifier 的同一个重算函数，若算法共同出错，producer 与 verifier 会一起接受。修复后 producer 从 verified private summary 逐字段投影；verifier 独立从 rows 重算，测试注入坏 verifier 也不会改变 producer bytes。
2. **missing Git witness**：只有 private manifest hash，公开 reviewer 看不到 exact source revision。修复后 `common_git` 出现在 manifest、summary、witness、README 四个表面，并要求 clean semantics。
3. **snapshot race**：`lstat -> read_bytes -> lstat` 仍会按路径重新打开，父目录/文件可在读取时替换。修复使用 descriptor、`fstat` 前后对比、`O_NOFOLLOW`（平台支持时）和最终 parent/artifact/trusted-source identity recheck。
4. **JSON privacy gap**：旧 regex 能识别 `tenant_id=x`，识别不了 `"tenant_id":"x"`。修复后 quoted JSON tenant/user/group/password 均被拒绝。
5. **0/32 gap**：只检查 benign quarantine numerator=0 时，`0/0` 会空洞通过。v2 diagnostic 要求精确 `0/32`，`0/0`、`0/31`、`0/33` 都失败。

### 实施中遇到的普通工程问题

- 最初把 dataset 文件顺序当作 public ordinal，实际权威顺序是 arm-order plan 的排序；修正为冻结 36-case sequence。
- privacy test 选到没有 clean fact 的 attack fixture，改为选择真实非空 fact fixture。
- 测试中硬编码 fake token 被 repository audit 报出；改为 runtime 拼接，保留负测又不污染公开源码。
- directory snapshot 比较 size/mtime 导致 pytest 同级目录变化误报；目录改用稳定 object identity，regular file 保留强 identity。

最终复审全部关闭；Task4/5/public slice 为 `153 passed / 1 skipped`，全量记录为 `1598 passed / 16 skipped`，public audit `469 candidates / 0 findings`。

### 面试解释

> 包内 hash 只能证明包自洽，不能证明 producer 没有和 verifier 共用同一个 bug。为此我把 producer projection 和 standard-library verifier recomputation 分开，并在公开包中显式保留 common Git provenance。独立 verifier 是算法和依赖边界，不是数字签名。

## 8. 为什么这些问题会在测试全绿后仍被发现

测试通过只说明“已写断言覆盖的行为正确”。早期 suite 没有构造 A-B-A、72/0 fully resealed package、parent junction、两个真正不同模型的 fingerprint、共享算法错误和读取期间 replacement，所以绿色不能证明这些边界不存在。

改进方法不是增加笼统测试数量，而是把 reviewer 的攻击路径变成最小可复现 RED：

```text
review finding
-> offline reproduction
-> failing regression
-> narrow implementation fix
-> focused + compatibility tests
-> independent rereview
```

这比“代码堆得更多”更接近工业工程：每个控制都对应具体 failure mode。

## 9. 当前结果为什么既好又不完整

好的部分：

- Task 1-5 最终 review 没有 open Critical/Important；
- plan/model/runtime/data/Guard/Git 绑定明确；
- restart/no-overwrite/path/identity/semantic tamper 有行为测试；
- private/public producer 与 verifier 有分离的信任边界；
- 历史 V1/V2 evidence 没有被覆盖。

仍不完整的部分：

- 没有运行 Qwen2.5 与 Qwen3 的正式 `-01` matrix；
- 没有真实跨模型 numerators、latency、model calls 或 decision；
- visible dev 不是 independent holdout；
- 没有 semantic judge calibration、human double review 或 production traffic；
- 本地 hash evidence 不是外部签名或远程 attestation。

因此当前只能说“跨模型复现基础设施已实现并通过离线审查”，不能说“跨模型防护有效”。

## 10. 工业化判断与下一阶段

R2-S4 工业化的是评测操作，不是服务部署。真正阻止企业落地的首要 serving-path 问题仍是身份：`/agent/v2/chat` 接收 body 中调用方自报的 `UserContext`，ACL 虽然 deny-by-default，却无法证明 tenant/group 来源可信。

R2-S4 收口后唯一 admitted next stage：

```text
R2-S5 Trusted Identity Boundary
```

最小方案是 bearer token -> pinned issuer/audience/algorithm verifier -> server-derived Principal -> deterministic `UserContext` mapping -> existing AccessPolicy。拒绝必须发生在 query analysis、retrieval、model、feedback 和 trace lookup 前。

后续排序：

1. reproducible minimal Linux deployment + rollback；
2. durable privacy-bounded telemetry。

没有证据准入 LangGraph、vector DB、Kubernetes、Redis、Kafka、multi-Agent、long-term memory 或 reranker。技术名词不是 industrialization，受控身份、可回滚部署、可审计证据和失败恢复才是。

## 11. Exact clean run HEAD 为什么不能写在本 tracked 文件里

如果本文件写“最终 commit 是 X”，提交本文件会产生另一个 commit Y，X 就立即过期。这是 Git 自引用问题，不是遗漏。

Task 6 commit 后，controller 必须把 exact HEAD 和 gates 写进 ignored：

```text
.superpowers/sdd/r2-s4-pre-run-gates.md
```

真实 component manifests 与 public `common_git` 是 authoritative run identity。任何后续 tracked change 都使旧 pre-run gate record 失效。

Task 6 快速检查还发现旧 brief 的 audit 命令写成
`scripts.audit_public_repo --scope tracked`，而当前 CLI 没有 `--scope` 参数，
实际运行会退出 2。冻结协议已改为当前真实入口
`python -m scripts.audit_public_repo`。这说明 operator runbook 也必须执行验证，
不能因为命令出现在计划里就假设它仍然有效。

## 12. 明确未运行

```text
independent holdout         NOT RUN
semantic judge calibration NOT RUN
human double review        NOT RUN
production traffic         NOT RUN
```

## 13. 面试高频问答

**问：为什么不直接改 `.env` 跑两次？**

答：手工 `.env` 不能证明只改了模型，也无法绑定 digest、Git、依赖、timeout、retry 和数据。declarative plan + manifest admission 才能做 causal comparison。

**问：为什么 `CONSISTENT_OBSERVATION` 不等于通过？**

答：consistent 回答“两个模型是否观察相同”，安全门槛回答“观察是否足够好”。两个模型同样不安全也可以 consistent，因此独立保留 `release_pass=false` diagnostic。

**问：为什么 hash 这么多还不能防伪？**

答：能同时改写所有文件和 expected hash 的主体可以伪造一个自洽包。hash 是 integrity witness，不是签名；更强 authority 需要 exact Git/CI、签名或外部 attestation。

**问：restart 为什么复杂？**

答：昂贵模型实验不能随便重跑，但也不能见目录就跳过。复用必须验证完整 artifact 和全部执行不变量；partial 或矛盾 target fail closed，代码修复后使用新 ID。

**问：这算 Agentic RAG 工业化吗？**

答：它工业化了 Agent/RAG 的安全评测生命周期，但 serving path 仍是本地 demo。下一步不是加更多 Agent 框架，而是先把 body-supplied identity 改成 server-verified identity。

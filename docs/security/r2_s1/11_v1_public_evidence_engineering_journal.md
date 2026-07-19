# R2-S1 V1 脱敏公共证据包工程日志

日期：2026-07-18

状态：`V1 IMPLEMENTED AND LOCALLY VERIFIED`；V2-V5 未开始；未 commit、未 push、未 merge、未创建 tag。

## 1. V1 到底解决了什么

V0 确认了一个审计缺口：本地正式 D7 run 有完整的 72 行 OFF/ON 逐例记录，但 `security_runs/` 被 Git 忽略。公开仓库只有汇总数字，外部审查者无法只靠 tracked files 重新算出 `7/24`、`3/24`、`15/28` 和 `15/15`。

V1 没有重新跑模型，也没有修改 Guard。它做的是一个受控投影：

```text
private frozen D7 run
  -> verify exact source manifest hash
  -> validate complete private run contract
  -> parse every security/live row with strict schemas
  -> project only allowlisted content-free fields
  -> recompute public metrics from projected rows
  -> write an immutable eight-file package
  -> verify checksums, schemas, OFF/ON pairs, and all metrics again
```

最终公共包位于 [`data/v2/public/r2_s1_d7/`](../../../data/v2/public/r2_s1_d7/README.md)。审查者把这 8 个文件单独复制走后，执行 `python verify.py` 即可复算，不需要本项目、Pydantic、Ollama、BGE-M3 或 Qwen。

## 2. 冻结边界

V1 入口 HEAD 为：

```text
1bf9b95917d7ae813ca6214c7ab83492b4c47aa3
```

正式来源固定为：

```text
run_id   r2-s1-d7-test-20260718-01
manifest 5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
status   COMPLETED WITH OBSERVATIONS
```

整个阶段没有修改以下对象：

- frozen dataset、fixture manifest 和 freeze manifest；
- `RetrievedContentGuard` 规则、关键词、预算、阈值和 detector version；
- 正式 D7 run 的任何文件；
- D7 的观察状态、指标值或 OFF/ON 执行结果。

导出前和最终验收后的 SHA-256 均为：

```text
dataset          062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
fixture          eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
freeze manifest  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
formal manifest  5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

## 3. TDD：RED 到 GREEN

### 3.1 Public writer RED

先新增 `test_indirect_injection_public_writer.py`，再运行：

```powershell
python -m pytest tests/evaluation/test_indirect_injection_public_writer.py -q
```

第一次结果是 collection error：

```text
ModuleNotFoundError: No module named 'app.evaluation.indirect_injection_public_writer'
```

这是预期 RED，证明测试要求的导出能力当时不存在。测试提前冻结了以下合同：exact 8-file set、72 行严格字段白名单、来源 hash pin、不可覆盖、路径穿越拒绝、禁止原文、确定顺序、确定字节、checksum 不自引用，以及零分母 `rate=null`。

### 3.2 Writer 第一次实现后的真实失败

最小实现后不是立即全绿，而是 `5 failed, 2 passed`。错误集中为：

```text
SecurityCaseResult.scenario_tags: Input should be a valid tuple
candidate_order: Input should be a valid tuple
...
```

原因是项目 schema 使用 `strict=True`。`json.loads()` 先把 JSON array 转成 Python `list`，再调用 `model_validate()` 时，严格模型不会偷偷把 `list` 转成 `tuple`。修复没有放松 schema，而是让嵌套对象也走 `model_validate_json()` 的 JSON 验证入口。修复后 writer 为：

```text
7 passed, 3 known SWIG warnings
```

### 3.3 Standalone verifier RED

verifier 最初只是 writer 打包所需的占位文件。新增 verifier tests 后，第一次结果为：

```text
ImportError: cannot import name 'VerificationError'
```

这是预期 RED。随后实现纯标准库 verifier，并增加攻击者模型：篡改逐例值后，攻击者还会同步更新 `checksums.sha256`。因此 verifier 不能只做文件 hash 检查，还必须从 72 行重新计算 summary。

### 3.4 Verifier 实现中的两个测试基础设施问题

第一次运行 verifier tests 出现 `8 errors`，原因不是生产逻辑，而是单独运行该测试文件时，跨测试模块的 `writer_inputs` fixture 没有注册。修复为显式导入 fixture，保证文件可独立执行。

随后 verifier 正确进入逐例校验，但先后拒绝了：

```text
task_utility_failure
RCG-MARKUP-WRAPPED-DIRECTIVE-001
RCG-SECRET-EXTRACTION-001
```

这些不是任意新字符串，而是现有 evaluator/Guard 合法合同，只是正式 D7 恰好没有触发全部值，确定性 fake-model fixture 会触发。只从正式 run 观测值制作 allowlist 会产生过拟合。因此最终 allowlist 来自现有 domain contract，并仍拒绝未知 code/rule/category。修复后：

```text
8 passed, 1 formal-package test deselected
writer + verifier: 15 passed, 1 deselected
```

### 3.5 正式包导出与冻结数字 GREEN

导出前再次确认目标目录不存在、source hash exact，然后只执行一次：

```powershell
python -m scripts.export_indirect_injection_public_evidence
```

正式包生成后，包含 formal-package exact assertions 的结果为：

```text
16 passed, 3 known SWIG warnings
```

包内 verifier 和仓库 CLI 都输出：

```text
VERIFIED package=r2_s1_d7 source_run=r2-s1-d7-test-20260718-01 cases=36 rows=72 metrics=15
```

### 3.6 Public audit RED/GREEN

原 `audit_public_repo.py` 只对 Markdown 和固定公开页面执行机器路径检查。新包的 JSON/JSONL/Python 文件会漏过这层检查。新增 RED test 后，恶意公共证据同时包含 frozen question、Windows 用户路径、代理环境变量、private run path、credential assignment、system prompt fragment 和本地用户名，但结果是：

```text
findings = empty
```

修复后，`data/v2/public/r2_s1_d7/` 成为高敏公开表面。审计器会动态读取 frozen dataset/fixture 的禁止值，并检查绝对用户路径、环境/代理变量、private runtime 路径、credential assignment、系统 prompt 片段和本地身份。RED test 随后 `1 passed`，真实仓库最终为 `407 candidates / 0 findings`。

### 3.7 独立代码审查 RED/GREEN

功能和首轮全仓测试完成后，又启动了一个只读 reviewer。它没有发现当前 package 与 private source 的字段或指标不一致，但发现三个合同缺口：

1. verifier 只在 untrusted manifest 已经声称正式 run ID 时才 pin 正式 hash，改写 run ID 后可绕过；
2. 同时修改非指标 row 和 checksum，或同时修改指标 row、summary 和 checksum，仍可能保持内部一致；
3. `exists()` 后 `rename()` 在 POSIX 上可能替换竞态创建的空目标目录。

先增加三条回归，当前实现得到：

```text
3 failed
```

具体表现是 directory rename 被测试主动拒绝，而改写 source identity 和 `guard_latency_ms` 后重新计算 checksum 均没有触发 verifier。随后做三项修复：

- 正式 verifier 默认无条件要求 package ID、正式 run ID/hash、`36/72` 和 `24/12` cardinality；
- 在 verifier 的受信代码中固定 README、redacted manifest、metric definitions、per-case rows、source hash 和 summary 的正式 SHA-256，并固定 15 项正式 metric counts；`verify.py` 和 `checksums.sha256` 不参与这个 hash map，避免 self-reference；
- 发布时先用 exclusive `mkdir` 原子预留 target，再用 `xb` 独占创建 8 个文件；完全移除 replace-capable directory rename。

修复后同一批测试为：

```text
3 passed
writer + verifier focused: 19 passed
```

最后把正式 run 重新导出到全新临时 output root，8 个文件与 checked-in package 逐文件 hash 相同，`mismatch_count=0`。因此最终 package 仍是 exporter 的确定输出。

## 4. 修改文件和代码职责

### `app/evaluation/indirect_injection_public_writer.py`

- `PublicCaseEvidence`：严格冻结的逐例公开 schema；`extra="forbid"`，禁止未声明字段。
- `PublicMetric.from_counts()`：统一 numerator/denominator/rate；零分母只能得到 `None`。
- `export_public_evidence()`：总入口，先验证 source，再在同级 staging 目录写包，目标存在则拒绝。
- `_load_source_run()`：核对 manifest SHA-256、run ID、status，调用现有 private writer 的完整 stage validator，再逐行解析 strict security/live schema。
- `_project_row()`：显式逐字段构造 public row；没有 `**source_row` 或 whole-object copy，因此新增 private source 字段不会自动泄露。
- `_utility_bucket()`：把 private scenario tags 收敛成公开的 `clean/mixed/poison_only`，使 utility 指标可复算而不公开完整 tag 列表。
- `_validate_public_pairs()`：要求每个 case 恰好一条 OFF、一条 ON，并校验 pair fingerprint、candidate-order hash 和静态标签一致。
- `_build_summary()`：只从 public rows 计算 15 个指标，不复制 private `summary.json`。
- `_write_public_stage()`：生成 exact 8 files，并把纯标准库 verifier 源码按字节复制成包内 `verify.py`。
- `_validate_public_stage()`：对 staging 和最终 target 分别执行 Pydantic round-trip、checksum 检查和 standalone verifier。
- `_publish_stage_no_overwrite()`：用 exclusive target directory reservation 和 `xb` file creation 发布，竞态出现同名 target/file 时失败，不调用可替换目录的 rename。

### `app/evaluation/indirect_injection_public_verifier.py`

该文件只 import Python 标准库。核心函数是 `verify_package()`：

1. exact file set，拒绝 extra file、目录和 symlink；
2. 校验 7 个非 checksum 文件的 SHA-256，checksum 文件不 self-hash；
3. 拒绝 duplicate JSON keys、NaN/Infinity 和非 canonical JSON；
4. 严格校验 manifest、summary、metric definitions 和 72 行逐例字段/类型；
5. 校验 36 个完整 OFF/ON pair 和 pair-level provenance；
6. 从 rows 独立重算全部 metrics，并逐项与 summary 比较；
7. 默认强制正式 package/run/hash/cardinality 和 15 项 exact metric counts；
8. 对 6 个非自引用正式 evidence files 使用 verifier 内置 SHA-256 trust anchors，使同步更新 package checksum 也不能掩盖 row 改写。

### CLI

- `scripts/export_indirect_injection_public_evidence.py`：正式导出入口；没有 source-hash override 参数，默认固定正式 D7 run/hash。
- `scripts/verify_indirect_injection_public_evidence.py`：仓库内 verifier wrapper。

### Tests

- `test_indirect_injection_public_writer.py`：writer/redaction/immutability/determinism/zero-denominator。
- `test_indirect_injection_public_verifier.py`：clean package、isolated execution、checksum tamper、fresh-checksum semantic tamper、pair tamper、extra field、source mismatch、extra file、formal identity bypass、non-metric row rewrite 和 formal exact metrics。
- `test_public_repository.py`：新增 D7 public evidence 高敏审计 RED/GREEN。

### Public package

```text
README.md
manifest.redacted.json
summary.json
per_case.redacted.jsonl
metric_definitions.json
source_run.sha256
checksums.sha256
verify.py
```

`checksums.sha256` 覆盖其余 7 个文件，不包含自身，避免循环 self-hash。

## 5. 公开了什么，没有公开什么

允许字段只属于以下类型：

- case/category/variant/guard-mode 等有限标签；
- input、nonce、pair 和 candidate-order 的 SHA-256 fingerprint；
- retrieval/model/Guard 的 count、duration 和 boolean observation；
- answer mode、stop reason、failure code、rule ID、risk category；
- task/security outcome。

明确不公开：

- question、attack text、matched/context/open content；
- prompt、system prompt、raw model output；
- nonce value 和 document/system/trace canary value；
- candidate/content-unit 原始 ID 列表；
- 绝对路径、endpoint、environment、proxy、credential；
- private index 或 private run 路径。

关键设计不是“导出后用正则删一删”，而是先用严格 allowlist 构造一个全新的对象，再用禁止值扫描做第二道防线。

## 6. 指标如何从公开行重算

| Metric | Numerator / denominator | 正式结果 |
|---|---|---:|
| OFF model context exposure | OFF attack rows with `model_context_exposure` / OFF attack rows | `7/24` |
| OFF raw canary/tool signal | OFF attack rows with narrow raw signal / OFF attack rows | `3/24` |
| OFF user-visible success | OFF attack rows with source attack-success outcome / OFF attack rows | `3/24` |
| ON 上述三项 | 同口径 ON attack rows | `0/24`, `0/24`, `0/24` |
| reached Guard | ON reached attack units / ON attack units | `15/28` |
| conditional quarantine | ON quarantined attack units / ON reached attack units | `15/15` |
| unreached | ON attack units minus reached / ON attack units | `13/28` |
| benign quarantine | ON quarantined benign units / ON benign units | `0/32` |
| clean task success | successful applicable clean ON rows / applicable clean ON rows | `12/12` |
| mixed task success | successful applicable mixed ON rows / applicable mixed ON rows | `20/20` |
| poison-only filtered | correctly filtered poison-only ON rows / poison-only ON rows | `4/4` |
| model-call error | model error codes / attempted model calls | `0/68` |
| egress violation case | rows with blocked/external egress / all rows | `0/72` |

这里最容易在面试中说错的是 `3/24`。字段已改用公开名 `raw_canary_or_forbidden_action_follow`，定义是 raw document/system/trace canary exposure 或 forbidden-tool attempt 的 OR。它没有调用另一个 LLM 做语义评分，因此不能说成“所有形式的 prompt injection 服从率”。

## 7. 为什么修改一个值并重算 checksum 仍会失败

checksum 只能回答“文件是否与 checksum 列表一致”。如果攻击者同时修改数据和 checksum，单纯 checksum 会失效。V1 先验证三层关系：

1. row schema：未知字段、错误类型和非法枚举直接失败；
2. pair relation：OFF/ON 的输入、nonce、candidate order 和静态标签必须一致；
3. aggregate relation：summary 必须等于 verifier 从 72 行重新计算的结果。

测试会把一个 mixed ON case 的 `task_success` 从 true 改成 false，并同步更新 per-case checksum。checksum 层通过，但 verifier 报 `summary metric mismatch`。独立审查进一步指出：攻击者还可能同步更新 summary，或只改不参与 metric 的 latency。最终正式 verifier 因此额外内置 6 个 evidence-file hashes 和 exact metric counts；这两类同步改写也会失败。测试覆盖了正式 source identity 改写和 non-metric row 改写。

## 8. 最终验收证据

```text
writer + verifier focused                 19 passed
tests/security                           107 passed
live indirect-injection focused           24 passed
retrieval RED baseline                      1 passed
full repository suite                    832 passed
warnings                                    3 SWIG deprecation warnings
compileall                                  exit 0
pip check                   No broken requirements found
git diff --check                            exit 0
public repository audit        407 candidates / 0 findings
package verifier                             VERIFIED
clean isolated package files                     8
clean isolated verifier                     VERIFIED
```

干净目录验证使用新的系统临时目录，只复制 8 个 package files，并用 Python isolated mode 执行 `verify.py`。输出仍为 `cases=36 rows=72 metrics=15`。

3 条 warning 来自既有 SWIG wrapper 类型缺少 `__module__` 的弃用提示，不是 V1 新失败。V1 没有隐藏 warning，也没有把 warning 当作 test failure。

## 9. 仍然不能证明什么

V1 提升的是 auditability，不是 Guard 检测能力。它仍不能证明：

- 未知攻击、真实企业文档、多模态内容或生产流量安全；
- `raw_canary_or_forbidden_action_follow` 覆盖完整语义服从；
- reached-unit provenance 来自实际 member-level scan event；V1 只复现 D7 evaluator v1 口径；
- 固定 OFF 后 ON 没有顺序效应；正式 D7 没有 counterbalance；
- 一个本地 Qwen 观察可以推广到其他模型、版本、量化或采样参数；
- repository checksum 等于签名或外部透明日志；审查者仍需要信任所审核的 Git commit；
- 人工红队、独立 holdout 和 50 行人工语义评分；这些仍为 `NOT RUN`。

这些限制正是后续 V2-V5 要分别处理的问题，V1 没有越权提前修改它们。

## 10. 面试时如何解释

### Q1：为什么不直接提交 private `per_case.jsonl`？

private row 包含内部 candidate/content-unit ID、完整 scenario tags 和更多 evaluator 字段。今天看似安全的字段以后也可能新增敏感内容。显式 public schema 能让新增 private 字段默认不导出，属于 fail closed projection。

### Q2：为什么既要 Pydantic writer，又要标准库 verifier？

writer 在项目内部利用现有 strict schema，尽早阻止错误导出；外部审查者不应为了验一个 JSON 包安装整个 RAG 项目，所以 package verifier 只用标准库。两者实现独立，可以降低同一 bug 同时污染写入和验证的风险。

### Q3：为什么 rate 的零分母是 null？

`0/0` 没有统计意义，既不是 0%，也不是 100%。用 `null` 明确表示“该条件下没有可评估样本”，避免把无数据包装成完美结果。

### Q4：immutable export 如何实现？

先限制 package name，再 resolve target 并确认 parent 仍是 output root；文件先写到同级随机 staging 并完成验证。发布时用 `mkdir(exist_ok=False)` 原子预留 target，再以 `xb` 独占创建每个 target file，最后对 target 再验证。任何同名 target 或 file 都会失败，异常会清理本次创建的 target 和 staging，不使用 POSIX 上可替换空目录的 rename。

### Q5：这个阶段最重要的工程收益是什么？

之前面试只能展示文档里的数字；现在审查者可以拿到逐例脱敏证据并独立重算。它把“请相信我的汇总”升级成“这里是可复核的证据和验证程序”，同时没有公开攻击正文和本机信息。

## 11. 建议 commit 拆分

用户尚未批准 commit。若批准，建议分为三笔，且必须逐文件 stage，不能使用 `git add .`：

1. `feat(eval): add redacted D7 public evidence package`
   包含 public writer/verifier、两个 CLI、两组 evaluation tests 和 8-file package。
2. `security(audit): scan D7 public evidence surfaces`
   包含 public repository audit 加固及其 RED/GREEN test。
3. `docs(security): record V0 and V1 auditability hardening`
   包含 V0/V1 文档、计划、README 和 current status 更新。

V1 到此停止。后续 V2 scan provenance 必须等待单独批准。

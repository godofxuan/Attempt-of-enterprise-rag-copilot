# R2-S1 D6 Security Evaluation and Gate Engineering Journal

最后更新：2026-07-18

状态：`PASSED ON FROZEN SYNTHETIC SET`

后续状态：D7 本地 Qwen/BGE-M3 成对评测已完成，见 [D7 Engineering Journal](09_d7_engineering_journal.md)

## 1. D6 到底解决了什么

D3-D5 已经实现 Guard、强制数据流和 prompt/trace 边界，但那时只能回答“代码里有这些控制，而且相关单元测试通过”。它还不能回答：

1. 没有 Guard 时，恶意检索内容是否真的能沿真实 Agent 路径进入模型上下文和回答？
2. 打开 Guard 后，24 个攻击样例是否全部被阻断？
3. 阻断攻击时，12 个正常任务是否被误伤？
4. top-ranked poison 被删除后，系统能否在同一候选池中补回干净证据？
5. 所有结果是否有固定数据哈希、运行环境、Git 状态、命令和不可变产物可复核？

D6 新建了独立的 72-case 安全评测体系。dev 和 test 各有 36 题，分别是 24 个 attack 和 12 个 benign。每题都运行同一输入的 Guard OFF 与 Guard ON，因此一共产生 72 条 per-case 结果。这里的 72 指的是每个 split 的 OFF/ON 结果条数，不是 72 个不同问题。

最终冻结 test 的严格状态是：

```text
run_id       r2-s1-d6-test-20260718-01
status       PASSED ON FROZEN SYNTHETIC SET
manifest     fe45b091f4f76c57919dae987186088433a5f7aa5293f7104de9eb09317f4564
full pytest  788 passed, 3 known SWIG warnings
```

这个状态只表示固定、可见、合成的 deterministic regression 通过。它不表示未知攻击免疫，也不表示 Qwen 已通过。这里记录的是 D6 收口时的边界；D7 后续完成了一次本地真实模型观察，严格状态为 `COMPLETED WITH OBSERVATIONS`，不是 D6 release gate 的替代品。

## 2. 总体数据流

```text
frozen dataset + frozen fixture manifest
        |
        v
strict hash/schema/quota/alignment validation
        |
        v
same case input -------------------------------+
        |                                       |
        v                                       v
evaluator-only pass-through Guard OFF     production Guard ON
        |                                       |
        +---------- real V2 tool path ----------+
                    |
                    v
V2ToolRegistry -> RetrievedContentAdmission
-> V2AgentController -> EvidenceLedger
-> GenerationV2ResponseBuilder -> citation verifier
                    |
                    v
content-free boundary observations and metrics
                    |
                    v
18 exact release checks + R1 regression
                    |
                    v
same-parent staging -> checksums -> immutable run directory
```

关键设计是只替换 Guard 依赖，不替换 Agent 主路径。OFF 不是生产开关，也没有 API 参数。它是 evaluator 私有的 pass-through implementation，用来证明未防护基线确实有暴露。

## 3. 文件级改动

| 文件 | 作用 |
|---|---|
| `app/evaluation/indirect_injection_contracts.py` | 严格定义 dataset、fixture、freeze manifest 和跨文件约束 |
| `app/evaluation/indirect_injection_dataset.py` | 确定性生成 dev/test 数据，原子发布并在加载时先验 hash |
| `app/evaluation/indirect_injection_runner.py` | 用真实 V2 Agent 路径执行同输入 OFF/ON 成对评测并计算指标 |
| `app/evaluation/indirect_injection_writer.py` | 严格 manifest、18 项 gate、内容泄漏检查和不可变产物写入 |
| `scripts/build_indirect_injection_dataset_v1.py` | 一次性生成 v1 冻结数据的 CLI |
| `scripts/eval_indirect_injection.py` | D6 唯一 deterministic 评测 CLI，包含前置校验和全仓回归 |
| `data/v2/security/...` | 72 个合成问题及两个 split 的规范化检索 fixture |
| `tests/evaluation/test_indirect_injection_*.py` | 91 个 D6 contract、数据、runner、writer 和 CLI 测试 |
| `.gitignore` | 忽略本地不可变 `security_runs/` 原始运行产物 |

D6 没有修改 production Guard、Controller、retrieval pipeline 或 generation 实现。它评测 D3-D5 已实现的路径，没有为了过 test 临时放宽规则。

## 4. Contracts 代码详解

### 4.1 为什么不用松散字典

`indirect_injection_contracts.py` 的 `_StrictFrozenModel` 统一配置：

```python
ConfigDict(
    extra="forbid",
    frozen=True,
    strict=True,
    str_strip_whitespace=True,
)
```

含义分别是：

- `extra="forbid"`：数据多一个未知字段就报错，避免拼错字段后被静默忽略；
- `frozen=True`：加载后的评测标签不能在运行中被修改；
- `strict=True`：字符串 `"1"` 不能偷偷变成整数 `1`；
- `str_strip_whitespace=True`：字符串边界统一，但不会改写正文内容。

### 4.2 `IndirectInjectionCase`

每题保存 case ID、split、攻击/良性标签、taxonomy、问题、场景 tags、预期回答模式、required fact IDs、攻击 unit IDs、document/system/trace/tool canary 和任务成功预期。

validator 不只检查类型，还检查语义关系。例如：

- attack case 必须属于八个 attack taxonomy 之一；
- benign case 必须属于四个 benign taxonomy 之一；
- poison-only 必须预期 `security_filtered`；
- 非 poison case 不能伪造“Guard ON 应失败”的标签；
- chunk/unit ID 禁止 `:`，因为聚合键使用明确分隔，不能产生歧义；
- case 内所有 ID 必须唯一。

### 4.3 Dataset 级配额

`IndirectInjectionDataset` 不接受“差不多 36 题”，而是要求每个 split 精确：

```text
attack cases  24
benign cases  12
total         36
```

八个攻击类别和四个良性类别都必须各有三个变体。场景标签还要求覆盖 mixed clean/poison、poison-only、same-chunk fact+attack、split payload、parent/open context、metadata surface 和 top-ranked poison。

这避免开发者只生成最容易拦截的一类 `ignore previous instructions`，然后用一个好看的平均数掩盖覆盖缺口。

### 4.4 Fixture 对齐

`FixtureManifest` 表示 post-parser 的合成检索结果，不是私有真实语料。每个 candidate 保存 synthetic ID、rank、matched/context text、source metadata、fact IDs、attack unit IDs 和预期 Guard outcome。

`validate_dataset_fixture_alignment()` 检查：

- dataset 中每个 case 恰好有一个 fixture；
- candidate 和 open result 的 unit ID 唯一；
- required fact ID 在 fixture 的实际 fact text 中存在；
- same-chunk 场景真的同时含 clean fact text 和 attack payload；
- attack unit 和 benign unit 的预期 ADMIT/QUARANTINE 与 case 标签一致；
- parent/open/split/metadata 标签有对应的真实 fixture 面。

这一步防止标签写着“same chunk”，但实际 fixture 根本没把事实和攻击放在一起。

## 5. Dataset Builder 代码详解

### 5.1 确定性生成

`build_v1_bundle()` 从显式模板生成 dev/test，不调用 LLM，也不读取 Ollama。case ID、payload、canary、rank、source path 和 fact text 全由固定规则构造。同样的参数会生成逐字节相同的五个文件。

builder 使用临时 sibling 目录完成全部文件和 hash 后再 rename。目标已经存在时失败，不提供 force overwrite。这样不会留下“dataset 已写一半、manifest 还没写”的半成品。

### 5.2 为什么 dev/test 文本不同

两边使用相同 taxonomy 和配额，但 payload、question、canary 和 fixture 文本不同。dev 用于查看失败和修代码；test 在冻结后只用于最终回归。test 是公开可见的 frozen regression，不冒充真正 unseen benchmark。

### 5.3 五个冻结文件

```text
indirect_injection_dev_v1.json
  bytes   45292
  sha256  18d042c21e7cbc46f90859c59cbc440566de636009080de763253a8ab7598064

fixtures_v1/dev/manifest.json
  bytes   78024
  sha256  d53a48b08d823adf3ac0823e5c27506297a4ad0cc727d6f1accc3df6e9009ad4

indirect_injection_test_v1.json
  bytes   45565
  sha256  062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c

fixtures_v1/test/manifest.json
  bytes   77779
  sha256  eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d

indirect_injection_test_v1.manifest.json
  bytes   1217
  sha256  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
```

注意最后一个 hash 是 freeze manifest 自身的 hash。manifest 内又记录 test dataset 和 fixture 的精确 bytes/hash、36/24/12 配额、taxonomy/scenario counts、冻结时间和冻结起点 HEAD。

### 5.4 Hash-first loader

`load_security_bundle()` 对 test 的顺序是：先定位安全相对路径，再读取 freeze manifest，再计算 dataset/fixture hash，最后才解析 case 并交给 evaluator。篡改 test 文件时，`evaluate_paired()` 不会被调用。

## 6. Paired Runner 代码详解

### 6.1 `CountRate`

每个比例都保存：

```text
numerator
denominator
rate
status = applicable | not_applicable
```

分母为 0 时，rate 不是伪造的 0 或 1，而是 `None/not_applicable`。这样“没有 poison-only case”不会被误报成 100% 正确。

### 6.2 固定资源预算

`DeterministicSecurityConfig` 固定：

```text
top_k             1
candidate_k       4
max_search_calls  1
max_open_calls    1
max_steps         3
max_context_chars 50000
```

OFF/ON 共用同一个 config、question、candidate order、fixture、user context、nonce 算法和 fake chat。`_input_fingerprint()` 验证成对输入完全一致，防止 OFF 故意拿难题、ON 拿简单题。

### 6.3 Guard OFF 不是生产开关

`_PassThroughGuard` 只存在于 evaluator 文件。它返回 admitted decision，并准确累计原始/规范化字符数。CLI 没有 `--guard-off`，API 没有 Guard OFF 参数，环境变量也不能关闭默认 Guard。

因此基线的含义是“在同一套 Agent 代码中依赖注入一个 evaluator-only pass-through”，不是上线服务被临时关防护。

### 6.4 Recording adapters

`_RecordingGuard`、`_RecordingAdmission` 和 `_RecordingController` 不改业务判断，只记录内容是否到达关键边界。runner 分别检查：

- attack unit 是否被 Guard quarantine；
- 是否进入 admitted tool execution；
- 是否进入 Controller/EvidenceLedger；
- 是否进入 nonce-bound structured prompt record；
- 是否进入 verifier/source/claim/answer；
- 是否进入 public trace；
- 是否触发 forbidden tool 或 network egress。

传播检查使用结构化对象递归扫描，不依赖把整个 JSON 字符串做一次 substring。这样 Base64 或 JSON escaping 不会造成假阴性。

### 6.5 Fake chat 的正确含义

`_DeterministicCompliantChat` 是 propagation witness。它从 fresh nonce 包围的 admitted evidence JSON 中解析 records；看到 fixture 定义的攻击 unit 时，按固定规则回显 synthetic canary 或 forbidden action。它不判断“答案好不好”，也不模拟 Qwen 的概率行为。

OFF 出现 document canary，证明恶意文本可以到达生成边界并被合法 response parser/citation path 接受。ON 不出现 canary，证明软件边界切断了这条固定传播路径。

### 6.6 No-egress boundary

`_NoEgressBoundary` 在进程内拦截：

- `requests` transport；
- `urllib`；
- `socket.create_connection`；
- `socket.socket.connect/connect_ex`。

测试包含一个正向校准，即主动尝试 inert `.invalid` 地址并确认被 blocker 捕获。否则“0 次 egress”可能只是监控器根本没工作。

### 6.7 Task utility 与恢复

安全评测不能只追求全拒绝。runner 同时计算：

- clean task success；
- attack task success OFF/ON；
- mixed recoverable success；
- poison-only `security_filtered` correctness；
- post-Guard required-fact coverage；
- recovery rate，即 OFF 失败但 ON 成功的可恢复任务比例；
- top-up count 和 bounded resource violations。

这能识别一个“安全但没用”的 Guard。例如把所有内容都 quarantine，会得到 0 attack success，但 clean task success 和 benign quarantine gate 会失败。

## 7. Writer 与 CLI 代码详解

### 7.1 18 个 exact checks

`ReleaseGate` 要求固定顺序的 16 个 behavior checks，再加 2 个 R1 checks。少一个、多一个或调换成伪造 check 都不能通过 schema。

16 个行为门禁覆盖 ON 的 attack/canary/tool/egress/model-context 归零、quarantine recall、guard error、benign false positive、clean/mixed/poison-only utility、resource bound，以及 OFF 至少出现一个 model-context 与 document-canary exposure。

R1 两项检查 frozen hash mismatch 和 full pytest regression failure。check 的 observed numerator 必须与 manifest 的实际计数一致。

### 7.2 Provenance

manifest 记录：

- Git HEAD、branch、dirty、status entry count 和 dirty state SHA-256；
- untracked 文件不仅记录名字，还把文件内容 hash 纳入 dirty fingerprint；
- 运行前后重新采集 Git provenance，任何变化都在发布前失败；
- Python/platform；
- `requirements.txt` 的路径、hash 和 `pinned-direct-requirements` 类型；
- 排序后的 `python -m pip freeze --all` hash 与包数量，不保存可能带本机路径的原文；
- Guard detector version、ruleset path/hash 和扫描预算；
- dataset/fixture/R1 hashes；
- evaluator path/hash/argv；
- synthetic index 的明确 N/A hash、corpus hash 和 chunking strategy；
- corpus hash 必须等于 fixture manifest hash。

### 7.3 内容泄漏防护

安全产物只保存 synthetic IDs、布尔值、计数和 hash，不保存 question、fixture raw text、prompt 或 canary。

`_assert_content_free()` 在发布每个 artifact 前检查：

- 原始 fixture text；
- JSON escaped fixture text；
- NFKC + casefold 变体；
- document/system/trace canary；
- Windows drive、UNC、device 和 Unix absolute paths；
- API key/token/password/bearer/private-key/AWS/GitHub token patterns。

`redact_security_artifact_text()` 先清理 pytest 失败输出，再由 writer 做第二次拒绝式检查。前者是 best-effort redaction，后者是 fail-closed publish boundary。它不是通用 DLP，也不保证识别所有秘密格式。

### 7.4 不可变发布

`publish_security_run()` 的顺序是：

```text
validate manifest/result consistency
-> create same-parent staging directory
-> write seven content artifacts
-> scan forbidden content
-> calculate checksums and artifact evidence
-> write final manifest
-> reparse/rehash every artifact
-> atomic rename to final run ID
```

目标 run ID 已存在就失败，没有 force。`CON`、`NUL`、`COM1.txt`、`LPT9` 和尾点等 Windows 不安全名称也在 CLI 和 Pydantic manifest 两层拒绝。

### 7.5 CLI 顺序

`scripts.eval_indirect_injection.main()` 严格执行：

```text
validate run ID / refuse overwrite
-> record start Git and installed dependency fingerprints
-> verify three R1 frozen hashes
-> load and hash-check D6 bundle
-> paired evaluate
-> run full pytest
-> verify Git state unchanged
-> construct strict manifest and release gate
-> redact and publish immutable artifacts
-> return 0 only when release gate passes
```

R1 hash或 test freeze hash 不匹配属于 precondition failure。evaluator 尚未运行，因此没有伪造一个“FAILED protocol-compliant run”目录。这个限制在错误信息和文档中明确保留。

## 8. 测试先行和故障闭环

### 8.1 初始 RED/GREEN

五个 D6 模块都先写测试。第一次运行分别因模块不存在或接口不存在产生预期 RED；实现最小 contract 后逐组转绿。最终 D6 focused suite 是：

```text
91 passed, 3 known SWIG warnings
```

### 8.2 实际发现并修复的问题

| 问题 | 为什么危险 | 回归与修复 |
|---|---|---|
| `chunk-1` substring 命中 `chunk-10` | unit outcome 可能归错攻击单元 | 改为严格分隔解析，并禁止 chunk ID 含 `:` |
| prompt parser 取第一个任意 `matched_text` | 可能扫描到非本次 nonce 的文本 | 只解析 fresh nonce 包围的 evidence JSON |
| OFF pass-through normalized length 不准 | 资源指标失真 | 按真实 Guard contract 计算长度 |
| dev 成功也标 frozen pass | 夸大证据范围 | 新增 `PASSED DEV DIAGNOSTIC` |
| writer 接受 Pydantic scalar coercion | manifest 类型可能悄悄被修 | strict/frozen/extra-forbid schema |
| dirty hash 只含 untracked 文件名 | 内容变化但 provenance 不变 | 对每个 untracked regular file 加内容 hash |
| pytest 失败会带 fixture 原文 | ignored run 仍可能泄漏合成攻击正文或本机路径 | fixture-aware redaction + fail-closed writer scan |
| same-chunk 标签未验证真实 fact text | 场景名和 fixture 可不一致 | alignment 必须同时看到 clean fact text 和 attack |
| JSON escaping 造成传播假阴性 | raw substring 扫描不可靠 | Controller/model/verifier/trace 使用结构化递归检查 |
| top-up 只看单次 outcome | 两次调用各合法但累计越界可能漏报 | 累计 search/open/top-up 并统一 resource violation |
| poison-only 混入普通 utility 分母 | task success 指标语义错误 | 由 tag 决定 applicable denominator |
| egress blocker 可能只是没生效 | 0 egress 没有校准 | 新增 direct socket 正向拦截测试 |
| URL 被改成 `http<absolute-path>` | 证据输出被错误脱敏，难以复核 pytest 文档链接 | drive regex 增加前置边界，保留 `https://` |
| Git 命令失败时返回空 provenance | 可能伪造 clean state | 所有 Git subprocess 非零都 fail closed，HEAD 必须 40 hex |
| release checks 可缺失或伪造 R1 expected | gate 可以“自己证明自己” | exact 18-check sequence，R1 expected 单一常量源，计数互相绑定 |
| 泄漏规则只看大写 canary/少数路径 | 小写、UNC/device、secret assignment 可漏 | NFKC/casefold、escaped text、路径与凭据模式测试 |
| Git 只在评测后采集 | 无法证明运行期间代码稳定 | 运行前/后指纹比较，manifest 使用前置快照 |
| index/corpus 只写名字 | 无法复核到底评了哪份 fixture | index N/A 原因、corpus SHA-256、chunking 和 hash binding |
| `CON` 等名字通过正则 | Windows 创建/rename 行为不可靠 | shared Windows-safe run ID validator |
| 根状态日期测试仍锁定 D5 日期 | D6 文档正确更新后公开仓库合同失败 | `1 failed / 13 passed`，同步日期断言后 `14 passed` |
| 安全测试源码含完整 synthetic private-key marker | public audit 不区分测试意图，公开源码仍不应保留完整敏感 marker | 运行时拼接两个无害片段，保留测试语义并使 audit 从 1 finding 归零 |
| 教学日志手抄 freeze-manifest hash 时交换了相邻字符 | 人眼看长摘要很容易误抄，错误文档会破坏复现 | 以 `Get-FileHash` 六文件机器核对为准并修正文档，不修改冻结数据 |
| 历史 `05_results.md` 末尾有孤立代码围栏 | 后续 D6 内容可能被 Markdown 渲染成整段代码 | 围栏计数检查定位到文件末尾，删除多余标记后恢复成对 |

最后三类 review 修复的测试过程为：

```text
artifact leakage expansion   8 expected failures -> 29 passed
retrieval/Git/run-ID gaps    34 failures -> 44 passed
dependency provenance        3 failures -> 47 passed
all D6 tests                                91 passed
```

这里 `34 failures` 中大部分是新必填 retrieval 字段使旧 helper 连锁失败，不表示突然出现 34 个独立 production bug。日志保留这个区别，避免用测试数量制造夸张叙事。

## 9. 三次 dev 诊断为什么都保留

### 9.1 dev-01

```text
run_id    r2-s1-d6-dev-20260718-01
status    PASSED DEV DIAGNOSTIC
manifest  ef244126d1dbffadf9fca46c384085a5f9e433c9484bfc568c43d7ce8736e811
```

行为门禁通过，但 `test_output.txt` 中 pytest 文档 URL 被错误 path sanitizer 改成 `http<absolute-path>`。这不是 Guard 行为失败，而是证据质量失败。run 不覆盖、不删除，作为问题发现记录。

### 9.2 dev-02

```text
run_id    r2-s1-d6-dev-20260718-02
status    PASSED DEV DIAGNOSTIC
manifest  ee9e720be9321b33f50f72f061e0c67c5470d24c732c24f44e2d6c15c4e0aacc
```

URL sanitizer 修复后，pytest URL 可读，全仓当时 `757 passed`。随后独立 review 又发现 gate/provenance/leakage 的结构问题，因此它也不是最终 dev 证据。

### 9.3 dev-03

```text
run_id    r2-s1-d6-dev-20260718-03
status    PASSED DEV DIAGNOSTIC
manifest  259f660e82248716fe9fc962537a69dbcdc64e78262b39a6429c3ef23f538f93
full      788 passed, 3 warnings
```

这是所有 review remediation 完成后的最终 dev 诊断。它与正式 test 使用同一个 evaluator SHA-256：

```text
f3e2fae9aa35ae4f918f4c08634101f1aa434e0d08270e59ee25a445951f27af
```

## 10. Frozen Test 最终结果

### 10.1 OFF/ON 安全对照

| 指标 | Guard OFF | Guard ON |
|---|---:|---:|
| attack success | 21/24 | 0/24 |
| document canary exposure | 21/24 | 0/24 |
| model-context exposure | 20/24 | 0/24 |
| attack-task success | 6/20 | 20/20 |
| forbidden tool call | visible in composite attack outcome | 0/24 |
| external egress attempt | visible in composite attack outcome | 0/24 |

OFF 的 21/24 不是 live model attack rate。它是 deterministic fake generator 对已传播攻击单元的固定响应。20/24 model-context exposure 与 21/24 document exposure 不相同，是因为不同 taxonomy/surface 的攻击触发位置不同，这两个指标故意分开报告。

### 10.2 Guard ON detection 与 utility

| 指标 | 结果 |
|---|---:|
| quarantine recall | 28/28 |
| benign quarantine | 0/32 |
| clean task success | 12/12 |
| mixed recoverable success | 20/20 |
| poison-only security_filtered correctness | 4/4 |
| post-Guard evidence coverage | 32/32 |
| recovery | 14/14 |
| resource-bound violations | 0 |
| Guard p50 / p95 | 0.2711 ms / 0.4572 ms |

28 个 attack units 多于 24 个 attack cases，因为 split/多面场景可以在一题中包含多个恶意内容单元。32 个 benign units 也不是 12 个 benign cases，因为 mixed attack cases 同时含需要保留的 clean units。

latency 只反映这台机器上的 deterministic rule scan，不是生产 SLA，也不包含 Ollama 推理。

### 10.3 Provenance

```text
HEAD                       0946ad90a7d9b54e219006b271c7c7bdc440863c
branch                     codex/rag-eval-system
dirty state SHA-256        77cbc928b638df2d73b836c414210454cfdfccc27d14ca6acb5088216c8d03b3
dataset SHA-256            062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
fixture/corpus SHA-256     eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
Guard ruleset SHA-256      78ed0509144820ccd05aff61c1509357dd8fe3dbfc8a0c6df30fc304a15e9cd2
evaluator SHA-256          f3e2fae9aa35ae4f918f4c08634101f1aa434e0d08270e59ee25a445951f27af
installed package count    75
installed snapshot SHA-256 d15f7750cf1df9e44b838e2d9f7210816195535bdcb64bba5fce8b9c64c825b9
```

运行时 HEAD 是 D5 commit，D6 文件仍处于 dirty worktree，所以 manifest 同时记录完整 dirty fingerprint。核心 evaluator、ruleset、data、fixture 和 dependency 都有单独 hash，不能只靠 HEAD 猜测运行内容。

## 11. 产物说明

本地 ignored 目录：

```text
security_runs/r2-s1-d6-test-20260718-01/
```

八个文件：

| 文件 | 内容 |
|---|---|
| `manifest.json` | run identity、provenance、18 gates、artifact hash、limitations |
| `summary.json` | OFF/ON aggregate metrics 与 release result |
| `per_case.jsonl` | 72 条 content-free case outcome |
| `failures.csv` | ON case/gate 失败；本次只有表头，0 failure rows |
| `red_green_evidence.md` | 最小 OFF/ON 对照摘要 |
| `commands.txt` | 规范化 evaluator 与 pytest 命令 |
| `test_output.txt` | 脱敏后的全仓 pytest 输出 |
| `checksums.sha256` | 六个内容 artifact 的 SHA-256 |

独立复核结果：8 files，7 个 artifact evidence entries 加 manifest 本身，content checksums 全匹配，manifest SHA-256 为：

```text
fe45b091f4f76c57919dae987186088433a5f7aa5293f7104de9eb09317f4564
```

## 12. 可以说和不能说

### 12.1 面试中可以准确说

> 我把 retrieved content 当成不可信输入，在 ACL 后、Controller 前做 content-unit quarantine，并用同输入 Guard OFF/ON 的 deterministic paired evaluator 验证数据传播。固定 test 上 OFF 有 21/24 攻击传播成功，ON 为 0/24；同时 clean task 12/12、mixed recovery 20/20、benign false positive 0/32。数据、规则、evaluator、依赖和 artifact 都有 hash provenance。

### 12.2 必须附带的限制

- dataset 是 synthetic、visible frozen regression；
- fake generator 证明传播，不代表 Qwen 攻击成功概率；
- regex/normalization Guard 不是通用语义安全证明；
- artifact secret/path scan 是 defense in depth，不是完整 DLP；
- 真实 IAM、多模态、任意编码深度、跨任意距离组合攻击不在 D6 范围；
- 本条是 D6 完成时的历史限制；D7 live Qwen/BGE-M3 后续已完成，但人工红队和独立 holdout 仍未完成。

## 13. 面试高频问题与参考回答

### Q1：为什么不是只改 system prompt？

因为恶意文本在 prompt 之前已经可能进入 Controller、EvidenceLedger、extractive response 和 citation verifier。只告诉模型“不要听文档指令”是概率控制，不能阻止其他 deterministic 组件消费投毒内容。我的主边界放在 retrieval ranked pool 与 Controller 之间，prompt nonce/JSON envelope 只是第二层防御。

### Q2：为什么一定要有 Guard OFF？

如果只跑 ON 得到 0/24，无法判断是 Guard 生效，还是攻击 fixture 根本没有走到模型。OFF 的 model-context 20/24 和 document-canary 21/24 校准了评测敏感性，证明 baseline 真的会暴露。OFF 只通过 evaluator dependency injection 提供，没有生产开关。

### Q3：fake LLM 有什么价值？

它把随机模型行为从 propagation test 中拿掉。只要攻击 unit 到达 nonce-bound evidence record，fake 就固定触发 canary，因此结果可复现。它回答“软件边界是否允许攻击数据传播”，不回答“某个真实模型有多容易被骗”。后者留给 D7 live paired trial。

### Q4：为什么 attack success 和 model-context exposure 分开？

context exposure 是内部边界事实，attack success 是外部复合结果。文本进入 context 不一定被 fake 触发或出现在 response；反过来，某些 response/source path 也可能暴露 canary。分开后可以定位失败是在 admission、prompt、generation、verifier、response 还是 trace。

### Q5：为什么不能把所有命中都拒绝？

企业 RAG 还要可用。D6 同时要求 0/32 benign quarantine、12/12 clean success、20/20 mixed recovery 和 32/32 evidence coverage。全拒绝虽然 attack success 是 0，但会在 utility gate 上失败。

### Q6：top-up 为什么只能一次且不能重新检索？

Guard 删除 top-ranked poison 后需要补干净候选，但无界 rewrite/re-embed 会放大成本和攻击面。系统在一次 ACL-visible `candidate_k=4` 排名池内最多补位一次，不改变查询、不访问额外 tenant 资源，预算可证明。

### Q7：为什么引用校验不能防 prompt injection？

引用校验只能确认回答是否被可见证据支持。恶意文档本身就包含 canary 或攻击指令时，复制它反而会获得很高 lexical support。D2 已证明 canary 在 cited evidence 中时 verifier 可以给 1.0，因此内容 admission 必须先发生。

### Q8：为什么不用另一个 LLM 当安全 judge？

D6 的 hard gate 需要稳定、便宜、可复现，核心判断是结构化传播、unit outcome、canary、tool/egress 和 task facts，不需要主观 judge。LLM judge 可作为后续语义覆盖补充，但它本身会受 prompt injection、版本漂移和评分不一致影响，不能替代 deterministic boundary tests 与人工 review。

### Q9：如何证明 OFF/ON 输入相同？

runner 对 question、candidate order、fixture unit、user context、config 和 nonce 建 canonical input fingerprint；成对结果必须一致。唯一允许变化的是 Guard implementation。这样 ON 的提升不能来自换题或换检索排序。

### Q10：为什么 test 不是 held-out？

文件已经提交并可见，所以诚实名称是 frozen visible regression。它在冻结后不用于继续调 detector，但任何人都能看到。真正泛化结论需要独立 holdout、人工红队或持续新增攻击分布。

### Q11：provenance 为什么同时要 HEAD 和 dirty hash？

D6 在尚未 commit 的实现上运行，只有 HEAD 会错误指向上一阶段代码。dirty fingerprint 把 tracked diff 和 untracked 文件内容纳入；同时 evaluator、ruleset、dataset、fixture 和 dependency 各有 hash。运行前后还比较 Git 状态，防止测试过程中代码变化。

### Q12：为什么 `pip freeze` 只存 hash 不存全文？

全文可能含 editable install 的本机路径，违反 artifact 零绝对路径要求。排序后 hash 和包数可以比较环境是否相同；`requirements.txt` 的路径/hash另行记录，说明声明依赖。两者结合比只写 Python 版本更可复现。

### Q13：为什么每个比例都保存分子分母？

单独写 100% 会隐藏样本量，也会误处理零分母。`28/28` 和 `1/1` 风险不同；没有 poison-only case 时更不能写 100%。`CountRate` 用 `not_applicable` 明确表达无分母。

### Q14：本次最有价值的工程故障是什么？

不是 Guard 规则失败，而是 dev-01 的证据 sanitizer 把正常 HTTPS URL 当 Windows drive path。行为 gate 虽通过，证据却不可读。我保留不可变 run，新增 URL 回归，修复 regex，再用新 run ID 重跑。这说明评测基础设施本身也要被测试，不能只相信退出码。

### Q15：下一步为什么是 D7？

D6 已证明 deterministic software boundary。剩余最大未知是固定本机 BGE-M3 + Qwen 在同一 OFF/ON case 上的真实行为、延迟和模型失败。D7 会单独标注 live、记录模型/Ollama/index identity，并保留 deterministic 与 live 指标的语义隔离。

## 14. 复现命令

先跑 focused D6：

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests\evaluation\test_indirect_injection_contracts.py `
  tests\evaluation\test_indirect_injection_dataset.py `
  tests\evaluation\test_indirect_injection_runner.py `
  tests\evaluation\test_indirect_injection_writer.py `
  tests\evaluation\test_indirect_injection_cli.py
```

重新运行时必须换新 run ID，不能覆盖历史：

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_indirect_injection `
  --split dev `
  --run-id <new-unique-dev-run-id>
```

冻结 test 已于 D6 正式运行，不应用它继续调规则。若只做完整回归，使用 pytest；不要为了得到另一个好看的 frozen status 反复试参。

## 15. 最终工程门禁

```text
D6 focused tests                 91 passed
full repository tests           788 passed, 3 known SWIG warnings
repository/config tests          14 passed
pip check                        No broken requirements found
compileall                       exit 0
public repository audit          380 candidates / 0 findings
R1 frozen hashes                 3/3 exact
D6 frozen test hashes            3/3 exact
accepted run manifest/hash       exact
unfinished markers               0
changed Markdown fence balance   0 unbalanced
git diff --check                 exit 0
ports 8000/8501                  0 listeners
project Python processes         0
Ollama process                   1, intentionally retained for possible D7
```

3 条 warning 来自已知 FAISS SWIG type deprecation，不是 D6 失败。D6 命令没有请求 Ollama；保留 Ollama 进程不等于 D7 已运行。

## 16. 当前验收断点

D6 deterministic dataset、paired evaluator、immutable artifacts、R1 regression 和 frozen test gate 已完成。D6 命令本身没有调用 Ollama/BGE-M3/Qwen；这些模型只在后续独立 D7 run 中调用。

下一条授权命令必须是：

```text
历史授权命令（已执行）：`批准D6，执行D7本地真实模型成对评测`。当前结果见 [D7 Engineering Journal](09_d7_engineering_journal.md)。
```

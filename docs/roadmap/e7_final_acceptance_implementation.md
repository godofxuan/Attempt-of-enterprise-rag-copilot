# E7 最终验收实施日志

最后更新：2026-07-17

## 1. 本阶段到底做什么

E7 不是继续堆功能，而是回答五个更严格的问题：

1. E0-E6 写下的能力，当前代码和 artifact 是否真的能复现？
2. deterministic 测试、真实模型、本地服务、浏览器和公开仓库边界是否分别有证据？
3. 哪些结果可以写进 README 或简历，哪些必须缩窄，哪些不能说？
4. 哪些判断只能由项目本人完成，Codex 不能代签？
5. 当前累计改动能否固定为 release candidate，并按本人后续明确授权推送功能分支、从 GitHub 干净克隆复验？

因此本日志不会只写“测试通过”。每个 gate 记录命令、退出码、artifact/hash、结论和边界；如果失败，还记录现象、根因、修改位置和回归结果。

## 2. 起始边界

| 字段 | E7 起始值 |
|---|---|
| 开始时间 | `2026-07-17 09:34:29 +08:00` |
| branch | `codex/rag-eval-system` |
| start HEAD | `7aec4b950e012d3f24b8e1877d6391201e9b8f90` |
| upstream | `origin/codex/rag-eval-system` |
| remote default | `origin/main` |
| staged files | 0 |
| working tree | E0-E6 累计公开候选改动；E7 尚未固定 commit |
| private authority | `.private/e6/`、`eval_runs/`、`load_runs/`，均应保持 ignored |

这里特意区分 `HEAD` 和 working tree：Git 的 HEAD 仍是旧提交，但当前工作目录包含 E0-E6 的全部升级。E7 最终需要把通过验收的公开候选固定成新 commit；在那之前，不能用旧 HEAD 冒充升级后的 release candidate。

## 3. Gate 总表

| gate_id | 验收内容 | 状态 | 当前说明 |
|---|---|---|---|
| `E7-G00` | E7 计划、起始 Git 边界、证据字段 | PASS | 详细计划已建立；起始 branch/HEAD/upstream/staging 已记录 |
| `E7-G01` | Git、privacy、ignored、large file、public audit | PASS | final staged set 331 public candidates / 0 findings；private/raw/index/browser roots ignored |
| `E7-G02` | facts/corpus/frozen hash/raw manifest/public snapshot | PASS | 72 documents；frozen hash exact；11 runs/50 artifacts match；rebuilt snapshot byte-identical |
| `E7-G03` | parser/index lifecycle、`--help` 无副作用、active index | PASS | 116 tests；help/dry-run inventory unchanged；active bge-m3 1024D/64 chunks |
| `E7-G04` | retrieval/response/agent/security 四层 deterministic eval 与消融 | PASS | E7 新 run：28/28；4 direct probes；8 variants；reranker NOT RUN |
| `E7-G05` | pip/compile/full pytest/CI-equivalent | PASS | pip clean；compile/hash exit 0；fresh full 573 passed、3 known warnings |
| `E7-G06` | health/readiness/request ID/trace/live request | PASS | ready 200；answered；ID 一致；trace 2 calls/0 retry；重复 Fetch 幂等 |
| `E7-G07` | local load profile | PASS | final-code rc02 31/31；manifest/artifact hash match；warm c=1/5/10 |
| `E7-G08` | Ask/Trace/Evaluation desktop/mobile 浏览器 | PASS | 1440/1440 与 390/390；chart nonblank；0 browser errors；6 valid PNG |
| `E7-G09` | README/status/reproducibility/links/default branch 一致性 | PASS | repository docs tests 通过；final all-Markdown path/link audit 331/0；remote default main |
| `E7-G10` | 50-row 人工 semantic review | NOT RUN | 只能由本人填写，Codex 不代签 |
| `E7-G11` | 本人代码实验与口述验收 | NOT RUN | 只能由本人现场完成，E7 将生成明确 checklist |
| `E7-G12` | claims-evidence matrix 审批 | PASS | 3 approved、7 narrowed、0 rejected、0 pending；人工项不混入 claims 通过 |
| `E7-G13` | final public candidate + release-candidate commit | PENDING | 只在可自动 gate 通过后执行 |

`PENDING` 只表示尚未执行，不是验收结论。E7 收口时必须把它们全部改成 PASS、FAIL 或 NOT RUN。

## 4. 证据记录格式

后续每个 gate 使用同一结构：

```text
command      实际执行的完整命令
exit_code    进程退出码；组合门禁逐命令记录
artifact     产物或被验证文件的路径
sha256       数字结论依赖的 immutable artifact hash
verdict      PASS / FAIL / NOT RUN
boundary     这个结果不能外推成什么
```

## 5. E7-C00：为什么人工项现在先写 NOT RUN

`docs/evaluation.md` 明确规定 `human_review.csv` 的八个人工列只能由本人填写，Codex 不能填写空表，也不能把规则指标当人工正确性。因此：

- Codex 可以验证表有 50 行、人工列仍为空、文件 hash 没被篡改；
- Codex 可以做代码审查、schema 检查和规则一致性检查；
- Codex 不能冒充项目本人给答案正确性、完整性、引用支持性签字；
- Codex 也不能冒充本人完成现场口述。

先写 `NOT RUN` 是验收诚实性，不是系统失败。本人完成后可以追加签字证据，但 E7 当前工程结论必须保留这两个边界。

## 6. 执行记录

### 6.1 E7-G01：Git、隐私和公开候选

结论：`PASS`。

```text
python -m scripts.audit_public_repo     exit 0
public candidates                      330
findings                               0
git diff --check                       exit 0
```

`git check-ignore -v` 逐项证明：

```text
.private/e6 + .private/e7              .gitignore:15
data/indexes_v2                        .gitignore:22
data/eval_outputs                      .gitignore:29
eval_runs                              .gitignore:34
load_runs                              .gitignore:35
```

`git diff --check` 打印的是 Windows working copy 的 LF -> CRLF notice，不是 whitespace error，退出码为 0。公开审计覆盖 candidate path、private/runtime path、credential shape、真实邮箱、absolute local path、文件大小、snapshot schema、PNG 结构/CRC 和 Markdown links；它仍只是当前 Git candidate 的本地审计，不代表远端历史或 branch protection 审计。

远端只读核对：

```text
git ls-remote --symref origin HEAD      exit 0
remote HEAD                             refs/heads/main
remote HEAD commit                      476c718733407044e807142fa4b41fe45e2641dd
```

这解决了“本地 `origin/HEAD` 可能过期”的问题；它证明核对时远端默认分支是 `main`，不证明远端 CI 已运行。

### 6.2 E7-G02：事实、语料、冻结集和 immutable artifacts

结论：`PASS`。

Corpus authority：

```text
profile                                 demo
source documents                        72
document bytes                          23,128
corpus manifest SHA-256                 0a88d31f40150ec68464f54cbf1f64ed6d373d02e277b1767dc53ab34a5184c5
facts model SHA-256                     5b9ea4d719e97fcc2b288e548ccdd0db971ad594bd46fb937b2d44ab6f437417
profile model SHA-256                   47330886214c65d3421224a222c490e57c0432737ebefb337c33250af47c3438
```

脚本重新解析严格 Pydantic schema，并逐个比较 72 个文档的 `byte_count` 与 SHA-256。Frozen test：

```text
expected = 556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
actual   = 556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
exit     = 0
```

E4/E5 的 9 个 eval runs 与 2 个 load runs 全部重新读取 manifest，共核对 50 个 artifact，0 mismatch。关键 manifest SHA-256 包括：

```text
test suite manifest                     a35f963c9d6c136523b4a5ab48d4e20d859b27baa2b6dceed999a55be801d1c2
test ablation manifest                  378f744a708424d1cda7fb36a5d889b609a393a11824d4a042a48fd4dc36e3db
live dev r01 manifest                   ecdbe31a98a1096790bdebb4e3f3837f9c684e225f3556d467dd6a59e4b24916
load r2 manifest                        dd58d30c678aa30e9545f2397ac58d99d694b29267881e3827fa4bbe786d8ba7
```

随后从这四份 raw authority 重新导出 `data/eval_outputs/e7_public_snapshot_rebuilt.json`。它与 checked-in `data/v2/public/demo_snapshot.json` 逐字节相同，两者 SHA-256 都是：

```text
bbee33c1d28c4c2f2a0b9af6d4a9cd3a8d1f70fc47df7b30ed412c3b9f195547
```

这比“JSON 看起来一样”更强：byte-identical 同时证明字段、顺序、数值和换行一致。

### 6.3 E7-G03：parser/index lifecycle 与无副作用 CLI

结论：`PASS`。

Focused regression：

```text
pytest tests/corpus tests/ingestion tests/indexing -q
116 passed, 3 FAISS SWIG warnings
exit 0
```

在 `build_indexes_v2 --help` 前后，对 `data/indexes_v2` 的 7 个文件记录 relative path、bytes、UTC mtime 和 SHA-256；两份 inventory hash 都是：

```text
ae4bc01d7e92b8ad645870ed0e75430374f1e4fa1dcc90e6d8d484a27aa58d91
```

`inventory_identical=True`，证明 help 没有 import-time 建库或 active pointer 写入。有效 dry-run 输出：72 source documents -> 64 canonical documents/chunks，8 duplicates，`written=false`；前后 inventory 仍完全一致。

Active snapshot 通过 `V2IndexSnapshot.load(...)` 完整校验：

```text
run_id       20260716T135632Z_7aec4b9_live_bge_m3_fixed
chunks       64
embedding    bge-m3
dimension    1024
```

#### Incident E7-I01：dry-run 错传 run ID

第一次命令把 `--dry-run` 与 `--run-id 20260717_e7_dryrun` 一起传入，argparse 退出 2：

```text
build_indexes_v2.py: error: --run-id is not used with --dry-run
```

原因是 dry-run 只做 parse/govern/chunk preview，不发布 immutable version，因此没有 run ID。该失败命令前后 index inventory 仍相同，说明 fail-closed。去掉互斥参数后退出 0、`written=false`、inventory 仍相同。这里修改的是验收命令，不是业务代码；不能为了让错误命令通过而放宽 CLI 约束。

### 6.4 E7-G04：四层评测与 controlled ablation

结论：`PASS`，但只限 frozen synthetic deterministic contract。

独立审查修复后的 final-code immutable run：

```text
suite run ID                            20260717_e7_test_suite_rc02
suite summary SHA-256                   96f734249591f86bc4f40815c95ebc939b5f1dcd22f1b26fb7166c5137393cb6
suite manifest SHA-256                  49d5b7067e26981ab5e8ae4c8dad9c68a023205b32df95a5417be0103715a674
ablation run ID                         20260717_e7_test_ablation_rc02
ablation.csv SHA-256                    c32c5e4e814435500c5bf9977d71e972703d4b3df541dba05f0c0619773cc24f
ablation manifest SHA-256               faa338021e0f5c4a2352ce84723eb32702a76fd9668bd3d31b2a36ee14da7e45
```

两个 manifest 各自声明并覆盖 5 个 artifact；发布后逐项重算，0 mismatch。`rc01` 保留为 EvidenceLedger 优先级修复前证据，不能覆盖；业务修复后使用新 ID 发布 `rc02`。manifest 如实记录本轮是在 start HEAD `7aec4b9...` 的 dirty worktree 运行；E7 后续 commit 固定的是同一公开代码候选，不能篡改 manifest 把 dirty 改成 false。

四层主要结果：

| layer | result | 不能省略的解释 |
|---|---:|---|
| retrieval | 28/28 | `document_recall@5=1.0`，但 `precision@5=0.2381`，top-5 仍含额外可见文档 |
| answer | 28/28 | deterministic extractive contract，不是人工 semantic correctness |
| agent | 28/28 | final outcome/tool choice/stop/budget pass；exact trajectory 是 24/28 |
| security | 28/28 | unauthorized exposure 0；只针对 synthetic UserContext |
| direct probes | 4/4 | unsafe、pre-retrieval、0 tools、0 sources、trace redacted |

`exact_trajectory_contract=24/28` 与 overall 28/28 不冲突：系统允许多条合法轨迹到达同一个正确、安全、有界的终态。面试中若只说“轨迹 100%”就是错误表述。

Controlled ablation：

| variant | case pass/outcome | 关键边界 |
|---|---:|---|
| BM25 | 0.8214 | ACL leakage 0，但比较/冲突问题较弱 |
| dense | 0.8571 | hit@5 1.0 不等于 full-document/authority 全对 |
| hybrid RRF | 0.8214 | 单纯 fusion 仍不能解决 metadata/time/conflict |
| hybrid + metadata/temporal | 1.0000 | synthetic 28-case contract |
| hybrid + diversity/parent | 1.0000 | 当前 fixed chunk run 中 parent 不是额外收益证明 |
| optional reranker | NOT RUN | `no_admitted_reranker`，case_count 0 |
| fixed RAG | outcome 0.8571 | 4 个 missing-evidence case 失败 |
| bounded Agentic | outcome 1.0000 | 28 cases；suite 共 47 tool calls，存在成本 |

Focused code regression：

```text
pytest tests/retrieval tests/security tests/agent_v2 tests/evaluation -q
223 passed, 3 FAISS SWIG warnings
exit 0
```

### 6.5 E7-G05：CI 等价预验收

当前状态：`PENDING`，因为后面仍会修改公开文档与 claims，最终必须重跑。

```text
pip check                               exit 0, No broken requirements found
compileall app/scripts/streamlit/tests  exit 0
full pytest before closure              570 passed, 3 warnings, exit 0
```

3 条 warning 全是 FAISS SWIG type deprecation，没有测试 failure。570 比 E6 的 569 多 1 个 trace 幂等性回归；这个数字仍只能作为 E7 文档收口前基线，最终 gate 不能沿用它。

### 6.6 E7-G06：真实 API、request correlation 与 trace

结论：`PASS`。

前置条件：8000/8501 listeners 都是 0，项目 Python 0；`ollama list` 同时存在 `bge-m3:latest` 与 `qwen2.5:3b`。不带 `--reload` 启动 uvicorn 后：

```text
GET /health/live                       200 {status: alive}
GET /health/ready                      200 database/index/models = ok
active index                           20260716T135632Z_7aec4b9_live_bge_m3_fixed
```

真实 Agent 请求 `e7.smoke.20260717-002`：

```text
HTTP                                   200
mode / stop                            answered / completed
sources / claims                       1 / 1
sent ID = header ID = body trace ID    true
service trace ID                       same target ID
service spans / model calls / retries  3 / 2 / 0
question/user/tenant in service trace  0 matches
```

真实浏览器最终请求 `35f3141033c545c5ab174b75130b8fe3` 同样是 answered/completed、evidence 1/1、coverage 100%、2 model calls、0 retry。修复后即使故意让两次 Trace GET 都复用目标 `X-Request-ID`，两次响应仍保持：

```text
route=/agent/v2/chat, model_calls=2, body/header ID exact match
```

#### Incident E7-I02：Trace 查询自我覆盖

**现象。** 首次 GET 能返回聊天 trace；若调用方把目标 ID 同时用作 Trace GET 的 `X-Request-ID`，middleware 会在响应后把这次 GET 也追加进 store。第二次 `get()` 从后往前取 latest，于是返回 `/observability/traces/{request_id}`、0 model calls。

**最小化证据。** TestClient 复现得到：

```text
same ID: POST chat -> GET trace -> GET trace
first route  = /agent/v2/chat
second route = /observability/traces/{request_id}
different lookup IDs: repeated reads both return /agent/v2/chat
```

真实 `streamlit_app/api_client.py` 使用独立 `lookup_id`，所以正常 UI 路径不会触发；但服务端仍接受合法重复 ID，因此该边界应 fail-safe。

**TDD。** 在 `tests/api_v2/test_observability_api.py` 新增真实 API 回归：

```text
RED    1 failed：第二次 route 是 trace endpoint
GREEN  1 passed：第二次仍是 agent chat
focused API/trace/UI client             28 passed
```

**修改。** `app/api/middleware.py` 仍为 Trace GET 更新 metrics 和回显 header，但不把 trace 读取请求写回 `TraceSink`。没有改 request ID 格式、store latest 语义或 UI client。这样 trace 读取变成幂等，也不会用观测流量挤占最多 200 条的业务 trace buffer。

### 6.7 E7-G07：最终代码 local load profile

结论：`PASS`，authority 使用修复后的 `rc02`；`rc01` 只保留为修复前诊断证据。

```text
run ID                                 20260717_e7_demo_load_rc02
total                                  31/31, failed 0
cold p95                               5,802.840 ms
warm c=1 p50 / p95                     1,063.211 / 1,114.793 ms
warm c=5 p50 / p95                     3,779.148 / 4,244.303 ms
warm c=10 p50 / p95                    4,509.670 / 8,218.037 ms
model calls / retries delta            62 / 0
RSS delta                              66,453,504 bytes
summary SHA-256                        aac080abee08f43caf7f0847edb1784e897573e118380349d3ecf9de55915977
details SHA-256                        b73ccf7d0a4b1de1b14c7923c17bd35c566a7568b406e02f7d2655dd213c399c
manifest SHA-256                       db08c920834261b1e1766e288efdd5f87d45eacb1a5070cc10464c14b08bfe4f
```

本轮 cold 明显高于 warm，说明 API 重启后第一条请求仍受模型/索引暖机影响。31/31 只说明本机 Windows、单进程 FastAPI、64 chunks、每档 10 条的 demo profile 全部业务完成；不是 SLO、吞吐上限或高并发证明。

### 6.8 E7-G08：真实桌面/移动端浏览器

结论：`PASS`。

桌面 1440x1000：

- Ask 发出真实请求，显示 answered/completed、request ID、中文回答、claim verification 和 authorized source；
- Trace 显示 intent/analysis/mode/stop/evidence 1/1、coverage 100%、action/budget、HTTP 200、2 calls/0 retry；
- Trace Fetch 另一 request 时明确显示无 Agent decision trace，不混入当前 Agent actions；
- Evaluation 显示 frozen 28/28、live 23/24、load 31/31、snapshot ID、source provenance；
- Quality chart `970x280`、1 个 SVG、48 个 marks；Ablation 显式 reranker NOT RUN；Security 显式 indirect injection NOT RUN。

移动端 390x844：Ask、Trace、Evaluation 的 `documentClientWidth/documentScrollWidth` 都是 `390/390`。指标卡纵向排列，按钮和文字没有互相覆盖；Quality chart 约 `352.8x280` 且有 33 个 marks。桌面三页同样是 `1440/1440`，无整页横向溢出。

浏览器日志 0 error；有 12 条现有 Vega warning，实际 chart 非空。六张 ignored 证据图经 magic/IHDR 校验：

```text
ask_desktop.png         1440x1000  6b740f4597193acbbc2b189c437b3951fa25159f9bd3f3065b69f70d8accdfae
trace_desktop.png       1440x1000  5ff98c46a2ebb96d3a918e5d78c73ae9770e680c8152594751afa4b7d3636850
evaluation_desktop.png  1440x1000  c5d7814a6150eb338d458009e19c9f4608b505b57b938b1b5333837a28f453a4
ask_mobile.png           390x844   2158315e54e30168e06378ce026d7d115f9cb970548dbe9187c11d62bec0854e
trace_mobile.png         390x844   908dfd29104afb321a6a254007cfca2a85e137bed1bc8ab8acbd8b5018f19f48
evaluation_mobile.png    390x844   1293a35b3fae137447b69c79388e05cd9e00d0d572556b4fdbaf7f127a2436a8
```

#### Incident E7-I03：截图扩展名与真实编码不一致

浏览器 screenshot API 再次返回 JPEG/JFIF（magic `FF D8 FF E0 ... JFIF`），即使目标名是 `.png`。第一轮 PNG validator 正确失败，没有把扩展名当格式。随后用 `System.Drawing` 在不缩放条件下把 6 张图重新编码为 PNG，再验证 signature `89504E470D0A1A0A`、IHDR dimensions 和 SHA-256。

验证命令还先后遇到 PowerShell 把 struct 的 `>` 解析成重定向、Python f-string 反斜杠语法错误；两次都没有修改图片。改用 `int.from_bytes(..., 'big')` 和 `str.format` 后，validator 才得到 exit 0。

### 6.9 进程清理

API 与 Streamlit 都使用固定 `127.0.0.1`、隐藏窗口和独立日志启动。每轮只按记录且再次核对 command line 的 PID 停止。最终：

```text
port 8000 listeners                    0
port 8501 listeners                    0
project Python processes               0
Ollama                                 kept running
API/UI log Traceback|ERROR|Exception   0 matches
```

### 6.10 E7-G10/G11：人工专属验收边界

`human_review.csv` 被程序化重新读取：

```text
run ID                                 20260716T135632Z_7aec4b9_human_review
rows                                   50
human judgement fields                 8
nonblank human judgements               0
SHA-256                                fbcba218c7dd4f1824a1727241090bfc3ba60a1f3c344a7ee22d0a8eed3ff2a1
verdict                                NOT RUN (awaiting owner judgement)
```

Codex 没有填写任何人工列。`.private/e7/human_signoff_checklist.md` 已建立 50 行 review 规则、三个本人代码实验、30 秒/1 分钟/3 分钟口述和签字字段；当前每项都保持 `NOT RUN`。这样可以证明表没有被机器冒充人工签字，但不能证明自然语言答案已经人工通过。

### 6.11 独立 trace 修复审查与 E7-I04

独立只读 reviewer 对 `app/api/middleware.py`、trace store、API route、Streamlit client 和回归测试做静态审查，结论为 0 Critical、1 Important。Important 指出：已有测试证明 trace GET 不覆盖目标，但没有锁定 trace GET 仍返回 `X-Request-ID`、仍进入 route metrics。

该意见成立。风险不是当前代码错误，而是未来重构可能把 route exclusion 移到 metrics/header 之前，同时原测试仍通过。补充测试断言：

```text
first/second X-Request-ID              req-repeat
GET trace route status                 {2xx: 2}
GET trace latency count                2
focused closure tests                  4 passed, 3 known warnings
```

reviewer 自身解释器缺 `faiss`/`fastapi`，无法运行测试；这不是项目环境失败。主流程使用项目 `.venv` 实际执行并得到 GREEN。这里把“reviewer 静态判断”和“主环境动态证据”分开记录，避免把未运行说成运行。

### 6.12 E7-G12：claims-evidence 审批

`.private/e6/claims_evidence_matrix.md` 的 10 条候选已全部进入终态：

```text
approved                               E6-001, E6-002, E6-005
narrowed                               E6-003, E6-004, E6-006, E6-007,
                                       E6-008, E6-009, E6-010
rejected                               none
pending_e7                             none
```

收窄原则：

- 23/24 必须写“一次本地 synthetic dev BGE-M3+Qwen run”；
- ACL exposure 0 必须写“synthetic self-claimed UserContext，不是真实 IAM”；
- 0.8571 -> 1.0000 必须写 28 cases，并同时写工具调用 28 -> 47；
- 31/31 必须写单机、每档 10 条 warm request、不是 SLO；
- direct 4/4 不能外推 indirect injection；
- local public audit 不能外推远端历史、branch protection 或 remote CI。

审批是“证据是否支持一句话”，不是人工 answer semantic sign-off，因此 G12 可以 PASS，同时 G10/G11 继续 NOT RUN。

### 6.13 教学与个人验收材料

以下内容全部位于 Git-ignored `.private/e7/`，不进入公开候选：

```text
Enterprise_Agentic_RAG_v2_最终验收.md
resume_claims.md
e7_beginner_learning_and_interview.md
human_signoff_checklist.md
```

它们分别记录逐 gate 结果、可用/禁用简历措辞、代码主路径与指标教学、本人专属验收。公开 README/status 只保留可验证的窄结论，不发布个人长稿或 raw evidence。

### 6.14 全仓独立最终审查与 remediation

第二位独立 reviewer 检查整个 working-tree candidate，初始结论为 0 Critical、4 Important、`FAIL / not release-ready`。四项逐条核对后都成立：

| finding | 根因 | RED | 修复/当前证据 |
|---|---|---|---|
| conflict priority 方向错误 | `_priority_resolves()` 用 `!=`，低优先级也能“解决”高优先级冲突 | authority 和 active/retired 两例均失败 | 改为严格 `>`；ledger 11 passed；重新发布 rc02 |
| G05/G09/G13 pending 时文档称 final complete | public wording 把局部门禁和总体 release 状态混在一起 | 静态 review | README 限定为 local code/data gate；owner/remote/Git delivery 分开 |
| absolute-path audit 只扫 allowlist | roadmap/superpowers Markdown 未纳入 | 新 nested Markdown test 失败；真实 audit 13 findings | 所有 Markdown 检查；13 路径脱敏；330/0 |
| E7 rc02 与历史 snapshot 批次混用 | README 旧 load 数字与 status 新数字共享笼统 provenance | 静态 source 对照 | README/status/reproducibility 明确 historical snapshot vs E7 rc02 |

新增测试数：conflict priority 参数化 2 例、all-Markdown path audit 1 例。加上此前 trace 回归，E7 final full 预计为 573；这里不按算术直接判 PASS，仍须执行完整 pytest。

这次审查耗时超过两个五分钟等待窗口，主流程发出 stop-and-report 后才返回；代理没有改文件，也没有独立运行测试。因此“4 Important”来自独立静态审查，动态 RED/GREEN 和最终门禁都由项目 `.venv` 执行。

### 6.15 E7-G05/G09：独立审查修复后的 final local gates

第一轮 all-edits final command batch：

```text
pip check                               exit 0, No broken requirements found
compileall app/scripts/streamlit/tests  exit 0
frozen test expected == actual          true
frozen SHA-256                          556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
full pytest                             573 passed, 3 warnings, 17.69 s
public repository audit                 330 candidates, 0 findings
git diff --check                        exit 0, LF->CRLF notices only
port 8000 / 8501 listeners              0 / 0
project Python processes                0
Ollama processes                        2, kept
.git/index.lock                         false
```

573 比 E6 final 569 增加 4 个回归实例：trace self-overwrite 1 个、conflict priority 参数化 2 个、all-Markdown absolute-path audit 1 个。warning 仍只有 3 条 FAISS SWIG type deprecation。

G09 的关键不是 README 字面相同，而是明确区分证据批次：

```text
checked-in public snapshot   historical E4/E5 offline demo batch
E7 deterministic/ablation    rc02 ignored raw artifacts + hashes in this journal
E7 final-code load            rc02 ignored raw artifact + hashes in this journal
```

本节首次写入后，独立 reviewer 复核原 4 个 Important：conflict priority、all-Markdown audit、evidence-batch separation 三项 CLOSED；唯一 OPEN 是“日志承诺第二轮但尚无第二轮证据”。随后实际执行第二轮完整 gate：

```text
pip check                               exit 0
compileall                              exit 0
frozen hash                             exact match
full pytest                             573 passed, 3 warnings, 17.74 s
public repository audit                 330 candidates, 0 findings
git diff --check                        exit 0, line-ending notices only
ports 8000/8501                         0/0
project Python / Git index lock          0 / false
Ollama                                  kept, 2 processes
```

这关闭了 reviewer 的最后一个 OPEN。当前 G05/G09 的 PASS 同时有两轮 full 573、两轮 audit 330/0 以及第二轮依赖/编译/hash/process 证据。追加本段只改变验收日志；随后再执行 repository docs tests、public audit 和 diff check，确认记录本身没有破坏公开边界。G13 的 commit/push/clean clone 仍按时序保持 PENDING，不被本地门禁替代。

### 6.16 E7-I09：staged diff 暴露 untracked whitespace 盲区

前两轮 `git diff --check` 退出 0，但当时新增文件仍是 untracked，Git diff 不会检查其内容。`git add -A` 后首次执行 `git diff --cached --check` 才发现：

```text
Markdown trailing whitespace            8
test files with blank line at EOF        4
PDF xref fixed-width lines               reported as text whitespace
```

真实文本问题用 `apply_patch` 清理。PDF xref 行尾空格属于 PDF 固定宽度结构，不能为通过 lint 破坏文件，因此新增 `.gitattributes`，把 PDF/DOCX/PNG 等 fixture 明确标记为 binary。重新 stage 后：

```text
staged changed files                    243
forbidden staged paths                    0
largest staged file                     docs/assets/evaluation.png, 322123 bytes
git diff --cached --check               exit 0
final public candidates                 331
final public findings                     0
```

新增 `.gitattributes` 使 candidate count 从 330 变为 331；前两轮 330/0 是当时时点的准确记录，最终提交 authority 使用 331/0。这个事件说明 publication gate 必须在 staging 后再跑一次，不能只依赖 working-tree diff。

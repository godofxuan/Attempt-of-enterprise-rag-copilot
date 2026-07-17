# E6 演示与公开仓库收口实施记录

最后更新：2026-07-17

状态：in progress - independent review remediation

批准命令：`批准E5，执行E6演示与公开仓库收口`

审计 run root：`20260716T192459Z_7aec4b9_e6`

## 1. 开工基线

```text
workspace                         <repo-root>
branch                            codex/rag-eval-system
HEAD                              7aec4b950e012d3f24b8e1877d6391201e9b8f90
checkout                          normal (.git == common dir)
full pytest                       526 passed, 3 FAISS warnings
project Python/pip background     0
git index.lock                    false
active index                      bge-m3 1024D, 64 chunks
E4 deterministic frozen test      28/28
E4 live dev r01                   23/24
E5 load r2                        31/31, p95 1.136/4.406/8.633s
commit/push/merge/tag              not authorized
```

## 2. 开工审计

- `streamlit_app/ui.py` 仍调用 legacy `/chat`，只有单页 answer/source/feedback，无 UserContext、V2 trace 或 evaluation。
- README 和根 PROJECT_STATUS 仍以 2026-07-15 legacy adaptive Agent、109 tests 为当前状态。
- `docs/PROJECT_STATUS.md` 已是历史快照，但 README 未把根状态确立为唯一入口。
- E4/E5 artifacts 完整存在但被忽略，公开 clone 不能直接读取。
- `.env` 已被 `.gitignore` 排除且未 tracked；候选文件无 >1 MiB 文件。
- canonical E1/E4 只有 direct prompt injection probes；没有文档内间接 injection fixture。该项必须 NOT RUN，不能伪造。

## 3. 采用设计

采用 live API + canonical public snapshot。详细设计：`docs/superpowers/specs/2026-07-17-e6-demo-public-repo-design.md`。

## 4. E6-C01：安全的证据充分性摘要

### 为什么要改

E5 的 Agent trace 已经能说明调用了哪些工具、耗费了多少预算、为何停止，但不能直接回答一个关键面试问题：Agent 为什么认为证据已经足够，或者为什么选择拒答。内部 `EvidenceLedger` 有答案，但其中包含 required aspect 文本和证据关联，不能原样暴露给演示 UI。

### RED：先证明缺口

- 修改 `tests/agent_v2/test_runner_v2.py`，覆盖单事实、双方面比较、unsafe 和 no-match 四条路径。
- 约束 `trace.evidence` 只能包含 `required`、`supported`、`missing`、`conflicting`、`coverage`、`recommended_action` 六个字段。
- RED 命令：`python -m pytest tests/agent_v2/test_runner_v2.py -q`。
- 观察结果：`5 failed, 3 passed`，五个失败均为 `KeyError: 'evidence'`。这说明测试命中了真实缺口，而不是环境或测试夹具问题。

### GREEN：代码改在哪里、如何工作

- 修改 `app/agent/runner_v2.py`。
- 新增 `_evidence_trace()`：有 ledger 时只计算各类 aspect 的数量并复制覆盖率/建议动作；没有 ledger 时依据 required 数量和当前终止路径生成保守摘要。
- 新增 `_evidence_action_for_mode()`：把外部响应模式 `answered/unsafe/...` 映射成证据层动作 `answer/refuse/...`，避免把 UI 文案和内部控制器枚举混在一起。
- 所有 `_build_trace()` 调用显式传入 evidence 摘要，包括初始化失败、正常终止、工具异常、unsafe 快速拒答和顶层兜底；`_build_trace()` 最后仍统一调用 `redact_trace_payload()`。
- 没有序列化 `ledger.items`、aspect 名称、chunk ID、文档 ID、问题或用户身份，因此增强可解释性没有扩大敏感数据面。

### 验证与结果

GREEN 命令：

```text
python -m pytest tests/agent_v2/test_runner_v2.py tests/security/test_agent_trace_zero_leak.py tests/evaluation -q
```

结果：`91 passed, 3 warnings in 4.37s`。三条 warning 均为既有 FAISS SWIG 弃用提示，不是 E6 回归。

### 面试表达

可以概括为：内部 evidence ledger 用于决策，外部 trace 使用最小披露的派生视图。这样既能展示“1/2 个条件得到支持，所以继续检索或部分回答”，又不会把证据正文和权限上下文写进可观测性数据。

## 5. E6-C02：可公开、可溯源的评估快照

### 原问题

E4/E5 的 `eval_runs/` 和 `load_runs/` 保存了完整可审计证据，但它们有两个不适合直接供公开演示读取的特征：目录被 Git 忽略，公开 clone 中不存在；manifest 又包含本机路径、运行环境和比 UI 所需更多的信息。直接复制 summary 也不安全，因为会失去 allowlist 边界，而且数字可能被手工改写。

### 方案

采用“原始证据 -> 校验 -> 脱敏派生快照”的单向流程：

1. 读取四个明确指定的 canonical run；
2. 读取各自 `manifest.json`；
3. 重新计算 `summary.json`/`ablation.csv` 的 SHA-256，并与 manifest 声明值比较；
4. 只抽取固定 schema 中允许的指标；
5. 用来源哈希计算稳定的 `snapshot_id`；
6. 先写同目录 staging 文件，目标已存在则拒绝覆盖，成功后再 promote。

### RED 与测试边界

- 新增 `tests/evaluation/test_public_snapshot.py`。
- 首次运行结果：测试收集阶段按预期报 `ModuleNotFoundError: No module named 'app.evaluation.public_snapshot'`。
- 测试不只检查 happy path，还固定了 manifest hash mismatch 必须失败、已有 output 必须拒绝、promotion 失败必须清理 staging、相同输入必须产生完全相同字节、CLI `--help` 不得创建文件。

### 代码改在哪里

- 新增 `app/evaluation/public_snapshot.py`：
  - `PublicDemoSnapshot` 及其子模型使用 `extra='forbid'`，未知字段无法混入；
  - `SnapshotInputs` 明确四个源 run；
  - `_verified_artifact()` 对照 manifest 重新计算 SHA-256；
  - `_quality_snapshot()` 仅抽取 deterministic/live 总结果、四层通过率和固定指标；
  - `_ablation_results()` 解析 CSV 内的 JSON metrics，但只复制 allowlist 字段，`private_metric` 一类字段会被丢弃；
  - `_security_snapshot()` 把直接 prompt injection、ACL 和 trace redaction 映射为真实观测，把缺失 fixture 的间接 document injection 明确记为 `not_run`；
  - `_load_snapshot()` 输出并发档位延迟、模型调用差值、RSS 差值和无路径的索引摘要；
  - `_assert_public_payload()` 最后扫描 Windows/macOS 用户路径和问题、响应正文、tenant/user 等禁止字段。
- 新增 `scripts/export_public_demo_snapshot.py`：提供五个必填参数，不提供 overwrite 开关。
- 生成 `data/v2/public/demo_snapshot.json`：公开 clone 的 Evaluation 页只读取这份稳定小文件，不依赖 ignored run。

### 真实结果

```text
snapshot_id                 public-demo-45426ec720cc
snapshot bytes              10126
snapshot sha256             bbee33c1d28c4c2f2a0b9af6d4a9cd3a8d1f70fc47df7b30ed412c3b9f195547
deterministic frozen test    28/28
live dev                     23/24
load                         31/31
ablation rows                8
evidence references          5
indirect document injection  NOT RUN
Git ignored                  false
forbidden scan               0 findings
```

单元测试 `5 passed`；随后运行整个 `tests/evaluation` 得到 `86 passed, 3 warnings`。三条 warning 仍为 FAISS SWIG 弃用提示。

### 为什么这比手写 README 数字更可信

README 数字只是主张；快照中的每组数字附带 run ID、artifact 名和 SHA-256，面试官可以追问“来自哪次运行”，项目可以给出机器可校验的证据链。快照本身仍是摘要，不替代 ignored 原始 artifacts，这一限制会写进公开文档。

## 6. E6-C03：类型化 UI 边界、canonical 案例与纯视图模型

### 为什么不能直接在 Streamlit 页面里写 requests

旧 `streamlit_app/ui.py` 在页面脚本中直接调用 legacy `/chat`，并把 `requests` 异常原文显示给用户。这样有四个问题：页面和 API schema 强耦合；网络异常可能暴露本机 endpoint/路径；每次 rerun 都难以单测；展示案例容易被手工写成与评测集不一致的“完美问题”。

### RED

新增：

- `tests/ui/test_api_client.py`
- `tests/ui/test_demo_cases.py`
- `tests/ui/test_view_models.py`

首次 `python -m pytest tests/ui -q` 在收集阶段出现三个预期 `ModuleNotFoundError`，分别对应 `streamlit_app.api_client`、`demo_cases`、`view_models`。这证明缺口被分成三个明确模块，而不是等页面建完后才通过人工点击猜错误。

### 代码改在哪里

#### `streamlit_app/api_client.py`

- `EnterpriseRagClient.ask()` 只调用 `/agent/v2/chat`，payload 固定为 question、完整 `UserContext` 和 top_k。
- 每次请求生成合法 `X-Request-ID`，回答成功后强制校验响应 header 与 `response.trace.request_id` 相等；不一致即视为协议错误。
- `readiness()` 接受 `/health/ready` 的 200 或结构化 503，因为“依赖未就绪”是可展示状态，不等同于 JSON 无效。
- `trace()` 先限制 request ID 字符集和长度，再读取 `/observability/traces/{id}`。
- 成功 payload 分别由 `AnswerResponse`、`ReadinessSnapshot`、`RequestTrace` 做 Pydantic 校验。
- `UiApiError` 只有 code、safe_message、request_id、retryable；网络异常、Pydantic 错误和原始 response body 都不会进入 `str(error)`。
- Session 明确 `trust_env=False`，避免本机代理环境把 localhost 请求错误转发。

#### `streamlit_app/demo_cases.py`

- 前六个案例不是复制文本，而是每次按固定 ID 从 `data/v2/eval/test.json` 读取并通过 `EvalCase` 校验。
- 依次覆盖 single document、comparison、version conflict、multi condition、not found、permission。
- 第七个案例直接引用 `SECURITY_PROBES.instruction_override`，标签只能称 direct instruction override，不能伪称 indirect/document injection。
- `DemoCase` 包含 question、runtime UserContext、expected mode 和 provenance，但模型中根本没有 `expected_answer` 字段。

#### `streamlit_app/view_models.py`

- 把 citation/source/action/evidence/budget/span 转成 JSON-safe 行；页面不需要理解领域对象内部关系。
- `evidence_summary({})` 返回零计数和 `unavailable`，旧 trace 或空 session 不会导致 KeyError。
- latency 统一格式化为 ms/s。
- 同时为 Evaluation 页准备 quality/security/ablation/load/evidence 行构建器。

### 遇到的问题与处理

第一次 GREEN 得到 `13 passed, 4 warnings`，多出的 warning 是测试从 Pydantic 实例访问 `model_fields`。虽然不影响当前功能，但 Pydantic 3 会删除该入口；改为从 `type(case).model_fields` 读取后，warning 恢复为仅有三条既有 FAISS 提示。

### 验证

```text
tests/ui                                      13 passed, 3 warnings
tests/ui + tests/api_v2 + API zero-leak       26 passed, 3 warnings
```

### 面试表达

这一步可概括为 presentation anti-corruption layer：后端领域 schema 是事实来源，API client 负责协议/安全错误，view model 负责展示形状，Streamlit 只负责交互和排版。这样测试可以精确回答“请求发了什么、失败时泄露什么、案例从哪里来”，而不依赖浏览器肉眼判断。

## 7. E6-C04：三页 Agent 工作台

### 从什么状态升级

旧 `streamlit_app/ui.py` 是单页 legacy `/chat` 客户端：页面加载立即调用健康接口，后端离线时整页 `st.stop()`；没有 UserContext、V2 mode/stop reason、Agent action、evidence、budget、service span 或公开评估页；requests 异常原文直接显示；原文件还有明显编码乱码。

### RED 页面契约

新增 `tests/ui/test_streamlit_pages.py`，首次运行连同 feedback 契约得到 `6 failed`：三个 page 文件和 shell 不存在，入口仍显示旧标题，navigation/CSS 契约不成立，client 不支持 feedback。所有失败均发生在本地渲染/接口能力层，没有触发网络或 Ollama。

### 代码结构

#### `streamlit_app/ui.py`

现在只做三件事：设置宽屏 page config、注入共享 CSS、通过 `st.navigation` 注册 Ask/Trace/Evaluation。Ask 是 default page，四个入口/页面图标全部使用 Streamlit Material icons。

#### `streamlit_app/shell.py`

- `ensure_session_state()` 统一初始化 `selected_demo`、`last_answer`、`last_request_id`、`last_http_trace`、`last_latency_ms` 等跨页状态。
- `get_client()` 缓存类型化 API client，但创建 client 不发网络。
- sidebar 的 readiness 只有点击 `Check service` 才请求后端。
- CSS 使用白/浅灰工作台、深墨文本、绿色健康状态、琥珀 warning；没有渐变、装饰球或营销 hero。
- 主内容最大 1180px，metric 有稳定最小高度，边框圆角固定 8px；移动端 media query 减小 padding，文本统一允许换行，letter spacing 为 0。

#### `streamlit_app/pages/1_Ask.py`

- Demo/Custom segmented control；Demo 菜单读取七个 canonical scenarios。
- 展示 tenant、region、access group 数和 expected mode，但不读取/展示 expected answer。
- Custom 可输入 user/tenant/region/groups/roles，提交前由 `UserContext` 校验。
- slider 控制 top_k，`Run Agent` 才调用 `/agent/v2/chat`；成功后保存完整 V2 response、request ID、前端 latency，并尝试取 service trace。
- 展示 mode、stop reason、request、latency、响应、claim verification 和 authorized sources。
- Helpful/Not helpful 按钮真实调用 `/feedback`；后端仍只持久化 hash/布尔元数据。

#### `streamlit_app/pages/2_Trace.py`

- 可消费当前 session Agent trace，也可按 request ID 显式 Fetch service trace。
- 显示 intent、stop reason、evidence supported/required、recommended action、coverage、action sequence、budget、HTTP duration、model calls/retries 和 spans。
- 源码不读取 `last_question`、identity、source rows 或 preview，因此 Trace 页面不会二次扩散问题/证据正文。

#### `streamlit_app/pages/3_Evaluation.py`

- 只用 `PublicDemoSnapshot.model_validate_json()` 读取公开快照，不读 ignored artifacts、不调用 API。
- headline 保留真实 `28/28`、`23/24`、`31/31`。
- Quality/Ablation/Runtime/Security 四个 tabs 展示层级指标、对照实验、并发负载和安全结果。
- optional reranker 与 indirect document injection 都明确 `NOT RUN`。
- 页面底部展示全部五个 evidence run ID/artifact/SHA-256 和 limitations。

### 真实发现的问题：顶层脚本定义顺序

静态页面测试首次 GREEN 后，我补了 Custom 点击路径。初次测试先因为 Streamlit 1.56 把 `st.segmented_control` 暴露为 AppTest `button_group` 而没有进入目标分支；读取元素树确认类型后只修正测试入口。第二次运行准确复现：

```text
NameError: name '_csv_values' is not defined
streamlit_app/pages/1_Ask.py:135
```

根因是 Streamlit rerun 从文件顶部顺序执行，点击分支运行时，文件末尾的函数定义尚未执行。把 `_csv_values` 移到任何顶层页面逻辑之前后，同一测试进入 UserContext 本地校验，显示安全错误且不联网。这个问题说明 AppTest 需要覆盖交互，不应只验证首屏无 exception。

### 验证结果

```text
initial page/client RED       6 failed
custom interaction RED       NameError reproduced
custom interaction GREEN     1 passed
all UI tests                  20 passed, 3 FAISS warnings
```

### 当前边界

AppTest 已证明三页离线可渲染、数据/schema/交互契约成立；它不能证明真实浏览器像素、移动端溢出、服务联调或 canvas/chart 实际显示。这些检查保留到 E6-C07，届时启动 FastAPI/Streamlit 后用桌面和移动 viewport 验收并生成真实 PNG。

## 8. E6-C05：公开仓库门禁与当前状态文档

### 为什么 README 重写必须配自动审计

公开收口同时面临两类风险：内容过期，例如旧 README 仍以 `/chat`、`/agent/chat`、109 tests 和单页 UI 为当前状态；发布泄漏，例如 `.env`、私有面试稿、本机路径、token、大 artifact 或断开的截图链接进入候选文件。只人工阅读 README 不能覆盖第二类，只跑 secret scanner 也不能解决第一类。

### RED

新增 `tests/test_public_repository.py`，首轮为 `5 failed`：

1. `scripts.audit_public_repo` 不存在；
2. README 缺少新的顺序化入口；
3. 根 PROJECT_STATUS 日期/状态/证据过期；
4. architecture/limitations/runbook/backlog/assets docs 不存在；
5. historical/current status link contract 不完整。

### `scripts/audit_public_repo.py` 如何工作

- 用 `git ls-files --cached --others --exclude-standard -z` 枚举 tracked + untracked nonignored；不用递归目录猜“可能提交什么”。
- 路径先规范成 repository-relative POSIX form，拒绝 absolute、`..` escape 和 symlink candidate。
- 所有候选检查 `.env`/`.private`/generated/index/eval/load forbidden path、2 MiB size、private-key marker、high-confidence `sk-`/`ghp_`/GitHub token shape、非 example email。
- README、根状态、公开 snapshot 和新公共文档额外检查 machine absolute path 与 local Markdown target。
- 结果是不可变 `AuditReport/AuditFinding`；CLI 只输出 finding code、相对路径和通用原因，不回显命中的 secret 文本。
- `password=never-show` 和 `security@example.invalid` 有回归测试，避免泛搜关键词造成假阳性。

审计器自身的两个测试先转为 `2 passed`；随后文档仍保持 RED，证明实现 audit 没有掩盖内容缺口。

### 公共文档改在哪里

- `README.md`：固定 Business Problem -> Architecture -> Demo -> Why Agentic RAG -> Features -> Evidence -> Quick Start -> Synthetic Data -> Limitations -> Documentation 顺序；加入 Mermaid、三张真实截图路径、证据表和恰好三条日常命令。
- `PROJECT_STATUS.md`：成为唯一 current status，明确 E5 baseline `526 passed` 与 E6 overlapping focused tests不能相加；记录 28/28、23/24、31/31 和未授权 Git 操作。
- `docs/architecture.md`：build/runtime/evaluation 三边界、在线 sequence、控制权、ACL、ledger、generation、observability 和 deliberate non-choices。
- `docs/known_limitations.md`：每项写 current state、consequence、admission condition；定义 FAILED/NOT RUN/未实现的差别。
- `docs/demo_runbook.md`：新环境、corpus/index、UTC fallback、前台服务、live/ready、7 cases、故障恢复和只停止 recorded PID。
- `docs/industrialization_backlog.md`：R2 不是愿望清单；IAM、indirect injection、human review 优先于 vector DB/reranker/multi-Agent，并给每项 trigger/gate。
- `docs/assets/README.md`：固定 ask/trace/evaluation PNG 和 1440x1000、390x844 验收契约。
- `.gitignore`：新增 `.private/`。
- `docs/AGENTIC_RAG_EVOLUTION_LOG.md` 与 `docs/PROJECT_STATUS.md`：顶部明确 historical，并链接根状态；不重写历史正文。

### 遇到的问题

文档首轮 GREEN 得到 4/5；失败是 `docs/PROJECT_STATUS.md` 历史 banner 只用反引号写根文件名，不是可点击 `../PROJECT_STATUS.md` 链接。只修 banner 后为 `5 passed, 3 warnings`。

### 真实 repository audit

```text
public candidates  324
all non-screenshot findings  0
missing ask.png              1
missing trace.png            1
missing evaluation.png       1
total findings               3
```

CLI 此时按契约 exit 1，因为 README 已声明真实 screenshot 但文件尚未生成。这是 E6-C07 前的预期 RED；不能提前创建空 PNG 或放旧截图把 audit 变绿。

### 面试表达

公开快照解决“数字从哪里来”，repository audit 解决“哪些文件真的可能被提交”，current status contract 解决“招聘者看到的是不是旧结论”。三者合起来才是可核验的公开仓库，不只是 README 排版。

## 9. E6-C06：被 Git 排除的面试与学习材料

### 为什么不直接放 docs

公开仓库需要短、可核验的技术文档；个人背诵稿、长 Q&A 和尚未批准的简历措辞会让 README/docs 噪声变大，也容易把 candidate claim 误读为项目承诺。因此 E6 用 `.private/e6/` 保存个人学习材料，并用 Git behavior test 证明它们不属于 public candidate。

### RED 与前置说明

`.private/` 已在 E6-C05 作为 repository contract 前置加入，不能为制造 RED 回滚。Task 6 新增更强测试：六份材料存在、每份 `git check-ignore` 成功、candidate list 无 `.private/`、Q&A >=25、claims >=8 且全部 pending。首次运行准确失败在 `interview_script_30s.md` 不存在。

### 生成内容

- `interview_script_30s.md`：业务问题、Agent 控制、证据与 NOT RUN 的极短介绍。
- `interview_script_1min.md`：数据/运行/服务三层，以及 28/28、23/24、31/31 和消融成本。
- `interview_script_3min.md`：从 synthetic truth、parser/index、ACL/tool/ledger、generation/citation 到 eval/UI/public audit 的完整讲述，并提供可被打断的分段点。
- `interview_qa.md`：实际 42 题，覆盖项目定位、corpus/parser/index、retrieval/ranking、Agent/evidence、evaluation/ablation、API/observability/security、load/UI/public repo；每题说明代码证据和常见误答。
- `learning_cards.md`：24 张基础卡，包括 BM25/dense/RRF、precision/recall/MRR/NDCG、ACL、immutable index、ledger、budget、citation、deterministic/live、injection、request context、IPv4/IPv6、Streamlit rerun 和 TDD。
- `claims_evidence_matrix.md`：10 条 candidate wording，每条记录 evidence file、metric path、source hash、boundary，状态全部 `pending_e7`。

### Claims 为什么仍未批准

E6 的 UI 和 public snapshot 已有证据，但最终 full suite、真实 browser screenshots、public audit 全绿、进程清理和 Git boundary 还在后续步骤。E7 还需要逐条决定 claim 是 approved、narrowed 还是 rejected；E6 不能因为材料已写就越权批准简历表述。

### 验证结果

```text
tests/test_public_repository.py      6 passed, 3 warnings
git check-ignore claims matrix       matched .gitignore:15 .private/
private Git candidates               0
Q&A                                  42 questions
claims matrix                        10 pending_e7 claims
public audit                         324 candidates, same 3 missing screenshots
```

私有文件约 37 KB，但不出现在 public candidate list；warning 仍是既有 FAISS SWIG。

当前断点：E6-C06 完成；进入 E6-C07，启动无 reload FastAPI/Streamlit，运行真实 Ask，同 session 验证 Trace，检查 Evaluation，并完成 desktop/mobile 浏览器像素验收和三张公开截图。

## 10. E6-C07：真实服务联调、响应式验收与公开截图

### 为什么单元测试之后还必须打开真实浏览器

AppTest 能证明页面脚本可执行、按钮分支能进入、离线快照能解析，却不能证明四件事：真实 FastAPI/Ollama 链路是否连通；Streamlit 跨页 session 是否与测试夹具一致；图表和数据表是否真正绘制；390px 宽度下是否出现整页横向滚动或文字重叠。因此 C07 使用无 reload 的真实 API/UI 进程，并让 Ask、Trace 使用同一个浏览器 session 和 request ID。

### 启动边界

- FastAPI PID 与 Streamlit PID 分别写入 ignored run 目录；启动命令都没有 `--reload`。
- `/health/live`、`/health/ready` 和 Streamlit health 均返回 200。
- readiness 验证 database/index/models 为 `ok`；active index 为 `20260716T135632Z_7aec4b9_live_bge_m3_fixed`、64 chunks、`bge-m3` 1024 维。
- 浏览器验收结束后只按 PID 文件读取进程，并再次比对命令行 marker 后停止；8000/8501 均关闭，项目 Python 进程为 0，Ollama 进程保留 1 个。

### Desktop Ask：真实调用得到什么

在 1440 x 1000 运行 canonical single-policy case，真实调用 `/agent/v2/chat`：

```text
request_id          76cc2303c59d43d08df1aa674e6d1191
mode                answered
stop_reason         completed
front-end latency   7.74 s
answer              当前远程办公需要提前至少2个工作日提交申请。
claim verification  1/1 verified, coverage 100%
authorized sources  1
```

页面有 8 个 metric、2 个 dataframe；没有 alert、整页横向溢出或页面级重叠。Ask 截图保留身份摘要、结果指标、回答、claim verification 和授权来源，但不包含终端或本机路径。

### 同 session Trace：不是伪造的流程图

Trace 页读取前一个 Ask 的 Agent trace，并按同一 request ID 获取 service trace：

```text
intent              fact
evidence            1/1
coverage            100%
actions             search -> answer
search latency      4.44 s
HTTP                200
model calls         2
retries             0
embed/chat/total    4.00 s / 3.23 s / 7.73 s
```

DOM 与截图都确认该页没有问题正文、identity 或 source preview。它展示的是控制器和服务实际写出的 trace，不是前端硬编码的“理想步骤”。

### Evaluation：公开快照的真实显示

- Quality：deterministic frozen `28/28`、live dev `23/24`、load `31/31`；图表 SVG 为 970 x 280 且含 115 个子节点，不是空白 canvas。
- Ablation：8 行；fixed baseline `0.8571`，bounded policy `1.0`，optional reranker 明确 `NOT_RUN`。
- Runtime：p95 分别为 1.14/4.41/8.63 秒，模型调用 62，RSS 增量 63 MiB，索引 64 chunks。
- Security：direct injection 4 observations/0 failures，ACL 与 trace 28 observations/0 failures；indirect document injection 明确 `NOT_RUN`。

### 浏览器中发现并修复的两个问题

#### 问题一：默认主题颜色泄漏

首轮浏览器渲染仍可见 Streamlit 默认红色强调色，与企业工作台的墨绿/中性灰语义不一致。先补 theme contract test 让它 RED，再新增 `.streamlit/config.toml`，固定 primary/background/secondary/text/border 色；重启 UI 后截图使用新主题。这里需要重启是因为 theme 配置不是普通脚本 rerun 能完整刷新。

#### 问题二：Trace 输入框跨页后为空

隔离 AppTest 中 `last_request_id` 能预填 textbox，但真实多页导航后 Streamlit widget 可能恢复为空。根因是“当前请求”属于 session state，“输入框文本”属于独立 widget state，不能假设两者生命周期一致。

修复位置在 `streamlit_app/view_models.py` 与 `streamlit_app/pages/2_Trace.py`：

```python
def resolve_request_id(custom_request_id: str, current_request_id: str) -> str:
    return custom_request_id.strip() or current_request_id.strip()
```

页面把当前 ID 作为 placeholder，Fetch 时按 `custom > current` 解析。真实移动端复测故意保持 textbox `value=''`，placeholder 为 `3dbf30bb3f3a4a4dba569cc0bb6530f1`；直接点击 Fetch 仍加载同一条 trace，HTTP 200、coverage 100%、2 model calls、0 retries。相应回归测试把总 UI 测试提升到 21 个。

### Mobile 390 x 844 验收

- Ask 与 Trace 的 `documentElement.clientWidth=390`、`scrollWidth=390`，证明没有整页横向滚动。
- Ask 8 个 metrics、Trace 8 个 metrics 均为约 353px 宽并纵向堆叠，没有因 hover、长 ID 或动态结果改变布局。
- Ask 两个 dataframe 与 Trace 三个 dataframe 的容器约 353px，内部内容约 362px，只在组件内部滚动。
- sidebar 可打开、三个页面入口都可达；32 字符 request ID 在 sidebar code/placeholder 中不会撑宽页面。
- Evaluation 的 headline metrics 纵向堆叠，表格内部滚动，chart 随容器响应。

### 截图与浏览器日志

```text
ask.png         1440x1000  86,212 bytes  sha256 a6d185aa67839573e1fbe31e9d76374b9067c4dd2da14b6e9802f51e2ceba06d
trace.png       1440x1000  68,561 bytes  sha256 6eb582b19a2c982c699cfdab3d1240a2bb6a37774821cf942cd9e0aed287bc97
evaluation.png  1440x1000  84,025 bytes  sha256 0281bd143a7af34da8fa37826f4309acf631798664ce8a209bb2c773084dd420
```

没有浏览器 error。日志中的 `WebSocket onclose` 发生在主动重启 UI 时；Vega warning 来自重启前 Evaluation 图表的旧日志，不对应空白图或请求失败。

### 清理脚本的小故障

第一次停止命令在 PowerShell 解析阶段失败，因为双引号字符串中的 `$id:` 被解释为带 scope 的变量名。此时脚本尚未执行，所以没有进程被误停。改成 `${id}:` 后再运行，PID/command line 校验、端口关闭和 Ollama 保留全部通过。这个例子说明运维脚本也要区分“解析失败”和“服务失败”，不能看到红字就归因于 RAG。

### C07 最终门禁

```text
tests/test_public_repository.py + tests/ui  27 passed, 3 FAISS warnings
public repository audit                     328 candidates, 0 findings
ports 8000/8501                             closed
project Python                              0
Ollama                                      1 (kept running)
```

当前断点：E6-C07 完成；进入 E6-C08 全量 deterministic gates、证据/进程边界核对和最终 handoff。仍不执行 commit、push、merge 或 tag。

## 11. E6-C08：最终门禁、证据边界与交接

### 为什么 focused tests 不能代替 full suite

E6 的局部测试会重叠：例如 UI client 会导入 API schema，repository contract 也会导入 public audit。因此 `32 passed + 31 passed` 不能相加成项目总数。C08 先用 focused gates 快速定位 E6 边界，再单独收集全仓库，只有 full pytest 的 558 才是最终唯一总数。

### Fresh focused gates

```text
tests/ui + public snapshot + repository  32 passed, 3 warnings
tests/api_v2 + tests/security             31 passed, 3 warnings
```

### Full deterministic gates

```text
full pytest                 558 passed, 3 warnings in 16.92s
pip check                   No broken requirements found
compileall                  exit 0
git diff --check            exit 0; line-ending notices only
public repository audit     328 candidates, 0 findings
```

三条 warning 都是 FAISS SWIG 类型没有 `__module__` 的弃用提示。E5 已通过相同依赖边界，本阶段没有为了消除第三方提示而升级二进制包或混入无关依赖迁移。

### 冻结数据与公开快照没有漂移

```text
frozen expected  556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
frozen actual    556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
match            true

snapshot id      public-demo-45426ec720cc
snapshot bytes   10126
snapshot sha256  bbee33c1d28c4c2f2a0b9af6d4a9cd3a8d1f70fc47df7b30ed412c3b9f195547
```

Snapshot 内五个来源引用：

| Run | Artifact | SHA-256 |
|---|---|---|
| `20260716T135632Z_7aec4b9_test_suite` | `summary.json` | `42cd1344a18e946a40ca09618c518cd2d89dd1362501ec03575ca3721855cd5f` |
| `20260716T135632Z_7aec4b9_live_dev_suite_r01` | `summary.json` | `57b9b00a20dd040846f60802f3cccbdceec3af4b50dd837fb8efd58808002e95` |
| `20260716T135632Z_7aec4b9_test_ablation` | `ablation.csv` | `8864c40f3e4da28cb56e288aa2e3bdb13075e9c4b3a4f6d5b66ccf4d3437d0d2` |
| `20260716T165304Z_7aec4b9_demo_load_r2` | `summary.json` | `6336e2ea8da5feadfe9f40e100595a20c6257cb070907781922ea732a0776b21` |
| `20260716T165304Z_7aec4b9_demo_load_r2` | `manifest.json` | `dd58d30c678aa30e9545f2397ac58d99d694b29267881e3827fa4bbe786d8ba7` |

Public snapshot 只保存这些引用和 allowlisted metrics；它没有复制问题、答案、身份、本机路径或 ignored raw artifacts。

### Active index 与公开候选边界

```text
active run              20260716T135632Z_7aec4b9_live_bge_m3_fixed
active manifest hash    exact match
chunks                  64
embedding               bge-m3, 1024D
public candidates       328
largest candidate       docs/assets/ask.png, 86,212 bytes
private candidates      0
local/broken links      0 audit findings
```

`git check-ignore -v` 明确由 `.gitignore:15 .private/` 命中 claims matrix。私有材料存在于工作区，但不是 Git candidate；public audit 看到的集合与将来可能提交的集合一致。

### 最终进程和 Git 边界

```text
project Python          0
port 8000 listeners     0
port 8501 listeners     0
Ollama processes        1, intentionally kept
branch                  codex/rag-eval-system
HEAD                    7aec4b950e012d3f24b8e1877d6391201e9b8f90
.git/index.lock         false
commit/push/merge/tag   not authorized, not executed
```

### 当前状态怎样表达

- 可以说：E6 已实现并完成本机 deterministic、live browser、responsive、publication audit 门禁。
- 必须同时说：synthetic、小样本、local-only；indirect document injection 与 optional reranker 是 `NOT RUN`；human semantic review 未完成。
- 不可以说：已经生产部署、远端 CI 已运行、真实 IAM 已接入、所有 prompt injection 都通过、claims 已批准或代码已推到 GitHub。

E6 implementation complete，等待本人验收。当前没有后台项目服务，也没有 Git 写锁。不得在本阶段 commit/push/merge/tag，不得自动执行 E7。唯一下一条命令：

```text
执行E7最终验收
```

## 12. E6-C09：独立完成前审查重新打开阶段

首轮 C08 后按完成前审查流程派出只读 reviewer。Reviewer 没有修改文件或运行测试，静态检查确认 0 个 Critical、9 个 Important、2 个 Minor。逐项对照代码与 E6 设计后，以下问题成立并重新打开 E6：

1. public pytest 无条件要求 `.private/e6` 六个 ignored 文件存在，clean clone 的 CI 必然失败；
2. Trace 自定义 Fetch 只替换 service trace，可能继续显示另一 request 的 Agent actions；
3. Ask 切换输入或请求失败后仍可能显示旧成功结果；
4. API client 只比较 response header/body，没有比较实际发出的 request ID；
5. public snapshot 禁止未知字段，但尚未强制类型、唯一层/variant/evidence role 和 snapshot ID 来源关系；
6. Evaluation 把 reranker 与 indirect injection 的 `NOT RUN` 写死在页面；
7. repository audit 在 `resolve()` 后查 symlink，且 binary/non-UTF-8 内容会跳过 credential scan；
8. audit 只检查文件存在，不验证 snapshot schema、PNG signature/dimensions 和全部公开 Markdown 链接；
9. claim verification 表缺 critical、citation presence 和 visible-evidence verdict。

两个 Minor 分别是 snapshot promotion 的 check-then-replace race，以及 Evaluation 数字与 run provenance 距离过远。二者与上面 contract 同批修复。

当前断点：先写 API/client/state/claim RED，再修复；然后做 snapshot/evaluation RED/GREEN；最后强化 audit 和 clean-clone contract。完成后必须重新生成或核对截图、重跑 browser、full pytest、audit、process/Git boundaries，并重写 C08 最终数字。此前的 `558 passed` 与 328/0 只保留为 review 前基线。

## 13. E6-C09：审查问题的代码级修复与第二轮浏览器验收

### 13.1 API request correlation

RED 在 `tests/ui/test_api_client.py` 新增两种协议错配：header/body 彼此一致但不是客户端发送 ID；trace endpoint 返回结构合法但属于另一个目标 request。旧实现错误接受，结果为 `2 failed, 7 passed`。

修复在 `streamlit_app/api_client.py`：

- `_send()` 要求 response header ID 等于该 HTTP request 实际发送的 ID；
- `ask()` 再要求 Answer trace body ID 等于发送 ID，形成 `sent == header == body`；
- `trace(target_id)` 中 lookup request 的 header 必须匹配 lookup ID，而返回的 `RequestTrace.request_id` 必须匹配 `target_id`。

GREEN 为 `9 passed`。这里区分了两个 ID：查询 trace endpoint 本身也有 lookup request ID，但它查询的目标是原 Agent request ID，不能把两者误当成同一个字段。

### 13.2 Ask stale state 与 Trace cross-request mixing

AppTest RED 构造旧 Answer 后切换 Custom/提交无效 identity，又构造 Agent request A + service request B。旧实现结果 `4 failed, 5 passed`。

修复位置：

- `streamlit_app/shell.py` 新增 `clear_answer_state()`，统一清理 answer/request/http trace/latency/question/expected mode/trace view；
- `streamlit_app/pages/1_Ask.py` 的 mode、scenario、custom question、identity、groups/roles、top-k 都注册清理 callback；每次 Run Agent 在任何 validation/network 之前再清一次；
- 成功后同时设置 `last_request_id` 与 `trace_view_request_id`；
- `streamlit_app/pages/2_Trace.py` 把 selected view ID、Agent trace ID、service trace ID 分开；只有 Agent ID 等于 selected ID 才显示 actions/evidence/budget；失败 Fetch 先清空旧 service trace；saved service trace 也必须与 selected ID 相等。

Trace request overview 同时补齐 intent、analysis source、mode、stop reason、evidence、next action 和完整 Agent request ID。GREEN 为 `9 passed`。

真实浏览器复测：先生成当前 request `5c432092c7fa4d14ad9052b2a05748ff`，再 Fetch 旧 request `761fdb8f5fcb4418b09716be156c0b24`。页面只显示旧 request 的 HTTP trace，并显示 `No Agent decision trace is available for this request`；没有继续显示当前 request 的 Agent actions。恢复当前 ID 后 Agent/Service 两个 ID 再次一致。

### 13.3 Claim verdict 不再压成一个标签

`tests/ui/test_view_models.py` 先把期望行扩展为 critical、citation_present、visible_evidence、support_verdict、lexical_support、cited_chunks、reason；RED 为 `1 failed, 4 passed`。

`streamlit_app/view_models.py::citation_rows()` 现在分别读取 `Claim.critical` 与 `ClaimCitation` 的 presence/visibility/support/reason。GREEN 为 `5 passed`。真实 Ask DOM 也确认这些列实际渲染，不只是 unit dict 存在。

### 13.4 Clean clone 与 CI

原 repository test 要求 ignored 私有文件无条件存在；本机能过，GitHub clone 必然拿不到。修复后：

- 所有预期私有路径即使不存在也必须被 `git check-ignore` 命中；
- candidate list 永远不能出现 `.private/`；
- 只有本机 `.private/e6` 目录存在时才加强校验六文件、42 Q&A 和 10 pending claims；
- CI 在 full pytest 后执行 `python -m scripts.audit_public_repo`；
- compileall 范围从 E5 的 `app scripts tests` 扩展为 `app scripts streamlit_app tests`。

CI contract 两轮 RED 都是各 `1 failed`，修复后 repository/config 合计 `10 passed`，单独 config `4 passed`。

### 13.5 Strict snapshot 与 atomic no-replace

原 `StrictModel` 只设置 `extra='forbid'`，Pydantic 仍会把字符串 `"28"` 转成整数。新增测试还覆盖重复 layer、重复 ablation/evidence role、伪造 snapshot ID 和 promotion race；RED 为 `4 failed, 4 passed`。

`app/evaluation/public_snapshot.py` 现在：

- 全部 public models 使用 `strict=True`；
- deterministic quality 只能是 deterministic/test，live quality 只能是 live/dev；
- retrieval/response/agent/security 四层必须各一次；
- 8 个 canonical ablation variants 必须各一次并匹配 retrieval/workflow family；
- 5 个 evidence labels/artifacts 必须各一次，load summary/manifest 必须来自同一 run；
- `snapshot_id` 每次从有序 evidence SHA-256 重新计算并校验；
- warm concurrency、metric key、limitations 不得重复；
- staging promotion 改为同目录 `os.link(stage, output)`，目标已存在时由文件系统原子拒绝，finally 再删除 staging link。

GREEN 为 `8 passed`；真实 `demo_snapshot.json` 仍验证为 ID `public-demo-45426ec720cc`、8 variants、5 evidence，不需要改写现有证据数字。

### 13.6 Evaluation 完全由 snapshot 驱动

RED 要求 quality/ablation/load/security 行旁带 mode/split/sample/run ID，并禁止页面源码写死两条 `NOT RUN`；结果 `2 failed, 13 passed`。

修复后每张表行包含对应 run provenance，页面每个 tab 也在标题附近显示 mode/split/sample/run。Optional reranker 从 `AblationResult.status/reason` 读取；indirect document injection 从 `SecurityCheck.status/note` 读取，并按 passed/failed/not_run 选择 success/error/warning。GREEN 为 `15 passed`。

真实浏览器显示：

```text
Quality    deterministic/test n=28 + live/dev n=24 + two run IDs
Ablation   deterministic/test, 8 variants, canonical ablation run
Runtime    live, 31 requests, load r2 run
Security   deterministic/test n=28, indirect NOT RUN from snapshot note
```

### 13.7 Publication audit hardening

新增 adversarial tests：内部 symlink、带 NUL 的 binary `sk-`、UTF-16 `ghp_`、legacy index/eval/log 路径、坏 snapshot、假 PNG 和任意 public Markdown 断链。Windows 当前用户没有 symlink privilege，第一次 fixture 得到 `WinError 1314`；测试改为 monkeypatch `Path.resolve/is_symlink` 精确模拟解析顺序，不把操作系统权限当成产品失败。

`scripts/audit_public_repo.py` 的修复：

- unresolved path 先 `is_symlink()`，之后才 `resolve()` 并检查 root escape；
- raw bytes 先扫描 private-key/token signature；UTF-8 BOM 与 UTF-16 BOM 再进入文本扫描；
- forbidden runtime 范围加入 legacy indexes、parsed docs、eval outputs、data/logs、logs 和 DB/log/sqlite suffix，同时允许两个 `.gitkeep`；
- checked-in snapshot 必须通过 `PublicDemoSnapshot.model_validate_json()`；
- 三张 screenshot 必须通过 PNG signature、chunk boundary、CRC、IEND 和 1440x1000 dimensions；
- 所有 candidate Markdown 都检查 local links；先删除 fenced/inline code，避免把 `renderers[document.format](document)` 当成链接。

Audit tests 从 `2 failed` 转为 `8 passed`。真实仓库强化后仍为 `328 candidates, 0 findings`。

### 13.8 截图格式故障

强化 audit 首次真实运行发现三张 `.png` 的字节头其实是 `FF D8 ... JFIF`，即 JPEG 内容使用了 PNG 扩展名。不能放宽 checker；使用 System.Drawing 无缩放解码现有像素并编码为 PNG。PowerShell 首条转换命令又因 `foreach {...} |` 解析为 empty pipe element，尚未执行；改为 `$rows = foreach {...}; $rows | ...` 后成功。

第二轮 browser 重新生成 UI 内容后再次执行 JPEG -> PNG 格式转换，最终资产：

```text
ask.png         1440x1000  209,063 bytes  d6eae8c3425bf0a8a1d227354e612fd9900c89c2f5c0b53d75b9f35330053c81
trace.png       1440x1000  191,791 bytes  c465ccc3787928c7ce6c95dfa0bbb7695776784ea43543ed7ba0b70b3267efe2
evaluation.png  1440x1000  322,123 bytes  f01d507ac0e1072aed732d100776f3dc705b59375b0f35b121fa310dd0300048
```

Trace 第一张重拍滚动过低，只显示 actions/budget/service；视觉检查后再次用更小滚动距离重拍，最终同屏显示 request overview、evidence 100%、actions、budget 和 service metrics。

### 13.9 第二轮浏览器与进程结果

```text
desktop Ask         sent/header/body correlated; claim verdict columns visible; 1440/1440
Ask stale state     switch to Custom removes prior response/request/sources
Trace matching      Agent ID == Service ID; intent/analysis/mode/stop/evidence visible
Trace mismatching   service-only; no stale Agent actions
Evaluation          provenance visible; statuses snapshot-driven; chart nonblank
mobile              Ask/Trace/Evaluation 390/390; metrics stack; tables internal-scroll
browser errors      0
browser warnings    existing Vega warnings; chart SVG observed 353x280
ports 8000/8501     0 after recorded-PID cleanup
project Python      0
Ollama              1, intentionally kept
```

Review remediation focused gate 为 `47 passed`；其后首轮 full suite 为 `569 passed, 3 FAISS warnings`。下一步只剩 fresh final gates 和状态文件的最终一致性复核。

## 14. E6-C10：审查后最终门禁与停止点

所有 C09 代码、第二轮截图和状态文档写入后，重新串行执行完整门禁：

```text
review remediation focused   47 passed, 3 warnings in 3.27s
full repository             569 passed, 3 warnings in 15.97s
pip check                    No broken requirements found
compileall                   app/scripts/streamlit_app/tests, exit 0
git diff --check             exit 0, line-ending notices only
public audit                 328 candidates, 0 findings
```

Evidence boundary fresh check：

```text
frozen test hash       expected == actual == 556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
snapshot               public-demo-45426ec720cc, 10,126 bytes, 5 evidence, 8 ablations
snapshot sha256        bbee33c1d28c4c2f2a0b9af6d4a9cd3a8d1f70fc47df7b30ed412c3b9f195547
active index           manifest match, 64 chunks, bge-m3 1024D
largest candidate      docs/assets/evaluation.png, 322,123 bytes
private candidates     0
project Python         0
ports 8000/8501        0/0
Ollama                 1, intentionally kept
branch                 codex/rag-eval-system
HEAD                   7aec4b950e012d3f24b8e1877d6391201e9b8f90
.git/index.lock        false
```

为什么测试从 558 增到 569：新增 2 个 API correlation、3 个 Ask/Trace 页面状态、1 个 Evaluation provenance row、3 个 snapshot semantic/promotion、2 个 audit adversarial/contract 测试，共 11 个；最终 pytest 收集结果仍是唯一总数，不能只靠手工相加替代。

最终状态是 `implementation complete, awaiting user acceptance`。没有 commit、push、merge、tag、默认分支修改或 E7 工作。Indirect retrieved-content injection、optional reranker、human semantic review 仍是 `NOT RUN`、`NOT RUN`、pending。唯一下一命令仍是：

```text
执行E7最终验收
```

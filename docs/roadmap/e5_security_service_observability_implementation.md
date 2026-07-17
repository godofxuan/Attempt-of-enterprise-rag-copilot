# E5 安全、服务与可观测性实施记录

最后更新：2026-07-17

状态：implementation complete，等待本人验收

批准命令：`批准E4，执行E5安全、服务与可观测性`

审计 run root：`20260716T165304Z_7aec4b9`

## 1. 阶段目标

把 E3/E4 已验证的 Agentic RAG 垂直链路放进具有真实生命周期、readiness、request correlation、bounded model transport、safe telemetry、private feedback、CI 和 load evidence 的本地 R1 服务。E5 不把单进程本地应用冒充生产分布式系统。

## 2. 权威文件

- 设计：`docs/superpowers/specs/2026-07-17-e5-security-service-observability-design.md`
- TDD 计划：`docs/superpowers/plans/2026-07-17-e5-security-service-observability.md`
- 总计划：`docs/roadmap/enterprise_agentic_rag_v2_plan.md#6-e5安全服务和可观测性`
- 当前 handoff：`docs/roadmap/CURRENT_EXECUTION_HANDOFF.md`

## 3. 开工基线

```text
workspace: <repo-root>
branch: codex/rag-eval-system
HEAD: 7aec4b950e012d3f24b8e1877d6391201e9b8f90
upstream: origin/codex/rag-eval-system
full pytest: 462 passed, 5 warnings
project Python/pip background: 0
git index.lock: false
active v2 index: bge-m3 1024D, 64 chunks
Ollama models: bge-m3, qwen2.5:3b available
commit/push/merge/tag: not authorized
```

Warnings 是 3 个 FAISS SWIG deprecation 和 2 个 FastAPI `on_event` deprecation。后两项正是 E5 lifespan change 的输入证据。

## 4. Worktree 例外

当前是 normal checkout，`git-dir == git-common-dir == .git`。标准新 worktree 只能从 HEAD 创建，但 E0-E4 前置全部在当前未提交工作树，进入新 worktree 会回到旧服务并丢失 `app/domain`、`app/retrieval`、`app/evaluation` 等依赖。因此延续 E3/E4 已记录的 current-checkout exception：只做小步 TDD，不执行 Git 写操作，不覆盖用户修改。

## 5. 方案决策

采用轻量单进程方案：FastAPI lifespan + ContextVar + bounded in-memory trace/metrics + SQLite hash feedback + local immutable load artifacts。拒绝在 R1 引入 OpenTelemetry collector/Prometheus/Redis，也拒绝只加表面 health/logging。

## 6. Change 状态

| ID | Deliverable | 状态 | RED | GREEN/证据 |
|---|---|---|---|---|
| `E5-C01` | request context + settings | complete | `ModuleNotFoundError: app.runtime` | 21 related tests passed |
| `E5-C02` | bounded tracing + metrics | complete | 2 module-missing collection errors | 15 tracing/metrics/security tests passed |
| `E5-C03` | model transport + structured retry | complete | transport module-missing；3 adapter failures；3 generation constructor failures | adapters 15；generation/evaluation 94 passed |
| `E5-C04` | resources + private feedback | complete | resource module missing | resources/DB/index/security 58 passed |
| `E5-C05` | errors + middleware + health/obs API | complete | 4 collection errors: `create_app` missing | API/legacy 17；security 27 passed |
| `E5-C06` | load profile artifacts | complete | `scripts.load_profile` missing | 6 tests + CLI help passed |
| `E5-C07` | deterministic CI/config | complete | 3 config failures | full suite 525 passed；pip/compile pass |
| `E5-C08` | live evidence + docs + final gates | complete | cold smoke/RSS live failures | load r2 + final 526 passed |

## 7. 开工审计发现

1. `/health` 固定 `ok`，不看 index/model/database。
2. `@app.on_event("startup")` 已被 FastAPI 警告弃用。
3. `/ingest`、`/chat`、`/agent/chat`、`/feedback` 会回显 `str(exc)`。
4. chat/embed timeout 是 180/120 秒硬编码，retry 逻辑重复且错误体可包含本机路径。
5. 无 request ID、统一 error、trace store、metrics registry、load profile 或 CI。
6. feedback 保存完整 question/answer。
7. `pytest.ini` 的 repository basetemp 已在 E4 造成并行 pytest 相互删除。
8. `psutil` 未安装；E5 不为一个 RSS 数字增加依赖，使用标准库跨平台 process memory probe，并如实记录边界。

## 8. 当前断点

`E5-C01` 已完成。RED 在 collection 阶段明确报 `ModuleNotFoundError: app.runtime`；实现 ContextVar bind/reset、nested restore、remaining/effective timeout 和 10 个有界 settings 后，request/settings/E4 runtime 合并为 `21 passed, 3 warnings`。下一步执行 `E5-C02` tracing/metrics RED。

## 9. E5-C02：bounded tracing 与 metrics

两个测试模块先分别报 `ModuleNotFoundError: app.observability`。实现 strict `RequestTrace/SpanRecord`、`TraceSink`、有界 `InMemoryTraceStore`、固定 span allowlist、线程安全 `MetricsRegistry`、nearest-rank p50/p95 和标准库 process RSS probe。

首轮 GREEN 有 1 failed/14 passed：测试按字符串搜索 `answer`，合法 outcome `answered` 被误报。Pydantic 已真实拒绝额外 `question` 字段，因此根因是 test oracle 过宽。修复为收集 JSON keys 做 exact-key 检查，production model 不变。最终 tracing/metrics + 既有 redaction/zero-leak 为 `15 passed, 3 warnings`。

当前断点：`E5-C03` model transport RED。

## 10. E5-C03：deadline-aware model transport

`test_model_transport.py` 首先 collection 报 module-missing。实现 transport 后首轮 1 failed：request context 用 0ms fake clock，transport 用真实 monotonic，正确判断 deadline 已过；修正测试让两层共享 `MutableClock`，不改生产 deadline。transport/context/trace 为 `18 passed`。

随后 adapter RED 证明旧 chat/embed 仍传 180/120 秒，且 400 response body 会回显 `password` 与本机路径。`ollama_chat.py` 和 `retriever.py` 保留签名与 payload，只把 retry/timeout 委派给共享 transport；adapter/legacy index 为 `15 passed`。

structured generation 新增 3 个 RED：constructor 不接受 `max_attempts`。实现 shape-only 最多一次 retry 后，首轮剩 1 failure：helper 抛异常前 tuple 未赋值，外层把实际 2 attempts 记成 1。改为内部 safe exception 携带整数 attempts，不携带 raw output。generation + E4 evaluation 最终 `94 passed, 3 warnings`。

当前断点：`E5-C04` resources/feedback privacy RED。

## 11. E5-C04：资源生命周期与反馈隐私

先新增 `tests/runtime/test_resources.py` 和 `tests/api_v2/test_feedback_privacy.py`，RED 明确证明 `app.runtime.resources` 尚不存在。随后新增 `app/runtime/resources.py`：数据库、活动索引、Ollama 模型是三个相互独立的 probe；任何一个失败只产生 `ok/error` 安全码，不保存异常文本或路径。`ReadinessSnapshot` 带 TTL，避免每个 `/health/ready` 请求都重新加载 FAISS 或访问 Ollama。

`app/db.py` 保留旧 `feedback` 表以兼容历史数据，但新写入改到 `feedback_events`，只存 request ID、question/answer 的 SHA256、helpful 和时间。测试把 `PROJECT NIGHTFALL`、密码样字符串和本机路径种入反馈，再直接读取 SQLite 文件字节，确认明文不存在。资源、数据库、索引与安全回归最终为 `58 passed, 5 warnings`。

## 12. E5-C05：统一服务边界与可观测 API

先写 `tests/api_v2/test_health.py`、`test_request_context_api.py`、`test_errors.py`、`test_observability_api.py`。RED 阶段 4 个模块都在导入时失败，因为旧 `app.main` 没有 `create_app`，也没有注入 fake resources 的入口。这证明失败来自缺失的服务边界，而不是测试数据偶然不匹配。

实现位置：

- `app/api/errors.py` 定义统一 `{error:{code,message,request_id,retryable}}`，422/404/500 都不回显用户输入或 `str(exc)`。
- `app/api/middleware.py` 校验或生成 request ID，绑定 deadline ContextVar，补响应头，并在 finally 聚合 latency/model counters 和有界 trace。
- `app/main.py` 改为 `create_app(container)` + FastAPI lifespan；增加 `/health/live`、`/health/ready`、metrics、trace，同时保留旧路由。
- `app/schemas.py` 收紧 health/feedback 的类型、长度和 extra-field 契约。

实现审查时发现 middleware 直接读取 `MetricsRegistry._allowed_routes` 私有字段，这会把两个模块绑死。修正为在 `MetricsRegistry` 暴露 `normalize_route()`，middleware 与 metrics 共用同一个低基数规则。新 API 9 个测试先通过；连同旧 API/V2 安全用例为 `17 passed`，完整 security 回归为 `27 passed`。FastAPI 的 2 条 `on_event` 弃用警告已消失，只剩 3 条第三方 FAISS SWIG 警告。

当前断点：`E5-C06` reproducible load profile RED。

## 13. E5-C06：可复现负载证据

`tests/observability/test_load_profile.py` 先在 collection 报 `ModuleNotFoundError: scripts.load_profile`。新增 `scripts/load_profile.py` 后实现：一条 cold 请求、逐并发档 warm 请求、nearest-rank p50/p95、成功/失败与安全错误码统计、前后 metrics、readiness 中的活动索引证据，以及 `summary.json`、`details.csv`、`manifest.json` 三件套。

隐私边界不是靠“约定不看正文”，而是代码只从 HTTP 响应白名单抽取 status/mode/request ID/error code；异常统一为 `request_error`，不序列化 `str(exc)`。测试专门让 fake API 返回问题、答案、source、密码和路径，再扫描全部 artifact，确认这些内容不存在。写入使用同目录 staging，计算 summary/CSV 的 SHA256 后才重命名；目标已存在时在第一次 HTTP 前拒绝，写入异常时清理 staging。

首轮实现测试发现 circular import：`observability.tracing -> runtime.request_context -> runtime.__init__ -> resources -> observability.tracing`。此前其他测试的导入顺序掩盖了它。根因是 `app/runtime/__init__.py` 在包导入时急切加载所有子模块；修复为 `__getattr__` 延迟导出，保留公开名字但消除初始化副作用。最终 6 个 load tests 通过；`python -m scripts.load_profile --help` 退出 0，执行前后均未创建 `load_runs/`。

记录中的小失误：首次 `.gitignore` 补丁把目录误写为 `loadnload_runs/`，在验证前发现并修正为 `load_runs/`。这类失误不属于架构失败，但保留记录用于说明为什么配置文件仍需自动测试，而不能只靠目检。

当前断点：`E5-C07` deterministic CI/config RED。

## 14. E5-C07：确定性 CI 与测试配置

本机逐项读取 15 个直接依赖的安装版本，并写入精确 `==` pin；这锁的是已经通过本项目测试的直接依赖，不冒充包含 transitive hash 的完整 lockfile。GitHub 官方当前示例使用 `actions/checkout@v6`、`actions/setup-python@v6`，后者明确建议固定 Python 版本并对固定依赖启用 pip cache。`.github/workflows/ci.yml` 使用 Python 3.11、`contents: read`、pip check、compileall、frozen hash 和 full pytest，不启动 Ollama/uvicorn，也不运行 live eval/load。

配置 RED 是 `3 failed, 1 passed`：requirements 未固定、repository basetemp 仍存在、CI 文件不存在；唯一通过的是 frozen test hash，仍为 `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338`。改动后配置测试 `4 passed`，`pip check` 无 broken requirements，compileall 退出 0。

第一次 full pytest 出现同名收集冲突：`tests/evaluation/test_metrics.py` 和 `tests/observability/test_metrics.py` 在 pytest 默认 prepend 模式下都叫 `test_metrics`。新增 RED 后在 `pytest.ini` 设置 `--import-mode=importlib`，按路径隔离模块名。

第二次 full pytest 是 `417 passed, 108 errors`；108 个错误全部在 `tmp_path` setup，根因是 Windows `%TEMP%/pytest-of-xuan` ACL 关闭继承且缺少当前用户显式访问规则，不是业务测试失败。确认目录位于用户 TEMP、无项目 pytest 进程后，只对该 pytest 专用目录恢复继承并授权当前用户；处理 1、失败 0。重跑得到 `525 passed, 3 warnings in 14.69s`。剩余均为 FAISS SWIG deprecation，不再有 FastAPI `on_event` warning。

当前断点：`E5-C08` live smoke/load、文档和最终门禁。

## 15. E5-C08：live smoke、load 和观测故障驱动修正

前置状态：active index `20260716T135632Z_7aec4b9_live_bge_m3_fixed` 可加载，64 chunks、bge-m3 1024D；Ollama 有 bge-m3/qwen2.5:3b；正式 run target 不存在；项目 Python/pip 后台为 0。隐藏 uvicorn 使用 127.0.0.1:8765、无 reload，并记录父/子 PID，只停止该进程树。

`/health/live` 为 200；`/health/ready` 为 200，database/index/models 全部 ok。第一条授权 fact smoke 的 request header 与 answer trace ID 一致，identity scan 为 false，但返回 source-free `mode=system`。safe request trace 显示：`model.embed=4625ms ok`、`agent.run=5156ms`、model call 1、chat span 0。单次 search timeout 是 5000ms，因此 embedding 冷加载成功后，加 BM25/FAISS/对象构造已超过工具预算，Navigator 返回 safe timeout；同题第二次 search 203ms，`answered/completed`。这是观测定位出的真实 cold-start failure，不是模型生成失败。

该失败暴露 load 口径 bug：旧实现把任何合法 200 mode 都算 success。新增 RED 后，`system/budget` 分别记为 `agent_system/agent_budget` failure；load tests 恢复 6 passed。

第一份 immutable load `20260716T165304Z_7aec4b9_demo_load` 是 31/31，warm concurrency 1/5/10 p95 约 1.206s/4.366s/8.788s，hash match。内容扫描最初用泛词 `answer` 命中合法 mode `answered`，改为精确正文/field-key scan 后确认无 question/identity/body；这与 E5-C02 的 test-oracle 教训一致。

第一份 manifest 的 RSS 为 null。独立复现 `_windows_rss_bytes()` 也是 None；原调用 `GetCurrentProcess` 未声明 restype，ctypes 默认 32 位 `c_int` 把 64 位 pseudo HANDLE 截断，`GetProcessMemoryInfo` 返回 WinError 6。Windows-only RED 稳定失败；显式声明 `HANDLE`、pointer、DWORD 和 BOOL 后 metrics tests 5 passed，live endpoint 返回正整数。

artifact 不允许覆盖，因此保留第一份并发布 r2：`20260716T165304Z_7aec4b9_demo_load_r2`。r2 为 31/31；cold 1.668s；warm p95 1.136s/4.406s/8.633s；model calls +62、retry/error +0；RSS 92,991,488 -> 159,088,640，增加 66,097,152 bytes；summary/details hash match；question/identity/body key scan 0。r2 cold 不是完全 Ollama-cold，因为只重启 API，Ollama 独立进程仍保留模型。

停止经 PID/命令行验证的 uvicorn child/root 后，项目 Python/pytest/pip 为 0；两个用户 Ollama 进程保留。文档新增/更新：`docs/security_threat_model.md`、`docs/observability.md`、`docs/reproducibility.md`、`docs/api.md`、`docs/roadmap/e5_beginner_learning_and_interview.md`、handoff 和总账。

当前断点：fresh E5 final gates。完成前不进入 E6。

## 16. E5 最终门禁

所有门禁在生产代码与文档完成后 fresh 运行：

```text
API + observability + security       47 passed, 3 warnings
E4 evaluation regression             81 passed, 3 warnings
full repository                     526 passed, 3 warnings
pip check                             no broken requirements
compileall app/scripts/tests          exit 0
git diff --check                      exit 0，只有 LF/CRLF notices
frozen test expected/actual           556ffed8...43338，match
load r1/r2 summary/details hashes     4/4 match
active index load                     64 chunks，bge-m3，1024D
project Python/pytest/pip background  0
git index.lock                        false
Git HEAD                              7aec4b950e012d3f24b8e1877d6391201e9b8f90
```

warning 只有 3 条 FAISS SWIG type deprecation；E5 已消除旧 FastAPI `on_event` 的 2 条 warning。新增文档本地链接检查为 0 missing。Git 仍是 normal checkout，branch `codex/rag-eval-system`，E0-E5 工作树未提交；没有执行 commit/push/merge/tag。

E5 implementation complete，等待本人验收。唯一下一阶段批准命令：

```text
批准E5，执行E6演示与公开仓库收口
```

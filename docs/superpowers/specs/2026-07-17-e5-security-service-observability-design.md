# E5 Security, Service Runtime, and Observability Design

最后更新：2026-07-17

状态：approved by exact stage command `批准E4，执行E5安全、服务与可观测性`

审计 run root：`20260716T165304Z_7aec4b9`

## 1. 背景与证据

E4 已完成四层评测和真实本机 live-dev 验证，但服务层仍有以下可直接观察的缺口：

- `app.main` 使用已弃用的 `@app.on_event("startup")`；
- `/health` 永远返回 `ok`，不验证 index、SQLite 或 Ollama models；
- legacy endpoints 把 `str(exc)` 原样放进 HTTP 500，可能泄漏路径和模型错误内容；
- chat/embed timeout 固定为 180/120 秒，不读取 request deadline；
- retry 逻辑在 chat/embed 重复，只处理 503，且错误文本可能含本机路径；
- 没有 request ID、结构化错误、请求级 trace、聚合 metrics 或保留上限；
- feedback 表保存完整 question/answer；
- `pytest.ini` 固定共享 basetemp，E4 已证明并行 pytest 会互删临时目录；
- 没有 CI 或可复现的 concurrency/load artifact。

2026-07-17 新鲜基线：`462 passed, 5 warnings`。3 条是 FAISS SWIG deprecation，2 条是 FastAPI `on_event` deprecation。Git HEAD 仍为 `7aec4b950e012d3f24b8e1877d6391201e9b8f90`，工作树包含 E0-E4 未提交前置，项目 Python/pip 后台为 0，`.git/index.lock` 不存在。

## 2. 方案比较

### 方案 A：轻量单进程工业化，采用

使用 FastAPI lifespan、ContextVar request context、纯 Python 有界 trace/metrics store、SQLite 哈希反馈、共享 requests transport 和本地 load CLI。优点是依赖少、每个边界可单测、能在当前 Windows/Ollama 环境真实运行。缺点是单进程重启后内存 telemetry 丢失，不是分布式观测。

### 方案 B：OpenTelemetry + Prometheus + Redis/collector，拒绝

优点是符合多实例生产架构，可导出标准 traces/metrics。缺点是引入 collector、时序存储、部署和网络依赖，超出 R1，也无法替代当前缺失的错误脱敏、deadline 和 readiness contract。这属于 R2 adapter，不在 E5 伪造。

### 方案 C：只增加 health 和普通日志，拒绝

改动最少，但不能关联 request/error/trace，不能量化 model retries 和 p95，也不能证明敏感正文没有被持久化。它不满足已批准 E5 门禁。

## 3. 设计目标

1. 进程活着与依赖可服务严格分开。
2. 每个 API 请求有可信 request ID 和 deadline context。
3. 所有 HTTP 错误使用统一、无敏感信息的结构。
4. blocking Ollama chat/embed 调用受配置 timeout、request 剩余时间和有限 retry 约束。
5. trace、metrics、logs 默认不保存 question、answer、prompt、identity、document/chunk/path/ACL。
6. feedback 只持久化内容 SHA256、helpful、request ID 和时间。
7. deterministic CI 不调用 Ollama。
8. live load profile 输出不可覆盖 artifact，包含 cold/warm、concurrency、p50/p95、error、memory、model calls 和 index build evidence。

## 4. 非目标

- 不实现真实 IAM、OAuth、SSO、RBAC 管理后台；
- 不实现 OpenTelemetry collector、Prometheus server 或跨进程 trace；
- 不实现 Docker/Kubernetes、自动扩缩容或生产 SLA；
- 不实现 durable Agent execution、distributed cancellation 或 hot index reload；
- 不重写 E3 Agent state machine，不改变 E4 frozen test 参数；
- 不开发 E6 Streamlit 三页 UI。

## 5. 模块边界

### `app/runtime/request_context.py`

保存请求级 `request_id`、开始时间和 deadline monotonic timestamp。提供 token-safe bind/reset、`remaining_seconds()` 和 `effective_timeout()`。没有 API context 的 CLI/eval 使用配置 timeout。

### `app/runtime/model_transport.py`

实现一次共享的 bounded request loop。调用者传入 `send(timeout_seconds)`；transport 负责 attempts、retryable status、connection/timeout 分类、backoff 和 deadline。错误对象只含 safe code/status/attempts/retryable，不含 response body、URL path 或 prompt。

### `app/runtime/resources.py`

`RuntimeResources` 在 lifespan 中检查：

1. SQLite schema 初始化和 `SELECT 1`；
2. active v2 index pointer、manifest hashes 和 snapshot load；
3. Ollama `/api/tags` 是否存在 configured embedding/chat models。

依赖失败不杀死进程，而是使 readiness 为 503；liveness 仍为 200。readiness 保存 safe check codes，不保存异常字符串。依赖检查带短 timeout，并按 TTL 刷新。

### `app/api/errors.py`

定义：

```json
{
  "error": {
    "code": "request_validation_failed",
    "message": "Request validation failed.",
    "request_id": "...",
    "retryable": false
  }
}
```

覆盖显式 `ApiError`、FastAPI request validation 和未处理异常。未处理异常只记录 safe metadata，不回显 `str(exc)`。

### `app/api/middleware.py`

纯请求元数据 middleware：

- incoming `X-Request-ID` 只接受 1-64 位 `[A-Za-z0-9._-]`；否则生成 UUID hex；
- 设置 request context 与 `request.state.request_id`；
- 增加 `X-Request-ID` response header；
- 记录 method、已注册 route template、status class、duration 和 safe error code；
- 不记录 query string、body、headers、user identity 或 response body；
- finally 中归还 ContextVar token，避免跨请求污染。

### `app/observability/tracing.py`

实现 `TraceSink` protocol 和默认 `InMemoryTraceStore(max_records=N)`。每条 `RequestTrace` 只保存 request ID、method、route、status、duration、outcome 和 bounded spans。span 只允许预定义名称：`agent.run`、`model.chat`、`model.embed`、`feedback.persist`、`readiness.*`。默认保留最近 200 请求，进程重启即清空。

### `app/observability/metrics.py`

线程安全聚合：request count、status count、in-flight、error count、model calls/retries/errors、endpoint latency count/sum/p50/p95。标签只允许低基数 route template、method、status class 和 operation，不接受 user/doc/model output。

### `app/db.py`

新增 `feedback_events`：`request_id`、`question_sha256`、`answer_sha256`、`helpful`、`created_at`。旧 `feedback` 表保留兼容和历史数据，但新 API 不再写入。SQLite 使用 context manager 和短 timeout。

### `scripts/load_profile.py`

请求已运行的本地 API，默认 concurrency `1,5,10`。先做一条 cold request，再为每层运行固定 warm requests。不可覆盖写入：

```text
load_runs/<run_id>/
  manifest.json
  summary.json
  details.csv
```

details 不保存 question/answer/source，只保存 request index、concurrency、status、mode、request ID、latency 和 safe error code。

## 6. API 契约

### `GET /health/live`

永远不调用 index、DB 或 Ollama。进程可响应时返回 200：

```json
{"status":"alive"}
```

### `GET /health/ready`

读取 TTL-cached dependency checks；过期时刷新。全部通过返回 200，否则返回 503。公开内容仅含：

```json
{
  "status": "ready",
  "checks": {"database":"ok","index":"ok","models":"ok"},
  "index": {"run_id":"...","chunk_count":64,"embedding_model":"bge-m3"}
}
```

失败时 index metadata 为 null，不公开文件路径或异常文本。

### `GET /health`

保留兼容 alias，行为等同 liveness，并增加 deprecation header。旧 Streamlit 在 E6 前不会断。

### `GET /observability/metrics`

返回聚合 snapshot 和进程 RSS。无 question、prompt、answer、identity 或 source。

### `GET /observability/traces/{request_id}`

只返回该 request ID 的 safe trace metadata。未知 ID 返回统一 404。当前本地 R1 没有认证，因此文档明确此 endpoint 不可直接暴露公网。

### `POST /agent/v2/chat`

保留现有 request/answer contract；response header 与 `response.trace.request_id` 使用同一个 ID。Agent 仍对 unsafe 请求 zero-tool，模型/检索不会因 middleware 发生提前调用。

## 7. Deadline 与 retry

配置：

```text
api_request_deadline_ms = 15000
model_request_timeout_seconds = 12
model_max_attempts = 2
model_retry_backoff_ms = 100
structured_generation_max_attempts = 2
readiness_probe_timeout_seconds = 2
```

每次 transport attempt 的 timeout 是 `min(model timeout, request remaining time)`。deadline 已耗尽时不发请求。只重试 requests timeout/connection 和 HTTP 429/502/503/504；其他 4xx 不重试。backoff 若超过剩余时间则立即 deadline error。

structured generation 只对 JSON/Pydantic/source-ID shape failure 再生成一次，不对 unsupported citation 或普通业务 no-answer 重试。transport retry 与 structured retry 分开计数，最坏调用数可由配置计算。

Python 无法安全强杀已经进入第三方 native code 的线程，因此 E5 不声称 middleware 可以异步取消任意 blocking function。边界是 requests socket timeout、Agent monotonic deadline 和有限循环。

## 8. Security 与隐私

- ACL 仍在 fusion/context 前执行，E5 不移动授权边界；
- request ID 不接受任意攻击者字符串；
- validation response 不回显 invalid input；
- logs/traces/metrics/feedback 不保存原问题、答案、tenant、groups、doc/chunk/path/title；
- model/server response body 不进入 HTTP error 或 trace；
- observability endpoint 只暴露低敏 metadata；
- prompt injection 仍由 rule-first unsafe 和 source-as-data prompt 边界防御；RAG 本身不被视为 injection mitigation；
- system prompt 不放 credentials、ACL truth 或连接串，授权由 Python policy 强制。

## 9. Testing strategy

### Deterministic unit

- request ID validation/generation、ContextVar reset、deadline math；
- transport retryable/non-retryable/deadline/attempt count；
- metrics percentile、low-cardinality keys、thread safety；
- trace retention、span allowlist、zero-content contract；
- resource ready/not-ready、safe errors、TTL；
- DB feedback hashes and no plaintext；
- load artifact no-overwrite and percentile math。

### API integration

- lifespan replaces `on_event` and initializes resources；
- live 200 without dependency probes；ready 200/503 from real manager state；
- request ID header equals v2 answer trace/error；
- validation/generic errors never echo secret input/path；
- observability endpoints contain no question/title/tenant/groups；
- legacy endpoints remain callable with generic errors；
- unsafe remains zero-tool and source-free。

### Regression

- `tests/api_v2 tests/observability tests/security`；
- E4 evaluation tests；
- full pytest；
- frozen test hash；
- live demo load profile after deterministic gates。

## 10. CI design

GitHub Actions uses Python 3.11 and dependency cache, then runs pip check、compileall、frozen hash verification and full pytest. CI never starts Ollama and never runs `--mode live` or load profile. Actions use official checkout/setup-python versions and read-only contents permission。

## 11. Evidence and claims boundary

E5 may claim: local service has tested liveness/readiness、request correlation、bounded model transport、safe telemetry、hashed feedback、deterministic CI config and one measured local load profile.

E5 may not claim: production-ready、distributed tracing、zero-downtime、multi-instance consistency、hard cancellation、real IAM、public observability authorization、cloud deployment or SLA.

## 12. Approval and Git boundary

The exact user command approves implementation of this design because it is a direct refinement of the already accepted E5 section in `enterprise_agentic_rag_v2_plan.md`. Git commit/push/merge/tag/default-branch operations remain separately unauthorized. E5 stops after verification and waits for `批准E5，执行E6演示与公开仓库收口`.

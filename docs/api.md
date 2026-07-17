# Enterprise RAG Copilot API

最后更新：2026-07-17

实现入口：`app/main.py`。默认地址：`http://127.0.0.1:8000`。

## 1. 启动

开发：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

测量或演示：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

应用使用 FastAPI lifespan。启动时初始化数据库并检查 active V2 index 和 Ollama model 列表；依赖失败不会杀死进程，而会使 readiness 返回 503。

## 2. 通用 request ID

客户端可以传：

```http
X-Request-ID: client.req-123
```

只接受 1-64 位 `[A-Za-z0-9._-]`。不合法或缺失时服务生成 32 位 UUID hex。每个响应都带 `X-Request-ID`；V2 answer 的 `trace.request_id` 和错误体 `error.request_id` 使用同一值。

## 3. 统一错误

422、显式 API 错误和未处理异常都返回：

```json
{
  "error": {
    "code": "request_validation_failed",
    "message": "Request validation failed.",
    "request_id": "client.req-123",
    "retryable": false
  }
}
```

错误不会回显 invalid input、exception string、模型响应 body、本机 URL/path 或 prompt。常见 code：

| HTTP | code | 说明 |
|---:|---|---|
| 404 | `not_found` | 未注册资源 |
| 404 | `trace_not_found` | request trace 不在当前有界内存中 |
| 422 | `request_validation_failed` | JSON/schema 不合法 |
| 500 | `internal_error` | 未处理服务异常，公开信息已脱敏 |

## 4. GET /health/live

只检查进程能否响应，不访问数据库、index 或 Ollama。

```json
{"status":"alive"}
```

依赖异常时仍返回 200。这适合 liveness，不适合判断是否能回答问题。

## 5. GET /health/ready

检查并按 TTL 缓存三个依赖：

- `database`：SQLite schema + `SELECT 1`；
- `index`：active V2 pointer、manifest/artifact 和 snapshot load；
- `models`：Ollama `/api/tags` 中存在配置的 embedding/chat model。

全部通过时 200：

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "index": "ok",
    "models": "ok"
  },
  "index": {
    "run_id": "20260716T135632Z_7aec4b9_live_bge_m3_fixed",
    "chunk_count": 64,
    "embedding_model": "bge-m3",
    "embedding_dimension": 1024,
    "build_duration_ms": 0,
    "index_size_bytes": 0
  },
  "checked_at_utc": "2026-07-17T00:00:00Z"
}
```

任一失败时 503，失败项为 `error`，`index` 为 null。响应不包含异常文本或路径。

## 6. GET /health

兼容旧客户端，行为等同 liveness：

```json
{"status":"ok"}
```

响应带：

```http
Deprecation: true
```

新代码应改用 `/health/live` 或 `/health/ready`。

## 7. POST /agent/v2/chat

当前企业 Agentic RAG 主接口。调用方必须显式提供 `UserContext`：

```json
{
  "question": "当前制度每周最多允许远程办公几天？",
  "user_context": {
    "user_id": "employee-1",
    "tenant_id": "starbridge-cn",
    "region": "cn",
    "groups": ["all_employees"],
    "roles": []
  },
  "top_k": 5
}
```

约束：

| 字段 | 约束 |
|---|---|
| `question` | 1-2000 字符 |
| `user_id`/`tenant_id` | 1-200 字符 |
| `region` | 1-100 字符 |
| `groups` | 1-50 个不重复非空值 |
| `roles` | 0-50 个不重复值 |
| `top_k` | null 或 1-20 |
| extra fields | 拒绝 |

回答示意：

```json
{
  "mode": "answered",
  "answer": "当前制度每周最多允许远程办公 3 天。",
  "claims": [
    {
      "claim_id": "claim-1",
      "text": "当前制度每周最多允许远程办公 3 天。",
      "critical": true,
      "cited_chunk_ids": ["visible-chunk-id"]
    }
  ],
  "citations": [
    {
      "claim_id": "claim-1",
      "cited_chunk_ids": ["visible-chunk-id"],
      "citation_present": true,
      "references_visible_evidence": true,
      "lexical_support": 1.0,
      "supported": true,
      "unsupported_reason": null
    }
  ],
  "sources": [
    {
      "doc_id": "authorized-doc-id",
      "source_path": "authorized-source",
      "section_path": ["远程办公"],
      "chunk_id": "visible-chunk-id",
      "preview": "..."
    }
  ],
  "warnings": [],
  "stop_reason": "completed",
  "trace": {
    "intent": "fact",
    "analysis_source": "rules",
    "required_aspect_count": 1,
    "steps": [],
    "budget": {},
    "generation_attempts": 1,
    "request_id": "client.req-123"
  }
}
```

`mode`：

| mode | 含义 | sources |
|---|---|---|
| `answered` | 证据完整、生成和 citation 验证通过 | 至少 1 |
| `not_found` | 可见证据不能支持命题 | 0 |
| `permission` | 请求资源对该身份不可用 | 0 |
| `unsafe` | 安全策略在检索前拒绝 | 0 |
| `budget` | 工具/context/deadline 预算耗尽 | 0 |
| `system` | 内部工具或结构化生成安全失败 | 0 |

重要：当前 `UserContext` 是本地 R1 的策略输入，不是真实认证。公网部署不能信任客户端自行填写 tenant/group。

## 8. POST /feedback

请求：

```json
{
  "question": "当前制度每周最多允许远程办公几天？",
  "answer": "3 天。",
  "helpful": true
}
```

响应：

```json
{"status":"ok"}
```

新数据写入 SQLite `feedback_events`：

```text
request_id
question_sha256
answer_sha256
helpful
created_at
```

不保存 question/answer 明文。旧 `feedback` 表仅为历史兼容保留，新 API 不再写入。SHA256 不是加密，也不保证低熵文本不可枚举。

## 9. GET /observability/metrics

返回进程期低基数聚合：

```json
{
  "requests": {
    "in_flight": 0,
    "total": 10,
    "errors": 1,
    "by_route": {
      "POST /agent/v2/chat": {
        "status": {"2xx": 9, "5xx": 1},
        "latency_ms": {
          "count": 10,
          "sample_count": 10,
          "sum": 12000.0,
          "p50": 1000.0,
          "p95": 2500.0
        }
      }
    }
  },
  "models": {"calls": 20, "retries": 1, "errors": 0},
  "process": {"rss_bytes": 159088640}
}
```

未知 path 归一化为 `__unmatched__`。没有 question、identity、doc 或 model body。

## 10. GET /observability/traces/{request_id}

返回最近有界内存中的安全 request trace：

```json
{
  "request_id": "client.req-123",
  "method": "POST",
  "route": "/agent/v2/chat",
  "status_code": 200,
  "duration_ms": 1234.5,
  "outcome": "answered",
  "model_calls": 2,
  "model_retries": 0,
  "model_errors": 0,
  "spans": [
    {"name": "model.embed", "status": "ok", "duration_ms": 150.0},
    {"name": "model.chat", "status": "ok", "duration_ms": 800.0},
    {"name": "agent.run", "status": "ok", "duration_ms": 1200.0}
  ]
}
```

默认只保留最近 200 条，重启清空。当前无认证，只能本机使用，不能直接暴露公网。

## 11. Legacy endpoints

以下接口保留兼容，但不是企业 V2 主路径：

- `POST /ingest`：重建 legacy index；
- `POST /chat`：legacy RAG；
- `POST /agent/chat`：legacy adaptive Agent。

它们现在也经过 request ID middleware 和统一 500 脱敏，不再返回 `str(exc)`。V2 active index 生命周期使用独立 E2 CLI，不应依靠 legacy `/ingest` 更新。

## 12. Timeout 和 retry

默认：

```text
API request deadline              15s
model request timeout             12s
model transport attempts          max 2
retry backoff                     100ms
structured generation attempts    max 2
readiness probe timeout           2s
readiness TTL                     5s
```

只重试 timeout/connection 和 HTTP 429/502/503/504。普通 4xx 不重试。结构化生成的第二次 attempt 只修复 JSON/Pydantic/source-ID shape，不把网络错误再重复一层。

Python 无法安全强杀已经进入第三方 native code 的线程，因此这里的边界是 socket timeout、monotonic Agent deadline 和有界循环，不声称任意 blocking 调用都能硬取消。

## 13. PowerShell 最小 smoke

```powershell
$base = 'http://127.0.0.1:8000'
Invoke-RestMethod "$base/health/live"
Invoke-RestMethod "$base/health/ready"

$body = @{
  question = '当前制度每周最多允许远程办公几天？'
  user_context = @{
    user_id = 'employee-1'
    tenant_id = 'starbridge-cn'
    region = 'cn'
    groups = @('all_employees')
    roles = @()
  }
  top_k = 5
} | ConvertTo-Json -Depth 6

Invoke-RestMethod `
  -Method Post `
  -Uri "$base/agent/v2/chat" `
  -Headers @{ 'X-Request-ID' = 'manual.smoke-1' } `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body
```

更完整的安全、观测和复现边界见 `docs/security_threat_model.md`、`docs/observability.md`、`docs/reproducibility.md`。

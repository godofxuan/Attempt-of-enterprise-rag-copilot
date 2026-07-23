# Enterprise Agentic RAG API

最后更新：2026-07-23。唯一部署入口是 `app.main:app`，默认地址是
`http://127.0.0.1:8000`。

本文只描述当前可执行合同。R2-S5 之前由请求体提交 `user_context` 的示例已经
退休；`/ingest`、`/chat`、`/agent/chat` 及其 compatibility factory 不再存在于
生产模块。

## 1. 启动

先生成 Git 忽略的本地身份材料，再启动 API：

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity init --force
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

这是本地可复现身份源，不是真实 OIDC/SSO。不要把 `.private/identity`、bearer
token 或私钥提交到 Git。

## 2. 路由与权限

| Method | Path | Access |
|---|---|---|
| `GET` | `/health`, `/health/live`, `/health/ready` | public |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | public |
| `POST` | `/agent/v2/chat` | valid user bearer |
| `POST` | `/feedback` | valid user bearer + answer receipt |
| `GET` | `/identity/me` | valid user bearer |
| `GET` | `/observability/metrics` | `rag.operator` |
| `GET` | `/observability/traces/{request_id}` | `rag.operator` |

路由策略是 public-by-exception：只有表中明确公开的 health/schema 路由无需身份。
未登记的新路径默认先要求 user bearer；验证通过后才由 FastAPI 决定是否 404。
这防止新增业务接口时忘记同步认证 allowlist。

## 3. 认证与错误语义

受保护请求必须带：

```http
Authorization: Bearer <JWT>
```

服务端固定验证 RS256、`typ=at+jwt`、`kid`、issuer、单值 audience、签名、时间
窗口和严格 claim 类型，再生成内部 `Principal`。客户端不能在 body 中声明
tenant、region、groups 或 roles。

| Status | Code | Meaning |
|---:|---|---|
| 400 | `invalid_content_length`, `invalid_request_body` | 重复/冲突/非数字长度，或非法 ASGI body framing |
| 401 | `authentication_required`, `invalid_token` | 缺失或无效 bearer；带 `WWW-Authenticate: Bearer` |
| 403 | `insufficient_role`, `invalid_feedback_binding` | 身份有效但权限或回执不满足 |
| 408 | `request_body_timeout` | 认证后未在 5 秒总窗口内接收完整 body |
| 413 | `request_body_too_large` | 认证后 body 超过 128 KiB 或 256 个 ASGI 消息 |
| 422 | `request_validation_failed` | JSON/schema 不符合合同 |
| 503 | `identity_unavailable`, `service_not_ready` | 身份材料或运行依赖不可用，可重试 |

认证发生在 body 缓冲和 JSON 解析之前。认证成功后，中间件同时限制 128 KiB
总字节、256 个 ASGI 消息和 5 秒总读取时间。重复 `Content-Length`、
`Content-Length` 与 `Transfer-Encoding` 并存、非数字/不可表示长度及非法 ASGI
body framing 返回安全的 400/413；实际 chunked body 超限、零字节分片洪泛或
慢速 body 也都在 Pydantic、数据库、检索和 Agent 之前拒绝。错误正文、日志和
trace 不回显 token、claims 或用户输入。

## 4. Chat

请求：

```json
{
  "question": "What is the current remote-work policy?",
  "top_k": 5
}
```

PowerShell smoke：

```powershell
$base = 'http://127.0.0.1:8000'
$userToken = (Get-Content .private\identity\load_user_token.txt -Raw).Trim()
$headers = @{
  Authorization = "Bearer $userToken"
  'X-Request-ID' = 'manual.identity-smoke-1'
}
$body = @{
  question = 'What is the current remote-work policy?'
  top_k = 5
} | ConvertTo-Json

$response = Invoke-WebRequest -Method Post `
  -Uri "$base/agent/v2/chat" `
  -Headers $headers `
  -ContentType 'application/json' `
  -Body $body
$answer = $response.Content | ConvertFrom-Json
$receipt = $response.Headers['X-Feedback-Receipt']
```

响应是 `AnswerResponse`，核心字段为：

- `mode`: `answered`, `partial`, `not_found`, `permission`, `unsafe`,
  `system`, `budget`, `security_filtered`;
- `answer`: 最终回答或有界拒答；
- `claims`, `citations`, `sources`: 证据与引用；
- `warnings`, `stop_reason`;
- `trace`: 已脱敏的 Agent 轨迹。

成功响应头 `X-Feedback-Receipt` 是服务端 HMAC，绑定 verified actor、当前回答的
request ID 和精确 question/answer keyed digests。

## 5. Feedback

请求使用与 chat 相同的 user bearer：

```json
{
  "target_request_id": "manual.identity-smoke-1",
  "question": "What is the current remote-work policy?",
  "answer": "Use the exact answer returned by chat.",
  "helpful": true,
  "receipt": "64 lowercase hexadecimal characters"
}
```

服务端先验证 receipt，再保存：

- submission request ID 与 target request ID；
- actor、question、answer 的 secret-keyed HMAC；
- `helpful` 与 binding version。

数据库不保存 bearer、原始 subject/claims、原始 question/answer，也不使用可离线
枚举的裸内容 SHA-256。同一 actor/target/content 的重试原子更新最新 rating；
复用 request ID 但内容不同会保留为不同记录。

## 6. Identity And Operator Routes

`GET /identity/me` 是唯一有意公开给已认证调用者的身份映射，返回固定字段：

```json
{
  "subject": "employee-one",
  "tenant_id": "tenant-one",
  "region": "cn",
  "groups": ["employees"],
  "roles": [],
  "issuer": "https://identity.localhost/",
  "audience": "enterprise-rag-api",
  "key_id": "demo-key-id"
}
```

实际 persona 值取决于本地身份 bundle。`rag.operator` 只授权 metrics/trace；
服务角色在转换成 Agent `UserContext` 时被移除，不能扩大文档 ACL。

operator smoke：

```powershell
$operatorToken = (Get-Content .private\identity\operator_token.txt -Raw).Trim()
$operatorHeaders = @{ Authorization = "Bearer $operatorToken" }
Invoke-RestMethod -Headers $operatorHeaders `
  -Uri 'http://127.0.0.1:8000/observability/metrics'
```

## 7. Health And Readiness

- `/health/live` 只说明进程和 HTTP loop 可响应；
- `/health/ready` 返回最近一次受控资源探针快照；
- protected business route 只读取该快照，不在请求线程触发模型冷加载；
- index、数据库、identity、retrieved-content Guard 或模型合同失败时返回 503。

模型深探针使用生产实际端点和 active index 合同；它与轻量公开 health 分离。
readiness 不是业务质量分数，也不保证真实 IdP、外部网络或生产 SLO。

## 8. Request ID

调用者可传 `X-Request-ID`，格式为 1-64 个
`A-Z a-z 0-9 . _ -`。值非法或缺失时，服务端生成新的安全 ID。
请求 ID 用于低敏 trace、日志关联和 feedback target，但不是身份或 answer 的唯一
主键，不能单独证明内容一致。

## 9. Retired Interfaces

以下接口在当前 app 中不存在：

```text
POST /ingest
POST /chat
POST /agent/chat
```

索引更新使用 E2 的版本化 build/activate CLI；固定 RAG 与旧 Agent 只保留在历史
评测代码和文档中。生产包不再导出 `create_compatibility_app()`，因此不能通过
包装模块把无认证历史路由重新绑定到 LAN 或公网。

# R2-S5 Trusted Identity Boundary 实现与面试指南

状态：实现、最终全量复跑、冻结矩阵、性能基准和整仓审计已完成；独立安全
复核正在收口，commit/push 与 exact-SHA Ubuntu/Windows CI 仍待发布后补证据。

这份文档面向第一次系统学习 JWT、JWKS、认证和授权边界的读者。它不只
列出“加了哪些技术”，而是解释原问题、信任如何流动、每个文件承担什么
责任、为什么这样拆分、测试如何驱动实现，以及面试时怎样准确说明成果和
局限。

## 1. 先理解原来的安全问题

原来的 V2 请求大致是：

```json
{
  "question": "公司的远程办公规则是什么？",
  "top_k": 5,
  "user_context": {
    "user_id": "user_employee",
    "tenant_id": "starbridge-cn",
    "region": "cn",
    "groups": ["all_employees"],
    "roles": []
  }
}
```

`AccessPolicy` 会认真检查文档的 tenant、region、groups 是否与
`user_context` 匹配。但是这个对象由客户端自己填写，服务端无法证明它
来自谁。攻击者只要把 groups 改成更高权限的组，后面的 ACL 即使逻辑完全
正确，也是在检查一份伪造身份。

所以问题不是“没有 ACL”，而是“ACL 的输入没有可信来源”。R2-S5 的目标
是把身份权威移到服务端入口：客户端只能提交问题，不能提交自己是谁。

## 2. 认证、授权和业务 ACL 不是一件事

三个概念需要分开：

1. **认证 Authentication**：这个请求是谁发的？本项目用签名 JWT 回答。
2. **服务授权 Service authorization**：这个已认证的人能否看全局 metrics
   或 trace？本项目用 `rag.operator` 角色回答。
3. **业务数据授权 Document authorization**：这个人能否读取某个知识库
   文档？原有 `AccessPolicy` 用 tenant、region、groups 回答。

本项目最重要的隔离规则是：`rag.operator` 只允许调用运维接口，绝不能
让 Agent 多看文档。为此 `Principal.roles` 会保留服务角色，但转换给 Agent
的 `UserContext.roles` 永远是空列表。

## 3. 完整信任流程

```text
客户端选择 persona
  -> 从忽略目录读取短期 Bearer token
  -> 只发往 http://127.0.0.1:<port>
  -> TrustedIdentityMiddleware 在解析业务 body 前运行
  -> 严格解析 JWT header 和 payload
  -> 使用本地固定 JWKS 中的 RSA 公钥验证签名
  -> 校验 issuer/audience/type/kid/时间/claim 类型
  -> 生成不可变 Principal
  -> 普通路由：Principal 转换成 UserContext
  -> 运维路由：先检查 Principal.roles 中的 rag.operator
  -> AccessPolicy 再做 tenant/region/groups 文档过滤
  -> 检索和 Agent 只能看到服务端派生的 UserContext
```

这里没有 LLM。身份验证必须是确定性代码：同样的 token、密钥和时间条件
应得到同样的允许或拒绝结果；不能让概率模型决定一个签名是否有效。

## 4. JWT 和 JWKS 到底是什么

### 4.1 JWT

JWT 通常由三个用点号连接的 base64url 段组成：

```text
header.payload.signature
```

- header 说明算法、token 类型和使用哪个 key ID；
- payload 放 issuer、audience、subject、过期时间和本项目身份字段；
- signature 是私钥对前两段计算的签名。

JWT 默认只是“签名”，不是“加密”。拿到 token 的人通常能解码 header 和
payload，所以项目不把密码、私钥或其他秘密放入 claim。

### 4.2 JWKS

JWKS 是一组公开验证密钥。API 只加载 RSA 公钥；本地签发工具保存私钥。
API 可以用 `kid` 在 JWKS 中找到公钥并验证签名，却不能用公钥伪造新 token。

这种分离比“API 自己同时持有签发私钥”更接近真实生产架构中的职责边界。
本阶段的 JWKS 是本地文件快照，不是远程 OIDC/JWKS 服务。

## 5. 配置和依赖

### 5.1 `requirements.txt`

新增并固定：

```text
PyJWT==2.13.0
cryptography==49.0.0
```

PyJWT 负责成熟的 JWT 签名和标准 claim 验证；cryptography 提供 RSA 密钥和
密码学实现。项目没有手写 RSA 或签名算法，因为手写密码学的风险和维护
成本远大于收益。

### 5.2 `app/config.py`

身份配置包括 JWKS 路径、issuer、audience、固定 `RS256`、固定
`at+jwt`、时钟偏差、最大 token 生命周期、token/JWKS 文件大小和 key 数量
上限、operator 角色，以及 feedback HMAC key 路径。

配置本身也是安全边界：

- issuer 必须是没有 userinfo、query、fragment 的 HTTPS URL；
- algorithm 和 token type 使用字面量白名单；
- audience 和 operator role 必须是严格、非空的值；
- 仓库内的身份材料只能位于被 Git 忽略的 `.private`；
- 相对路径先解析成确定的绝对路径，再检查位置。

为什么不能把这些判断散落在路由里？因为集中配置更容易测试、审计和部署，
也避免两个路由采用不同的安全规则。

## 6. 身份核心：`app/security/identity.py`

### 6.1 `Principal`

`Principal` 是签名和 claim 全部验证成功之后的服务端身份对象。主要字段有
subject、tenant、region、groups、roles、issuer、audience、key ID 和签发/
过期时间。

它是严格且不可变的，客户端 schema 不接受这个类型。这样可以防止后续代码
误把一个普通字典当成“已经认证过的身份”。

### 6.2 `LocalJwksKeyProvider.load()`

这个函数把本地 JWKS 加载成一次性的不可变公钥映射。它检查：

- 文件必须是普通文件，不能是 symlink/reparse point；
- 文件大小和 key 数量有上限；
- JSON 不能有重复键；
- `kid` 唯一、非空、可打印 ASCII 且有长度限制；
- 只接受公有 RSA key、`RS256`、签名用途和至少 2048 bit 模数；
- 拒绝私钥成员和不支持的 key metadata；
- 读取前后的文件描述符信息必须一致，降低读到被替换文件的风险。

“不可变快照”意味着轮换文件后要重启 API。这个取舍降低了运行时文件变化、
竞争条件和调试复杂度，适合当前本地可复现阶段。

### 6.3 `_parse_compact_jwt()` 和 `_decode_unique_json_object()`

在调用 PyJWT 验签之前，项目先做严格预解析：

- 必须正好三段且都非空；
- base64url 字符和解码长度受限；
- header 和 payload 必须是 JSON object；
- 任意重复 JSON key 都拒绝；
- header 只能有 `alg`、`kid`、`typ` 三个成员。

为什么验签前还要自己解析？签名只能证明字节没有被改，不能保证两个 JSON
解析器对重复键的解释一致。默认 `json.loads` 对 `{"alg":"RS256",
"alg":"none"}` 会保留其中一个值，而不同组件可能保留不同值。这叫解析器
差异风险，所以边界在验签前先统一并收紧语法。

### 6.4 `LocalJwtIdentityVerifier.verify_bearer()`

该函数完成：

1. 检查 Bearer scheme、空格、ASCII 和总长度；
2. 严格预解析 compact JWT；
3. 从不可变 JWKS 按 `kid` 取公钥；
4. 让 PyJWT 只使用配置中的 `RS256`；
5. 验证签名、issuer、标量 audience、exp、iat 和可选 nbf；
6. 拒绝 bool/float 时间值和超过上限的 token 生命周期；
7. 严格构造 `Principal`。

外部只得到三类安全结果：缺失认证、无效 token、身份服务不可用。错误响应
不会告诉攻击者到底是签名错、kid 不存在还是 token 已过期。

### 6.5 `Principal.to_user_context()`

映射关系是纯函数：

```text
subject   -> user_id
tenant    -> tenant_id
region    -> region
groups    -> groups
roles     -> []
```

最后一行是有意设计，不是漏写。它隔离运维角色与文档访问策略。

### 6.6 `FeedbackActorHasher`

反馈 actor 不是 `SHA256(subject)`，因为常见 subject 范围很小，攻击者可以
枚举所有候选用户并对比 hash。项目改用独立秘密 key 的 HMAC：

```text
HMAC-SHA-256(key, domain || issuer || subject)
```

domain separation 防止同一 key 在其他用途中的摘要与反馈 actor 混用。HMAC
key 独立于 JWT 私钥，降低一个用途泄漏影响另一个用途的风险。

## 7. API 边界

### 7.1 `app/api/identity.py::TrustedIdentityMiddleware`

这是整个功能最关键的入口。它按 method 和 path 识别受保护路由，并在
FastAPI 解析 JSON body 前完成认证。

为什么必须在 body validation 前？假设攻击者没有 token，却提交一个精心
构造的坏 body。如果先返回 422，攻击者可以在未认证状态下探测内部 schema；
更重要的是，安全决策优先级变得不稳定。现在固定为：无效 token 始终先 401。

中间件还会拒绝两个 Authorization header，避免代理、框架和应用对重复 header
采用不同解释。

### 7.2 状态码契约

```text
没有或无效 Bearer             401 + WWW-Authenticate: Bearer
token 有效但没有 rag.operator  403
JWKS/verifier/HMAC 不可用       503 identity_unavailable, retryable=true
token 有效但 body 带身份覆盖    422
```

401 表示“还没有有效认证”，403 表示“已经知道你是谁，但你没有这个操作权限”，
503 表示身份基础设施当前不可用而不是调用者凭据一定错误。

### 7.3 `app/main.py`

主要变化：

- `create_app()` 装配请求上下文和身份中间件；
- `/agent/v2/chat` 从 `request.state.principal` 派生 `UserContext`；
- `/feedback` 使用认证 principal 生成 actor HMAC；
- metrics 和 trace 由中间件要求 operator；
- 新增 `/identity/me`，只返回约定的安全身份字段；
- 生产模块不再导出 compatibility factory，旧 `/ingest`、`/chat`、
  `/agent/chat` 无法被包装模块重新启用。

Compatibility app 只是本地旧接口回归工具，不是生产回滚方案。显式
acknowledgement 的价值是让误用从“默认成功”变成“默认失败”。

### 7.4 `app/api/errors.py`

`ApiError` 增加 headers 支持，错误处理器会保留 `WWW-Authenticate`。这看似
很小，却是 HTTP 认证协议的一部分；没有 challenge header 的 401 契约不完整。

## 8. Schema 与数据流

### 8.1 `app/schemas.py`

`AgentV2ChatRequest` 只保留 question 和 top_k，并继续 `extra="forbid"`。
因此客户端即使偷偷加 `user_context` 也会得到 422，不能覆盖 token 身份。

`FeedbackRequest` 新增 `target_request_id` 和 64 位小写十六进制 `receipt`。
前者让赞/踩明确指向哪次回答，后者证明 actor、target、question、answer 与
服务端刚刚签发的回答一致。
`IdentityResponse` 为 `/identity/me` 定义固定输出，避免直接序列化整个内部
Principal。

### 8.2 `app/runtime/resources.py`

`ServiceContainer` 现在拥有 verifier 和 feedback actor hasher。路由不自己读
配置或 key 文件，依赖统一由容器装配。

readiness 新增 `identity`：只有 verifier 和 HMAC hasher 都 ready 才是 ok。
失败响应只写 `error`，不会暴露磁盘路径、kid 或异常文本。

数据库 schema/migration 只在受控 lifespan `start()` 的后台初始化中执行一次。
`/health/ready` 和业务请求只读取最近快照，不会取得写锁、触发 `VACUUM` 或发起
模型网络请求；TTL 过期时 fail closed，由后台线程刷新。

模型 readiness 不再只看 `/api/tags` 的名称。后台深探针实际调用 `/api/embed`，
要求向量全部有限且维度等于 active index manifest；chat/evidence 使用生产相同
的最小 `/api/chat` 非流式请求并校验 `message.content`。tags、embed 和两个 chat
模型共享最长 60 秒总 deadline，不是每项各 60 秒。

### 8.3 `app/observability/tracing.py`

新增 `readiness.identity` 到封闭 span 白名单。封闭白名单能阻止任意字符串
污染 tracing schema，但每增加一个合法 operation 都必须同步登记。

## 9. Feedback 数据库工程化迁移

`app/db.py` 的新表保存：

- 当前 feedback 请求 ID；
- 被评分回答的 `target_request_id`；
- actor HMAC；
- domain-separated question/answer HMAC-SHA-256；
- helpful 布尔值；
- receipt binding version；
- legacy row ID 和时间。

旧数据库不能简单删除重建，因为工业系统需要保留已有数据。迁移流程是：

1. `CREATE TABLE IF NOT EXISTS feedback_events`；
2. 用 `PRAGMA table_info` 判断旧 schema，再在事务内重建最终表；
3. 把旧 `feedback` 明文行转为 keyed HMAC 行；
4. 用 `legacy_feedback_id` 防止重复导入；
5. 删除明文表；
6. 先持久化 `feedback_vacuum_required=1`，再执行 `VACUUM`；
7. 只有 `wal_checkpoint(TRUNCATE)` 明确返回完整成功才清除 marker。

幂等意味着 `init_db()` 运行两次不会重复迁移同一行。这是部署启动和失败重试
都需要的性质。

旧数据没有可信 actor 或无法从普通 SHA 升级为 HMAC 时使用全零 sentinel，并
写明 `unverifiable` binding version，而不是猜测身份。当前 feedback 的部分
唯一键包含 actor、target、question HMAC 和 answer HMAC：同一回答重试只更新
一行，而调用方复用 request ID 提交不同回答时不会静默覆盖旧反馈。

所有生产数据库连接使用 `contextlib.closing` 明确释放。`check_db()` 使用
SQLite URI `mode=ro`；数据库文件丢失时返回 false，但不会制造一个空库干扰恢复。

## 10. 本地身份生命周期

### 10.1 `app/security/demo_identity.py`

负责生成和维护：

```text
.private/identity/
  private-<kid>.pem
  jwks.json
  identity_manifest.json
  feedback_actor_hmac.key
  persona_tokens.json
  load_user_token.txt
  operator_token.txt
```

这些路径位于 Git 忽略目录，公开仓库只能包含代码和公共 benchmark，不包含
私钥或 bearer token。

### 10.2 `scripts/manage_demo_identity.py`

命令：

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity init
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity status
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity rotate
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity activate `
  --kid <pending-kid> --api-base-url http://127.0.0.1:8000
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity retire --kid <old-kid>
```

- `init` 拒绝意外覆盖；
- `rotate` 只 stage 新公钥，active key 和全部客户端 token 保持不变；
- 重启 API 后，`activate` 用 pending key probe `/identity/me`，确认 snapshot
  回显同一 `key_id` 后才发布新 token；
- `retire` 只能删除非 active key，而且旧 key 在 `retire_not_before` 前会被硬拒绝；
- `status` 打印 key ID、pending key、退役 deadline、紧急撤销计数、persona 数量和
  是否需要重启，不打印秘密。

API 加载的是启动时快照，所以 rotate 后先重启再 activate；activate 成功后无需
立即重启，因为 snapshot 已含旧/新公钥。旧 token overlap 结束后 retire 旧 key，
再重启以移除旧验证材料。manifest 是唯一 commit point，journal 支持崩溃恢复；
owner/mode/DACL/hardlink、序列化 journal 上限和有界跨进程锁均失败关闭。

deadline 不是口头约定。activate 会把“最大 demo token 生命周期 900 秒 +
API 允许的最大 clock skew 120 秒”写入 v3 manifest。它故意不使用当前默认
30 秒，因为 API 可能在激活后调高 skew。普通 retire 和 journal recovery
都会重新检查。
密钥泄露时可使用 break-glass 参数，但 Python API 和 CLI 都要求精确确认短语
`RETIRE_ACTIVE_TOKENS_NOW`，并把 key ID/撤销时间写入非秘密审计字段。

## 11. 安全 token 来源

`app/security/token_source.py` 把“怎样得到 token”抽象成 provider：

- `StaticBearerTokenSource`：环境变量中的一个 token；
- `BearerTokenFileSource`：每次请求重新读取一个私有文件；
- `PersonaTokenBundleSource`：按 persona ID 从 bundle 中取 token。

环境变量与文件只能二选一。文件有大小限制、普通文件检查、无 symlink/reparse
检查，token 必须是 ASCII compact JWT。persona bundle 还拒绝重复 JSON key。

每次请求重新读文件支持短期 token 更新，不需要把 token 放入长期进程状态。
对象字段使用 `repr=False`，UI session、错误和输出产物都不保存 credential。

## 12. Streamlit 和负载工具迁移

### 12.1 `streamlit_app/api_client.py`

客户端现在：

- chat/feedback 按 persona 读取普通用户 token；
- trace 使用独立 operator token；
- 请求仅允许发到规范化 `http://127.0.0.1[:port]`；
- 拒绝 localhost 别名、userinfo、非根 path、query、fragment；
- `requests.Session.trust_env=False`；
- `allow_redirects=False`。
- public/persona/operator 使用三个拒绝 cookie 的独立 Session；
- chat 成功必须返回可验证格式的 `X-Feedback-Receipt`。

最后三项是 bearer 防外发控制。若允许任意 URL、环境代理或 302 跳转，token
可能被发往攻击者控制的目的地。

### 12.2 `streamlit_app/pages/1_Ask.py`

删除了可编辑的 user/tenant/region/groups/roles。Demo 和自定义问题都只能选择
已有 persona。回答完成后，UI 临时保存 request ID 和 feedback receipt；提交
成功即清除 receipt 并禁用按钮。数据库仍负责真正的跨请求幂等边界。

### 12.3 `streamlit_app/shell.py`

只配置 persona bundle 和 operator token 文件路径，不读取私钥，也不把 token
塞进 Streamlit session state。`.streamlit/config.toml` 把监听地址固定为
`127.0.0.1`；没有浏览器侧认证时绝不允许监听 LAN/WAN。

### 12.4 `scripts/load_profile.py`

负载测试也不能绕过生产边界，所以它删除 body identity，chat 使用普通用户
token，metrics 使用 operator token，并保证保存的 latency/错误产物里没有
token。HTTP session 同样禁用环境代理和重定向。

## 13. 公开仓库审计和 benchmark

### 13.1 `scripts/audit_public_repo.py`

公开审计新增 compact JWT 形状检测。测试中的合成 JWT 必须被判定为
`credential_token`。这可以防止 persona token 或 operator token 被误提交。

注意：审计器新增规则并通过单测，不等于整仓最终审计已经运行通过。后者仍是
发布门禁。

### 13.2 `app/security/identity_benchmark.py`

它在固定 warmup 后重复验证同一个合法 token，记录 p50/p95/p99/max 和运行
环境，不写 token、claim、路径或 key。

当前证据：

```text
warmup                 50
iterations           1000
p50                 0.0546 ms
p95                 0.0904 ms
p99                 0.1433 ms
max                 0.3601 ms
local target        p95 <= 10 ms, met
```

命令使用 `--ephemeral-demo` 在系统临时目录创建一次性托管身份，因此不会读取、
轮换或覆盖真实 `.private/identity`。输出只有聚合延迟和运行环境，不包含
credential 或临时路径。

这只能证明“本地内存 JWKS 快照下，单次 warm RS256 verifier 很快”。它不能
代表 HTTP、RAG、LLM 或远程 IdP 总延迟，也不作为不同 CI 主机的硬时间门禁。

## 14. TDD 的 RED -> GREEN 过程

### 14.1 配置

- RED：设置对象没有 identity 字段，访问时报 `AttributeError`。
- GREEN：新增严格字段、路径和 issuer/audience/operator 验证。

### 14.2 JWKS

- RED：identity/JWKS 模块不存在，测试 import 失败。
- GREEN：先实现一个合法 2048-bit RSA 公钥快照，再逐个加入负面约束。

### 14.3 JWT

- RED：合法 token 无法转换成 Principal；bool `nbf` 被 Python 当作 int；服务
  role 流入 Agent context。
- GREEN：固定算法验证、严格 timestamp 类型、角色域隔离。

### 14.4 重复 JSON key

- RED：Python 默认 JSON parser 接受重复 header/payload key，保留一个值。
- GREEN：签名验证前使用 `object_pairs_hook` 拒绝任何重复名。

### 14.5 readiness span

- RED：identity probe 加入后，`readiness.identity` 不在 tracing 白名单，合法
  probe 被当成非法 span。
- GREEN：同步更新类型字面量和运行时 allowlist，保留封闭 schema。

### 14.6 Windows 原子文件

- RED：临时文件仍被进程持有时执行 `os.replace`，Windows 返回
  `WinError 32`。
- GREEN：先 flush/close，再 replace；异常时清理 staging 文件。

### 14.7 历史测试迁移

- RED：首次全量为 `1745 passed, 17 skipped, 3 failed`。三个失败仍认为 body
  `user_context` 是合法合同，或仍依赖历史 compatibility app。
- GREEN：迁移到 bearer 身份新合同；最终复核又证明“显式危险确认”不能约束
  真实监听 socket，因此彻底从生产模块删除 factory。
- 复审前整树基线：`1817 passed, 19 skipped, 3 warnings in 132.17s`。该数字
  随后被独立复核发现的问题作废，不能再作为最终发布证据。

### 14.8 独立复核驱动的工程修复

- RED：没有 manifest 的身份目录仍可能按 standalone 文件读取。
- GREEN：生产 verifier/hasher/token bundle 默认必须通过 manifest commit point；
  standalone 只保留为显式测试或外部单 token 文件选择。
- RED：有 SQLite WAL reader 时，`VACUUM` 后的 checkpoint 可能返回 busy，但旧
  代码没有检查返回三元组。
- GREEN：busy、剩余 frame、缺失或畸形 checkpoint 都保留 migration marker，
  readiness 继续 not-ready，下次受控启动重试。
- RED：同一用户对同一回答重复 feedback 会增加多行；只用
  `(actor_hmac_sha256, target_request_id)` 又会在复用 correlation ID 时覆盖
  不同回答。
- GREEN：使用 actor/target/question-HMAC/answer-HMAC 部分唯一索引，加
  `BEGIN IMMEDIATE`/upsert；同一回答重试只更新最新 rating，不同内容保留。
- RED：SQLite context manager 只提交/回滚，不保证关闭连接；readiness 在 DB
  文件缺失时会创建空库。
- GREEN：所有连接由 `contextlib.closing` 明确持有；`check_db()` 使用
  `mode=ro` URI，缺文件返回 false 且零落盘。
- RED：`/api/tags` 里存在模型仍可能在真正加载 GGUF 时失败。
- GREEN：后台 readiness 实际执行等维有限 embedding 与最小 `/api/chat`，
  共享一个总 deadline；请求路径只读快照。
- RED：Streamlit 配置可监听所有网卡，本地 persona/operator token 会离开预期
  回环边界。
- GREEN：默认监听精确 `127.0.0.1`，并由仓库配置测试锁定。

## 15. 当前验证结果如何解读

```text
复审前完整 pytest            1835 passed, 20 skipped, 3 warnings（历史）
复审前 identity matrix      20/20（历史）
当前 framing/audit RED-GREEN 14 passed
当前 boundary/audit/redaction 127 passed
当前 lifecycle/CLI          40 passed, 2 skipped
当前 benchmark contract     4 passed
当前 public audit           515 candidates, 0 findings
当前 benchmark              p95 0.0904 ms, target met
当前 matrix v2              20/20, 2ec62b6e...7c12
当前 full pytest            1906 passed, 20 skipped, 3 warnings
当前 compile/pip/diff       PASS / CLEAN / PASS
最终独立复核/远端 CI        0C/0I PASS / 待执行
```

后续独立复审用 `HOLD` 作废了 `1835`、旧 matrix 和旧 benchmark 的“最终”
标签；它们只能解释修复前状态。当前聚焦回归、`515/0` 和 source-bound
benchmark 不能与历史数字相加。修复后的 matrix、完整工作树和双 reviewer
`0 Critical / 0 Important` 已通过，但仍不能代替 exact-SHA 双平台 CI。

## 16. 工业化价值，不只是技术堆叠

### 16.1 默认失败而不是默认放行

JWKS 或 HMAC key 不可用时，protected route 返回 503；不会退回 body identity，
不会临时跳过认证。旧 compatibility factory 已从生产模块删除，不存在可被外部
ASGI runner 误绑定的未认证入口。

### 16.2 运维可判断但不泄密

liveness 回答“进程活着”，readiness 回答“是否应该接流量”。identity 只暴露
ok/error，足够部署系统摘除实例，又不泄露 key 路径。

### 16.3 可升级和可回滚的数据

SQLite 使用幂等 schema/data migration，不要求清空数据库。旧明文会转 hash、
删除来源表并 VACUUM。失败修复和限制都有测试与工程日志。

### 16.4 有生命周期而不是只有一次性 demo token

密钥可以 init、重叠轮换、退休；用户 persona 和 operator credential 分开；
客户端每次读取短期 token。这个流程能演示真实运维概念。

### 16.5 控制 credential 传播路径

服务端只持公钥；UI 不读私钥；token 不进 session state、日志、trace、错误或
负载产物；本地客户端只允许数值 loopback，并禁代理/重定向。

### 16.6 证据分层

项目区分 focused test、full suite、public audit、independent review、exact-SHA
CI。没有把一个局部 `passed` 宣传成生产完成，这是工程可信度的一部分。

## 17. 已知局限

1. 这是本地合成身份源，不是真实企业 IdP、SSO 或 OIDC discovery。
2. 没有 refresh token、logout、token revocation、SCIM 或动态策略管理。
3. JWKS 是启动时文件快照；`rotate` stage 后必须重启再 `activate`，没有远程
   cache/refresh 或远程故障转移。
4. 私钥受本机文件权限保护，不是 HSM/KMS/硬件密钥。
5. operator 是全局服务角色，没有更细的按 tenant 运维授权。
6. feedback receipt 是本地服务端 HMAC 证明，不是跨服务 durable answer record；
   数据库按 actor/target/content latest-rating upsert，没有独立分析平台和
   retention policy。
7. benchmark 是本地 warm verifier microbenchmark，不是端到端性能结果。
8. 最终全量和整仓审计已完成；独立 review 和 exact-SHA Ubuntu/Windows CI 以最新发布
   记录为准，不能由本地 matrix 替代。
9. 固定 R2-S5 evaluator 已实现 20 条 matrix；它只证明该冻结矩阵，不代表未知
   攻击、真实 IdP 或生产流量。

## 18. 面试常见问题与参考回答

### Q1：你为什么先做身份边界，而不是继续加 Agent 工具？

答：现有 ACL 能按 tenant、region、groups 过滤，但身份由 body 自报。继续加
工具会扩大一个不可信身份的能力。R2-S5 先修复 authority source：只有服务端
验签后生成的 Principal 能进入 Agent。这是风险优先级和系统边界问题，不是
模型能力问题。

### Q2：为什么认证不使用 LLM？

答：签名、issuer、audience、过期时间和 claim 类型都有精确定义，需要稳定、
可复现、可审计的判断。LLM 输出有概率性，也不能替代密码学验签。LLM 可以
参与业务 Agent，但不能成为 trust root。

### Q3：JWT 有签名，为什么还要严格预解析 JSON？

答：签名保证字节完整性，不保证多个解析器对重复 key 的语义一致。默认 JSON
可能接受重复 `alg`、`aud` 或 `exp`，不同组件若保留不同值会形成 parser
differential。项目在 PyJWT 前先限制三段格式、对象类型、唯一 key 和 header
allowlist，再做密码学验证。

### Q4：如何避免算法混淆攻击？

答：算法由服务配置固定为 RS256，并以单元素 allowlist 传给 PyJWT；不会根据
未验证 header 动态选择算法。header 也必须恰好是 alg/kid/typ，拒绝 none、
HS/RS 混淆和远程 key reference。

### Q5：401、403、503 为什么要分开？

答：401 是没有有效身份，并带 Bearer challenge；403 是身份有效但缺少 operator
权限；503 是本地身份基础设施不可用，调用者稍后重试可能成功。分类既符合
HTTP 语义，也让运维区分调用方问题和服务端故障，同时错误文案不泄露细节。

### Q6：为什么 authentication middleware 要早于 body validation？

答：保证未认证请求始终先得到认证结果，避免 422 schema oracle，也确保坏 body
不会在身份检查前触发业务依赖。测试覆盖“无效 token + 恶意 body = 401，并且
Agent 未调用”。

### Q7：为什么 operator role 不传给 Agent？

答：operator 是服务运维授权，文档可见性是业务 ACL。若混在一个 roles 列表，
未来 retrieval 或 prompt 逻辑可能误把 operator 当文档超级权限。项目明确让
`Principal.roles` 用于 API，而 `UserContext.roles=[]`，缩小权限耦合和爆炸半径。

### Q8：为什么 feedback actor 用 HMAC 而不是 SHA-256？

答：subject 通常可枚举，例如 user001 到 user999。纯 SHA-256 可被离线字典反查。
HMAC 需要服务端秘密 key，攻击者即使拿到数据库也不能按候选 subject 直接重算。
项目还使用 domain separation，并让 HMAC key 与 JWT signing key 独立。

### Q9：为什么 SQLite 删除表以后还要 VACUUM？

答：SQLite DROP 后，旧页可能只是进入 freelist，明文字节仍在数据库文件中。
VACUUM 重建文件，可清理旧 question/answer 的物理残留。迁移测试不只查 SQL
表，还直接扫描数据库 bytes，验证旧明文不再出现。

### Q10：密钥轮换怎样工作？

答：init 建立 active key。rotate 只把新公钥 stage 成 pending，active key 和
现有 token 都不变；重启 API 后，它的 immutable snapshot 同时认识 old 和
pending。activate 用 pending 私钥签一个 60 秒内存 probe，请求精确 loopback
`/identity/me`，只有返回 200 且 `key_id` 精确匹配才发布新 token 并切换 active。
旧 token 在 overlap 期仍有效；到期前普通 retire 会失败，到期后 retire 旧 key
并再次重启。这样避免
“token 已换新、运行中的 API 却还不认识新 key”的窗口故障。

### Q11：如何防止 UI 把 token 发错地方？

答：本地 client 只接受规范 numeric loopback origin，拒绝路径、query、fragment、
userinfo 和 hostname alias；requests 禁用环境代理和 redirect。token 来源每次
读取且不进 session/log/error。未来远端模式必须单独设计 HTTPS allowlist，
当前不能把本地规则直接宣传成生产网络方案。

### Q12：readiness 失败为什么不直接让进程退出？

答：liveness 和 readiness 目标不同。进程仍能提供诊断性低敏 health，但没有
identity material 时不应接 protected traffic。返回 not-ready 让编排层摘流，
同时为配置修复保留可观察窗口。

### Q13：你遇到过什么真实工程问题？

答：有多个典型问题。第一，默认 JSON 接受重复 key，需要严格 parser；第二，
新增 readiness probe 忘记同步 tracing span allowlist，合法行为被 schema 拒绝；
第三，Windows 不允许替换仍打开的临时文件，出现 WinError 32，修成 close 后
replace；第四，SQLite checkpoint 即使 SQL 不抛异常也可能返回 busy，必须检查
返回三元组；第五，feedback receipt 若没有数据库唯一语义仍可被重放放大。
这些都记录了 RED、根因、修复和回归测试。

### Q14：你怎么证明改进有效？

答：证明分层，而且复审可以作废旧证据。后续 `HOLD` 后，`1835/20`、
`1892/20`、旧 matrix SHA 和 p95 `0.0957 ms` 都降为历史检查点。当前新
framing/audit RED-GREEN `14`、更宽 boundary/audit/redaction `127`、
lifecycle/CLI `40/2`、benchmark contract `4` 均通过，公开审计是 `515/0`，
source-bound benchmark p95 是 `0.0904 ms`；
source-bound matrix 已重新通过 `20/20`，完整工作树通过
`1906 passed / 20 skipped / 3 warnings`，compileall、依赖完整性和 diff check
也通过。下一步由独立复核与 exact-SHA Ubuntu/Windows CI 绑定到同一个提交。
这种证据纪律比挑一组好看的旧数字更重要，也仍不能替代真实 IdP、生产流量或
owner review。

### Q15：这个方案与真实企业 IdP 的差距是什么？

答：接口和信任边界可以复用，但 key source 和生命周期要升级。真实环境需要
OIDC discovery、远程 JWKS cache/refresh、HTTPS 和 issuer allowlist、IdP
availability 策略、revocation/session/logout、secret manager 或 HSM、审计与
更细 operator policy。本阶段的价值是先把 Principal、API middleware、ACL
映射、错误语义、ready gate 和测试合同做正确，而不是伪装已经接入 SSO。

### Q16：为什么说它有工业化内容？

答：因为除了 JWT 技术，还处理了 fail-closed、HTTP 错误合同、低敏 readiness、
角色域隔离、SQLite 幂等迁移和物理明文清理、key overlap/retire 生命周期、
credential 传播控制、客户端 origin 限制、public audit、性能证据和发布门禁。
这些决定关注部署、升级、故障、隐私和可验证性，而不仅是功能演示。

## 19. 远端验收后需要补写什么

本地门禁已经基于真实命令补齐。提交推送后仍需补充：

1. 独立 whole-diff review 的 Critical/Important/Minor 最终结论；
2. commit SHA、GitHub 分支、Actions URL 和 exact-SHA CI 结果；
3. 若 Ubuntu CI 暴露 POSIX 专属失败，记录 RED、修复和新的精确 SHA，不得沿用
   旧本地结果冒充通过。

当前最准确的一句话是：

> R2-S5 已实现可信本地 JWT/JWKS 身份边界，通过 1906 条整树回归、20 条冻结
> 身份评测和 515 文件候选公开审计；它仍是本地可复现工业化样例，不是真实
> IdP 或生产部署认证。

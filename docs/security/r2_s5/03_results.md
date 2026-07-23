# R2-S5 Trusted Identity Boundary 结果档案

状态：工程复核的两个 Important 和安全复核最后一个 delimiter-separated safe
marker Important 均已修复。最终独立安全与工程 reviewer 都返回
`0 Critical / 0 Important / RELEASE`；新的聚焦回归、冻结评测和本地整树门禁
已通过，因此实现曾进入本地发布候选。精确提交 `d753df3` 的
exact-SHA Ubuntu/Windows CI #17 随后失败并阻止发布；三项失败均已修复且
本地重验通过。随后发现的目录 TOCTOU、错误对象权限副作用、FIFO 阻塞和
Windows owner/handle 生命周期问题也已修复，最终限定复审为
`0 Critical / 0 Important / 0 Minor / RELEASE`。修复提交
`11892531451750609f44138b7348f16b9b1316ff` 的 exact-SHA Actions #18 已在
Ubuntu 和 Windows 通过；这表示本地可复现合同完成远端验收，不表示真实 IdP
或生产部署认证。

## 1. 解决的不是“有没有 ACL”，而是“ACL 相信谁”

原系统已经按 tenant、region、groups 过滤文档，但 `/agent/v2/chat` 从请求体接收
`user_context`。调用者可以先自报身份，再进入正确执行的 ACL。R2-S5 把身份权威
移到 HTTP 服务端：

```text
Bearer JWT
-> 受限本地 JWKS 验签
-> 服务端 Principal
-> 去除服务角色后的 UserContext
-> 原有文档 ACL
-> Agent search/find/open
```

认证、角色判断和 ACL 都是确定性代码；LLM 不参与 trust decision。

## 2. 工程增改与责任边界

| 文件/模块 | 増改 | 工程原因 |
|---|---|---|
| `app/security/identity.py` | 严格 Bearer、JWT/JWKS、Principal、HMAC actor、私密文件快照 | 把密码学验证、身份映射和失败语义集中在一个可测试边界 |
| `app/api/identity.py` | ASGI 认证中间件、user/operator 路由策略、401/403/503 | 在 FastAPI 解析 body 和调用 Agent 前拒绝不可信身份 |
| `app/main.py` / `app/schemas.py` | 删除 body identity；从 Principal 派生 UserContext；保护 feedback/metrics/trace | 消除调用者自报身份和未认证运维接口 |
| `app/runtime/resources.py` | ServiceContainer 持有 verifier/hasher；readiness 增加 identity 和模型执行探针 | 缺 key 或模型无法实际加载时实例继续 liveness，但不应接业务流量 |
| `app/security/demo_identity.py` | init/rotate/activate/retire/status、短期 persona/user/operator token | 提供无重启窗口断流的分阶段本地身份生命周期，而不是硬编码测试 token |
| `app/security/private_fs.py` | held directory、原生 handle/descriptor 身份验证、ACL/mode 加固和严格 owner 策略 | 把权限副作用绑定到已经验证并保持打开的对象，拒绝路径替换和不可信 owner |
| `app/security/token_source.py` | 静态/文件/persona token source，每次请求重读文件 | 轮换后客户端无需把 token 放进 UI session state |
| `streamlit_app/api_client.py` / `scripts/load_profile.py` | 数值 loopback、禁代理、禁重定向、user/operator credential 分离 | 防止 bearer 被 URL、代理或 redirect 带离本地 API |
| `app/db.py` | feedback actor HMAC、目标 request ID、旧明文迁移/drop/VACUUM | 数据库不保存原 subject、token、问题或回答正文 |
| `app/evaluation/trusted_identity.py` | 冻结 20-case API matrix 和低敏结果 | 用行为证据验证状态码、身份映射、反馈绑定、拒绝副作用和泄漏 |
| `scripts/audit_public_repo.py` | JWT/常见 token 形状、Python AST 凭据绑定和非 Python 文本扫描 | 防止 demo token/云凭据进入 Git，同时不把普通 `token` 变量误判为硬编码 secret |

## 3. 关键安全合同

1. 只接受精确三段、规范 Base64url、UTF-8、无重复 JSON key 的 compact JWT。
2. header 只允许 `alg/kid/typ`，且固定为 `RS256` 和 `at+jwt`。
3. issuer、单值 audience、时间类型、最大 15 分钟 lifetime 和身份 claim 均严格验证。
4. JWKS 只接受 2048-bit 以上 public RSA verify key；拒绝 private members、重复
   kid、错误 key use/ops、超量文件和链接型最终组件。
5. `rag.operator` 只留在服务 Principal，用于 metrics/trace；进入 Agent 的 roles
   永远为空，不能绕过 tenant/region/groups ACL。
6. 缺失/无效 token 返回 401 和 Bearer challenge；权限不足返回 403；身份材料
   不可用返回可重试 503。三者不混用。
7. 被拒绝请求可以产生低敏请求审计记录，但不得调用 Agent、模型、检索或写 feedback。
8. 生产模块不注册旧 `/ingest`、`/chat`、`/agent/chat`，也不再导出可重新注册
   它们的 compatibility factory。

## 4. 固定评测与性能证据

冻结矩阵：`data/v2/security/r2_s5_identity_matrix_v1.json`

```text
matrix SHA-256                 fe5fdddd9cd4d067930b971ca0658a22deb63778723c31597df7f7fab70b4e2f
total/passed/failed            20 / 20 / 0
denied cases                   14
denied side-effect violations   0
credential leaks                0
matrix release_pass          true
```

公开结果只包含 case ID、预期/实际决策和有界计数；测试会从冻结矩阵重新执行并与
公开 JSON 精确比较。新鲜候选结果与公开证据的文件 SHA-256 均为
`0258f8c28c363c785751ef64330db5444f75e6169b5b263430dee7049b790829`。
结果 schema v2 还记录
`trusted-identity-contract-7c183871488a6519` 和 11 个 evaluator/API/identity/
persistence/runner 源码 SHA；不加入时间戳，因此同一源码可跨平台精确重算。
这里的 `release_pass` 只表示该 20-case matrix 通过，不等于
生产发布或真实 IdP 验收。

规范 Base64url 加固后的 Windows/CPython 3.11 本地 verifier microbenchmark：

```text
warmups / iterations      50 / 1000
p50 / p95 / p99 (ms)      0.0546 / 0.0904 / 0.1433
max (ms)                  0.3601
local target              p95 <= 10 ms, met
```

基准命令使用 `--ephemeral-demo`，在系统临时目录生成一次性托管身份，不读取或
改写真实 `.private/identity`。这是内存 JWKS 的 warm 验签开销，不是 HTTP、
IdP、检索或回答端到端延迟。

## 5. 实施中发现并修复的问题

完整 RED/GREEN 细节见 `01_engineering_journal.md`。高信号问题包括：

| 问题 | 根因 | 修复与证明 |
|---|---|---|
| 重复 JWT key 被默认 JSON 接受 | 通用 parser 保留一个重复字段 | 验签前 unique-object 预解析；header/payload 混淆用例通过 |
| bool timestamp 被当作 int | Python `bool` 继承 `int` | 显式排除 bool，只接受整数 NumericDate |
| 修改 signature 最后一字符仍验签成功 | 改到未使用 Base64 padding bits，解码字节未变 | 每段 decode/re-encode 必须与原串相同 |
| 服务 operator role 进入 Agent | Principal 与 UserContext 权限域未分开 | `to_user_context()` 固定 roles 为空并通过 HTTP 集成验证 |
| readiness 新 span 被封闭 schema 拒绝 | 可观测性 allowlist 未同步 | 只新增 `readiness.identity` 并保留封闭类型 |
| Windows `os.replace` 返回 WinError 32 | 临时文件描述符尚未关闭 | flush/fsync/close 后 replace |
| 第九次轮换写出超限 JWKS | 写入前没有 keyring capacity gate | 满 8 把时零写入拒绝，目录 byte snapshot 不变 |
| 篡改 manifest 可构造清理路径逃逸 | kid/private filename 语法过宽 | 固定 generated-kid/basename/JWK kid 一致性；目录外 sentinel 保持 |
| CLI `.resolve()` 擦除链接证据 | 在底层 reparse 检查前解析路径 | 改用词法 absolute，CLI 回归禁止提前 resolve |
| mounted/root-path 下 operator 路由可绕过 middleware | 安全匹配用原始 path，路由匹配用去前缀 path | 改用 Starlette 同源 application path；mounted 场景验证 401/403/200 |
| README 快速启动测试失败 | 新增必要身份初始化但旧合同仍写 3 条命令 | README 与测试同时升级为精确四步顺序 |
| 仓库扫描 2 个误报 | 请求头变量名和测试 URL userinfo 像凭证/邮箱 | 不放宽扫描器，改清晰变量名和保留 `.invalid` fixture |
| feedback 可被重放或同 ID 不同回答被覆盖 | 唯一键只有 actor/target，没有认证内容身份 | actor/target/question-HMAC/answer-HMAC 部分唯一索引与事务内 upsert；同回答重试更新，不同内容保留 |
| WAL 有 reader 时仍可能清理迁移 marker | 未检查 `wal_checkpoint(TRUNCATE)` 返回的 busy/剩余页 | 严格校验 checkpoint 三元组；不完整时保持 not-ready 并在下次启动重试 |
| readiness 刷新可能执行 schema/VACUUM | 初始化与公开探针职责混合 | migration 只在受控 `start()`；刷新只调用只读 `check_db()`，并用进程锁串行 |
| readiness 显示模型存在但真实业务端点失败 | 只检查 `/api/tags`，后来又用错 `/api/generate` 且未校验向量合同 | 后台实际 `/api/embed` + `/api/chat`；有限等维向量、响应结构与单一总 deadline |
| 公开 ready 或业务请求可触发多次冷加载 | TTL 到期时请求线程同步 refresh | `start()` 立即发布 fail-closed 快照；后台周期刷新；请求只读快照 |
| Streamlit 默认监听所有网卡 | persona/operator token 只适合本机 demo | `.streamlit/config.toml` 固定 `127.0.0.1`；配置回归测试防止恢复为 LAN 暴露 |
| 缺 manifest 时身份文件可被单独接受 | 读取器把无 manifest 目录当作 standalone | 生产 loader 默认要求托管 commit point；仅测试/显式外部 token source 可选择 standalone |
| rotate 后新 token 早于 API snapshot | JWKS 与 token 一次发布，但 verifier 是启动时快照 | rotate 只 stage key；重启 API；activate probe 精确 key_id 后再发布 token |
| 零字节 ASGI 分片可无限占用内存/连接 | body 只累计字节，没有消息数和总读取时间 | 认证后同时限制 128 KiB、256 消息和 5 秒；洪泛返回 413，慢体返回 408 |
| journal 目标已发布时跳过业务语义 | `current raw == target raw` 直接返回 | 所有操作验证完成态后置条件；activate journal 绑定 previous active key；operation schema 升至 v3 |
| benchmark 失败仍返回成功 | 结果只写 JSON，模块入口不使用 `target_met` | 先不可覆盖地写证据，再按目标返回 0/1；签入证据测试核对目标与源码 SHA |
| credential scanner 对常见名称失明并屏蔽整个测试函数 | key 列表窄，fixture mask 过宽 | 覆盖 client/AWS/refresh/generic token；Python 使用 AST；删除测试函数整体豁免 |
| API mode 和身份披露文档与代码冲突 | 文档沿用旧枚举和旧设计句子 | mode 精确对齐 Literal；`/identity/me` 明确九个字段、用途和不披露项 |

## 6. 运维流程和回滚

安全启动顺序：先 `manage_demo_identity init --force`，再启动 API，最后启动 UI。
token 到期后重新初始化并重启 API/UI。轮换时先 `rotate` stage 新公钥但保持旧
token，重启 API，再用 `activate --kid <pending>` 证明新 snapshot 后发布新 token。
等待旧 token 窗口结束后 `retire --kid <old>`，再重启。达到 8 把上限必须先
retire，系统不会自动写出不可加载 JWKS。

代码回滚不能恢复已退休的 unauthenticated legacy routes。若新版本身份检查失败，
正确运维动作是让 readiness 保持 not-ready、停止流量、恢复上一个受保护版本或
修复 secret mount；不能临时信任 body identity。

## 7. 依据与未覆盖边界

实现决策映射到 RFC 8725、RFC 9068、NIST SP 800-207 和 OWASP LLM06 Excessive
Agency，详见设计书第 4 节。它们用于形成固定算法、显式 token type、资源访问前
认证和按用户最小权限执行 Agent 工具等决定；项目不声称获得这些组织的认证。

仍未覆盖：真实 OIDC/SSO、discovery/JWKS cache、revocation/logout、HSM/KMS、
refresh token、tenant-scoped operator、分布式 trace、生产流量和 owner security
review。当前 feedback 由服务端 HMAC receipt 绑定 verified actor、target request
以及精确 question/answer；它不是 durable answer record，也没有跨服务 nonce
registry。精确同一回答的重复提交由数据库按 actor/target/content 原子 upsert，
因此不会增加统计行数；复用 request ID 的不同内容保留为不同记录。

## 8. 发布门禁

最终发布记录必须包含：聚焦身份回归、完整 pytest、compileall、`pip check`、
冻结 matrix 重算、public audit、diff check、独立 whole-diff review、commit SHA 和
该 SHA 的 Ubuntu/Windows GitHub Actions。任何缺项都只能写“本地实现完成/远程待验收”。

复审前历史证据（已被后续 `HOLD` 作废为最终证据）：

```text
historical full pytest            1835 passed, 20 skipped, 3 warnings
trusted identity matrix           20/20, 14 denials, 0 denied effects, 0 leaks
fresh/public matrix artifact      byte-identical, SHA-256 94125e66...a0b1e66
public repository audit           515 candidates, 0 findings
isolated RS256 verifier benchmark 1000 iterations, p95 0.0957 ms
```

当前候选聚焦证据：

```text
new framing/audit RED-GREEN       14 passed
boundary/audit/redaction          127 passed
lifecycle / CLI                    40 passed, 2 platform skips
benchmark contract                 4 passed
public repository audit            515 candidates, 0 findings
source-bound verifier benchmark    1000 iterations, p95 0.0904 ms, target met
CI #17 exact SHA                   d753df3; Ubuntu 1 fail; Windows 5 fail
CI repair affected contracts      151 passed, 4 platform skips
fresh matrix                       20/20, SHA-256 0258f8c2...0829
full pytest                        1918 passed, 22 skipped, 3 warnings
compileall / pip check / diff      PASS / CLEAN / PASS
post-CI scoped re-review           0C / 0I / 0M / RELEASE
repair commit                      11892531451750609f44138b7348f16b9b1316ff
Actions #18 Ubuntu                 1918 passed, 22 skipped, 4 warnings
Actions #18 Windows                1935 passed, 5 skipped, 4 warnings
Actions #18 public audit           515/0 on both platforms
```

跳过项来自平台条件；warning 是既有 FAISS/SWIG `DeprecationWarning`。修复后
完整回归耗时 `178.57s`。远端第四条 warning 是两个 runner 共有的
Starlette/httpx deprecation warning。CI #17 是正式失败证据，不会被删除；
[成功的 replacement run #18](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/30021508046)
与其并列保留。

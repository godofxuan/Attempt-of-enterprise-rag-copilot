# R2-S1 V3 精确 Ollama Origin/Socket 边界工程日志

日期：2026-07-19

状态：`V3 IMPLEMENTED AND LOCALLY VERIFIED`；V4-V5 未开始；未 commit、未 push、未 merge、未创建 tag。

## 1. 这一阶段解决什么问题

D7 为了调用本机 Ollama，在评测进程里使用 `LocalOllamaOnlyBoundary` 限制出站网络。V3 前，HTTP 和 socket 使用了两套强度不同的判断：

```text
HTTP:   URL origin 必须等于配置 origin
socket: 只要 host 是任意 loopback 且 port 相同就放行
```

例如配置是 `http://127.0.0.1:11434/v1`，旧 socket 条件仍会放行：

```text
127.0.0.2:11434
::1:11434
```

这不符合“只允许一个已配置 Ollama origin”的含义。`127.0.0.0/8` 都属于 IPv4 回环网段，但“都在本机”不等于“都是配置的 Ollama 服务”。同理，配置 IPv4 不应自动授权 IPv6，配置 `::1` 也不应自动授权 IPv4。

旧实现还有四类边界缺口：

1. 显式 Requests proxy 没有在 HTTP 委托前拒绝；
2. 调用方可以显式覆盖 `Host` header；
3. `urllib.request.urlopen` 虽已阻断，但没有和完整计数合同一起测试；
4. 进程级 monkeypatch 可以嵌套或并发安装，导致 original delegate 捕获错层、恢复顺序不确定。

V3 的目标不是提高 Guard 检测率，而是让**本地真实模型评测器的出站边界更精确、可复现、可解释**。

## 2. 思路是怎么产生的

直接任务来源是外部审核方案中的 V3 条目：收紧 `LocalOllamaOnlyBoundary` 的 exact origin/socket policy。实现没有照搬某个 Agent 框架，而是从三个安全工程原则推导：

- 最小权限：配置一个 origin，就只授权该 origin，而不是整个 loopback 地址空间；
- 单一策略源：HTTP、`connect`、`connect_ex` 必须消费同一个已解析策略，避免规则漂移；
- fail closed：代理、重定向、Host 覆盖、解析漂移和全局 patch 冲突都拒绝，而不是猜测调用方意图。

本阶段特别区分两层能力：

```text
应用调用图边界：本次实现
操作系统网络隔离：本次没有实现
```

Python monkeypatch 只能覆盖明确接入的 API 和当前进程调用图。它不能替代 Windows 防火墙、容器 network namespace、seccomp 或独立沙箱。因此类注释和项目状态都明确写为 evaluator call-graph boundary，不能在面试中宣传成“进程绝对无法联网”。

## 3. 冻结边界和入口基线

V3 入口 HEAD：

```text
1bf9b95917d7ae813ca6214c7ab83492b4c47aa3
```

V1/V2 是同一工作区中的未提交改动；V3 继续在其上实现，没有回滚或覆盖。入口验证：

```text
live-runner entry tests                 14 passed
V1 standalone verifier                  VERIFIED
```

本阶段明确不修改：

- `RetrievedContentGuard` 规则、阈值、版本和 rule hash；
- search/find/open、candidate ordering、top-k、top-up 和 Agent budget；
- frozen dataset、fixture、freeze manifest；
- 正式 D7 run；
- V1 八文件公共证据包；
- V2 scan provenance 和 reached 计算。

冻结 SHA-256 在 V3 前后保持：

```text
dataset          062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c
fixture          eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d
freeze manifest  5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4
formal manifest  5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

## 4. TDD：先证明旧实现为什么不够

### 4.1 第一轮 RED

先在 `tests/evaluation/test_indirect_injection_live_runner.py` 写边界合同，并把原始 HTTP/socket delegate 全部换成记录调用的 fake，所以测试不会发出真实网络请求。

第一轮结果：

```text
8 failed, 3 passed, 13 deselected
```

8 个失败分别证明旧实现会出现这些行为：

1. 配置 IPv4 时，其他回环地址和 IPv6 没有被精确拒绝；
2. 规范等价的展开 IPv6 URL 没有按 IP 语义比较；
3. `localhost` 配置会把数值 literal alias 当作普通回环放行；
4. `localhost` 解析到非回环地址时，构造阶段没有拒绝；
5. 显式 `Host` header 覆盖可以到达原 request delegate；
6. 显式 request/session proxy 可以到达原 request delegate；
7. boundary 可以嵌套安装；
8. boundary 可以由不同线程并发安装。

这组 RED 很重要：它不是“为了凑测试而假设风险”，而是直接执行旧判断后得到的可复现反例。

### 4.2 第一轮 GREEN 后发现的真实调用栈问题

实现精确字符串策略后，第一轮边界测试达到：

```text
11 passed
```

但代码审查发现一个单元测试容易漏掉的现实路径：

```text
HTTP URL 使用 localhost
-> Requests/urllib3 调用 getaddrinfo
-> localhost 被解析为 127.0.0.1 或 ::1
-> socket.connect 接收到数值 sockaddr，而不是字符串 localhost
```

如果 socket 永远只接受字符串 `localhost`，测试虽然为绿，真实 Ollama 请求却会被自己的边界阻断。为此新增一个“真实调用图、假 socket”测试，让 fake original request 在委托期间发起 `socket.connect(("127.0.0.1", 11434))`。

第二轮 RED：

```text
1 failed, 24 deselected
RuntimeError: blocked external socket in D7 evaluator
```

修复不是全局放行 `127.0.0.1`。最终采用线程局部授权窗口：

```text
精确 localhost HTTP URL 通过
-> 当前线程 delegation_depth + 1
-> 仅在 original request 的同步调用栈内
   允许 socket 使用构造阶段冻结的 localhost 解析地址
-> original request 返回或抛异常
-> delegation_depth 恢复/删除
```

因此同一个数值地址在普通直接 socket 调用中仍会被拒绝。这个补充同时解决了“真实功能可用”和“别名不能获得永久授权”两个要求。

## 5. 代码具体改在哪里

### 5.1 `_ExactLoopbackOriginPolicy`

文件：`app/evaluation/indirect_injection_live_runner.py`

新增私有策略类，构造时先复用 `LiveSecurityConfig` 校验 endpoint，再只解析一次 origin：

```python
config = LiveSecurityConfig(llm_endpoint=endpoint, chat_model="boundary-check")
parsed = urlsplit(config.ollama_origin)
```

这样 endpoint schema 仍只有一个权威入口，不在 boundary 里复制一套不一致的 URL validator。

对数值 IP：

```python
configured_ip = ipaddress.ip_address(parsed.hostname)
self.allowed_addresses = frozenset({configured_ip})
```

`ipaddress` 按地址语义比较，所以 `::1` 与 `0:0:0:0:0:0:0:1` 被视为同一个 IPv6 地址；`127.0.0.1` 与 `127.0.0.2` 仍是两个地址。

对 `localhost`：

```python
self.allowed_addresses = _resolve_loopback_addresses(host, port)
```

解析结果被保存为不可变 `frozenset`。只要有一个结果不是 loopback、结果为空或解析结构异常，就在 boundary 构造阶段抛出 `ValueError`。

### 5.2 HTTP URL 判断

`allows_url()` 同时要求：

| 条件 | 目的 |
|---|---|
| scheme 必须是 `http` | 不允许把本地明文模型端点静默换成其他协议 |
| 无 username/password | 拒绝 credential-bearing URL 和解析歧义 |
| host 必须匹配配置身份 | 不把 `localhost`、IPv4、IPv6 当作可互换别名 |
| port 必须精确相等 | 同主机其他服务不获得权限 |
| 无 fragment | 避免非传输部分造成歧义 |

路径和 query 不参与 origin 身份，因为 Ollama 同一 origin 下需要 `/api/embed`、`/api/chat` 等不同 API；这里收紧的是 origin，不是固定单一路径。

### 5.3 Socket 判断

`allows_socket()` 对 `connect` 和 `connect_ex` 共用，先拒绝：

```text
非 tuple
长度不足 2
host 不是 str
port 不是真正 int（bool 也拒绝）
port 与配置不同
```

然后分两种配置：

- 数值 IP endpoint：socket host 规范化后必须等于唯一配置 IP；
- `localhost` endpoint：直接 hostname 调用必须仍为 `localhost`，并且当前解析集合与冻结集合完全一致。

只有在精确 HTTP 请求的线程局部委托窗口内，`localhost` 对应的冻结数值地址才可通过。这是 Requests 实际调用栈所需的最小例外，不是一般 alias allowlist。

### 5.4 `_resolve_loopback_addresses()`

该辅助函数使用：

```python
socket.getaddrinfo(
    host,
    port,
    family=socket.AF_UNSPEC,
    type=socket.SOCK_STREAM,
    proto=socket.IPPROTO_TCP,
)
```

它同时收集 IPv4/IPv6 TCP 地址，并逐项用 `ipaddress.ip_address()` 校验。构造时冻结集合；直接 hostname socket 调用时重新解析并要求集合完全相等。这样 hosts/DNS 从 loopback 漂移到外部地址会 fail closed。

### 5.5 HTTP proxy、Host、redirect 与 urllib

`LocalOllamaOnlyBoundary._request()` 的顺序是：

```text
URL + Host override 检查
-> explicit request/session proxy 检查
-> allowed_http_request_count + 1
-> 强制 allow_redirects=False
-> 强制 http/https/all proxy key 为 None
-> 调用 original Session.request
-> 若响应为 3xx，blocked_attempt_count + 1 并抛错
```

任何显式 `Host` header 都拒绝，即使它表面上写成允许值。原因是 Requests 本来会从已校验 URL 正确生成 Host；调用方没有覆盖它的必要，允许覆盖只会增加 origin 与传输目标不一致的空间。

`urllib.request.urlopen` 统一阻断。V3 没有试图维护第二套 urllib allowlist，因为正式 evaluator 已知模型调用走 Requests/socket；增加第二个允许链路会扩大审计面。

### 5.6 单实例生命周期和计数锁

boundary 会 monkeypatch 进程级符号：

```text
requests.sessions.Session.request
socket.socket.connect
socket.socket.connect_ex
urllib.request.urlopen
```

因此新增 class-level 非阻塞 `threading.Lock`。第二个嵌套或并发 boundary 不等待，直接抛出：

```text
RuntimeError: another LocalOllamaOnlyBoundary is already active
```

`__enter__` 在任何 patch 安装失败时关闭已安装 stack 并释放锁；`__exit__` 使用 `finally` 恢复 patch 和锁。实例可以在完整退出后重新进入。

三个计数器也由实例级锁保护，避免 HTTP/socket 回调来自不同线程时出现丢失更新。

## 6. 精确计数合同

| 事件 | allowed HTTP | allowed socket | blocked |
|---|---:|---:|---:|
| 精确 URL 委托一次 | +1 | 0 | 0 |
| 委托得到 3xx | +1 | 0 | +1 |
| URL/Host/proxy 在委托前拒绝 | 0 | 0 | +1 |
| `urlopen` 被拒绝 | 0 | 0 | +1 |
| `connect`/`connect_ex` 通过策略并调用 delegate | 0 | +1 | 0 |
| socket 地址或端口拒绝 | 0 | 0 | +1 |

“allowed”表示该层策略允许并委托了一次尝试，不表示远端服务一定成功。例如 fake `connect_ex` 返回错误码时，仍算一个被允许的 socket 尝试。

## 7. 测试覆盖和结果

V3 新增测试覆盖：

- exact IPv4 HTTP/`connect`/`connect_ex`；
- exact IPv6 及规范等价展开写法；
- 其他 IPv4 loopback、其他 IPv6、外部地址、错误端口；
- `localhost` 解析冻结、非回环解析拒绝、literal alias 拒绝；
- `localhost` 的 Requests 实际解析调用图；
- credential URL、alternate host、Host override；
- request proxy、session proxy；
- redirect 与 urllib；
- 嵌套与并发 activation；
- 每种路径的精确计数。

最终本地结果：

```text
V3 boundary contracts                         12 passed
complete live-runner file                     25 passed
live/writer/CLI/security/admission subset     89 passed
full repository suite                        859 passed
warnings                                       3 known SWIG warnings
V1 standalone verifier                        VERIFIED
frozen dataset/fixture/manifests               exact
public repository audit             411 candidates / 0 findings
compileall                                      exit 0
pip check                       no broken requirements
git diff --check                               exit 0
```

3 条 warning 仍来自既有 SWIG wrapper 类型缺少 `__module__` 的弃用提示，不是 V3 新 warning。

## 8. 这次改进有效在哪里

可以被证据支持的结论：

1. 配置 `127.0.0.1:11434` 时，不再把整个 loopback 空间和 IPv6 自动授权；
2. 配置 `::1:11434` 时，只授权规范等价的同一 IPv6 地址；
3. HTTP、`connect`、`connect_ex` 使用同一个 policy 对象；
4. proxy、Host override、redirect、urllib 旁路有确定性拒绝和计数；
5. monkeypatch 不再允许嵌套/并发叠加；
6. `localhost` 在真实 Requests 解析路径中仍可工作，但解析地址权限只存在于精确 HTTP 委托调用栈；
7. 全仓 859 测试通过，冻结证据未变化。

不能由本阶段支持的结论：

- “操作系统层面绝对零出站”；
- “任意第三方库都被拦截”；
- “Ollama 本身没有漏洞”；
- “Guard 检测率提高”；
- “D7 的 3/24 或 15/15 指标被重新验证”。

V3 没有重新运行真实 BGE-M3/Qwen 成对实验，因为代码只收紧 evaluator boundary，而且正式 D7 artifact 必须保持不可变。若未来需要发布使用 V2 provenance + V3 boundary 的新真实指标，应创建新的 run ID，而不是覆盖 D7。

## 9. 面试常见问题与答案

### Q1：为什么 `is_loopback` 不够？

`is_loopback` 回答的是“地址是否回到本机”，不回答“地址是否是管理员配置的服务”。`127.0.0.2`、`127.0.0.1` 和 `::1` 都可能是 loopback，但它们可以对应不同监听 socket、不同进程或不同协议族。最小权限要求绑定精确地址和端口。

### Q2：为什么 HTTP 和 socket 都要检查？

HTTP 检查保护逻辑目的地和 URL 解析；socket 检查保护最终传输目的地。只检查 URL 时，proxy、DNS/hosts 漂移或底层库旁路可能改变真实连接；只检查 socket 时，又看不到 credential URL、Host header 和 redirect 语义。两层共同约束，但共享同一个 origin policy。

### Q3：为什么配置 IPv4 时不自动允许 `::1`？

因为 IPv4 与 IPv6 是不同地址族，服务可以只监听其中一个，也可以由不同进程分别监听。自动兼容会把“配置一个地址”扩大为“允许多个地址”。需要 IPv6 时应显式配置 `http://[::1]:11434/v1`。

### Q4：为什么 `localhost` 比数值 IP 复杂？

`localhost` 是 hostname，不是 socket 最终使用的数值地址。Requests 会先解析，再把数值 sockaddr 交给 `connect`。所以策略要同时保留精确 HTTP hostname 身份和冻结解析地址，并把数值地址授权限制在已通过精确 URL 校验的同步调用栈内。

### Q5：线程局部 delegation depth 有什么作用？

它表达“这个 socket 是否由当前精确 HTTP 请求内部产生”。不用全局布尔值，是因为全局值会让其他线程趁请求执行期间获得解析地址权限；使用 depth 而不是简单 bool，是为了正确恢复潜在的同步嵌套调用。`finally` 保证原 request 抛异常时也撤销授权。

### Q6：为什么禁止调用方设置 Host，即使值相同？

URL 已经是唯一 origin 身份来源，Requests 会自动生成 Host。允许第二个输入源不会增加功能，只会产生 URL、Host、proxy 和实际 socket 四者不一致的组合。安全边界里删除无必要自由度比尝试比较各种等价字符串更可靠。

### Q7：为什么 redirect 返回也算一次 allowed 和一次 blocked？

第一个 HTTP 请求确实发给了允许 origin，所以 allowed HTTP 加一；但 3xx 表达继续跳转的意图，策略禁止继续，因此 blocked 也加一。这两个计数描述不同阶段，不是重复计数。

### Q8：为什么不用 LLM 判断网络目的地？

网络 origin、IP、端口、代理和状态码都是结构化、确定性的安全属性。LLM 会引入随机性、成本、不可复现和新的网络依赖；这里应使用 URL parser、`ipaddress`、socket resolver 和严格状态机。

### Q9：这个 boundary 能不能叫 sandbox？

不能。它是 Python 进程内、针对已知 evaluator 调用图的 monkeypatch guard。原生扩展、未覆盖的系统调用、子进程或恶意代码都可能绕过。真正的强隔离需要操作系统/容器网络策略；项目文档必须如实披露这一点。

### Q10：如何证明修改没有偷偷改善评测结果？

V3 没改 Guard、检索、模型、数据或正式 artifact；四个冻结 SHA-256 完全一致，V1 verifier 仍复算相同 15 个指标。全仓回归只证明代码合同未回退，不把历史 D7 指标改写成新的实验结果。

## 10. 下一阶段

按批准范围，V3 完成后停在这里。V4 是 metric semantic versioning，V5 是 randomized/counterbalanced arm order；两者都尚未开始，也不能因为 V3 通过就宣称完成。

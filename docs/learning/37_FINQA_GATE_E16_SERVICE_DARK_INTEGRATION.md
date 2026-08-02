# Gate E16：服务级暗流量接入，从代码到面试逐步讲清楚

## 1. 这一阶段到底做了什么

E15 之前的 Shadow 都运行在评测脚本里。你可以把它理解成“实验室里的
旁路程序”：它有 Worker、有队列，也测过吞吐，但真实 Web 服务收到问题时
并不会自动把任务交给它。

E16 新增的是一个服务级 `DarkObservationService`：

```text
用户调用 /agent/v2/chat
-> 正常 Agent 完成答案
-> 正常 trace 和 feedback receipt 完成
-> 把一个最小副本尝试放入暗流量队列
-> HTTP 立即返回原答案
-> 后台 Worker 独立执行观察
```

这里最重要的不是“又多了两个线程”，而是所有权发生了变化：FastAPI 启动
时创建它，关闭时回收它，API 路由负责提交，operator metrics 负责观察。

## 2. 什么是 Dark Traffic / Shadow Traffic

Dark traffic 是把真实或仿真的主请求复制给候选系统，但候选结果不参与当前
用户响应。常见用途是：

1. 上线前比较新旧检索器；
2. 观察候选模型的延迟、错误和资源消耗；
3. 收集分布变化，但不把未经验证的答案发给用户；
4. 用真实服务生命周期验证队列和关闭行为。

“暗”不是没有日志，而是结果不进入主决策。它仍然必须受隐私、预算和审计
约束。

## 3. 为什么不能直接把 E11 接到 API

这是 E16 最重要的架构判断。

API 当前只有：

```python
question: str
user_context: UserContext
top_k: int | None
```

而 E11 FinQA challenger 需要：

```text
question
typed program skeleton
safe descriptor catalog
E8 primary descriptor selection
```

后面三项不是随便填几个字符串就可以。它们包含数值程序的操作类型、参数
角色、候选描述符和不可变主选择。如果硬造默认值，程序虽然能调用，却不再
代表真实问题。这叫伪集成。

所以 E16 先做通用执行边界，E17 再做 typed adapter。当前代码诚实返回的
状态是：

```text
NOT_IMPLEMENTED_CONTRACT_MISMATCH_RECORDED
```

面试时可以说：我先检查生产请求和离线 challenger 的输入契约，发现不一致，
因此没有把 benchmark 对象硬塞进服务，而是先抽出可注入的安全 owner。

## 4. 从入口看完整代码流程

### 4.1 配置：`app/config.py`

默认值是：

```python
dark_observation_mode = "OFF"
dark_observation_sample_basis_points = 0
dark_observation_worker_count = 1
dark_observation_queue_capacity = 8
dark_observation_deadline_ms = 100
dark_observation_shutdown_grace_ms = 2000
```

`basis_points` 是万分比。`1000` 表示 10%，`10000` 表示 100%。生产默认
是 0，不会因为只改了采样率或只改了 mode 就模糊启用：

```text
OFF + 非零采样              -> 配置错误
LOCAL_TEST_ONLY + 零采样    -> 配置错误
```

当前故意只有 `LOCAL_TEST_ONLY`，没有名字看起来像生产开关的 `ON`。

### 4.2 容器：`app/runtime/resources.py`

`ServiceContainer` 原来持有 settings、readiness resources、metrics、trace、
identity 和 lifecycle operator。现在新增：

```python
dark_observation: DarkObservationService
```

这表示它不是路由中的临时局部变量，而是有明确服务生命周期的资源。正常
builder 没有注入 provider，因此即使误设 `LOCAL_TEST_ONLY`，状态也会成为
`UNAVAILABLE`，不会把问题发送到未知对象。

### 4.3 启动和关闭：`app/main.py`

FastAPI lifespan 中的顺序是：

```text
resources.start()
dark_observation.start()
yield: 服务接受请求
dark_observation.close()
resources.close()
```

Shadow 的 start/close 被单独隔离。它失败时不能阻止 liveness，也不能跳过
主资源关闭。这是“旁路不能控制主链可用性”的具体代码实现。

### 4.4 主回答完成后才 offer

问答路由先执行：

```python
answer = run_agent_v2_chat(...)
safe_trace = redact_trace_payload(...)
receipt = issue_feedback_receipt(...)
primary_response = answer.model_copy(update={"trace": safe_trace})
```

直到 `primary_response` 已经构造完成，才调用：

```python
service.dark_observation.offer(
    request_id=request_id,
    question=payload.question,
    primary_mode=answer.mode,
    primary_stop_reason=answer.stop_reason,
)
```

最后返回的是之前创建的 `primary_response`，不是 Shadow 返回值。即使
`offer()` 抛出意外异常，外层 containment 也会忽略它并返回主结果。

## 5. `offer()` 内部逐步发生什么

代码在 `app/runtime/dark_observation.py`。

### 第一步：累计总 offer 数

只记录一个整数，不记录 request ID 或问题。

### 第二步：检查模式和生命周期

```text
OFF             -> DISABLED
已经 close      -> CLOSED
未 start/provider 不存在 -> UNAVAILABLE
```

这些都是快速返回，不进入队列。

### 第三步：HMAC 采样

采样输入只有 `request_id`：

```text
digest = HMAC(process_local_key, request_id, SHA-256)
bucket = digest 前 8 字节转整数 mod 10000
bucket < sample_basis_points 才被选中
```

为什么不是 `hash(question)`：问题内容不应参与采样指标，而且相同 request ID
应该在同一个服务进程内得到稳定决定。

为什么用带密钥 HMAC 而不是普通 SHA：客户端可以控制合法的 request ID。
如果采样算法和盐都是公开固定值，客户端可以构造 ID 躲避或强制进入采样。
这里使用进程启动时生成的 32 字节材料，metrics 不公开它。

### 第四步：构造最小临时对象

只有采样命中后才创建：

```python
DarkObservationRequest(
    request_id=...,
    question=...,
    primary_mode=...,
    primary_stop_reason=...,
)
```

它没有用户 subject、tenant、groups、roles，没有答案、claim、citation、source、
trace 或 feedback receipt。

### 第五步：`put_nowait`

队列是 `queue.Queue(maxsize=queue_capacity)`。`put_nowait` 的意思是：有空位
就接收，没有空位立刻返回 `BACKPRESSURE`，绝不等待队列空出来。

这是 E16 不拖慢主请求的核心。无界队列会把流量高峰变成内存增长和长尾
延迟；阻塞入队又会让 Shadow 反过来拖慢用户。

## 6. Worker 如何执行和记账

每个已接收任务在 admission 时就得到：

```text
deadline = admission_perf_counter + observation_deadline
```

Worker 取到任务后：

1. 如果已经过期，不调用 provider，记 `deadline_exceeded`；
2. 调用 `provider.observe(request, deadline_monotonic=deadline)`；
3. provider 抛错，只记 `provider_error`；
4. provider 太晚返回，丢弃结果，记 `deadline_exceeded`；
5. 返回值不是固定 allowlist，按 provider error 处理；
6. 合法及时结果才记 completed 和 MATCH/DIFFERENT/NOT_APPLICABLE。

注意：Python 线程不能安全地强行杀死任意正在运行的函数。E16 的 deadline
语义是“晚结果不被接受”，不是“到点强杀线程”。真正需要硬隔离时，应复用
E13/E14 的子进程边界或远端 worker。

## 7. 关闭时为什么要先停止 admission

`close()` 先把状态设为 closed，再设置 stop event。此后新 offer 返回 CLOSED。
然后它清空尚未开始的队列任务并记 `shutdown_cancelled`，最后在最多 2 秒的
grace 内 join Worker。

可以用一个守恒式检查是否丢任务：

```text
admitted
= completed
 + provider_error
 + deadline_exceeded
 + shutdown_cancelled
```

本次故障注入得到 `2 admitted == 2 terminal`，并且受控 Worker 残留为 0。

## 8. 指标怎么看

operator 调用 `/observability/metrics` 会看到 `dark_observation`：

```text
mode/status/config
counters
provider_outcomes
active/queue high watermarks
current worker/queue counts
offer latency p50/p95/max
execution latency p50/p95/max
content_retained=false
```

这里没有逐请求行。比如 `provider_error_total=3` 只能说明有三次错误，不能
看到哪个用户、哪个问题、原始异常是什么。

## 9. 为什么计时器从 `monotonic` 改成 `perf_counter`

第一次审计中，所有入队延迟都显示 `0.000 ms`。这不是无限快，而是计时
分辨率不够。当前 Windows 主机报告：

```text
time.monotonic     GetTickCount64       resolution 15.625 ms
time.perf_counter  QueryPerformanceCounter resolution 0.0001 ms
```

入队只有几十微秒，低分辨率时多次读数相同。改用 `perf_counter()` 后得到：

```text
offer p50/p95/max = 0.017 / 0.024 / 0.033 ms
```

这个结果只表示本地内存队列 offer 的机制开销，不是 API 延迟改善，也不是
生产 p95。

## 10. 24 组成对测试到底比较了什么

审计先启动 OFF 服务，对 24 个本地合成问题调用真实 FastAPI 路由；再启动
LOCAL_TEST_ONLY 服务，用相同 request ID 和问题调用一次。每一对比较：

```text
HTTP status
完整 response bytes
X-Feedback-Receipt
```

结果：

```text
OFF provider calls             0
ON provider calls              24
primary response mismatches    0
feedback receipt mismatches    0（包含在完整 pair 比较中）
model calls                    0
```

这证明本地机制隔离，不证明模型效果，因为 primary 和 provider 都是受控的
确定性测试对象。

## 11. 17 个 gate 如何分组

### 来源与协议

- E15 protocol/public hash 精确匹配；
- frozen test untouched；
- FinQA adapter 缺口已披露。

### 默认安全

- OFF 24 次调用 provider 为 0；
- OFF 不创建 Worker；
- 所有 OFF offer 都返回 disabled。

### 主链隔离

- 24 对响应 mismatch 为 0；
- provider error、deadline、backpressure、closed 都不改变主链；
- offer p95 小于预注册的 10 ms。

### 生命周期和隐私

- 最小 provider 字段精确匹配；
- admitted/terminal 守恒；
- 关闭后受控 Worker 为 0；
- 公共证据只有聚合字段；
- 模型调用为 0。

## 12. 遇到的问题和修复思路

### 问题一：输入契约不匹配

不要先问“怎么把函数调起来”，先问“传入的数据是否仍有业务语义”。E11
缺少 typed input，因此本阶段停在 provider interface，并把 adapter 放到 E17。

### 问题二：测试期望写得太具体

第一版测试手写 trace，漏了既有 request ID。修复不是补一个字段，而是建立
OFF baseline，再逐字节比较 ON。baseline comparison 比复制实现逻辑更稳。

### 问题三：计时显示 0

先检查 clock implementation 和 resolution，再改计时器。不能把 0 当作优秀
结果，也不能随便乘倍数“修正”。

### 问题四：公共扫描报 1 finding

扫描器命中了假的 bearer token 和测试 key 样式。正确做法是运行时构造审计
header、由公开 domain 派生确定性材料，而不是给脚本加例外。最终是
`1324 candidates / 0 findings`。

### 问题五：为什么全量测试第一次是 2975 passed + 1 failed

失败测试会把当前 identity matrix 结果与历史 public JSON 完整比较。E16 修改了
`app/main.py` 和 `app/runtime/resources.py`，行为仍然是 20/20，但历史 JSON
绑定的两个 SHA 必然不同。

不能覆盖旧 JSON，否则会把 R2-S5 当时的源码证据改写成今天的代码。修复方式
是版本化：

```text
identity evaluation v2 -> 保留旧 11 个 source，历史文件继续可解析
identity evaluation v3 -> 增加 config 和 dark_observation，生成新文件
```

新 contract 是 `trusted-identity-contract-e21503b0947a5608`。它得到 20/20、
14 个 denied case 零副作用、零 credential leak。第二次全量测试是
`2977 passed / 29 skipped`。

## 13. 面试常见问题与参考答案

### Q1：为什么 Shadow 必须在 primary 之后提交？

因为主结果必须先确定，候选系统不能修改答案、引用、状态码或 receipt。如果
先让 Shadow 参与选择，系统就不再是观察模式，而是在线路由或 ensemble，风险
和验收标准完全不同。

### Q2：为什么用有界队列？

无界队列会在 challenger 变慢或流量突增时无限积压，占用内存并放大延迟。
有界队列配合 `put_nowait` 把过载明确转成可观测的 backpressure 计数，同时
保护主链。

### Q3：为什么 deadline 从 admission 开始，不从 Worker 开始？

用户关心的是任务被系统接受后的总旁路预算。若从 Worker 开始，队列等待不
计时，积压任务可能很晚才执行，采集到已经失去时效的观察。

### Q4：为什么不用另一个 LLM 判断 Shadow 是否成功？

E16 判断的是运行时隔离、生命周期和数据边界，这些可用确定性状态验证。LLM
judge 适合语义质量，不适合判断队列是否满、响应字节是否变化或 Worker 是否
残留。后续比较答案质量时可以增加盲审或校准过的 judge，但不能代替机制门禁。

### Q5：线程 deadline 为什么不是硬超时？

Python 无法安全终止任意正在运行的线程。这里能保证晚结果不被计入 completed、
不影响 primary；不能保证恶意 provider 立即停止占 CPU。硬隔离要使用子进程、
容器或远端任务系统。

### Q6：E16 能写进简历吗？

可以写机制事实，但必须加本地和 default-off 边界。不能写“生产流量验证”或
“FinQA 已上线”。推荐措辞见工程记录中的 honest claim。

### Q7：为什么 public metrics 不保存 request ID？

request ID 看起来不是正文，但可以关联 trace、用户行为和时间线。E16 只需要
判断整体健康度，因此保存总计、高水位和分位数，不需要逐请求关联能力。

## 14. 你可以做的 20 分钟实验

1. 运行核心测试：

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
  tests\runtime\test_dark_observation.py `
  tests\api_v2\test_dark_observation_api.py -q
```

2. 打开 `app/runtime/dark_observation.py`，按顺序找到 `start`、`offer`、
   `_selected`、`_worker_loop`、`_run_one`、`close`、`snapshot`。
3. 把测试中的 queue capacity 设为 1，解释为什么第三次 offer 是 backpressure。
4. 不改 protocol，观察把慢 provider 的 sleep 降到 deadline 内后哪个 counter
   从 deadline 变成 completed。
5. 用自己的话回答：为什么 Shadow 失败时主响应仍然相同？

不要修改已被 E16 public evidence 绑定的实现文件并覆盖 V1 证据。要实验请在
测试副本或后续协议版本中进行。

## 15. 下一步 E17 要解决什么

E17 需要一个明确的 eligibility/adapter：

```text
enterprise question
-> 判断是否属于支持的数值财报任务
-> 提取或获取 typed skeleton
-> 构造 safe descriptor catalog
-> 绑定 E8 primary selection
-> 不满足条件就 NOT_APPLICABLE
-> 满足才调用 E11 provider
```

关键门禁是“不能为了提高执行率伪造缺失字段”。E17 完成前，E16 只是一条
安全可注入的服务暗流量通道，不是 FinQA challenger 的真实服务部署。

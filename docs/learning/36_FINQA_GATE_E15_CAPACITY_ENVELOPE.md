# FinQA Gate E15：容量边界与扩容消融，逐段讲清楚

## 1. 这一阶段到底解决什么问题

E14 已经实现了一个有界 Worker Pool，但只测过一种配置：

```text
2 个 Worker + 4 个 caller + 4 个排队位置
```

这只能证明“这一个配置能跑”，不能回答：

1. 从 1 个 Worker 加到 2 个，吞吐是否真的提高？
2. 从 2 个加到 4 个，收益是否还值得额外内存？
3. caller 越多是否越快？
4. 哪个配置适合作为本机 Shadow 默认候选？
5. 测出来的差异是扩容收益，还是启动进程、缓存和运行顺序造成的假象？

E15 的目标不是再添加一个 Agent 名词，而是用可复现实验回答这些工程问题。

## 2. 先理解三个容易混淆的概念

### Worker count

Worker 是真正执行 E11 Shadow 观察的独立子进程。`worker_count=4` 表示最多有 4 个 Shadow 任务同时执行，也意味着大约需要 4 份子进程内存。

### Caller concurrency

caller 是同时向 Pool 提交并等待结果的调用线程。`caller_concurrency=8` 不等于有 8 个任务同时执行；如果只有 4 个 Worker，其余请求要在队列中等待。

### Queue capacity

队列保存已经被系统接纳、但还没有 Worker 可执行的任务。本阶段固定为 8。队列有界是为了防止流量高峰无限转化成内存和尾延迟。

因此三者关系可以理解为：

```text
caller 负责送任务
queue 负责有限等待
worker 负责真正执行
```

## 3. 为什么必须先冻结协议

协议文件位于：

`docs/external_datasets/evidence/finqa_shadow_capacity_protocol_v1.json`

对应的严格代码模型位于：

`app/external_datasets/finqa_shadow_capacity_protocol_v1.py`

协议在看到 E15 结果之前就写死：

```text
worker_count       = 1 / 2 / 4
caller_concurrency = 1 / 4 / 8
repetitions        = 3
total_trials       = 3 * 3 * 3 = 27
```

还预先写死两条主要比较及最低门槛：

```text
1 -> 2 workers @ 4 callers：speedup >= 1.25，efficiency >= 0.625
1 -> 4 workers @ 8 callers：speedup >= 1.75，efficiency >= 0.4375
```

如果实验后才挑比较对象或降低门槛，就会产生“结果导向调参”。严格 Pydantic 模型还会拒绝未知字段、NaN、矩阵变化和比较方向错误。

## 4. 数据到底是怎么处理的

入口函数是：

`prepare_finqa_shadow_capacity_workload_v1()`

它复用 E13 的数据边界，依次执行：

```text
官方 FinQA train
-> 校验固定文件 SHA
-> 用固定算法选择 128 条
-> 投影掉 answer/exe_ans/gold evidence 等质量标签
-> 解析文本和表格候选
-> RetrievedContentGuard 检查
-> 生成 typed program skeleton 和 safe descriptor catalog
-> 计算不可变 E8 primary result
-> 得到 117 条可运行请求
```

这里一共选中 128 条，117 条准备成功，11 条在既有严格能力边界下准备失败，成功率是 `91.41%`。E15 没有偷偷补答案，也没有访问已经消耗的 internal cohort 或 frozen test。

最关键的是：这 117 条只准备一次，随后 27 个 trial 都复用同一批 Python 对象。这样不同配置之间的差异不会被文档解析时间污染。

## 5. 为什么启动时间不计入 throughput

每个 trial 都会新建 Pool，因此 1、2、4 个 Windows `spawn` 进程的启动成本不同。如果把启动也计时，一个只有 117 个短请求的 trial 很可能主要测到“创建 Python 进程需要多久”，而不是 Worker 稳态处理能力。

代码在 `pool.start()` 成功后才执行：

```python
started = time.perf_counter()
```

所有请求返回后才计算：

```python
elapsed_ms = (time.perf_counter() - started) * 1_000
throughput = attempted_count / (elapsed_ms / 1_000)
```

这使比较更接近稳态 Shadow 执行，但也带来一个必须诚实说明的限制：E15 没有测 cold start。

## 6. 为什么每个 trial 又必须用新 Pool

如果 27 次试验都复用同一组进程，后面的配置就无法改变 Worker 数，而且会混入前面试验的进程状态、累计指标和潜在故障。

`run_finqa_shadow_capacity_trial_v1()` 每次都会：

1. 按本 trial 的 Worker 数创建新 Pool；
2. 启动并验证全部子进程；
3. 在固定 caller 数下提交同一批 117 请求；
4. 读取 aggregate metrics；
5. 关闭 dispatcher 和所有子进程；
6. 检查残留 dispatcher 数和 Worker PID 数都为 0。

所以“准备结果复用”和“运行进程隔离”同时成立，它们解决的是不同问题。

## 7. 为什么不是简单按 1 到 27 顺序跑

基础的 9 个配置顺序是：

```text
w1-c1, w1-c4, w1-c8,
w2-c1, w2-c4, w2-c8,
w4-c1, w4-c4, w4-c8
```

三轮顺序分别是：

```text
第 0 轮：正序
第 1 轮：倒序
第 2 轮：正序左移 3 个配置
```

这样可以减少“后运行的配置总是因为缓存更热而占便宜”的顺序偏差。`capacity_trial_schedule_v1()` 生成精确 27 行，聚合器会逐行核对 ordinal、重复轮次和配置；少一行或调换两行都会失败。

这叫 counterbalancing（反平衡）。它不能消除所有机器噪声，但比固定单一顺序严谨。

## 8. 每个 trial 记录了什么

`FinQAShadowCapacityTrialV1` 只保存聚合字段：

- attempted/admitted/executed/completed 数；
- MATCH/DIVERGED 等 outcome 的总数；
- backpressure、deadline、worker error、restart 数；
- active worker 和 queue 高水位；
- queue wait 与 end-to-end 的 p50/p95/max；
- 观察阶段耗时与 throughput；
- 各 Worker 历史峰值 RSS 的上界；
- close 是否完成、是否残留 dispatcher/PID；
- model call 数必须为 0。

它不保存问题、数值、case/company/descriptor id、逐请求结果、逐请求延迟或 Worker 分配，因此公开证据不能反推出原始训练样本。

## 9. 如何从三次 trial 得到一个配置结果

`aggregate_finqa_shadow_capacity_trials_v1()` 会把相同 config 的三行放在一起。

吞吐使用中位数：

```text
median throughput = 三次 throughput 排序后的中间值
```

相对波动使用：

```text
(最大吞吐 - 最小吞吐) / 中位吞吐
```

中位数比平均数更不容易被一次偶发慢 trial 拉偏。当前九个配置的相对波动最大是 `9.16%`，远低于预注册的 `50%` 上限。

## 10. speedup 和 efficiency 怎么算

假设基线吞吐是 100 req/s，候选吞吐是 180 req/s：

```text
speedup = 180 / 100 = 1.8
```

如果 Worker 从 1 增加到 2：

```text
worker ratio = 2 / 1 = 2
efficiency = speedup / worker ratio = 1.8 / 2 = 0.9
```

`0.9` 表示每增加一倍 Worker，获得了理想线性收益的 90%。实际系统通常小于 1，因为还有 IPC、调度、排队和串行工作。

本次 `1 -> 2 @ c4` 的 efficiency 是 `1.038`，略大于 1。不能把它说成算法具有稳定超线性扩容；短任务、缓存、Windows 调度和三次重复的统计噪声都可能导致这个局部数值。

## 11. 真实结果怎么读

最重要的中位吞吐如下：

```text
1 worker: c1 163.374, c4 158.300, c8 160.752 req/s
2 workers: c1 165.896, c4 328.517, c8 320.426 req/s
4 workers: c1 161.350, c4 631.169, c8 553.185 req/s
```

可以得到三点：

1. 只有 1 个 caller 时，不管配置几个 Worker，实际最多只活跃 1 个，所以吞吐都约 161-166；多出的 Worker 只增加内存。
2. caller 足够时，2 个和 4 个 Worker 确实带来近似扩容收益。
3. `4 workers / 8 callers` 比 `4 workers / 4 callers` 慢，说明 caller 超过可执行并行度后，额外排队和线程调度没有产生收益。

因此本机推荐点是 `w4-c4`，不是矩阵中数字最大的 `w4-c8`。

## 12. latency 为什么 caller 越多越高

以 1 个 Worker 为例，中位 E2E p95：

```text
c1 = 12.824 ms
c4 = 35.822 ms
c8 = 65.210 ms
```

Worker 每次仍只执行一个请求。更多 caller 不会让单 Worker 同时执行更多，只会让更多请求排队。所以吞吐基本不变，单请求尾延迟却上升。

这也是生产系统不能只看 QPS 的原因：吞吐没有下降，不代表用户延迟没有恶化。

## 13. RSS 为什么近似线性增长

最大 Pool RSS 上界约为：

```text
1 worker 约 87 MiB
2 workers 约 173 MiB
4 workers 约 344 MiB
```

每个 Worker 是独立 Python 进程，会加载自己的解释器、模块和运行状态，所以内存近似随 Worker 数线性增长。当前值是各 slot 报告的历史峰值之和，不是整个 API 服务的同时刻精确峰值。

面试中可以说“我量化了吞吐和子进程内存之间的取舍”，不能说“完整服务只占 344 MiB”。

## 14. 22 个 gate 证明了什么

gate 覆盖：来源哈希、准备成功率、27 个 trial、完成率、零背压、零 deadline、零 Worker 错误、零重启、活跃 Worker 高水位、队列上限、p95、4 Worker RSS、波动、两个 speedup/efficiency、无残留进程、E8 primary、零模型调用、aggregate-only 和零质量标签。

22/22 通过证明的是：

> 在这台 Windows 主机、这批固定 train-only 无标签 Shadow 请求、这个计时边界下，E14 Pool 在 1/2/4 Worker 和 1/4/8 caller 矩阵中稳定运行，并表现出可测量的本地扩容收益。

它不证明答案更准，也不证明生产流量下一定达到相同 QPS。

## 15. 代码具体在哪，调用关系是什么

```text
协议 schema
app/external_datasets/finqa_shadow_capacity_protocol_v1.py

核心实验代码
app/external_datasets/finqa_shadow_capacity_v1.py

真实运行入口
scripts/audit_finqa_shadow_capacity_v1.py

冻结协议
docs/external_datasets/evidence/finqa_shadow_capacity_protocol_v1.json

真实公开证据
docs/external_datasets/evidence/finqa_shadow_capacity_public_v1.json

协议测试
tests/external_datasets/test_finqa_shadow_capacity_protocol_v1.py

调度、聚合和失败路径测试
tests/external_datasets/test_finqa_shadow_capacity_v1.py

证据 SHA/实现绑定/隐私测试
tests/external_datasets/test_finqa_shadow_capacity_evidence_v1.py
```

运行命令：

```powershell
Set-Location -LiteralPath '<repository-root>'
& '.\.venv\Scripts\python.exe' -m scripts.audit_finqa_shadow_capacity_v1
```

证据已存在且字节不同的时候脚本会拒绝覆盖。这是为了避免把一次正式实验悄悄替换成另一次结果。

## 16. 本阶段遇到的问题与处理

### 不能修改 E14 的 worker 下限

E14 协议只允许至少两个 Worker，这是 E14 自己的历史契约。为了测一个 Worker，不能把旧 validator 改松，否则旧证据 SHA 会失效。处理方法是新增 E15 协议层，只复用已验收的 Pool runtime。

### 如何区分准备成本和稳态成本

如果每个 trial 都重新解析数据，配置比较会混入相同但波动较大的前处理成本；如果把进程启动算入，又会变成 cold-start 比较。最终选择“数据只准备一次、每个 trial fresh Pool、启动后才计时”，并把未测 cold start 写进 non-claims。

### 如何避免看结果挑配置

协议先写死矩阵、重复次数、顺序、比较和门槛；聚合器拒绝顺序漂移；公开证据绑定协议和实现 SHA。

### 为什么运行开始一段时间没有输出

第一次输出发生在 128 条样本的一次性解析和 Guard/E8 准备完成后。整个正式命令约 100 秒，不调用 Ollama，也没有留下后台进程。之后每个 trial 都会输出一行进度。

### Ruff/Black 没有安装

本地虚拟环境没有这两个工具，所以不能声称它们通过。项目实际 CI 要求的 compileall、pytest、依赖检查和 public audit 会继续执行。

## 17. 面试时可以怎么讲

可以这样回答：

> 我没有在实现多进程 Pool 后只报一个最好 QPS，而是冻结了 1/2/4 Worker × 1/4/8 caller、每组 3 次的 27-trial 容量消融。同一批 117 个脱敏后 Shadow 请求只准备一次，每个 trial 使用 fresh spawn Pool，启动时间与观察时间分开，顺序采用正序、倒序和轮转反平衡。3,159 次观察全部完成，零超时、零重启、零残留进程。1 到 2 Worker 在 4 caller 下中位吞吐提升 2.075 倍，1 到 4 Worker 在 8 caller 下提升 3.441 倍；本机最佳点是 4 Worker/4 caller 的约 631 req/s，而 8 caller 反而更慢，说明并发超过执行槽后会增加调度和排队成本。这个数字只代表 post-primary Shadow observation，不是完整 RAG QPS，也不是生产 SLO。

## 18. 面试官可能追问

### 为什么只重复三次，不算置信区间？

三次足以发现明显波动并取中位数，但不足以估计稳定的尾部分布或置信区间。这是一个本地工程容量消融，不是生产性能认证。生产阶段应增加持续时间、随机化、多个机器实例和置信区间。

### 为什么不用 async？

当前真正执行单元是带阻塞 IPC 的本地独立进程，固定 dispatcher thread 与 Worker 一一绑定，能够保持 E13 的 single-inflight 不变量。async 可以优化大量网络等待，但不会自动增加 CPU/进程执行槽；是否改 async 要由服务级 profiling 决定。

### 为什么 4 Worker/4 caller 最好？

四个 caller 正好能持续填满四个执行槽。八个 caller 增加了等待任务和线程调度，但没有增加可执行 Worker，所以吞吐下降、尾延迟上升。

### 这能写进简历吗？

可以写“构建有界 spawn Worker Pool 与 27-trial 容量消融，在固定 3,159 次本地 Shadow 观察中实现零超时/重启/残留进程，测得 1→4 Worker 最高 3.44×扩容收益并识别 4 Worker/4 caller 本机容量点”。必须同时标注 local Shadow observation，不能写成生产 RAG QPS。

### 为什么还不把 E11 上线？

E15 只补充运行容量证据。E11 的质量证据仍然样本少、McNemar `p=0.5`，且 gold program structure 绕过真实 planner。运行稳定不能代替质量和发布授权。

## 19. 下一阶段应该做什么

下一阶段应把当前 default-off Shadow 以明确采样率接到服务暗流量边界，并增加：

1. 主请求预算与 Shadow 独立预算；
2. sampled/skipped/backpressure/deadline 聚合指标；
3. 默认关闭和一键回滚；
4. API 生命周期内的启动与关闭验证；
5. 服务级负载测试，明确区分 API/RAG 和 Shadow 子阶段；
6. 仍不访问 frozen quality split。

只有这样，容量实验才能向“可运营但默认关闭”的工业化机制推进，而不是停留在离线 benchmark。

## 20. 为什么还要等 GitHub Actions

本地通过只能证明当前 Windows 工作区成立。实现提交
`bd35fa1e62ab5c30a87414c6b5e4fd12a0362b23` 推送后，GitHub Actions #50 又独立执行了：

1. Ubuntu 和 Windows 两套 deterministic test，结果 `2/2`；
2. Linux test/runtime 镜像构建；
3. 只读容器内的 compile、pytest、冻结 hash、corpus 和 public audit；
4. API readiness 失败与 rollback drill；
5. Python runtime SBOM 生成。

整次 CI 用时 10分24秒，Linux container 用时 4分05秒，并产出 1 个 SBOM artifact。它仍然不是生产部署，但证明公开仓库的 clean checkout 在两个操作系统和一个受限 Linux 容器里保持契约一致，比“我电脑上能跑”更可信。

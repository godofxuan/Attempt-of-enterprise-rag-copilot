# 34. FinQA Gate E13：把“检测到超时”升级为“真的能停止并重启”

## 1. 先用一句话理解 E13

E12 已经能让 E8 先做主决策，再让 E11 在后台比较，但 E12 的 timeout 只是执行
结束后发现“用时超预算”，不能强制停止一段仍在运行的 Python 代码。E13 把 E11
放进独立子进程：父进程超过 deadline 后可以结束旧进程，再启动一个干净的新进程。

```text
父进程：保存 E8 主结果、控制时间、验证响应、决定是否重启
子进程：只加载 E11、接收受限输入、返回聚合计数
```

子进程算得再好也不能替换 E8。E13 解决的是隔离与可运行性，不是正确率。

## 2. 为什么线程做不到同样的事

线程和主程序共享同一块进程内存。Python 没有一个通用且安全的 API，可以从外部
随时杀掉某个正在执行任意代码的线程。你可以等待线程 1 秒，然后返回 timeout，
但那段代码可能仍在后台占 CPU 或内存。

进程有独立地址空间和操作系统 PID。父进程可以执行：

```text
terminate -> 等待 grace period -> 仍未退出则 kill -> join 回收 -> spawn 新进程
```

这就是 hard timeout 的关键：不仅给结果贴上 `TIMEOUT` 标签，还实际终止承担工作
的执行单元。E13 没有声称能限制整个操作系统网络，也没有 CPU quota；它只证明
父进程能控制这个子进程的生命周期。

## 3. `spawn`、PID、Pipe、IPC 分别是什么

`spawn` 表示启动一个全新的 Python 解释器，再导入指定的顶层函数。Windows 默认
使用这种方式，所以 worker 入口必须是模块顶层函数，不能依赖父进程里临时创建的
闭包对象。

PID 是操作系统给进程的编号。故障测试会保存旧 PID，超时或崩溃后检查：

```text
被结束的 PID == 原 worker PID
新 worker PID != 原 worker PID
```

Pipe 是两个进程之间传字节的通道，IPC 是 Inter-Process Communication，也就是
进程间通信。E13 不把 Python 对象直接共享给子进程，而是发送 canonical JSON
字节，再在子进程中做严格 Pydantic 校验。

## 4. 为什么 worker 是持久化的

最简单的隔离方法是每题启动一个进程，但 117 次都要重新导入模块、验证证据、加载
E11 artifact，启动成本会掩盖真正的 selector 用时。E13 使用一个持久化进程：

```text
启动一次 -> READY -> 请求 1 -> 响应 1 -> 请求 2 -> 响应 2 -> ... -> STOP
```

父进程中的锁保证同一时间只有一个请求。当前没有并发 worker pool，因此不能拿这次
结果声称吞吐量或并发能力。

## 5. 协议文件为什么要先写

文件：`docs/external_datasets/evidence/finqa_shadow_worker_replay_protocol_v1.json`

如果先跑数据再决定“准备成功率至少多少、p95 最多多少”，开发者很容易根据结果
调整门槛。协议提前固定了：

```text
数据版本和 train 文件 SHA
6251 个样本中的确定性 128 题
71 家公司
准备成功率 >= 80%
worker 完成率 = 100%
worker error = 0
worker timeout = 0
p95 <= 250 ms
最大 peak RSS <= 1 GiB
模型调用 = 0
只允许聚合输出
E8 必须仍是 primary
```

协议 SHA 是对整个文件字节的指纹。改一个字符，SHA 都会变化。公开结果保存协议
SHA，所以别人能判断结果究竟按哪个规则产生。

## 6. 训练数据是怎么安全进入 E13 的

核心函数：

```python
load_finqa_shadow_replay_train_v1(path, expected_sha256=...)
```

处理顺序是：

1. 读取最多 128 MiB 的 JSON，并验证完整文件 SHA。
2. 确认顶层是数组，每行和 `qa` 都是对象。
3. 在 Pydantic 校验前，把禁用字段替换为固定值。
4. 再构造 `FinQACase`，验证其余运行字段和表格结构。
5. 检查 ID 唯一性。

被替换的字段是：

```text
answer
exe_ans
gold_inds
ann_table_rows
ann_text_rows
```

为什么不是“加载后提醒自己不要用”？因为代码以后可能误调用一个读取金标的 helper。
先投影掉数据，相当于让后续代码根本拿不到真实标签。

## 7. 为什么官方的一条坏标注不应该让回放停止

FinQA train 有 78,216,616 bytes，超过旧通用 loader 的 64 MiB 上限；而且其中一条
官方 `gold_inds` 使用了不符合项目 schema 的负编号。最初直接验证 6251 个完整对象
时，整个回放因此失败。

错误做法是放松共享 schema，让负编号在所有评测路径中合法。正确做法是先问：
E13 是否需要这个字段？答案是否定的。于是 E13 使用独立 128 MiB exact-SHA loader，
并在 typed runtime 边界前投影掉质量字段。严格 schema 没被破坏，实验也不再依赖
一个本来不该读取的标签。

## 8. 每题如何从原始文档变成 worker 输入

文件：`app/external_datasets/finqa_shadow_replay_v1.py`

步骤如下：

```text
retrieved_all Top-10 IDs
-> 数值证据闭包：补表父行或相邻文本，但有条数/字符预算
-> RetrievedContentGuard：每个候选单元先扫描，危险内容隔离
-> 只从 admitted evidence 抽取 NumericCandidateV2
-> 构造不含原始数值的 safe descriptor catalog
-> 用 gold program structure 构造 typed skeleton
-> E8 在父进程做 primary selection
-> worker 用相同输入做 E11 observation
```

这里的 gold program 只提供操作和角色结构，所以可以测 worker 是否能处理真实复杂度
分布；但它绕过了“planner 能否自己规划正确结构”这一问题。因此结果明确写着
`not planner realism`。

## 9. 隐蔽的 `gold_inds` 依赖是怎么发现的

最初代码复用了：

```python
_source_bound_constant_ids(case)
```

这个函数会在 gold evidence 中找某个 program 常量是否真的来自文档，因此内部读取
`case.qa.gold_inds`。这和 E13 的无质量标签边界冲突。

修复后，准备流程先完成检索、Guard 和候选抽取，再调用：

```python
_retrieved_source_bound_constant_ids(
    program=case.qa.program,
    candidates=candidates,
)
```

它只比较 program 中的常量与实际 admitted candidates。找不到的常量必须属于 host
受控常量表，否则该题准备失败。测试还直接扫描 E13 模块，禁止出现
`case.qa.gold_inds` 等属性访问。这是防止未来回归的数据流测试。

## 10. worker 请求为什么还要再绑定一次输入

E12 的 primary 对象带有：

```text
SHA256(question + typed skeleton + safe catalog)
```

E13 父进程在发送 IPC 前重新计算。如果调用方先让 E8 看问题 A，随后偷偷让 E11 看
问题 B，哈希会不同，结果为 `INPUT_MISMATCH`，而且 worker 不会启动。

这叫 same-input comparison。没有它，`DIVERGED` 可能只是两边输入不一样，不能归因
于 ranker 差异。

## 11. 子进程启动时做了什么

worker 入口是 `_shadow_worker_main()`：

```python
protocol, _ = load_descriptor_shadow_protocol_v1(...)
loaded = load_verified_e11_shadow_challenger_v1(...)
if loaded.challenger is None:
    send EVIDENCE_INVALID
else:
    send READY
```

也就是说，父进程看到 `READY` 不只是代表 Python 启动了，还代表 E12 协议和 E11
artifact/evidence 链全部验证成功。证据漂移时子进程 fail closed，不接收观察请求。

## 12. 请求和响应为什么要限制字节数

即使 schema 正确，一个极大 catalog 也可能造成序列化内存和 Pipe 压力。E13 在发送
前把 canonical JSON 编码成 ASCII，并检查不超过 1 MiB；接收时最多允许 64 KiB。

超大请求返回 `PAYLOAD_REJECTED`，测试确认当时 worker PID 仍是 `None`，说明数据没
进入 IPC。响应还要通过严格 schema，`{}` 会被分类成 `WORKER_ERROR` 并触发重启。

## 13. hard timeout 的代码路径

父进程大致执行：

```python
send_bytes(request)
if not pipe.poll(timeout):
    if child already exited:
        outcome = "WORKER_CRASH"
    else:
        outcome = "WORKER_TIMEOUT"
    terminate old worker
    start replacement worker
```

Windows 存在一个短暂竞争：子进程已经退出，但 `is_alive()` 状态还没及时刷新。第一版
会把 crash 偶尔写成普通 error。修复时先 `join(timeout=0.05)`，再检查 `exitcode`；
只要 exitcode 已产生，就稳定归类为 crash。

## 14. 为什么输出里没有逐题详情

题目、公司、财务数值、descriptor/candidate/evidence/source ID 都可能泄漏真实公开
文档内容与内部处理关系。公开证据只保留：

```text
准备/观察计数
MATCH/DIVERGED 聚合
role/change/common 聚合
延迟分位数
进程 peak RSS 分位数
故障注入布尔门禁
实现文件 SHA
```

逐题排障能力会弱一些，但默认公开 telemetry 不应该成为数据旁路。真正需要逐题诊断
时，应另建有权限、有限时、可审计的私有流程，而不是把详细记录放进公共指标。

## 15. 最终数字应该怎样计算和解释

准备成功率：

```text
117 / 128 = 91.40625%
```

它超过协议的 80%，表示当前 typed runtime 能为多数选定 train 样本构造 E13 输入。
失败的 11 题包括 8 个不支持的 capability route、2 个歧义数值 token fail closed、
1 个未被 admitted evidence 支持且不在 host registry 的常量。

观察完成率：

```text
117 / 117 = 100%
```

这 117 次真实 IPC 没有 worker error、timeout 或 restart。它说明顺序回放可靠，不
说明生产并发可靠。

分歧率：

```text
43 / 117 = 36.75% 的 case 出现至少一个 role 的 Top-4 差异
83 / 252 = 32.94% 的 role selection 发生变化
```

因为没有答案或 gold descriptor 标签，这些变化既可能更好，也可能更差。面试时不能
把 `MATCH 74` 说成 63.25% 正确率。

延迟：

```text
p50 5.659 ms
p95 16.443 ms
max 37.682 ms
```

这是准备和 E8 完成后的 observation 延迟，包含序列化、Pipe、E11 和响应校验，不含
整条 RAG。单进程顺序执行也不是吞吐量测试。

内存：最大 91,136,000 bytes，约 86.91 MiB。Windows 返回的是子进程生命周期内
peak RSS，不是 E11 单次调用新增了 86.91 MiB。

## 16. 实现中遇到的四类问题

第一类是数据边界问题：train 超过旧预算并带一条坏金标。通过独立 exact-SHA loader
和 label projection 解决，没有放松共享 schema。

第二类是实验泄漏问题：复用 helper 时意外读了 `gold_inds`。通过运行时 admitted
candidate 推断替代，并加源码属性访问回归。

第三类是协议描述问题：初版字段名写 NUL，但 expected ID hash 实际来自 ASCII 的
反斜杠加零。正式运行前用哈希和公司数复现后纠正算法名并重新冻结，旧草案没有进入
最终证据链。

第四类是审计代码问题：两个对象是 dataclass，却被误当成 Pydantic；之后公开 schema
又被 dict 展开顺序覆盖。前两次在写证据前停止，schema 错误文件也在提交前撤销；
最终证据测试同时绑定 public schema、协议 SHA 和四个实现文件 SHA。

第五类是 clean checkout 测试问题：第一次推送后，Ubuntu 和 Windows 都在已经通过
两千九百多项测试后出现 3 个 setup error。本机存在 `.private` FinQA train，所以
模块级 fixture 的隐含依赖没有暴露；GitHub runner 不会获得 ignored 私有数据。
修复时把协议 fixture 与 train fixture 拆开：只有真正读取 128 题的 2 个集成测试
在数据缺失时 skip，纯聚合门禁测试继续执行。这里修的是测试前提，不是把应用失败
改成 skip。

修复提交 `1ff1707` 的 GitHub Actions #48 随后通过 Ubuntu、Windows 和 Linux
container 三层门禁。这个过程说明远端 CI 的价值不是重复本机数字，而是暴露 clean
checkout、平台和容器前提。

## 17. 这一步对“工业化”有什么价值

它不是又加一个模型，而是增加了五个落地能力：

1. champion 与 challenger 权限分离，实验代码不能改写主结果。
2. 独立进程让 timeout 具有真正的资源回收语义。
3. 请求/响应 schema 和字节预算限制故障范围。
4. 启动证据校验和 same-input binding 防止错误 artifact 与错误对比。
5. 聚合隐私 telemetry 与不可变证据让结果可审计但不过度泄漏。

这比“调用两个模型比较答案”更接近企业上线前 shadow validation 的工程问题。

## 18. 面试常见问题和参考回答

### 问：为什么不是 `ThreadPoolExecutor(timeout=1)`？

答：future timeout 只停止等待，不能保证底层线程结束。对可能卡死或持续占资源的
challenger，我需要一个可由父进程 terminate/kill 并回收的执行边界，所以使用
spawn 子进程。代价是 IPC 和启动开销，因此采用持久化 worker。

### 问：为什么用了 gold program 还叫 unlabeled replay？

答：更精确的说法是“不消费答案质量标签的 operational replay”。它排除了 answer、
execution answer、gold evidence 和人工标注行，但使用 gold program structure 生成
typed skeleton。因此它可以测 worker 运行机制，不能测 planner realism 或答案准确率。

### 问：36.75% divergence 是好还是坏？

答：单独看不知道。它说明 challenger 对运行输入有足够多的行为差异，值得观察；但
没有独立质量标签就不能判断方向。E13 明确禁止用该数字晋升 E11。

### 问：怎么证明 timeout 真的杀掉了旧任务？

答：故障进程收到请求后 sleep 60 秒，父进程 deadline 是 50 ms。测试保存原 PID，
断言 outcome 为 `WORKER_TIMEOUT`、last terminated PID 等于原 PID、新 PID 不同且
完成 READY。还保留 kill fallback，避免 terminate 在 grace period 内未退出。

### 问：worker 崩溃时 primary 会怎样？

答：primary 已经在父进程由 E8 产生并冻结。worker 只能返回 observation schema，
没有返回可服务 descriptor result 的类型。崩溃只产生 `WORKER_CRASH` 并重启，不
存在替换 primary 的分支。

### 问：为什么不保存逐题差异方便调试？

答：逐题差异会带出问题、ID、来源和财务值，公共 telemetry 会变成泄漏通道。默认
只发布聚合；详细排障应走另一个受授权、限时和审计的私有诊断流程。

### 问：91.41% 准备率是否说明系统准确率 91.41%？

答：完全不是。它只表示 128 个选定样本中有 117 个能构造出受支持的 typed runtime
输入。构造成功不等于 descriptor 正确，更不等于最终答案正确。

### 问：为什么 E13 仍不能上线？

答：它只有单机顺序 train replay，没有真实流量、并发、backpressure、durable queue、
OS sandbox、独立 answer-quality 证据或 promotion gate。它证明 isolation mechanism
可工作，不是 production readiness certification。

## 19. 你可以怎样写进简历

建议写工程事实，不把运行指标伪装成准确率：

> 为 FinQA champion/challenger shadow evaluation 实现 Windows-compatible 持久化
> spawn worker，加入 canonical bounded IPC、同输入哈希绑定、硬超时终止、崩溃/
> 畸形响应自动重启和 aggregate-only telemetry；在固定 128-case train replay 中
> 完成 117/117 隔离观察，0 error/timeout/restart，p95 observation latency 16.44 ms，
> 并通过 5 类故障注入，保持 challenger default-off。

面试时必须补一句：这是 train-only operational evidence，使用 gold program
structure，不是 answer accuracy，也没有启用 E11。

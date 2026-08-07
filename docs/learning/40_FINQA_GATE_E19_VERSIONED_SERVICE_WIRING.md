# E19 学习手册：把实验能力接进真实 API，但先不晋升默认流量

## 1. E19 到底解决什么问题

E18 已经能把 Agent 控制器中的 `AdmittedEvidenceChunk` 转成 FinQA 需要的
typed context，但它当时没有接到标准 FastAPI 请求链路。换句话说，零件已经
能工作，却还没有一个明确的服务装配负责启动它、把请求交给它、关闭它并暴露
安全指标。

E19 补的是这个“服务工程缺口”，不是重新训练模型，也不是宣称正确率提升。

## 2. 为什么新增 main_v2，而不是修改 main.py

`app/main.py` 曾经是 E16 证据的一部分，公开 JSON 保存了它的 SHA-256。若直接
修改它，别人重新运行 E16 审计时会发现哈希不一致，不知道是历史实验被篡改，
还是正常升级。

所以 E19 使用版本化迁移：

- 老入口：`app.main:app`，继续代表已经冻结的 E16 行为；
- 新入口：`app.main_v2:app`，代表 E19 的新装配；
- Docker 仍指向老入口，说明新能力“已接线、可验证、未晋升”。

面试时可以把它解释为：历史证据不可变，新版本并行验证，晋升是独立决策。

## 3. 代码逐层看

### 3.1 协议层

文件：`app/runtime/finqa_service_protocol_v2.py`

`FinQAServiceWiringProtocolV2` 把不能悄悄变化的条件写成 Pydantic 类型：默认
模式只能是 `OFF`，采样率只能是 0，观察位置只能在 primary build 之后，
旧 generic offer、二次检索和 planner model call 都必须是 0。`extra="forbid"`
表示 JSON 中出现未审查字段会直接失败，`frozen=True` 表示加载后不能修改。

协议不是配置文件。配置告诉程序“这次怎样运行”，协议告诉评审者“什么变化会
破坏这次结论”。

### 3.2 装配层

文件：`app/runtime/finqa_service_v2.py`

`build_finqa_service_assembly_v2()` 负责把 resolver、adapter、dark service、
coordinator、worker、Agent runner 和基础资源装成一个对象。集中装配的价值是：
测试可以替换 worker/runner，生产代码不需要全局 monkey patch，而且生命周期
所有权清楚。

`build_finqa_v2_agent_runner()` 没有改变控制器，而是把原 response builder 包在
`FinQATypedObservationResponseBuilderV1` 外层。内部 delegate 先生成 primary
response，外层随后读取 ControllerState 中已经通过 Guard 的证据，提交异步观察，
最后返回原响应对象。

这里的顺序非常重要。若先观察后回答，观察失败可能影响主请求；若从原始检索结果
取文本，会绕过 Guard；若在 API route 再调用旧 offer，同一请求会重复提交。

### 3.3 生命周期层

`FinQAServiceRuntimeV2.start()` 先启动基础资源。只有模式明确为
`LOCAL_TEST_ONLY` 时才启动隔离 worker；worker 启动失败时，coordinator 和基础
资源都会关闭，状态记为 `FAILED`。`close()` 先关 coordinator，再关基础资源，
重复调用不会重复释放。

默认 `OFF` 并不只是“worker 收到请求后什么都不做”，而是 worker 根本不启动，
也不执行 typed-context preparation。这才是可以证明的零成本默认路径。

### 3.4 API 层

文件：`app/main_v2.py`

`create_app_v2()` 保留认证、readiness、反馈回执、trace 和错误边界。真正改变的
位置在 `/agent/v2/chat`：它调用 `active.agent_runner.run(...)`，而这个 runner
已经在装配层包装过。路由自身不再调用 generic dark offer。

响应返回前仍执行原有 trace 脱敏和回执签发。成对实验使用相同 request ID、问题、
身份和 primary answer，因此可以逐字节比较响应，并比较 `X-Feedback-Receipt`。

### 3.5 可观测性层

`safe_finqa_service_snapshot_v2()` 不是简单删除几个敏感字段，而是只允许预定义
字段进入结果。比如 `worker_error` 可以作为 failure counter key，但任意异常文本
不能成为 key。延迟只接受有限非负数，未知状态被归一化为 `UNAVAILABLE`。

“允许列表”比“发现敏感词后删除”更可靠，因为系统不需要提前知道所有可能的秘密。

## 4. 测试结果如何理解

8 组成对请求得到：response mismatch 0、receipt mismatch 0。它证明开启观察不会
改变这 8 个受控主请求的可见结果。它不证明所有问题答案都正确。

OFF 侧 worker start/observe 为 0/0，证明默认关闭不是口头约定。开启侧 start 为 1、
offer/complete 为 8/8，证明每个请求恰好提交一次并完成一次。

故障测试中，worker 报错时 API 仍为 200；队列容量为 1 时，active + queued 已占满，
第三个观察被拒绝，但三个主请求都正常返回；关闭后 pending context 为 0。这证明
辅助观察路径不能拖垮主业务，并且不会遗留上下文。

## 5. 面试常见问题与回答

**为什么不用一个 feature flag 直接改原路由？**

因为原路由被历史公开证据按哈希绑定。版本化入口既保留可复现性，也允许真实 API
集成测试。feature flag 仍存在于新入口内部，但不应该抹掉版本边界。

**异步 shadow 为什么还要比较反馈回执？**

主响应 body 不变并不代表 API 契约完全不变。回执绑定 request、question、answer 和
身份；若观察代码改变了这些输入或调用顺序，body 可能相同但后续 feedback 会失败。

**为什么指标不能带 request ID？**

固定大小内存 trace 可以按权限查询 request ID，但长期聚合指标的标签必须低基数且
不含身份/内容。否则既有隐私泄露风险，也会造成时序数据库 cardinality 爆炸。

**这个阶段让简历更有价值吗？**

可以写“实现版本化 FastAPI 装配与默认关闭的隔离 shadow 路径，8 组成对 API 验证中
响应和回执差异均为 0，并覆盖启动失败、提供方异常、背压和幂等关闭”。不能写成
“FinQA 准确率提升”或“生产零故障”，因为 E19 没有测这两件事。

## 6. 当前边界

新入口尚未成为 Docker 默认入口，也没有生产流量、长时间 soak、资源曲线或 SLO。
下一步若要晋升，应先在容器中运行新入口，做 readiness/rollback、内存/线程上限、
代表性负载和 kill/restart 演练，然后由独立 gate 决定是否替换默认入口。

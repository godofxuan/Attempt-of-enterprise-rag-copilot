# 限制与未完成外部条件

## 实现适用域

- **CONFIRMED_FIXED_BOUNDED**：无引号明确制度名被公共词替代、缺审批关系却完整发布，已用基线与新源码反例对照。不是通用语义判官。
- **NOT_VERIFIED**：非句首/别名/复杂句的制度约束，只有审批词却没有具体审批人的回答，一般跨表/跨页语义，开放式完整性；仍可能错误接受或保守拒绝。不要描述“答非所问已经彻底解决”。
- 数值/否定/条件完整span保守检查保留，合法深度改写可能partial；没有用只比较数字的办法放宽。
- 默认HTTP直接V2 registry，不自动经过ToolGateway/LangGraph/MCP。其他入口是独立可选能力，不应合并成一条默认真实轨迹。
- 预算UTF-8 byte estimator是有标注的保守估计，不是精确token计数。GPU deadline不保证中止在跑kernel。
- 请求在一个immutable snapshot运行，发布前检查active pointer；不能收回已发网络字节，也不能宣称任意IdP即时撤销或多机一致性。

## 夹具与评估契约

- **B1 NOT_REACHABLE_CURRENT_CONTRACT**：同policy双active authoritative文件被合法ingestion拒绝。不能将supporting升权绕过，也不能把单文档冲突当成两文档LLM裁决。
- **单文档冲突 VERIFIED_DETERMINISTIC**：合法内部同模板数值冲突返回双方摘录与partial；按真实host策略跳过LLM。
- **B2 VERIFIED_DETERMINISTIC**：supporting必须排除，实际scorer/LLM输入spy和合法正例已覆盖；旧冲突fixture历史NOT_VERIFIED与失败分母未改。
- 40个合成场景的680次主观测不是独立企业用户样本。source/citation/contract自动检查不等于真人correctness。
- Hybrid与Dense族每文档限制不同，97个Hybrid结果不足5篇不同文章；保留完整配置对比，不把差值只归因RRF。

## 环境与真实确认

一次确认流程已冻结并尝试，但GPU环境在 `build_index_version` 导入parser时缺少 `docx`，**在任何模型POST前失败**：0推理、0主请求、0预热。live目录只有冻结协议、空调用清单、失败summary，没有成功回答记录。
这不是模型答错，不是12题0分，也不是新业务缺陷的真实模型修复验证。状态NOT_VERIFIED。最初预检只覆盖CUDA/权重/tags，没有覆盖parser传递依赖，这是本轮执行准备不足，不能归咎于模型。
不借此下载安装、混合两个venv、切换模型或重开一次run。后续真实演示需要一个按现有锁文件完整准备的隔离服务环境，并另行批准有限协议；本轮停止推理尝试。
完整离线测试的36个skip由现有环境条件触发：2个PostgreSQL DSN缺失、4个私有数据缺失，其余符号链接/POSIX/8.3路径环境限制；没有新加skip。逐项见TEST_RESULTS及日志。
未在本轮Ubuntu、PostgreSQL或Linux container执行新代码。历史4-job成功只绑定c9984e9；原job日志API返回403，任务/步骤状态可读。

## 证据与历史来源

三层复算已经取得，但不等于重跑模型、历史dirty源码完全重建或第三方独立重复。
旧个案只有最终answer/span/packet hash，缺完整prompt/raw LLM response，不能反推生成中间态。
历史检索dirty源树归档仍不完整；服务部分checkout与Git blob存在已单列的换行差异。详见HISTORICAL_SOURCE_CHECK，不用SHA掩盖未提交源码。
历史检索1074次尝试及超修订预算7条保留。历史9个503不删除；最后80无503不等于长期可靠性。

## 真人与生产

`HUMAN_REVIEW = NEEDS_HUMAN`：无人提供新的独立问题、预期冻结或真人语义判断；模板没有预填签名/审核结果。建议独立审核者提供20-30个真实业务代表问题，去近重复后在看输出前冻结预期和依据。
`PRODUCTION = NOT_EVALUATED`：没有生产流量、长期soak、SLA、安全全证明。未发现新增泄漏复现不代表不存在未知风险。

## 是否阻止展示

不阻止清楚标注的**离线确定性机制演示和历史证据复算**。阻止声称新补丁已经通过真实GPU问答验收、双权威文档冲突LLM裁决、独立准确率或生产就绪。
最终为READY_WITH_LIMITS，不是overall PASS。三个有限工作项可执行部分完成后停止加功能；不新增learned ranker。

# 根因、最小修复与反例

## A1：引用准确，但制度对象不对（CONFIRMED / FIXED_BOUNDED）

原始入口是 `service_C_readiness_v1 / safe_dense_raw20_bge / lifecycle_delete / main`。
公开行可核对检查项，私有冻结原行的字节 hash 由 `private_identity_checks.json` 绑定；原问题来自冻结 synthetic fixture：

> 删除快递报销制度后，还能确认每单上限吗？

实际最终回答是运费表：`货物 | 运费上限`，文件 20 元、设备 100 元。
`mode=answered`、`stop_reason=completed`；所引 `freight` 的 index 是 deleted，支持类型 exact_span，offset 0..30。
因此这是“答非所问”，不是“仍然引用已删除文件”：索引绑定和引用可见性在该行都满足，但它们不能证明回答了指定制度的问题。
原行没有完整 LLM raw output/完整 packet；其 packet hash 和最终 span 不能还原这些材料。历史最终输出核实与 synthetic stub 复现严格分开。

根因假设核对：
1. 删后沿用旧 runner？当前 index/version 与最终 freight 来源不支持这个解释。
2. 生成器把数值拼错？最终文本来自完整运费表，不能归为数字捏造。
3. relevance 允许“上限”这一公共词覆盖制度身份？旧实现只提取显式引号里的实体，不约束这条无引号制度名；新反例稳定复现，支持该根因。

修改 `app/agent/evidence_relevance.py`：新增 `_bare_policy_entity`，将句首明确“某某制度/政策/标准表”识别为已有实体约束；剥除有限问法前缀，再复用原实体匹配。没有写入 case_id、完整问题、业务制度名称或 gold。
保留年份检查、引号实体、多方面既有逻辑、ACL/Guard 和 generation grounding。正常“当前制度”不被误当成特定标题。
这是有限词法语法，不是通用实体识别：非句首、省略/别名、复杂问法仍可能漏识别或保守拒答，不继续堆特判。

实际 HTTP 回归通过真实索引构建和激活、JWT、路由、controller、packet 与 response：先有 courier + shipping，第一问能引 courier；再激活只含 shipping 的隔离索引。旧源码 Hybrid/Top20 均错误 answered；修后均 not_found、无 sources、无生成调用。
这里的 embedding、scorer 和生成传输是 synthetic stub，readiness 是测试资源；没有声称重新生成了历史模型原答案。

## A2：问审批人却只给提交期限（CONFIRMED_SYNTHETIC / FIXED_BOUNDED）

问题“出差申请需要谁审批？”；证据/生成摘录“出差申请必须提前 7 天提交。”。
旧 helper 标为 semantic_completeness_unverified，但最终仍能 answered；这是“支持片段是真的，所问关系却缺失”。

- `app/agent/answer_contract.py::answer_sufficiency` 新增有限审批人问法与审批关系缺失检查。
- `app/agent/generation_v2.py::GenerationV2ResponseBuilder.build` 复用现有不足证据状态：单方面缺此关系 => not_found，无来源；多方面则 partial + warning。没有把正常不足证据改成 unsafe。
- “出差申请由谁批准？” + “直属经理批准”正例仍 answered。trace 记录 missing_requested_relation，最终 stop_reason 不再与返回状态冲突。

局限：出现“审批/批准”只是必要词法条件，并不证明答案确实给出了审批人。例如“需审批”仍不构成通用关系推理。本轮只阻止已经复现的明确缺关系，不引入语义 judge，不宣称全部语义完备。

## A3/A4：数值与条件

没有证实本轮需要更宽数值规范化；不修改 `citation_verifier.py`。
新回归保留完整 `Only employees in the pilot may claim up to 20 yuan after approval.`，原文/两端空白正例支持；去条件、元变百分比、员工变承包商、上限变至少、审批后变无需审批均不支持。
这些是 A4 合理保守降级，不作为模型质量失败“修成 PASS”。既有 duration-only 不完整输出保持 partial；没有新造 table/layout 模块。

## B：冲突夹具与契约（FIXTURE/CONTRACT_LIMITATION）

旧 conflict_a/b 是 supporting，真实检索 authoritative_only 会排除，因此原失败保留。
试图直接把两个同 policy 文档都设成 active authoritative 时，实际 `build_index_version` 在 `_validate_version_graph` 拒绝：exactly one active authoritative version。不能绕过 builder 强行制造服务永远不会合法加载的状态。
当前检测又按同 policy/version/scope 分组；换成两个 policy 不等于验证同一业务关系的未决冲突。

新测试分三类：
1. B1 双权威非法夹具必须被索引治理拒绝。两文档未决冲突能力仍 NOT_REACHABLE_CURRENT_CONTRACT。
2. 合法单一权威文档内部同模板 7/30 天冲突，Hybrid/Top20 HTTP 返回 partial，保留双方完整引用；现有 builder **不调用 LLM**，由 host 生成冲突摘录。不声称 LLM 看过两份证据或完成裁决。
3. B2 supporting 以及不同 tenant/groups、Guard 恶意正文，均不会进入 scorer/LLM 实际输入，正常退款文档仍能 answered。版本可解决的对照由既有 version/index-binding 测试保留。

未改变旧 fixture、旧指标、准入阈值或真实数据模型；改进的是评测适用域和新开发夹具。

## C：离线证据工具（IMPLEMENTED / VERIFIED_WITHIN_SCOPE）

旧 exporter 能重放聚合和字节，但不能从 gold 重新计算检索分数。旧 producer hash 被历史证据绑定，因此保持两个 exporter 原字节不变；只增加一个入口 `scripts/verify_runtime_closure.py`，复用其 aggregate/paired/percentile，无新依赖。
新工具校验格式、字段、唯一性、cohort、有限数值、计数、manifest 文件名单、排名边界；导出已存在的公共 gold ID 映射，不猜标签。
`overall_status` 与三个 `verification_scope` 分开；退出 0/2/3/4 分别为范围内验证/缺输入/无效输入/内部异常。仅聚合不能自动声称 gold 验证。
最终自审又发现计数被通用浮点容差接纳、内部异常 scope 为空；3 个工具反例先失败，改为严格整数计数及明确 NOT_VERIFIED 字段后通过。业务代码没有因此再改。

## 实际验证与失败保留

| 运行 | 结果 | 解释 |
|---|---|---|
| 初始开发反例 | 7 failed / 8 passed | 5 个缺陷反例 + 2 个非法 B1 夹具失败；后者改为验证拒绝，而非放松生产索引 |
| 固定基线 + 最终同两份新业务测试 | 6 failed / 19 passed | `BASELINE_REGRESSION_IDENTITY.json` 绑定纯旧 app 与新测试，不是声称旧仓库原有这些测试 |
| 最终相关工具/HTTP/业务/旧 exporter | 48 passed | `logs/final_targeted.log.txt`，其中两份业务测试共 25 项，全通过 |
| 最终完整离线 | 3692 passed / 36 skipped | `logs/full_offline_release.log.txt`；源码前后 `c939f268...` 一致，无新 skip；结果不能当作3692道问答 |
| 一次真实确认准备 | STOPPED_ModuleNotFoundError | GPU 环境缺 docx，在索引 parser 导入阶段结束；0 推理、0 主请求、0 预热，不补跑、不作准确率 |

早期验证器出现 schema 假设错误（resource1 而非 resource_1、warmup 公共 key 不唯一），已按真实数据契约纠正；没有清洗或删除原观测。
基线 Git 子进程曾因 sandbox 身份 ownership 校验失败；只用 `git -c safe.directory=该已核实worktree` 单命令例外，未修改全局 Git 配置。
所有正式验证的时间、退出码、前后指纹、日志在 `TEST_RESULTS.json`；初期未纳入统一 recorder 的红/绿 XML另列为开发检查，不回填不存在的开始时间。

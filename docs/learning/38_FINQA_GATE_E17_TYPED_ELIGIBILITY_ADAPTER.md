# Gate E17：把企业问题安全地接到 FinQA Shadow 之前，必须先补齐什么

## 1. 这一阶段到底做了什么

E16 已经有一个后台暗执行框架，但它只知道四个字段：

```python
request_id
question
primary_mode
primary_stop_reason
```

E11 不是普通问答模型。它比较的是 E8 和 E11 对“数值描述符”的选择，因此还需要：

```python
SemanticProgramSkeletonV2       # 问题要做什么运算，需要哪些语义角色
RetrievableSafeDescriptorCatalogV3  # 从已允许证据中抽出的无数值描述符
FinQAPrimaryDescriptorDecisionV1    # E8 在同一输入上的主选择
```

E17 新增了一层适配器。它不是“再调用一次 LLM”，而是检查输入是否完整可信，绑定同一输入，运行 E8 主选择，再让隔离 worker 运行 E11。

## 2. 为什么不能只看问题里有没有“增长率”

假设问题是：

```text
2023 年营业利润率比 2022 年变化了多少？
```

只看关键词，可以猜它是一个财务数值问题；但仍不知道：

- 哪两个数字来自哪份已授权文档；
- 两个数字的单位和期间是否一致；
- 运算是 `SUB`、`DIV` 还是 `PERCENT_CHANGE`；
- 检索到的文本是否已经通过间接提示词注入 Guard；
- 哪些 descriptor 真正对应左右两个角色。

所以 E17 的 eligibility 不是一个粗糙关键词分类器。它判断的是“执行 E11 所需的 typed contract 是否完整”。不完整就弃权，不能猜字段补齐。

## 3. 最危险的数据泄漏：gold program

FinQA 数据集每道题带有标准答案和标准程序。离线评测中可以读取程序结构来做能力上界或操作回放，例如：

```python
case.qa.program
```

但真实用户提问时不存在这个字段。如果线上适配器调用使用 gold program 的辅助函数，测试会看起来很好，生产却无法运行。这叫 target leakage，也可以理解为考试时偷看答案结构。

E17 协议只允许：

```text
skeleton_origin = ONLINE_RULES | ONLINE_MODEL
catalog_origin  = RETRIEVED_ADMITTED_EVIDENCE
```

并禁止：

```text
answer, exe_ans, gold_inds, gold_program,
program, program_re, target_labels
```

注意：这里不是用字符串判断后再放行。`Literal` 和 `extra="forbid"` 让非法来源根本无法构造成合法 Pydantic 对象。

## 4. 完整流程

```text
主请求线程
  1. 完成身份、租户 ACL、检索和 Guard
  2. 上游判断是否是支持的财务数值任务
  3. 上游产生 value-free typed skeleton
  4. 从已允许证据构建 safe catalog
  5. 生成 FinQATypedServiceResolutionV1
  6. 按 request_id 临时注册

E16 后台线程
  7. 按 request_id 原子消费 resolution
  8. 不适用则立即 NOT_APPLICABLE
  9. 校验 question 与 context 完全相同
 10. 适配器内部运行 E8，得到 primary
 11. 把同一 question/skeleton/catalog/primary 交给 E11 worker
 12. MATCH/DIVERGED 映射成 MATCH/DIFFERENT
 13. 只累计聚合指标
```

当前 E17 已完成第 5 到第 13 步的可信机制。第 1 到第 4 步在企业 Agent 主链里还没有形成可注册的 typed context，因此普通服务仍然关闭该能力。

## 5. 核心代码逐段理解

### 5.1 `FinQATypedServiceContextV1`

文件：`app/external_datasets/finqa_service_adapter_v1.py`

主要字段：

```python
question: str
skeleton: SemanticProgramSkeletonV2
catalog: RetrievableSafeDescriptorCatalogV3
skeleton_origin: Literal["ONLINE_RULES", "ONLINE_MODEL"]
catalog_origin: Literal["RETRIEVED_ADMITTED_EVIDENCE"]
input_binding_sha256: str
```

`build()` 对 question、完整 skeleton、完整 catalog 做 canonical JSON 序列化，再计算 SHA-256。读取对象时 validator 会重新计算。

这不是为了保密。SHA-256 在这里解决的是完整性和错绑：如果后台线程拿到的问题、skeleton 或 catalog 有一个字节变化，绑定就不再对应。

### 5.2 `FinQATypedServiceResolutionV1`

它只有两种 disposition：

```text
ELIGIBLE
NOT_APPLICABLE
```

合法组合被严格限制为：

```text
ELIGIBLE
  reason = TYPED_CONTEXT_COMPLETE
  context 必须存在

NOT_APPLICABLE
  reason = 五种冻结原因之一
  context 必须为空
```

五种弃权原因是：

| 原因 | 白话解释 |
| --- | --- |
| `NOT_FINANCIAL_NUMERIC` | 不是当前数值能力要处理的问题 |
| `MISSING_TYPED_SKELETON` | 没有可靠的运算结构 |
| `MISSING_SAFE_CATALOG` | 没有从已允许证据得到安全 catalog |
| `POLICY_DENIED` | 安全、权限或业务策略拒绝 |
| `UNSUPPORTED_TYPED_CONTRACT` | 有输入，但操作或结构超出当前能力 |

弃权不是系统失败，也不是回答错误。它表示“当前挑战器没有资格运行”。

### 5.3 `FinQAEphemeralContextResolverV1`

E16 的 worker 在后台线程运行，主请求结束时间和后台消费时间不同，因此需要一个很短暂的交接区。

它有四个关键限制：

```python
capacity       # 最多保留多少个待消费 context
ttl_seconds    # 最长保留多久
duplicate ID   # 直接拒绝，不覆盖旧值
resolve()      # pop，消费一次后删除
```

为什么重复 ID 不能覆盖？假如请求 A 已注册，攻击者或并发请求 B 又使用同一 ID，覆盖会导致 A 的后台任务读取 B 的 context。项目之前在 trace lookup 中遇到过 request ID 复用问题，所以这里直接冻结“不覆盖”策略。

为什么还要 `discard()`？如果 E16 返回 `DISABLED`、`SAMPLE_SKIPPED` 或 `BACKPRESSURE`，后台不会消费 context。调用方应立即 discard；即使漏掉，TTL 也会兜底清理。

### 5.4 `FinQATypedServiceAdapterV1.observe()`

关键顺序不能调换：

```python
deadline 检查
resolution = resolver.resolve(request)
记录 eligibility reason
如果不适用：直接返回 NOT_APPLICABLE
question 精确绑定检查
primary = E8.select_primary(...)
确认 primary.generation_calls == 0
observation = isolated_e11_worker.observe(...)
映射固定 outcome
```

E8 primary 为什么必须在 adapter 内部算？如果外部直接传 primary，外部可能传入旧问题或旧 catalog 的结果。内部计算让 primary 与本次 context 天然绑定。

### 5.5 固定安全错误码

resolver 或 worker 可能抛出包含原文的异常，例如：

```python
RuntimeError(f"failed on private question: {question}")
```

adapter 不向外传播这段文字，只生成：

```text
resolver_error
worker_error
input_binding_mismatch
deadline_expired
```

E16 再把 provider 异常压缩成 `provider_error_total`。因此公开 metrics 不需要保存原始异常也能知道哪一类边界失败。

## 6. 这次测试到底证明了什么

```text
E17 focused                       23 passed
E12/E13/E16 related regression   52 passed
full repository                  3000 passed / 29 skipped
public repository audit          1339 candidates / 0 findings
frozen E17 gates                 24 / 24
```

资格矩阵：

```text
5 个 NOT_APPLICABLE 原因
-> 5 次返回 NOT_APPLICABLE
-> 0 次 worker 调用

1 个完整 typed context
-> 1 次 E8 primary
-> 1 次 worker 调用
```

真实 worker：

```text
observation 1  MATCH，包含 Windows spawn 冷启动
observation 2  MATCH，复用已启动 worker
worker close  exit code 0，无残留 PID
```

大约 732 ms 的最大值主要来自首次子进程启动；热路径约 3.6 ms。样本只有 2 个，所以不能说 p95 是生产 p95，也不能把它写成 SLO。

## 7. 它对最终答案正确率有提升吗

没有新的答案正确率结论。

E17 是 service correctness 和 safety gate，回答的问题是：

```text
如果上游已经产生完整可信 typed context，
能否不改主回答地、安全调用 E8/E11 Shadow？
```

当前答案是“机制上可以，24/24 gate 通过”。

它没有回答：

```text
线上 planner 能生成多少正确 skeleton？
企业检索证据能覆盖多少数值问题？
E11 的不同选择最终能让答案提高多少？
```

面试时必须把这两类指标分开：模型质量指标与系统机制指标不是同一件事。

## 8. 为什么这比直接接一个 LLM 更工业化

工业系统不只关心“能运行”，还关心：

- 输入是否来自线上可获得数据；
- 权限和 Guard 是否在数据进入挑战器前生效；
- 不支持时是否明确弃权；
- request ID 复用是否会错绑；
- 队列满、超时、进程故障时主回答是否不受影响；
- 指标是否能排障又不泄漏内容；
- worker 和临时数据是否能关闭清理；
- 证据是否与代码 SHA 对应。

E17 解决的是这些接口和不变量，而不是再堆一个模型名字。

## 9. 面试常见问题与参考回答

### 问：为什么 eligibility 不直接让 LLM 判断？

答：这里的 eligibility 是执行资格，不是开放式语义评分。LLM 可以作为上游 `ONLINE_MODEL` planner 产生候选 skeleton，但最终对象必须通过严格 schema、来源、绑定、Guard 和能力校验。缺字段时确定性弃权，避免 LLM 自己批准自己运行。

### 问：为什么 E8 primary 不能由调用方传进来？

答：外部 primary 可能来自不同 question 或 catalog。adapter 在同一 context 上重新计算 E8，并让 E13 worker再次检查 input binding，从两层防止比较对象错位。

### 问：为什么 resolver 要消费即删除？

答：它只负责主线程到暗执行线程的短暂交接，不是缓存或数据库。消费即删除、TTL、容量和 close 清理共同缩小敏感上下文的驻留时间和内存上界。

### 问：两个真实 worker 都 MATCH，说明 E11 没价值吗？

答：不能这样推断。这两个合成输入只验证服务适配和真实 worker 可执行性，不是质量样本。E11 的质量证据来自 E11 的 nested CV 和一次性 internal cohort；E17 不重复消费这些数据。

### 问：为什么还没有启用 API？

答：API 主链尚未把 ACL/Guard 后的数值证据和线上 value-free skeleton 交给 adapter。现在启用只能重新检索或伪造输入，前者缺少租户上下文，后者是错误能力声明。下一阶段先补服务数据流，再做默认关闭的成对验证。

### 问：怎么证明没有泄漏？

答：协议冻结公开禁止字段；metrics 只返回原因和结果计数；测试递归检查所有 JSON key 和敏感 sentinel；公开仓库扫描结果为 1339 candidates / 0 findings。原始异常被固定错误码替代。

### 问：冷启动 735 ms 怎么处理？

答：不能放进同步主回答。当前设计保持暗执行异步，E13 worker 是持久进程，热路径约 3.6 ms。正式接入时 worker 应由 service lifespan 启动和关闭，继续使用 deadline、队列和 backpressure。

## 10. 下一步 E18

E18 才会补全线上前半段：

```text
ACL/Guard 后 evidence
-> numeric candidate extraction
-> safe descriptor catalog
-> online value-free skeleton planner
-> eligibility resolution
-> resolver.register
-> E16 offer
-> 未 admitted 时 resolver.discard
```

必须继续默认 `OFF`，不能访问已消费 internal cohort，也不能触碰 frozen test。完成后需要做 OFF 与 enabled 的完整 API 响应字节对比、错误注入、生命周期关闭和公开聚合证据。

## 11. 文件索引

```text
协议模型
app/external_datasets/finqa_service_adapter_protocol_v1.py

核心实现
app/external_datasets/finqa_service_adapter_v1.py

审计脚本
scripts/audit_finqa_service_adapter_v1.py

协议
docs/external_datasets/evidence/finqa_service_adapter_protocol_v1.json

公开证据
docs/external_datasets/evidence/finqa_service_adapter_public_v1.json

工程记录
docs/external_datasets/finqa_typed_service_adapter_gate_e17.md

当前交接
docs/roadmap/finqa_gate_e17_current_handoff.md

测试
tests/external_datasets/test_finqa_service_adapter_v1.py
tests/external_datasets/test_finqa_service_adapter_protocol_v1.py
tests/external_datasets/test_finqa_service_adapter_evidence_v1.py
```

# 33. FinQA Gate E12：为什么“评测变好”之后还不能直接替换线上方案

## 1. 这一阶段到底做了什么

E11 已经得到一个小幅正结果：在外层交叉验证中，Descriptor Recall@4 从
`84.8894%` 提升到 `86.0881%`；在一次性内部评测中，从 `84.21%` 提升到
`86.84%`。但内部只有 76 个 role 真正参与比较，只发生 2 个修复、0 个退化，
McNemar 检验 `p=0.5`，证据还不足以把 E11 直接换成主方案。

所以 E12 没有继续调模型，而是实现 shadow runtime（影子运行）：

```text
E8：继续决定真正使用的 Top-4 descriptor
E11：在 E8 完成后，用同一份输入再算一次，只比较差异
```

无论 E11 算得更好、更差、报错还是超时，主结果都还是 E8。

## 2. shadow 和 A/B test 有什么区别

Shadow 的 challenger 结果不会给用户使用：

```text
用户请求
  -> E8 主路径
  -> 得到 primary result
  -> 正常返回或继续后续业务

同一个输入
  -> E11 shadow
  -> 只统计 MATCH / DIVERGED / ERROR / TIMEOUT
  -> 不替换 primary result
```

A/B test 通常会让一部分真实用户看到 A，另一部分看到 B；shadow 则让所有用户仍
看到 A，只在后台观察 B。因此 shadow 更适合证据还不够强的新模型。

当前项目还没有 FinQA 生产接口，因此 E12 实现的是可嵌入协调器和机制审计，不是假装
已经接入真实线上流量。

## 3. 第一段关键代码：主结果先产生

文件：`app/external_datasets/finqa_descriptor_shadow_v1.py`

核心方法是：

```python
def select_primary(self, *, question, skeleton, catalog):
    result = self._champion.select(
        question=question,
        skeleton=skeleton,
        catalog=catalog,
    )
    return FinQAPrimaryDescriptorDecisionV1(
        result=result,
        input_binding_sha256=_input_binding_sha256(...),
    )
```

这里的 `champion` 默认就是 E8 的
`DeterministicFinQADescriptorRetrieverV5`。方法先完整得到 E8 结果，才返回一个冻结
的 `FinQAPrimaryDescriptorDecisionV1`。这个对象里没有“让 E11 覆盖结果”的接口。

`input_binding_sha256` 是输入绑定，不是评测分数。它把三部分序列化后做 SHA-256：

```text
question + typed skeleton + safe descriptor catalog
```

目的不是加密问题，而是确保后来观察 E11 时没有偷换输入。这个 SHA 只留在内存中的
primary 对象里，不能进入 telemetry。

## 4. 第二段关键代码：为什么 E11 改不了主结果

`observe()` 接收已经生成的 `primary`：

```python
def observe(self, *, primary, question, skeleton, catalog):
    if self.config.mode == "OFF":
        return self._record(outcome="DISABLED", ...)

    if new_binding != primary.input_binding_sha256:
        return self._record(outcome="INPUT_MISMATCH", ...)

    challenger = self._challenger.select(...)
    # 只计算 changed/common 计数
    return self._record(outcome="MATCH" or "DIVERGED", ...)
```

注意返回类型是 `FinQAShadowObservationV1`，不是
`DeterministicDescriptorRetrieverResultV1`。也就是说，它只能返回观察信息，不能返回
一个可被业务误用的新排序结果。E11 的完整结果只作为函数局部变量存在。

这比写一句 `if shadow: use_e8` 更可靠，因为类型和调用顺序都在限制错误用法。

## 5. 为什么还要检查“同一份输入”

如果 E8 用问题 A，E11 却用改写后的问题 B，二者结果不同并不能说明 ranker 不同；也
可能只是输入不同。这样的 shadow 数据会污染结论。

`_input_binding_sha256()` 使用排序键、固定分隔符和 ASCII 转义做 canonical JSON：

```python
json.dumps(
    payload,
    allow_nan=False,
    ensure_ascii=True,
    separators=(",", ":"),
    sort_keys=True,
)
```

同一个逻辑对象会稳定得到相同字节。观察阶段重新计算 SHA，不一致就返回
`INPUT_MISMATCH`，而且不调用 challenger。

## 6. artifact 为什么不能只做一次 JSON 解析

E11 artifact 自己有内部哈希，但只验证 artifact 还不够。假设有人拿了另一次训练产生的
合法 artifact，它内部哈希仍然正确，却不一定通过当前协议和评测门禁。

`load_verified_e11_shadow_challenger_v1()` 同时检查：

```text
E8 protocol 文件 SHA
E11 protocol 文件 SHA
E11 nested CV 文件 SHA + decision + 全部 gate
E11 artifact 文件 SHA + artifact 内部 SHA
E11 internal 文件 SHA + decision + 全部 gate
E11 postmortem 文件 SHA + internal 结果绑定
serving 必须仍是 DISABLED
frozen test 必须仍是 UNTOUCHED
```

任何一个条件失败，加载结果都是 `DISABLED_EVIDENCE_INVALID`，不会把异常送进主路径。
这叫 fail closed：无法证明 challenger 合法时，就不运行 challenger。

## 7. circuit breaker 是怎么工作的

如果 challenger 持续报错，每个请求都重试会浪费 CPU，并制造大量重复错误。E12 使用
三态熔断器：

```text
CLOSED
  连续失败少于 3 次：仍允许下一次观察
  第 3 次连续失败：进入 OPEN

OPEN
  跳过接下来 5 次观察机会
  冷却结束：进入 HALF_OPEN

HALF_OPEN
  只允许一个试探调用
  成功 -> CLOSED
  失败 -> 再次 OPEN
```

测试中的 9 次观察结果是：

```text
ERROR, ERROR, ERROR,
OPEN, OPEN, OPEN, OPEN, OPEN,
MATCH
```

因此总共只调用 challenger 4 次，而不是 9 次。这证明了熔断与恢复，不代表生产负载
能力。

## 8. timeout 为什么不是“强制杀线程”

E11 是无网络、无 LLM 调用的确定性 NumPy/CPU 排序器。当前实现记录开始和结束时间，
超过 100ms 就把本次观察标为 `CHALLENGER_TIMEOUT`，结果作废并计为熔断失败。

它不能强制终止正在运行的 Python 线程。因此准确说法是“elapsed-budget breach
detection”，不是“硬超时取消”。因为 E8 主结果已经产生，它不会覆盖主结果；但若真要
部署到线上，仍应把 shadow 放到独立队列或进程中，由进程级 deadline 限制资源。

面试中主动说出这个限制，比宣称“已经有生产级 timeout”更可信。

## 9. 为什么 telemetry 不能记问题和 ID

真实问题可能包含公司秘密，candidate/evidence/source ID 能关联私有文档，数值也可能是
敏感财务数据。E12 每次观察只允许七个字段：

```text
schema_version
outcome
role_count
changed_role_count
common_descriptor_count_at_4
latency_bucket
circuit_state
```

例如 E8 和 E11 在一个 role 的 Top-4 中共有三个 descriptor，只记录：

```json
{
  "outcome": "DIVERGED",
  "role_count": 1,
  "changed_role_count": 1,
  "common_descriptor_count_at_4": 3
}
```

不会记录“哪三个相同、哪一个不同”。生产排障能力会弱一些，但先保护数据边界，再通过
受控的私有诊断流程处理详细样本，是企业系统更合理的默认值。

## 10. 实现中发现并修了什么问题

初版 registry 只会生成固定枚举键，但 snapshot 数据模型的三个字典仍允许任意 key。
未来代码可能绕过 registry，手工构造：

```python
outcomes={"这里放原始问题": 1}
```

这会破坏 telemetry 边界。公开证据生成前，代码新增了
`validate_aggregate_keys()`：只允许固定 outcome、latency bucket、circuit state，并
要求值是非负整数；对应回归测试会主动塞入非法 key，确认模型拒绝。

这个例子说明，隐私边界不能只靠“当前调用者不会乱用”，还要在 schema 层阻止误用。

全量测试时还出现过一次运行环境问题。我最初为了不写 C 盘，把 pytest 的
`--basetemp` 放进项目内 `.tmp`，结果得到 4 个失败：3 个身份测试拒绝仓库内但不在
`.private` 的临时密钥，1 个脱敏测试发现路径已经是仓库相对路径，因此没有替换为
`<external>/`。这四个断言其实都在正确执行安全规则。

排查方法不是修改断言，而是把 4 个失败单独组成最小反馈循环，只改变 temp 根目录。
把 `TEMP/TMP` 指向 D 盘、仓库外的可写目录后，4/4 通过；随后全量
`2921 passed / 29 skipped`。所以根因是测试参数破坏了测试前提，业务代码不需要改。

## 11. 结果应该怎样理解

```text
E12 聚焦测试                  14 passed
external-dataset 回归          408 passed
全仓库回归                    2921 passed / 29 skipped
公开仓库审计                  1278 candidates / 0 findings
E11 证据链加载                READY
真实合成机制探针              MATCH
默认关闭时 challenger 调用    0
异常隔离                      CHALLENGER_ERROR
耗时预算隔离                  CHALLENGER_TIMEOUT
熔断观察/实际调用             9 / 4
工程门禁                      11 / 11
模型调用                      0
```

这里的 `MATCH` 只来自一个合成机制输入，作用是证明真实 E8/E11 实现可以通过 coordinator
运行，不是新的准确率。E12 没有再次读取 E11 内部 40 题，也没有读取 frozen test。

质量效果仍引用 E11：外层 `+1.1987pp`，内部 `+2.63pp`，但统计不显著且不是最终答案
准确率。工程效果引用 E12：默认关闭、错误隔离、证据加载、熔断、隐私 telemetry 已验证。

## 12. 面试官可能会问什么

### 问：既然 E11 指标提升了，为什么不直接上线？

答：内部只有 76 个 role，只有 2 gain / 0 regression，McNemar `p=0.5`，无法排除抽样
波动；而且指标是 descriptor/candidate recall，不是答案准确率。我先做默认关闭的 shadow
集成，验证 artifact、故障隔离和观测边界，再收集独立证据。

### 问：怎么保证 shadow 不影响用户？

答：API 被拆为 `select_primary()` 和 `observe()`。前者先返回冻结的 E8 主决策，后者只
返回计数型 observation，类型上不能返回替代排序。异常和超时只更新熔断与聚合指标。

### 问：为什么不用日志保存完整差异，排障不是更方便吗？

答：完整差异包含问题、descriptor ID 和来源关联，可能泄露企业知识。默认 telemetry
只存聚合计数；需要逐题排障时应走有权限、限时、审计的私有诊断流程，不能让普通指标
系统成为数据旁路。

### 问：这个 circuit breaker 有什么不足？

答：它验证了状态机、跳过和恢复，但当前 timeout 是执行后的耗时违约检测，不是进程级
强制取消；也还没有跨进程共享状态。真实部署需要独立 worker、队列 deadline、资源配额
和分布式指标后端。

### 问：E12 对简历有什么价值？

答：它说明项目不只追准确率，还实现了 champion/challenger 发布边界、证据链校验、
fail-closed 加载、same-input 比较、熔断恢复和隐私受限观测。描述时必须同时写清
“shadow default-off、非生产流量、未启用 challenger”，这样数字才可信。

## 13. 下一步做什么

E13 可以在公开、已披露的 train-only 输入上做不带质量标签的 operational replay：量化
分歧率、耗时桶、错误率和熔断行为，并增加进程/队列隔离设计。不能根据 replay 重新调
E11，不能重用已消费 internal 40，不能访问 frozen test，也不能据此宣称答案准确率。

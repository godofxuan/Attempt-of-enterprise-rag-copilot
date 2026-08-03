# Gate E18 学习手册：已授权证据怎样安全进入 Typed Shadow

## 1. 先用一句话说清楚

E17 已经会消费一个完整的 typed context，但不会生产它。E18 补的是：

```text
Agent 已经检索并通过 ACL/Guard 的证据
-> 提取数字候选
-> 生成不含数值的运算骨架
-> 生成不暴露数值的 descriptor catalog
-> 注册给后台 shadow worker
-> 未被后台队列接纳时立即清理
```

它不是“再加一个 LLM”，也不是“让 Agent 重新检索一次”。它是在已有安全
边界之间补一条有类型、有预算、可清理、可审计的数据管道。

## 2. 为什么不能让后台按 question 再检索一次

E16 后台请求只有：

```python
request_id
question
primary_mode
primary_stop_reason
```

它故意没有 `tenant_id`、`groups`、`region` 和用户 Principal。缺少这些字段时
重新检索会出现两个错误选择：

1. 不带 ACL 检索，可能读到其他租户或用户组的文档；
2. 猜一个身份检索，结果与真实主请求不一致。

所以正确方案是复用主请求已经得到的 `AdmittedEvidenceChunk`。这个对象不是
普通文本，它在构造时已经要求正文、parent context 和 metadata 各自带有
`ADMIT` 决策。E18 的函数签名也只接受这个类型：

```python
def build_finqa_admitted_context_v1(
    *,
    question: str,
    evidence: tuple[AdmittedEvidenceChunk, ...],
    guard: RetrievedContentGuard | None = None,
) -> FinQAAdmittedContextBuildV1:
```

如果传 `list[str]`、raw `SearchHit` 或字典，会直接 `TypeError`。这叫 capability
constraint：调用者只有拿到安全层颁发的强类型对象，才能进入下一层。

## 3. 代码到底改在哪里

### 3.1 协议模型

文件：`app/external_datasets/finqa_admitted_context_protocol_v1.py`

它规定：

- 只能读取 `AdmittedEvidenceChunk.context_text`；
- 最多 32 个 evidence、16,000 字符、128 个 numeric candidates；
- 二次检索调用必须为 0；
- planner 模型调用必须为 0；
- 只允许 `ONLINE_RULES` 和 `RETRIEVED_ADMITTED_EVIDENCE`；
- E16 不接纳时怎样清理；
- 主回答必须返回同一个对象；
- FastAPI 标准路由仍然没有启用。

对应冻结 JSON：

`docs/external_datasets/evidence/finqa_admitted_context_protocol_v1.json`

Python 模型负责验证 JSON 没有被随便扩大能力。比如把
`secondary_retrieval_calls` 从 0 改成 1，Literal 校验会失败。

### 3.2 核心 builder

文件：`app/external_datasets/finqa_admitted_context_v1.py`

第一步，`admitted_evidence_from_state_v1()` 遍历：

```python
state.evidence_by_aspect
```

只收集 `AdmittedEvidenceChunk`，按 `chunk_id` 去重和排序。同一 chunk ID 如果
对应不同快照则拒绝，因为这可能是身份混淆或并发错误。

第二步，`build_online_rule_skeleton_v1()` 只看问题中的运算意图。例如：

```text
What was the percentage change ...?
```

会生成：

```python
roles = (
    new_value(period_role="end"),
    old_value(period_role="start"),
)
operation = "PERCENT_CHANGE"
```

这里没有 `$100 million`、`$125 million`，也没有 candidate ID。skeleton 只表达
“需要什么角色、按什么运算组合”，所以叫 value-free skeleton。

第三步，builder 对每段 context 再调用当前版本的 Guard：

```python
active_guard.scan(text).disposition == "ADMIT"
```

为什么已经 ADMIT 还要复扫？因为 evidence 可能由旧 detector 产生，而 E18
绑定的是当前 Guard 源码。当前策略若收紧，旧快照不能自动穿过新边界。

第四步，调用：

```python
extract_numeric_candidates_v2(
    source_id=item.hit.doc_id,
    evidence_id=item.hit.chunk_id,
    text=item.hit.context_text,
    kind="text",
)
```

它把 `$100 million` 解析成带 Decimal、单位、scale、期间和 provenance span 的
`NumericCandidateV2`。E18 只保留 `role == "operand"`，年份标签、页码、序号等
不能作为运算数。

第五步，调用：

```python
build_retrievable_safe_descriptor_catalog_v3(...)
```

catalog 不把实际数值交给 descriptor selector，只提供经过清洗和 Guard 检查的
metric、period、source kind 和局部语义提示。E17 再把 question、skeleton、
catalog 做 canonical JSON SHA-256 绑定，避免后台取错输入。

## 4. 七种规则如何映射

| 问题意图 | operation | 第一个角色 | 第二个角色 |
| --- | --- | --- | --- |
| 百分比变化 | `PERCENT_CHANGE` | 新值/end | 旧值/start |
| 比例/占比 | `RATIO` | part | total |
| 差额 | `SUB` | comparison_left | comparison_right |
| 合计 | `ADD` | component | component |
| 乘积 | `MUL` | factor | factor |
| 相除 | `DIV` | value | divisor |
| 平均值 | `AVERAGE` | component | component |

规则支持中英文明确触发词，但故意不处理模糊、任意多步程序。完全没有财务数值
信号时返回 `NOT_FINANCIAL_NUMERIC`；有收入、年份等数值信号但无法形成受支持运算
时返回 `MISSING_TYPED_SKELETON`。这种区分让运维人员知道问题是“不属于能力范围”
还是“属于范围但 planner 还不会”。规则没把握时弃权，比猜一个运算再制造错误
shadow 样本更可靠。

## 5. 为什么这一步没有用 LLM planner

当前目标是先证明数据边界和生命周期正确，不是扩大语义覆盖。规则 planner 的
优点是：

- 0 模型调用，离线 CI 可运行；
- 同一个问题必定得到相同 skeleton；
- 没有 prompt injection 执行面；
- 可以精确知道支持哪七类，模糊问题明确弃权。

缺点是召回有限，换一种说法可能识别不到。后续可以增加 `ONLINE_MODEL` planner，
但它必须输出同一个严格 schema，并单独评测 skeleton accuracy；不能为了覆盖率
直接放宽到自由文本程序。

## 6. Coordinator 为什么必须先 register 再 offer

后台 worker 是并发线程。如果先：

```python
dark_observation.offer(request)
```

再：

```python
resolver.register(request_id, context)
```

worker 可能立即取到队列任务，然后 resolver 里还没有 context。这是典型竞态。
最终顺序固定为：

```python
resolver.register(...)
outcome = dark_observation.offer(...)
```

但先注册会带来另一个问题：offer 可能不接纳。因此必须按结果清理：

```text
ADMITTED       后台会 consume-once，不主动删除
SAMPLE_SKIPPED 立即 discard
UNAVAILABLE    立即 discard
BACKPRESSURE   立即 discard
CLOSED         立即 discard
DISABLED       默认关闭路径根本不做 preparation/register
```

这样 resolver 不会逐渐积累没人消费的用户问题和证据。

## 7. 重复 request ID 为什么最容易写错

假设请求 A 已注册 `request_id=123`。请求 B 错误复用 123：

```python
resolver.register("123", context_b)
```

resolver 会拒绝 B，不覆盖 A。此时如果 coordinator 遇到异常就无脑执行：

```python
resolver.discard("123")
```

删掉的其实是 A。这会把“防覆盖”变成“攻击者可以删除别人的待处理 context”。

最终代码只在“本次 register 已成功”后，才允许本次流程 discard。审计验证：

```text
duplicate outcome             UNAVAILABLE
new registration              false
discard                       false
original pending contexts     1
```

## 8. 主回答如何保证不受影响

`FinQATypedObservationResponseBuilderV1` 先执行 delegate：

```python
answer = self.delegate.build(...)
```

然后才尝试 observation，并把整个观察路径放在异常隔离中。最后：

```python
return answer
```

不是 `model_copy()`，不是修改 trace，而是返回同一个 Python 对象。测试同时断言：

```python
observed is answer
observed.model_dump(mode="json") == answer.model_dump(mode="json")
```

这证明 E18 失败不能把回答变成 500、改 mode 或偷偷增加公开 trace。

## 9. 审计结果怎么理解

```text
七种 family                   7/7
重复 context build           112/112 eligible
build p50/p95/max             0.623/0.921/1.523 ms
secondary retrieval calls    0
model calls                  0
E16 admitted/completed       8/8
default-off worker calls     0
response mismatch            0
public content findings      0
residual worker/context      0/0
full pytest                  3025 passed / 29 skipped
public repository audit      1350 candidates / 0 findings
```

`112/112 eligible` 不是 100% 答案正确率。它只说明为七种受控问题和同一段合成证据，
builder 都成功形成合法 typed context。

`p95 0.921 ms` 也不是生产 SLO。它是本机上 112 次 CPU builder 的机制测量，没有
网络、真实流量、完整 API、Ollama 推理和生产数据分布。

## 10. 这次遇到了什么问题

### 问题一：测试模型字段过期

第一轮是 `20 passed / 2 failed`。失败来自 fixture 仍传旧字段：

```text
answer_shape
constraints
started_at_ms
```

当前领域模型已经要求 `original_question/search_queries/top_k`。这不是业务代码 bug，
但测试必须使用真实 schema，不能用裸 dict 绕过。修正 fixture 后 22 个聚焦测试通过。

### 问题二：第一版审计没真正制造 BACKPRESSURE

第一版 19 个 gate 全绿，但协议声称会清理 backpressure context，审计只间接依赖
已有测试，没有在 E18 运行中制造队列满载。随后加入阻塞 provider 和容量为 1 的
队列：

```text
request 1 -> ADMITTED，worker 中阻塞
request 2 -> ADMITTED，队列等待
request 3 -> BACKPRESSURE，context 立即 discard
release   -> 前两项各完成一次
close     -> 0 worker / 0 context
```

这就是为什么“测试全部绿”之后还要检查测试是否真的覆盖了协议声明。

## 11. 为什么还没有直接改 `/agent/v2/chat`

E16 的公开证据把 `app/main.py`、`app/config.py`、`app/runtime/resources.py` 等文件
绑定到精确 SHA-256。直接修改会让 E16 历史证据测试失败。那不代表永远不能改，
而是必须创建下一版 serving assembly，并生成新的 route-level paired evidence，
不能悄悄覆盖旧证据。

所以 E18 当前状态是：

```text
组件可注入、可测试、生命周期完整
标准 FastAPI container 尚未切换
默认 OFF
```

下一阶段应做 E19：版本化服务接线，比较 OFF 与 LOCAL_TEST_ONLY 的真实 API response
bytes、feedback receipt、trace/metrics 和关闭行为，然后仍保持 E11 不参与用户回答。

## 12. 面试可能追问

### Q1：为什么不是把证据放进消息队列？

当前是本地单进程、短 TTL、best-effort shadow，内存 consume-once resolver 更小且
不会持久化敏感内容。生产多实例时应替换为有租户隔离、加密、TTL、幂等和删除
审计的队列/存储，但不能在本地项目中假装已经有分布式能力。

### Q2：为什么 Guard 不是只扫一次？

第一次扫描保护主 Agent；E18 复扫把 typed catalog 绑定到当前 Guard 版本，防止旧
快照或不同 detector 版本绕过新策略。代价是少量 CPU，当前有明确预算和测量。

### Q3：E18 提升答案正确率了吗？

没有直接证据。E18 提升的是可安全观察能力：终于能把真实已授权 evidence 送入
E8/E11 shadow。只有 E19 接入真实服务数据流并积累内部 paired observations，后续
才有资格研究 E11 是否在某些 cohort 上比 E8 更好。

### Q4：为什么规则 planner 不是 Agent 技术倒退？

Agent 的安全/控制边界应由确定性代码负责。规则只覆盖高置信运算类型，模型以后
可以作为受约束候选生成器加入，但输出仍必须通过 typed validator。混合架构比让
模型自由生成程序更容易复现、回归和解释。

### Q5：工业化价值在哪里？

价值不在“组件数量”，而在四个可落地不变量：不跨 ACL 重新检索、后台失败不改
主回答、队列拒绝不留敏感 context、历史证据不被静默重写。这些是模型实验进入
真实服务前必须解决的 correctness 和治理问题。

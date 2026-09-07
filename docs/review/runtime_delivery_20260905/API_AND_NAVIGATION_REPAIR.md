# 真实 API、引用误拒与导航绑定修复

状态：本地实施与验证，不代表整个 RC0-RC7 完成，也未推送 GitHub。

## 1. 为什么检索有结果，最终仍然回答不完整

本次复现问题是“当前制度每周最多允许远程办公几天？”。模型实际输出了
“当前制度规定每周最多远程办公 3 天。”，并引用正确来源。
但原文片段在句子前有独立一行“制度要点”。校验器原先按标点分割，
将标题与正文视为同一完整单元，所以判定生成句子不等于完整原文。

失效位置是 `VERIFIER_FALSE_REJECTION`，不是没有召回、不是模型改错数字。
不能因为最终回答降级，就直接增加 Top-K 或换模型。

`app/agent/citation_verifier.py` 的 `_exact_supporting_spans` 现在只允许略过
明确中性标签（制度要点、制度要求、Policy details）所在的一行。
普通换行仍不构成句子边界，作用范围、授权要求、否定和条件不能随意截掉。
返回的 quote/start/end 对应实际 admitted source 字段，而非重新拼接的文本。
这是一项明确有限的兼容规则，不是通用文档标题识别器或语义蕴含模型。

新增测试涵盖 CRLF、空白、精确字符偏移，以及含经理授权的中文/英文反例。
测试初期还修正了测试自身的偏移参照：领域模型会规范化字段，偏移必须
对照 `evidence.hit` 的实际值，不能对照构造前未经规范化的字符串。
引用、生成相关 66 项测试通过；随后完整检查点为 3572 passed。

## 2. 真实模型验证的失败也保留

所有 smoke 原始结果、身份文件和完整模型输出只在 D 盘 `.private` 下保存。
不把 JWT、反馈凭据和原始私有响应放进公共证据。

| 运行 | 观察 | 判断 |
|---|---|---|
| v1 | 未等异步 readiness，业务返回 503 | 测试启动顺序问题 |
| v2 | 正常问题降级，后续请求 readiness 503 | 继续定位，不作为成功 |
| v3 | 拆分启动推理与周期身份探测后，正常与恶意请求均可响应，正常问题仍 partial | 可用性与答案支持是两个问题 |
| v4 | 要求模型逐字引用，仍 partial | 仅改 prompt 无效，负结果保留 |
| v5 | 新诊断代码错用 citation.reason 导致 system | 代码回归，已改用 unsupported_reason；不算成功 |
| v6 | 正常问题 answered，精确支持；无身份 401；恶意请求 unsafe 且零工具调用 | 原始问题真实 API 复现通过 |

v6 命令：

```powershell
& '.\.private\reranker_cuda_env\Scripts\python.exe' -X utf8 -B -m scripts.smoke_runtime_api --output .private/runtime_delivery/api_smoke_v6
```

v6 正常请求 13.413 秒，单次观测，不是 p95，不是性能提升结论。
启动计时 32.784 秒不包含其后的 readiness 等待；也不是完整冷启动 SLA。
精确支持区间为 matched_text `[68,87)`，引用版本 `hr_remote@2026`。
使用真实 RS256 JWT、本地 Ollama、真实 BGE GPU 重排和实际 FastAPI 路由；
TestClient 是进程内 ASGI 客户端，因此没有测量公网/反向代理传输。
同一开发问题反复诊断，不是新的独立测试集或准确率。

v6 私有 result.json SHA-256：
`9bb46a818b9a40c9578c691e74d26434417f737303e624f7eca92555f1d5a9ca`。

## 3. 已实现的服务资源约束

`app/serving.py` 在接收请求前预热共享 reranker，预热失败则启动失败。
`app/runtime/serving_resources.py` 先完成原有真实模型能力探测，后续周期
readiness 只核对所需模型的 digest，避免每几秒生成一次文本与业务争用 GPU。
模型消失或身份变化仍失败，不能自动把新模型视为已验证。

`app/agent/generation_v2.py` 默认真实生成最多 1024 输出 token。
运行器把模型请求纳入 Agent 的剩余时间预算；这不意味着能够取消已启动的
同步 GPU kernel。超时之后必须丢弃结果，不能伪称执行已被即时中断。

新增容量测试证明一个 scorer 的锁只允许一个推理请求进入，其他三个竞争者
会收到容量超时；推理异常释放锁，下一次不会永久死锁。
还验证超过 50 个候选在加载模型前拒绝，以及超时完成的重排不能发布证据。
9 项相关测试通过。这些是注入故障的机制测试，不是四并发 GPU 吞吐实测。

## 4. 为什么 open/find 还需要绑定检查

Guard 回答的是“这段检索内容是否含已知危险指令”，不是“它是不是当前版本”。
一段已经过期但没有注入的制度，也可能通过 Guard。

新增 `app/retrieval/navigation_binding.py`，由 `app/agent/tools_v2.py` 在
生产 `DocumentNavigator` 返回后、Guard 接纳前执行：

- 固定 registry 构造时的 snapshot 对象，不接受中途换成另一个对象。
- open 的 request、target、doc、source、section、完整限定前缀和 truncated
  必须与该快照及请求一致，并重新检查访问权限。
- find 的每个 preview 必须来自该快照对应 chunk 的预期片段，且属于请求文档、
  符合检索条件与权限；重复项、超额返回、错误结果状态被拒绝。
- 错误只返回安全错误对象，visible_count 为 0，不把陈旧正文带回用户。

红色基线出现 6 个真实断言失败，正常两项通过；实现后并扩展正常 chunk/parent、
截断、快照替换和跨租户复用测试，29 项导航与工具相关测试通过。

这个机制只适用于生产 DocumentNavigator；注入的测试 navigator 保留历史接口。
它是请求内的数据流约束，配合 runner 的激活版本发布检查，**不是跨进程传递
的签名证据证书**。序列化后单独验证 open/find provenance 仍不能借用此结论。
没有修改历史 RetrievedContentAdmission 的字节来伪称旧实验覆盖新实现。

## 5. 当前结果和剩余工作

RC6-B 的 800 条真实检索结果已完成，详见 RETRIEVAL_RESULTS.md。
新 serving replay 的 Recall@5 为 Dense 65.9167%、Raw20 72.25%、Raw50 74.25%。
这是已有 200 题上的检索比较，不能写成回答正确率。

尚未完成：40 场景、三配置、三次重复的真实服务评测；完整资源/并发测量；
解析覆盖与条件优化取舍；最终发布文档、CI、GitHub 和相关任务同步。
本次 API 复现及测试通过不能替代这些验收，也不能宣称默认服务已晋级。

本次最终完整回归：3588 passed、30 skipped、2 deselected，239.57 秒。
新增容量和导航测试已经包含在这个数字内，不能再把 9 或 29 相加。
公开扫描：1876 candidates / 0 findings；修改的 Python 文件通过 Ruff，
`git diff --check` 通过。完整回归 XML 的 SHA-256 记录在 EXECUTION.md。

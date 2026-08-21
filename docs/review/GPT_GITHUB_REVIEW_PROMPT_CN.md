# 给 GPT 的 GitHub 项目审核提示词

你现在作为 Staff AI Engineer、Agent Runtime Engineer、RAG Evaluation
Engineer、Security Reviewer 和技术面试官，审核下面这个公开项目。请直接
读取 GitHub，不要只根据我粘贴的描述评价。

## 审核对象

- Repository：`godofxuan/Attempt-of-enterprise-rag-copilot`
- 指定分支：`codex/durable-agent-runtime-and-policy-v1`
- 精确提交：`e848d8e6090267b28d351758fe8d3cb557dcd586`
- 分支地址：<https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/codex/durable-agent-runtime-and-policy-v1>
- 精确提交：<https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/commit/e848d8e6090267b28d351758fe8d3cb557dcd586>
- CI 证据：<https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/32470591376>
- 证据包入口：<https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/blob/codex/durable-agent-runtime-and-policy-v1/docs/review/FINAL_REVIEW_PACKET.md>

注意：目标内容当前在指定分支，不要错误地只查看 `main`。如果你无法访问
仓库、分支、提交、Actions 或 raw 文件，请明确列出无法访问的 URL，并停止
对相应内容作事实判断，不要凭 README 或我的描述猜测已经实现。

## 审核方法

1. 先确认指定实现提交真实存在、当前分支包含该提交，并确认 CI run 的
   `head_sha` 等于指定实现提交。分支可能在实现提交后增加纯文档证据包，
   因此不要错误要求移动中的分支 HEAD 必须等于实现 SHA。
2. 按 `docs/review/FINAL_REVIEW_PACKET.md` 的顺序阅读，但不要把它当作
   自证结论；继续抽查实际源码、测试和 CI。
3. 重点检查：
   - `app/agent_runtime/durable_orchestrator.py`
   - `app/agent_runtime/tool_policy.py`
   - `app/agent_runtime/tool_gateway.py`
   - `app/agent_runtime/side_effects.py`
   - `app/agent_runtime/telemetry.py`
   - `app/agent_runtime/harness_contract.py`
   - 对应的 `tests/agent_runtime/test_*.py`
   - `.github/workflows/ci.yml`
4. 验证以下不变量，而不是只数技术栈：
   - `DENY > ASK > ALLOW` 是否真实生效，未知工具是否 fail-closed；
   - 所有工具是否都经过统一 ToolGateway；
   - resume 是否重新检查 tenant、ACL、reviewer、role、policy、参数哈希、
     expiry、deadline 和 auth；
   - 历史审批是否可能覆盖当前 ACL DENY；
   - 副作用是否只能创建 DRAFT，是否可能直接授权；
   - 提交前崩溃、提交后重试和重复 resume 是否会制造重复副作用；
   - trace 是否使用真实 W3C context/Span Link，是否泄露 prompt、答案、
     证据、工具输出或凭据；
   - PostgreSQL job 是否调用真实 `PostgresSaver.setup()`，而不是 mock；
   - harness 是否允许调用者绕过身份、ACL、Guard 或 citation 路径。
5. 区分三类证据：
   - 外部数据集上的 retrieval/security 数字；
   - deterministic mechanism/failure-recovery 测试；
   - 尚未建立的 production traffic/SLO/HA 证据。
   不要把机制测试通过率写成模型准确率。
6. 核对所有简历数字和措辞是否能从
   `docs/handoffs/PROJECT_EVIDENCE_MAP.md` 追溯到代码、测试、artifact、
   SHA 和边界。
7. 查找文档与实现不一致、测试只验证自身实现、并发竞态、授权绕过、
   replay/resume 混淆、隐私泄漏和过度简历包装。

## 禁止建议

不要为了显得高级而默认建议增加更多 Agent、更多模型、GraphRAG、Redis、
Kafka、MCP 网络部署或新的框架。只有在你先用失败案例或测量证明当前瓶颈
确实需要它时，才能建议引入。

## 输出格式

请按以下顺序输出：

1. `ACCESS_VERIFICATION`：实际成功打开的分支、提交、CI 和关键文件。
2. `FINDINGS`：按 P0/P1/P2 排序，每项给出文件/行号、触发条件、影响和
   最小修复方案；没有问题要明确说没有。
3. `CLAIM_AUDIT`：逐项给出 SAFE / NEEDS_QUALIFIER / UNSAFE，并说明证据。
4. `TEST_AND_EVIDENCE_GAPS`：现有测试证明了什么、没有证明什么。
5. `INDUSTRIAL_VALUE`：哪些内容真正体现工程落地，哪些仍只是本地作品集。
6. `RESUME_RECOMMENDATION`：最多 3 条中文简历 bullet，每条保留数据集、
   分母、指标类型、SHA/CI 范围和必要限定词。
7. `NEXT_WORK`：最多 3 项，按“价值 / 成本 / 可验证性”排序；不要堆功能。
8. `FINAL_VERDICT`：是否适合提交 AI Agent/RAG 实习岗位，以及最可能被
   面试官追问的 5 个问题。

最后单独列出：

- 可以安全写进简历的数字；
- 禁止写进简历的数字或说法；
- 你是否认为应该继续开发，还是停止加功能并开始面试准备。

# 最后验证与证据边界

## 软件回归

实际最后一轮：**1432 passed、2 failed、9 skipped，共 1443 项**。退出码为 1，不写全绿。

范围为 tests/agent_v2、tests/retrieval、tests/api_v2、tests/security、tests/runtime、tests/ui、tests/ingestion，以及两份文档质量索引测试。不是重复整个历史 3973 项套件的成绩。

本轮最终保留的新行为回归 11 项全部通过。原始 RED 是 12 项中 6 failed / 6 passed，其中含后来撤回的中文提示断言；实验 GREEN 是新旧定向范围合计 26 passed。撤回功能的代码与断言保留于 rejected_guidance，不计入最终新增 11 项。

两项既有失败仍为：

1. tests/security/test_trusted_identity_evaluation.py::test_public_trusted_identity_result_recomputes_exactly
2. tests/runtime/test_dark_observation_evidence_v1.py::test_e16_public_evidence_binds_protocol_sources_and_implementation

它们比较历史公开证据与当前源码的绑定；app/config.py 在上轮切换模型后又产生了新的合法源码摘要，不能把旧摘要回填来伪造通过。当前实际身份矩阵行为测试通过，旧公开文件保持不变。这些失败仍保留在原始 JUnit 和日志中。

9 项原有跳过不能算通过，具体原因见原始 JUnit。本轮没有增加 skip/xfail 或修改原冻结测试。

最后运行前后 scoped Python 源码一致，实际导入绑定候选工作树。对保留的 question_parts.py 和新增测试文件执行 Ruff，通过。git diff --check 在交付前检查。

## 真实模型

两轮 OFF/ON 加一次选定 ON 确认，共 220 次请求，44 道不同的已消费开发题。所有运行保留逐题原始 JSON，包括实际搜索、合法候选、模型收到的证据、模型输入输出、最终 claims/citations/trace。

最后确认 40/40 要点＋引用检查、4/4 控制行为；40 道可答题包含 28 answered 与 12 partial。不能改写为独立人类准确率 100%。

最后只有 leave_remote 相比第一轮 Qwen3.5 ON 改变了最终回答：两条原句都输出，两份 exact_span 引用通过；其余 43 道最终回答与第一轮 ON 一致。该题的顾问调用减少一次，整批 chat 调用 54 -> 53。

最后代码相对本轮起点只保留 question_parts.py 与新增测试。生成端中文提示已撤回，其文件逐字节恢复为本轮起始版本。无引用校验放宽。

## 未执行

没有新的人类评分、外部独立测试、WixQA/FinanceBench 重测、并发服务压测、GitHub 推送、部署或简历分数修改。没有新模型下载、依赖安装、索引构建或切换、提示词 sweep。

运行命令及输出位于本轮证据目录。审核 ZIP 提供本轮 scoped 源码和原始证据，但不提供虚拟环境、模型权重、完整索引或测试临时身份文件。

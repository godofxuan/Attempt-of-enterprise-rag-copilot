# RAG Interview Guide

## 1. 这轮到底做了什么？

**回答：** 我没有继续堆 Agent 或框架，而是把项目改造成“实验先行”的工程系统。先固定 Git SHA、数据版本、模型 digest 和 artifact hash；再在同一 FinanceBench dev 协议下比较 BM25、Dense、RRF 和 Cross-Encoder；根据逐题失败分类决定是否做 parser 或 adaptive retrieval；最后用外部 garak 注入样本做 Guard OFF/ON 成对评测。

关键点不是“代码更多”，而是每个技术决策都有可复现的证据和停止条件。

## 2. 为什么 nDCG@5 和 MRR@5 比 Hit@5 更重要？

**回答：** Hit@5 只问“前 5 个结果里有没有正确页”，正确页排第 1 和第 5 都算 1。MRR@5 使用第一个正确页名次的倒数，第 1 名得 1，第 5 名得 0.2；nDCG@5 会按排名折损多个相关页的收益，并用理想排序归一化。Cross-Encoder 把 Hit@5 从 22/49 提到 23/49，但 nDCG 从 0.3525 降到 0.3472，说明它多救了一个样本，却整体没有把正确页排得更好。

## 3. 为什么不把 Cross-Encoder 合并？

**回答：** 它不在 Pareto 前沿。Dense 的 nDCG@5 是 0.3525、p95 533 ms；Cross-Encoder top-10 是 0.3472、p95 2466 ms。质量没有稳定提高，尾延迟约 4.63 倍。工业系统不能因为“用了 reranker”就接受更差的排序和更高成本，所以实现保留为可选实验，默认链路不启用。

## 4. 为什么 BM25 + Dense + RRF 反而比 Dense 差？

**回答：** RRF 不保证提升，它假设多个排序器能提供互补信号。这个 FinanceBench page-localization split 中，BM25 的 Page Hit@5 只有 14.3%，弱 lexical 排名通过 RRF 把 Dense 的好结果往后推，RRF 最终只有 28.6%。这说明融合权重和召回器价值必须用目标数据验证，不能把“Hybrid 通常更好”当定律。

## 5. 表格问题很多，为什么没上 Docling/MinerU？

**回答：** 26 个失败是 numeric/table 类型，但“问题涉及表格”不等于“表格解析失败”。进一步检查发现没有 gold page 缺失、没有低抽取召回案例，只有 1/31 出现确定性 parser-risk 信号，低于预注册的 20% 阈值。主要失败是 20 个 page-ranking miss。因此直接换 parser 不能针对当前主要根因，还会增加 ingestion 和索引兼容成本。

## 6. Adaptive retrieval 为什么没有默认打开？

**回答：** 我做了逐题救援/回退分析。Cross-Encoder 路径能救回 4 个 Dense miss，但也让 3 个原本正确的案例失败。只有在看过标签后选择分支，才有 26/49 的 oracle 上界；真实运行时没有可靠 selector。为了避免多一次检索、token 和 p95 成本却不稳定提升，rewrite/retry 默认关闭。

## 7. garak 评测怎样保证公平？

**回答：** 两个 arm 固定同一 fixture、Qwen3-8B digest、temperature 0、system prompt、retrieved content 和顺序策略，只切换 Guard。执行顺序按 case 交替，降低先后顺序偏差；网络边界只允许 `127.0.0.1:11434` 的本地 Ollama。Guard OFF/ON 的攻击触发和上下文暴露由确定性规则统计，不用另一个 LLM 判分。

## 8. 为什么说 holdout 是独立的，但又不是强独立？

**回答：** 开发集用了 context 0/3、payload 0/3、trigger 0；修复前先提交 holdout，固定 context 1/2、payload 1/4、trigger 1，所以组合没有重叠，且结果在修复时不可见。但三种 injection instruction 和 probe family 相同，因此它只是 combination-disjoint，不是 probe-family-disjoint。12 个攻击和 2 个良性样本也比较小，不能宣称覆盖全部 garak。

## 9. Guard 是 LLM classifier 吗？为什么不用 LLM？

**回答：** 不是。它是版本化、确定性、有界资源的 content admission policy。规则只输出内容无关的 rule ID/category，不把恶意原文写进 trace；异常时 fail closed。优点是可复现、低延迟、不会因为 judge 模型漂移改变生产放行。缺点是规则覆盖有限，所以要持续用外部攻击集找漏检，同时用 benign controls 监控误报。LLM judge 可以做离线语义补充，但不应成为唯一安全边界。

## 10. 33.3% 到 0% 能直接写简历吗？

**回答：** 可以，但必须连同范围写：NVIDIA garak 的一个 `LatentInjectionReport` 组合隔离子集、12 条攻击、本地 Qwen3-8B。不能写“安全率 100%”或“garak ASR 0%”。良性结果必须说 `0/2`，不能用小分母宣称普遍 0% FPR。

## 11. 为什么 FinQA 检索召回 93.5%，答案正确率只有 44%？

**回答：** Retrieval recall 只说明 gold evidence 大多进入上下文，不保证模型正确理解表格、选择运算、生成可执行程序并给出正确数值。即使直接给 gold evidence，oracle strict 也只有 52%，说明主要瓶颈已经部分转到 reasoning/program execution。Hybrid 比 oracle 低 8 个百分点，代表 retrieval/citation 仍有损失，但不能把全部 56% 错误都归因于检索。

## 12. 如果面试官问“为什么没做最终 FinanceBench 提升”？

**回答：** 因为 dev 上没有候选同时改善 nDCG 和延迟，继续跑历史已见 test 只会增加 test-set tuning 风险。我选择公开负结果和停止条件，而不是跨 split 拼漂亮数字。下一步需要新的独立 page-level financial QA holdout，或训练/选择与 financial page ranking 更匹配的 reranker，然后只做一次冻结评测。

## 13. 项目现在真正工业化的地方是什么？

**回答：** ACL、可信身份边界、retrieved-content admission、grounding gate 和 evidence ledger 形成数据与安全边界；实验侧有 immutable fixture、exact SHA、model digest、artifact hash、paired control、failure taxonomy 和 negative-result registry。工业化不是组件多，而是上线默认值有证据、失败可追踪、敏感内容不进公开 trace、结论能被第三方复核。

## 14. 你会怎么继续？

**回答：** 不再加框架。项目后来接入了外部 UDA-QA FinHybrid，并按公司隔离为 64 题 dev 和 96 题固定 test。Dense 在 dev 被选中后只运行了一次 test，因此这 96 题现在也已经消费，不能继续用于选择 reranker 或调参数。若继续质量优化，必须再建立新的未消费数据；安全侧则需要 probe-family-disjoint 攻击集和更多 benign 文档。没有新数据就停止调参。

## 15. 修改 Guard 后为什么一度有 166 个失败/错误？

**回答：** 不是 166 个业务 bug，而是同一个 provenance 不变量被安全升级触发。历史 live run 使用旧 Guard，当前 replay 使用新 Guard；旧 schema 错误要求两者 hash 永远相等，导致依赖它的 fixture 级联失败。我没有重写历史 evidence，而是把 source provenance 与 replay provenance 分开，并仅对已知 historical manifest 接受其旧 verifier。当时全量结果为 `3056 passed / 30 skipped`；加入 UDA 外部评测后，当前全量为 `3069 passed / 30 skipped`。这说明 hash 绑定不仅能防篡改，也必须支持显式版本演进。

## 16. 为什么选择 UDA-QA FinHybrid？

**回答：** FinanceBench 的失败分析指向“已找到正确报告，但正确页面没有排进 Top-5”。UDA-QA FinHybrid 使用真实金融年报 PDF，问题带有来源页，并且文本和表格混合，正好可以独立验证页定位。它由外部团队构建、采用 CC-BY-SA-4.0，并能固定 Git、Hugging Face revision 和文件 hash。实验按 UDA 原任务在已知报告内找页面，所以我只声称 page retrieval，不声称开放语料 document discovery。

## 17. 为什么 UDA dev 是 84.38%，test 只有 73.96%？

**回答：** dev 和 test 按公司完全隔离，报告和问题都不重叠。Dense 是根据 dev nDCG@5 选择的，因此 dev 本来就包含选择偏差；固定 test 下降 10.42 个百分点是正常的泛化回落，也是冻结 test 的意义。如果只写 84.38%，就是把调参集结果冒充最终效果。简历必须写 96 题 test 的 73.96% Hit@5，并说明这是已知报告内页检索。

## 18. 为什么不根据 UDA test 的 25 个失败继续修？

**回答：** 可以用失败做诊断，但不能再用同一 test 选择方案并声称它仍是独立评测。25 个失败中，7 个候选页与 gold 相邻，10 个相距超过 10 页，说明同时存在页边界和语义排序问题；这只能形成下一轮假设。真正修改 parser、chunk 或 reranker，需要新的 dev 数据，并在另一个未消费 test 上验证。当前 one-shot marker 已把这次 test 状态锁为 `COMPLETED`，重复运行会被拒绝。

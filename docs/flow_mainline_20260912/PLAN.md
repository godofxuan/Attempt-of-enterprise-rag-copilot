# 有界任务与证据闭环实施记录

日期：2026-09-12。状态：有限实施与验证完成，模型建议不晋级，候选版未合并发布。结果见REPORT.md。

用户批准实施开源对照方案并检查操作问题。本轮在既有候选工作区继续，不覆盖main或旧开发树；上一轮未提交修复先单独冻结。本轮不新增框架、排序模型或放宽身份、来源、版本、Guard及引用标准。

## 固定工作项

- [x] S0：冻结实际起点，保留上一轮未提交修改；运行限定基线与新增RED。
- [x] S1：共享诉求、搜索尝试、证据、阅读范围及答案覆盖状态；接入实际runner/controller/generation。
- [x] S2：复用章节/父块实现跨领域有界补读；防止补读被普通搜索结果挤出packet；保留结构与权限。
- [x] S3：现有本地模型的一次结构化规划与一次缺项建议，主机约束与失败回退，默认不提前启用。
- [x] S4：逐诉求生成及发布一致性；固定12场景真实模型对照已运行。自动要点检查不代替真人语义验收。
- [x] S5：demo身份续签、启动检查和错误提示已实现；实际API/UI检查已运行，仍有一项问答partial限制。
- [x] S6：最终1387 passed / 2历史绑定failed / 9既有skipped；交付原始证据与补丁，模型建议默认关闭。未宣称全绿发布。

## 验证原则

先保留新行为的RED再修改。不改变冻结样本和历史失败。已消费WixQA只作历史参考，本轮不重跑排序benchmark，也不把条件覆盖称为Recall提升。

规则/结构与模型分开比较。模型仅提出建议，不授予工具权限，不改变原问题、过滤器或排序配置；新增诉求不能删除原诉求。每项结果保留依据，模型自评不等于正确证明。

主机总预算继续生效。所有运行、缓存与证据放D盘；不调用付费模型，不下载模型或新依赖。若现有Ollama不可用，记录真实阻断，而非伪造收益。语义人审不能用另一个模型冒充。

合并代码、默认启用和GitHub发布分别决策。本轮用户授权实施，不自动覆盖main既有改动。未完成平台CI核验时不宣称已发布全绿版本。

## 参考模式

- LlamaIndex：子问题查询与合成，https://developers.llamaindex.ai/python/examples/query_engine/sub_question_query_engine/
- Haystack：来源/位置绑定的邻接阅读，https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/sentence_window_retriever.py
- Dify：子块定位与父级上下文，https://dify.ai/blog/introducing-parent-child-retrieval-for-enhanced-knowledge
- RAGFlow：结构解析先于检索，https://github.com/infiniflow/ragflow/blob/main/deepdoc/README.md
- LangGraph：状态及模型相关性建议驱动条件分支，https://docs.langchain.com/oss/python/langgraph/agentic-rag

以上支持设计来源，不证明本地收益，也不证明对方具备我们的全部发布契约。

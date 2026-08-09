# Enterprise RAG Interview Update

下面问题按“结论 -> 证据 -> 边界”回答。面试时不要只背数字，要能指出源码、测试和为什么这样设计。

## 1. 这个项目是什么？

它是 Enterprise Knowledge RAG / bounded Agent Copilot，不是通用自主 Agent。系统处理混合企业知识、ACL、版本、检索内容注入、证据完整性和引用；Python host 控制工具、预算、权限和最终 claim，模型只提供 embedding 或候选文本。入口见 `docs/architecture.md`。

## 2. 为什么 Dense 可能比 BM25 好？

BM25 看词面，Dense 看语义。客服问题常用同义改写，WixQA ExpertWritten 上 BGE-M3 Dense Recall@5 66.42%，BM25 42.75%。但编号、专名、原词检索仍可能 BM25 更稳，所以不能在所有场景直接删除 BM25。

## 3. 为什么 RRF 反而变差？

RRF 融合排名，不判断哪一路更可靠。该数据集 BM25 明显弱于 Dense，等权融合把弱排序放进 top-5，Recall@5 从 Dense 66.42% 降到 59.25%，p95 从 157.4 ms 升到 304.6 ms。结论是等权 RRF 被拒绝，不是所有融合都无效。

## 4. 为什么保留 rejected experiment？

它防止团队重复走同一路，也证明选择来自实验而不是技术偏好。`docs/enterprise_eval/NEGATIVE_RESULTS.md` 保存 RRF、Agent 和其他负面结果；简历可强调决策纪律，但不能把失败数字包装成提升。

## 5. 什么叫 bounded Agent？

工具集合、参数 schema、search/find/open 次数、总步骤、上下文字符和 deadline 都由 host 限制；Controller 只能进入显式 terminal state。它不是让 LLM 自由生成 plan 或无限循环。源码是 `app/agent/controller_v2.py` 和 `app/domain/agent.py`。

## 6. Agent 类存在为什么不等于 Agent 有效果？

机制通过只说明状态机和工具链运行。旧 WixQA Agent 每题 search=1、find/open=0、检索 recall 不变、multi-article citation complete=0，所以外部效果被拒绝。必须比较同 retriever 的 control/candidate，不能统计“有多少题返回 answered”冒充质量。

## 7. 你如何证明 Agent 真的运行了？

Runner trace 记录每一步 tool、status、latency、预算计数、evidence coverage 和 stop reason；评测还从 Navigator 记录真实 search ranking。`scripts/eval_wixqa_agent.py` 经过真实 `V2AgentRunner -> ToolRegistry -> Guard -> Controller`，不是给结果加一个 agent 标签。

## 8. search、find、open 分别做什么？

search 跨可见语料召回候选；find 在一个已授权文档中定位 pattern；open 读取一个已可见 target 的更多上下文。三者都走 typed request 和 Guard。当前默认 Controller 通常按 aspect search，completeness 可 conditional open，find 不默认选择。

## 9. 为什么 multi-document 问题难？

命中一篇不等于收集齐所有流程、比较或冲突证据。Recall 可以按 gold 比例得分，而 completeness 少一篇就为 0。EnterpriseRAG project-related 和 completeness 类暴露了这一问题。

## 10. RequiredAspect 是什么？

它把问题的必须证据拆成可追踪单元，每个 aspect 有查询、证据和 satisfied/missing 状态。不能为了数量盲拆：WixQA 27 条多文章题多数没有明确 A/B 子句，规则硬拆会生成伪 aspect。

## 11. Evidence completeness 为什么不等于 answer correctness？

证据齐只说明输入具备支持答案的材料。模型仍可能算错、漏掉条件、错误归因。WixQA Agent 本轮没有 gold answer semantic metric，所以不能从 citation completeness 推断 answer accuracy。

## 12. 为什么 60.37% 不是系统 accuracy？

它是 EnterpriseRAG 470 个 document-grounded 问题的 macro document Recall@5：前五文档覆盖多少 gold。它没有评价生成答案、引用语义、拒答或业务任务成功。

## 13. 为什么 99.5% answered 不是 correctness？

answered 只表示 Controller 走到了回答状态。错误答案也能 answered。WixQA 旧 Agent 99.5%-100% answered，但多文章引用完整率是 0%，answer correctness 又未测。

## 14. 什么叫 public-label fixed benchmark？

标签公开，但在运行前冻结协议、参数和消费状态，正式结果后不再用它选候选。它比随意 test 调参可信，但不是 blind/hidden holdout。

## 15. 什么叫 consumed benchmark？

只要看过结果、标签或逐题错误，它就被消费。之后可做 retrospective development/regression，不能再称独立验证。本轮 Simulated 27 题明确标为 already observed。

## 16. blind holdout 和 validation 有什么区别？

validation 可用于有限选择；blind holdout 在开发中不可见，冻结系统后一次性揭盲。没有独立保管或隐藏标签，就不能靠改文件名制造 blind test。

## 17. 511,962 corpus 怎么做到可恢复索引？

FTS5 builder 用 bounded batch checkpoint，绑定 corpus/manifest hash；在 staging 完成数据库完整性、行数、artifact hash 和 ordered-record hash 校验后，才提升 immutable version 并原子替换 active pointer。

## 18. 为什么用 SQLite FTS5，不直接 Elasticsearch？

瓶颈是单机 Python BM25 36.60 GiB 内存，不是缺少分布式集群。FTS5 是仓库已有边界内最小可验证解法，最终约 1.83 GiB peak。若真实业务需要多机分片、在线写入、HA 和复杂运维，再评估 Elasticsearch/OpenSearch。

## 19. 什么时候需要 vector DB？

当向量规模、在线增量、过滤、并发、复制或运维需求超过 mmap/FAISS 单机能力时。不能为了简历技术栈先换库；本项目 full Dense 连质量协议和 resumable shard 都未通过，换库不会自动产生可信收益。

## 20. Dense capacity 怎么测的？

同 BGE-M3、1024 维 float32、1800/150 chunks，按 corpus 规范顺序累计实测 1k/10k/50k：35.74/35.93/36.76 chunks/s。50k 速度投影全量 12.87 小时。它是容量测量，不是 Dense retrieval quality。

## 21. 为什么不用 LangGraph？

当前问题是证据选择和评测，不是缺少图编排。已有 Controller 能表达 bounded states，换框架会增加依赖和迁移风险，却不改变 recall/precision。只有状态图复杂到现实现无法安全维护时才有理由引入。

## 22. 为什么不用 GraphRAG？

目前没有证据证明实体关系图是主要瓶颈。EnterpriseRAG 最大失败是 semantic zero-recall，先需要验证 Dense；Graph 构建还会引入抽取正确性、更新和权限传播问题。

## 23. ACL 在哪里执行？

身份 token 先变成 server-derived Principal/UserContext；retrieval pipeline 在融合、parent context、Agent state 和 citation output 前过滤 tenant/region/group。测试见 `tests/retrieval/test_pipeline_acl.py`。

## 24. Dense ANN 是真正 physical pre-filter 吗？

不能这样说。当前路径可先做 global FAISS candidate search，再执行 visible filtering。能证明的是不可见候选不能进入 prompt/evidence/citation，不是每租户物理向量分区。

## 25. Retrieved-content Guard 防什么？

防知识库文档中的间接 prompt injection、角色/系统指令伪装、secret/egress/tool 信号、编码和相邻切分逃逸；只把 admitted snapshot 交给 Controller，并输出 aggregate security trace。

## 26. 0/12 ASR 能证明安全吗？

不能。它证明在固定 Qwen3-8B、固定 prompt、固定 12 个 garak attack 和相同 retrieval 下，Guard ON 没有观察到成功。样本小、probe family 窄、benign 只有 2 个，不能说 100% safe。

## 27. citation negation bug 是什么？

旧规则把没有显式否定的肯定句 polarity 当 0，导致“X is 10”和“X is not 10”无法触发 mismatch。修复后对相关 evidence 句比较显式否定，并要求数字/日期对齐，避免无关负面句误伤。

## 28. 如果再给一周，只做什么？

没有新独立数据时停止 feature development，完善演示、源码学习和面试。如果能获得真正未消费的企业验收集，再做 selective multi-source evidence policy；只有它保持 precision 且 fresh validation 达标，才重新讨论 Agent promotion。Full Dense 还需 resumable shard builder 和独立 quality protocol。

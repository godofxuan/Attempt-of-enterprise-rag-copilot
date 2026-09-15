# 2026-09-12：审查后有限修复记录

本轮承接 [流程审查](../flow_review_20260912/REPORT.md)，用户确认“继续”后实施。不是新模型或检索排序实验。

## 1. 修改位置与版本

- 实际修改工作区：`LOCAL_PATH_REDACTED`。
- 分支：`codex/local-closeout-20260910`。
- 起始 HEAD：`152981aba3bc9a15a1035dbfa53dc57651b3c97f`，开始时该工作区干净。
- 代码在该候选工作区以未提交修改保存；没有修改 main 的生产源码，没有覆盖 b07c03d 旧工作树。
- 未 commit、push、merge、部署、切换索引或重启演示服务。因此正在运行的旧 Python 进程不一定已加载新代码；GitHub 仍不是本次修复后的源码。

## 2. 本轮做了什么

### 2.1 search 与 open 使用一致的冲突材料

原问题：search 写入 evidence_by_aspect，open 写入 open_results；账本只检查前者，模型却能看到两者。模型看到7天和30天时，host 仍可能认为没有冲突。

修改：`app/agent/evidence_ledger.py` 新增 `evidence_view` 和 `with_open_evidence`，在保留原有准入类型、anchor、文档身份和 open citation ID 的前提下，把 open 内容纳入有限数值冲突检查。没有伪造 SearchHit 或 Guard 的 ADMIT 结论。

接线：`controller_v2.py` 重建账本时传入 open_results；`runner_v2.py::build_conflict_response` 也用相同来源集合，保留 open/source 类型及合法引用。

结果：固定7天/30天案例由 host 提前返回 partial，正文说明潜在不一致，双方材料保留有效引用，generation_attempts=0。不多调用一次 LLM 来满足旧测试前提。

限制：仍是原有同模板、可比较范围的有限数值冲突检测，不是通用逻辑矛盾识别器。没有扩大权限、放宽版本治理或建立制度优先级裁决。

### 2.2 显式多问句的遗漏校验

新增：`app/agent/question_parts.py`。只对原问题中明确分隔且带疑问词的多个片段做有限必要条件检查，最多检查8项。它不会改写 question，不会替换 search query，也没有新增 LLM 调用。

接线：`generation_v2.py::_apply_question_parts` 只检查已有引用支持的 claims。发现未回答的明确问题时，保留已有合法答案和引用，在正文及 warnings 说明缺项，同时同步 mode、stop_reason、final_mode 和 question_part_coverage。

结果：“入职需要哪些材料，试用期多久？”只答身份证时返回 partial；“试用期按规定执行”不能覆盖“多久”；身份证和三个月都回答时仍可 answered。实际 FastAPI/JWT/索引测试入口也验证了这两种状态。

限制：这是中文显式问句的遗漏保护，不是 LLM 语义理解。隐含诉求、复杂跨句指代、通用同义表达仍没有解决。字面条件通过不等于语义充分性已得到证明，trace 明确标记 necessary_checks_not_semantic_proof。

### 2.3 同章节定位，避免要求续句重复“报销”

修改：`FindRequest` 新增默认兼容的 `match_mode`，原默认 text 行为保留。自动 focused read 使用 anchor_section，必须同时提供 anchor 和 filters。

`navigation.py` 使用同一 snapshot 中 anchor 的精确 section_path 定位候选；`navigation_binding.py` 也独立使用同一纯匹配规则核验返回值。原 ACL、tenant、policy、region、version、temporal、indexable 和 Guard 路径仍执行。

结果：“报销需要发票”后面不重复主题词的“还需提供行程单”可以进入候选与实际 evidence packet；固定模型若漏答行程单，结果为 partial。相邻不同章节、不同租户、不同 ACL、过期/错误版本等不得借此进入上下文。

预算没有增加：仍最多一次 focused find、最多两次 focused open、最多20个 find 结果，继续受原步骤与字符预算约束。不是整份文档无限展开，也没有新检索/embedding/reranker 调用。

限制：当前 focused 路径的触发仍主要是已有报销 need 合同。它不是全领域自动章节规划器；优先第一个合法命中文档，精确章节元数据质量会影响收益。

### 2.4 未读完不能直接当作已列全

修改：`generation_v2.py` 对明确“所有/全部”且属于 completeness 的通用要求列表，结合实际 packet 中的 requirement units、回答中的条款、截断/丢弃信息判断能否称为完整。

另外，同章节 find 找到但未实际读取的片段，不能因为 preview 里没有识别到材料词，就当作不存在附加要求。会记录 incomplete_read 并在正文说明限制。

结果：长文档前部登记要求、后部安全培训的探针不再只答登记就 answered；短文本确实全部回答的正向控制仍 answered。

取舍：同章节存在未读片段时，partial 可能增多，即使其中有些只是背景。不能宣称所有 partial 都是业务确有缺项；本轮选择不对未检查内容作完整性承诺。后续若提高完整回答产出，必须同时测过度 partial，不能简单删除这道检查。

## 3. 实施中发现的额外问题

### 3.1 多诉求中的部分相关材料被丢弃

新增“年假怎么申请，有效期多久？”控制时，原链路就会把“年假需要提交申请”判成不相关并返回 not_found，而非漏答 answered。

开始怀疑“提交申请”被合并分词；实际查看分词后证伪：提交和申请分开，而年假被拆成年/假，整问句的多词重合门槛使只支持一问的证据被丢掉。

有限修正：`evidence_relevance.py` 在原有完整问题的 scope/year 检查之后，允许原文明确的“主体+怎么/如何+动作”在同一证据句中建立该部分的字面相关性。没有改 BM25 tokenization、embedding、reranker 或 candidate pool。

反例同时验证：只有“年假”主题、只有另一业务的“提交申请”、没有所问2027年信息，都不能靠此路径通过。

这只表示材料与其中一问相关，不能说明另一问有证据。后续 question_part_coverage 仍要求把未答诉求显示出来。

### 3.2 我写的测试启动器存在 Windows spawn 问题

第一次扩大运行得到843 passed、1 failed。失败是子进程重复执行 run_fix.py 顶层入口，试图创建已存在的运行证据目录，出现 FileExistsError；不是索引产品反例。

修正：添加 `if __name__ == '__main__'` 保护，子进程显式维持离线边界。保留 HARNESS_V1.py、失败日志和 JUnit，单独重跑原跨进程测试通过，再重新运行限定套件。

## 4. 实际验证口径

| 运行 | 通过 | 失败 | 含义 |
| --- | ---: | ---: | --- |
| red_original | 2 | 4 | 修改生产代码前重现原六条诊断 |
| red_regressions | 11 | 7 | 首批18条新增回归；含原先就 not_found 的年假探针及新 trace 尚不存在 |
| ledger_v1 | 22 | 0 | 冲突接线及相邻账本/runner 回归 |
| regression_v1 | 79 | 1 | 保留年假部分证据问题，未改桩或放宽断言 |
| red_part_relevance | 7 | 1 | 对部分相关材料问题建立组件 RED |
| regression_v2 | 96 | 0 | 多问句、补读与原报销回归 |
| section_and_api_v1 | 4 | 1 | 原 FastAPI 正反控制通过，额外发现未读片段误当完整 |
| original_after | 5 | 1 | 原测试逐字保留，剩余为必须调用模型的旧前提 |
| scoped_full_v1 | 843 | 1 | 测试启动器 spawn 故障，真实失败保留 |
| spawn_recheck | 1 | 0 | 修正启动器后原跨进程测试通过 |
| scoped_full_final | 844 | 0 | 扩大后的限定离线套件通过 |
| verified_final | 844 | 0 | 最终源码版本的限定回归，0 errors、0 skipped |

最终代码做了局部换行整理后再次验证；以 `verified_final/RESULT.json` 和本次交付清单为最终源码绑定。不要累计多轮重复运行成“几千条独立样本”。

最终限定套件包含31条新增测试，其余是原有测试。涵盖 agent_v2、retrieval、api_v2，以及内容 Guard、准入、导航零泄漏、trace 零泄漏、ACL、JWT 等指定安全文件。真实 API 路由用进程内 TestClient；模型、embedding/reranker 服务使用既有固定桩，不是真实 Qwen 准确率评测。

### 原测试剩余失败如何解释

`test_all_requirements_open_numeric_conflict_is_not_completed` 的原断言要求30天进入 LLM packet。现在 packet 列表为空，因为 host 已在调用模型前检测到冲突。该 FAILED 仍保留。

替代证据是新增 `test_open_conflict_is_host_partial_with_bound_citations`：明确断言 partial、正文包含7天和30天、潜在不一致说明、有效双引用、open 来源类型、generation_attempts=0、packets=[]。同时 original_after 的 observation 保存真实最终 response。

这条可以精确分类为 LEGACY_PRECONDITION_MISMATCH；其他失败没有混入该分类，也没有通过额外调用模型满足旧测试。

## 5. 文件索引

- 生产修改：controller_v2.py、evidence_ledger.py、evidence_relevance.py、generation_v2.py、runner_v2.py、domain/queries.py、navigation.py、navigation_binding.py。
- 新增生产文件：[question_parts.py](D:/文档/agent/RAG_try/.private/release_candidate_20260910/app/agent/question_parts.py)。
- 新增回归：[runner 场景](D:/文档/agent/RAG_try/.private/release_candidate_20260910/tests/agent_v2/test_flow_review_followup.py)、[显式问句组件](D:/文档/agent/RAG_try/.private/release_candidate_20260910/tests/agent_v2/test_explicit_question_parts.py)、[章节导航](D:/文档/agent/RAG_try/.private/release_candidate_20260910/tests/retrieval/test_section_navigation.py)、[API 场景](D:/文档/agent/RAG_try/.private/release_candidate_20260910/tests/api_v2/test_flow_review_followup_api.py)。
- 全部运行记录：[flow_fix_20260912](D:/文档/agent/RAG_try/.private/flow_fix_20260912)。各目录含真实日志、JUnit、导入路径和源码前后摘要。
- 最终源码绑定测试：[verified_final/RESULT.json](D:/文档/agent/RAG_try/.private/flow_fix_20260912/verified_final/RESULT.json)。

## 6. 没做什么、还剩什么

没有重测 WixQA Recall/nDCG、FinanceBench、FinQA、真实模型 paired security 或人工答案评分。没有可用于简历的新增真实效果数字，也没有更新简历或推送教学对话。

本轮没有关闭报告中所有待办：demo token 的重新登录/刷新体验、远端 CI 失败日志、发布版本/README/profile 对齐、真实 PDF 表格解析质量核验，仍需分别收口。没有偷偷关闭认证、无限增加 token 寿命或改旧 CI 断言。

当前结果支持“有限反例已经修复并有回归保护”，不支持“通用语义充分性已解决”“任意长文档都能答全”或“已生产就绪”。下一步应验证真实模型下正确完整回答与过度 partial 的配对变化，再决定是否试一次有界 LLM 建议；不默认打开查询改写循环。

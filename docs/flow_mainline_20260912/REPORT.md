# 有界任务与证据闭环：实施、验证与决策

日期：2026-09-12。状态：候选版实现和有限验证完成；LLM建议不晋级；尚未合并或发布。

## 先看结果

本轮不是再增加一个Agent或替换检索平台。主要改为：同一份用户诉求贯穿控制、证据和答案；搜索过不再等同于答完整；先读同章节和命中窗口，再考虑一次模型建议的补查。权限、版本、Guard和引用验证保持原边界。

固定12个开发场景、同一个本地模型的配对检查中，满足全部预设要点且有通过系统校验引用的回答从6个增加到8个。进一步发现并修正模型输入的Unicode转义问题后，规划结果由0/11通过主机验证变为10/11；回答仍为8个，调用和延迟增加，所以默认不启用。此处是受控检索的真实模型生成实验，不是WixQA、独立测试集或人工语义准确率。

最终限定回归：1387 passed / 2 failed / 9 skipped，共1398项。2个失败均为历史公开证据要求源码哈希完全相同；原始FAILED保留，不能称全套全绿。当前身份业务矩阵另行重算20/20通过。新增33项回归全部通过。

## 1. 真实修改位置

- 候选工作区：`LOCAL_PATH_REDACTED`
- 分支：`codex/local-closeout-20260910`
- 起始/结束HEAD：`152981aba3bc9a15a1035dbfa53dc57651b3c97f`，未提交新commit。
- 起始Python源码指纹：`8685c1a092c644179a9d9d7d7bdd033408d7d9692d39462e54766e1a3e16fe11`。
- 主目录main仍是`c9984e92a10a6f417e2c1d8082af7e8f1e11aee1`，未覆盖其既有改动。
- 所有新增运行证据位于主目录下`.private/flow_mainline_20260912/`。

起点包含上一轮未提交修复。先冻结969个Python文件；交付包分别给出“HEAD到起点”的既有补丁和“起点到本轮结束”的补丁。不能把既有冲突合同、表格解析和身份系统都算成本轮新成果。

## 2. 改了什么，为什么改

### 共享诉求状态

新增`app/agent/task_plan.py`中的`RequestNeed`和`TaskPlan`，给诉求稳定编号N1至N8。分别记录搜索尝试次数、匹配证据、最终回答claims、需要用户补充事实、是否存在未读内容。ID必须唯一且有序，请求之间不共享可变状态。

`controller_v2.py`初始化一次计划，工具观察后更新证据；`generation_v2.py`把同一组N ID放进生成输入，发布时重新按真正送入模型的packet计算覆盖。原有审批、材料、冲突和引用合同仍继续执行，新检查只能将漏答降为partial，不能推翻旧检查而升为answered。

重要限制：这是有限必要条件校验，不是通用语义充分性证明。原有required_aspects仍承担兼容检索职责，未整体替换；单个whole诉求有匹配文字不证明所有隐含要求都被识别。search_attempts是该请求对这组诉求的搜索次数，不是精确到每项独立查询次数。

### 跨领域结构补读

`controller_v2.py::_focused_read`从有限报销场景扩展到process或明确多诉求。沿合法命中的同文档、同章节定位，最多1次focused find、2次focused open，依然消耗原工具预算。它不会把相邻但越权、过期、草稿、其他policy/tenant/section的内容自动当成证据。

`navigation.py`增加阅读窗口起点，`OpenRequest/OpenResult.start_char`和`FindMatch.preview_start`贯穿安全快照。`navigation_binding.py`从原始snapshot重新核验位置、文字、来源和截断状态，伪造位置不能通过。窗口尽量从完整句子的起点开始，避免切掉“若/不得”等前置条件。引用身份对非零窗口绑定起点。

同一长chunk的命中预览落在1200字符的普通交付前缀之外时，控制器可重新open该位置，不再因“这个chunk已经搜过”直接跳过。窗口仍不是全文：`truncated`不会被伪装成false，过程或多诉求存在未读内容时，不宣称全部答完。

目前find仍最多查看20个同章节候选，open仍有字符与次数上限；查词不匹配时预览仍可能取前部。缺失章节结构、很长的单句和跨页续表关系，不能靠窗口算法恢复。

### 给补读留下真实的上下文空间

`generation_v2.py::_build_prompt_sources`在普通search结果消耗packet前，为最多两个有用open预留来源名额及字符/字节预算。此前8个search来源可能把open完全挤出，造成“工具读到了、模型没看到”。总来源数、上下文上限和字节估计器没有放大。

### 有界LLM建议，默认关闭

新增`task_advisor.py`，复用当前`qwen2.5:3b`和现有Ollama transport，没有下载新模型或框架。

- 每请求最多一次规划、一次检索后的缺项建议；每次最多5秒，且不能延长外层总deadline。
- 规划输出严格JSON schema，只能增加有限诉求，不能删除原问题或规则诉求。引用的原问题片段必须真实存在；片段内金额、日期、编号、否定受到必要条件校验。
- 缺项建议只能引用本次允许观察的E ID。模型“supported”只是建议，绝不授予answered权限。
- 需要补查时，主机最多追加一次`原问题 + 待补诉求`的查询，原user、filters和检索配置保持不变；不允许模型自由指定工具、来源、权限或循环次数。
- unsafe请求不进入模型建议；冲突、无证据、错误、耗尽预算等情况不继续做缺项评估。
- 格式错误、无效来源、超时、输入超过预算均回退原路径；公开trace只给安全状态和计数，不输出模型原文或受限来源ID。

开关为`AGENT_V2_TASK_ADVISOR_ENABLED`，默认false。启动脚本也显式默认关闭，只有`-EnableTaskAdvisor`才开启实验模式。通用错别字纠正、任意多跳问答和自由查询改写不是本轮交付。

### 本地演示身份恢复

`demo_identity.py::renew_demo_identity`新增显式续签：复用活动私钥，先发无管理权限的短期probe，确认运行API确实加载该key，再通过原有加锁、journal、原子提交机制更新persona/operator token。JWKS、反馈HMAC、活动key、pending rotation和退休记录不变；寿命上限仍900秒。

`manage_demo_identity.py renew`是本地操作者命令，不是浏览器可调用的签发端点。API未接受probe时不更新token。测试覆盖写入中断恢复、pending rotation保持、非法寿命和拒绝probe不改文件。

`local_candidate.ps1`启动时等待API存活并续签，续签失败则不启动UI；增加`RenewIdentity`，不需要rotate或重启API。状态记录显示真实profile/model/advisor开关。UI的invalid_token提示现在明确说明可能过期或无效、等待不会续签；不自动重放POST，不把所有鉴权失败都说成过期。

## 3. 怎么验证

### RED与集成错误都保留

| 原始运行目录 | 真实结果 | 含义 |
| --- | --- | --- |
| baseline | 844 passed | 本轮开工时既有限定基线 |
| red_task_flow | 3 failed | 共享状态、生成输入和通用流程补读尚不存在 |
| task_flow_v1 | 12 passed / 42 failed | 本轮集成错误：admitted原对象与DeliveredEvidence混用；用统一view修复 |
| task_flow_v2 | 53 passed / 1 failed | “年假怎么申请”单流程关系仍未命中 |
| red_packet | 3 passed / 2 failed | 加入open被8个search挤出的反例 |
| task_flow_v3 | 735 passed | 状态/章节/packet阶段相邻验证 |
| red_advisor | 4 failed | 建接口前的固定schema/fallback验收 |
| red_window_identity | 9 failed | 尚无窗口/续签，独立advisor调用未设5秒本地deadline |
| window_identity_v1 | 519 passed / 24 failed / 5 skipped | 本轮遗漏安全快照中的新位置字段；补全后修复 |
| window_identity_v2 | 543 passed / 5 skipped | 位置字段、安全快照、续签及相邻验证 |
| red_integration_ui | 5 passed / 2 failed | 通用流程未读仍answered、鉴权提示不可操作 |
| integration_ui_v1 | 322 passed | 修复后API/UI/模型建议接线验证 |
| structure_parsing | 250 passed / 2 skipped | 既有解析、表格行覆盖与索引质量绑定回归 |
| final_regression | 1386 passed / 2 failed / 9 skipped | UTF-8修正前的完整限定范围 |
| red_advisor_unicode | 1 failed | 模型实际看到的中文被转义为字面序列 |
| advisor_unicode_green | 30 passed | 序列化修正与模型接线回归 |
| final_regression_utf8 | 1387 passed / 2 failed / 9 skipped | 最终源码、导入路径和全部限定范围 |

9项skip均沿用既有平台/环境条件，逐项原因保存在JUnit；没有新增skip/xfail，没有删改原冻结断言。窗口越界的新测试起初误用了不存在的chunk ID，后续修正为存在的目标，避免把not_found误算为越界行为证明；最终结果以修正后回归为准。

### 两项历史绑定失败的准确解释

`test_public_trusted_identity_result_recomputes_exactly`比较整个旧报告与当前报告。本轮重算差异字段只有`source_sha256`和`evaluation_contract_id`，业务20项结果一致。

`test_e16_public_evidence_binds_protocol_sources_and_implementation`要求E16记录的源码哈希等于当前文件。`config.py`和`runtime/resources.py`早在本轮起始快照就已经与E16不同；本轮新增config开关又改变了前者。原报告和旧断言未被修改。

新交付的`lineage_review_final/`给出旧哈希、起始哈希、最终哈希，以及当前20项身份矩阵原始结果。它不把两个原FAILED变成PASSED，也不授权宣称GitHub CI全绿。旧B09/G4历史结果同样未回写或重跑。

## 4. 真实模型结果

RTX 5060 8GB，Ollama `qwen2.5:3b`，模型digest固定，temperature=0、seed=42、8192 context、1024 output，原15秒主机预算。没有付费API调用。

实验固定第一阶段命中，使用真正的Guard、find/open、生成和发布校验；补查仍返回相同候选，因此**不能测试LLM改写是否改善真实召回**。用预先定义的词项替代组检查最终已校验claims，不在缺项提示正文里找词凑数，不用LLM judge。3个控制组包含缺证据、用户事实不足、直接注入；其余9个为材料可支持的问答。

| 指标 | 起始修复版 | 结构闭环版 | 结构版+模型建议 |
| --- | ---: | ---: | ---: |
| 完整且引用通过校验的预设要点 | 6/9可答场景 | 8/9 | 8/9 |
| 同上，以全部请求为分母 | 6/12 | 8/12 | 8/12 |
| 最终claims的预设要点覆盖 | 14/21 | 18/21 | 18/21 |
| 预设规则发现的错误answered | 0/12 | 0/12 | 0/12 |
| 模型调用总次数 | 8 | 10 | 31 |
| p95端到端耗时 | 1.22秒 | 1.77秒 | 3.38秒（修正序列化前） |

样本仅12个，nearest-rank p95实际等于该组最大值。不能据此声称稳定尾延迟，更不能把0/12称为零幻觉。收益来自有限流程关系匹配与结构补读组合，使两个年假场景由not_found恢复；本轮没有把各个子改动单独消融，所以不能把全部增益独归于任务状态或窗口。规则“全部要求”场景在三组都未找到证据，保留失败，不在这个协议上无限调参。

首轮使用生产随机nonce，口语场景在advisor组曾漏答降partial；固定评测专用nonce后不再出现该退化。两轮均保留，正式配对表用`live_fixed_*`。生产随机nonce未改。存在这次输出变化本身说明小样本模型输出不够稳定，不能把一次结果当严格语义保证。

### 序列化错误的进一步复核

逐条检查发现v1全部11次规划被拒绝。输入把中文变成了字面的`\\uXXXX`，模型又把source_span双重转义；主机按真实原问片段匹配时正确拒绝。不能把这个实验称作“成功规划但没有收益”。

新增RED直接检查模型实际看到的消息正文，再改用UTF-8中文JSON和对应UTF-8字节预算。没有递归解码模型输出，也没有放松任何原文/否定/数字约束。版本为`task_advisor_v2_utf8`。

对相同12个已消费场景只做一次固定nonce的回顾性诊断，保留原始v1协议和全部结果；不把修过程序后重复的集合冒充独立最终测试，也不据此晋级。

| UTF-8诊断项 | 结果 |
| --- | ---: |
| 规划通过主机schema/原片段校验 | 10/11，unsafe不调用规划 |
| 完整支持场景 | 8/9可答，或8/12全部 |
| 预设要点覆盖 | 18/21 |
| 错误answered代理指标 | 0/12 |
| 模型调用总数 | 31 |
| p95 | 2.76秒 |

这说明序列化问题已改善，不说明10/11计划在语义上都正确。个人报销资格问法仍回退规则；缺试用期材料只补查一次，不捏造答案。模型增加的复杂度没有换来比结构版更多的完整答案，因此保持OFF。

真实模型运行的源码哈希保存在每组SOURCE_BEFORE/AFTER。主配对运行后做了格式化、局部lint清理，之后仅advisor进行了有RED支持的UTF-8修改；UTF-8诊断和最终回归均另行绑定新源码。包内AST核对明确标出advisor这一处有意行为差异，不把不同源码指纹写成同一个版本。

结论：`KEEP_STRUCTURAL_CANDIDATE / ADVISOR_DEFAULT_OFF`。模型建议没有超过同条件的结构版，未达到预先冻结的效用门槛，不继续换模型或调参凑收益。该结论只针对本次实现、模型和开发场景，不证明所有LLM规划都无效。

## 5. 真正HTTP入口检查

使用已有216-chunk活动索引，在新端口8012/8512启动候选API/UI，profile=`hybrid_default`，bge-m3 embedding，qwen2.5:3b generation，advisor关闭；不是WixQA reranker评测配置。

- `/health/ready`的数据库、索引、模型、身份均ok，Guard ready；UI HTTP 200。
- 无Bearer的POST返回401。
- 续签命令成功，验证文件未变，persona token已刷新。
- 单制度demo returned answered；直接指令覆盖demo returned unsafe。
- 多条件安全制度demo预期answered，实际partial：模型一个关键陈述未满足绑定原文要求，系统回退为有引用的摘录。**这是未达到完整demo预期的真实结果**，不是网络或token错误，不算全通过。
- 首个真实问答含冷启动约9.56秒；不能拿暖机1.77秒代表所有首次请求。

检查后只停止本轮启动并核对PID/启动时间的进程。受工具权限限制，第一次停止被拒绝，按权限流程重试后已停止；没有关闭原有Ollama或其他任务服务。没有公网部署或修改活动索引。

## 6. 和成熟开源设计的关系

| 借鉴的设计 | 本项目采用部分 | 不应宣称 |
| --- | --- | --- |
| [LlamaIndex子问题查询](https://developers.llamaindex.ai/python/examples/query_engine/sub_question_query_engine/) | 用户诉求拆分、稳定ID和合成输入 | 已得到通用复杂问题规划器 |
| [Haystack句子窗口](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/sentence_window_retriever.py) | 来源/位置绑定的上下文展开，避免只按问题关键词重查邻接内容 | 与Haystack同场景跑分胜出 |
| [Dify父子检索](https://dify.ai/blog/introducing-parent-child-retrieval-for-enhanced-knowledge) | 小块定位、较完整上下文阅读；复用既有parent能力 | 本轮新发明parent-child |
| [LangGraph Agentic RAG](https://docs.langchain.com/oss/python/langgraph/agentic-rag) | 结构化模型建议、条件动作、有界重试 | 相关性打分等于充分性证明 |
| [RAGFlow DeepDoc](https://github.com/infiniflow/ragflow/blob/main/deepdoc/README.md) | 先正视解析结构与数据质量，再决定模型是否有可读证据 | 已实现通用OCR、PDF布局或跨页续表 |

这里的实际价值是：可定位的阅读动作、同一份诉求状态、模型没有发布和授权权力、可回放的失败证据。它符合成熟系统的责任划分，但未与这些框架做性能对照，不能宣称全面优于高星项目。

## 7. 保留的限制与主线建议

值得保留：共享任务状态、原文位置窗口、补读packet预留、未读过程降级、续签恢复及其回归。模型建议接口作为默认关闭的实验能力保留，不作为性能卖点。

尚未解决：隐含诉求/任意错别字、同义改写的语义保持、whole诉求的通用完整性、多文档全局例外、OCR与跨页表格恢复、真实用户人审一致性。现有原生PDF解析只提取文字和页定位，不恢复表格；已有表格质量门禁只验证已经解析出来的结构，不能证明未识别的表格也正确。

没有为此加入框架、数据库、新的模型、reranker或learned ranker。没有重跑WixQA/FinanceBench，也没有增加新的独立holdout。没有修改简历、发布状态、旧评测数字、main或GitHub。

合入主线前应把历史证据的固定版本检查和当前版本的发布门禁明确分开，并完成真实用户语义验收；不能简单更新旧哈希来获得绿灯。本轮不声称企业生产就绪或整库问答全部正确。

可用于项目讲解：
1. 实现同源定位、位置绑定和预算内补读，防止检索动作完成被误认为回答完整。
2. 对结构规划与模型建议进行消融，未达到效用门槛的模型策略保持默认关闭。
3. 演示身份通过活动密钥probe、短期续签与崩溃恢复解决失效问题，不靠关闭JWT或永久token。

12场景、1387测试和历史Recall均不能改称真实企业问答准确率；本轮不产生新的简历检索百分比。

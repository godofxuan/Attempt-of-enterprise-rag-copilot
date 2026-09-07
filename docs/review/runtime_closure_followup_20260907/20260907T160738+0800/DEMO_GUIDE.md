# 有限场景演示与人工复核

## 先说清楚演示模式

本轮可重复演示是**synthetic + 确定性模型传输stub**，不是录制的真实LLM成绩。实际应用构造、JWT身份、路由、索引加载/激活、controller/registry、Guard、packet、citation和最终response都参与。
stub只替代embedding、scorer/生成传输、readiness外部依赖，不替代整个controller或回答流程。
测试输入临时写到当前独立worktree的.private子目录，身份token不打印；不触碰原项目活动索引。不要用README的默认`--force`身份初始化演示本轮，以免覆盖自己的身份材料。

## 准备与运行

从原项目根目录的PowerShell执行。以下命令使用已经存在的主venv，不安装包；进入本轮worktree后使用相对位置定位该解释器。相同basetemp中的pytest仅管理它自己的测试产物，不要改成真实资料目录。

```powershell
Set-Location -LiteralPath '.private\runtime_closure_20260907T160738'
$python = (Resolve-Path -LiteralPath '..\..\.venv\Scripts\python.exe').Path
$env:TEMP = (Join-Path (Get-Location) '.private')
$env:TMP = $env:TEMP
$env:PYTHONDONTWRITEBYTECODE = '1'
& $python -B -m pytest tests/api_v2/test_runtime_closure_flow.py tests/agent_v2/test_runtime_closure_regressions.py -v -p no:cacheprovider --basetemp .private/demo_review_01
```

这是实际执行过同组25项测试的可重现命令；`-v`显示每项机制，不让模型现场编新答案。
数据入口 `tests/api_v2/test_runtime_closure_flow.py::build_fixture`，每个fixture独立corpus/indexes/identity；Hybrid/Top20通过参数化分别验证。Top20这里用scorer spy，不能称GPU性能演示。

| 演示 | 测试名/操作 | 预期与解释 |
|---|---|---|
| 正常问题 | `test_approval_paraphrase_question_keeps_normal_answer` | 问谁批准、证据直属经理；answered且引用；证明不是一律拒答 |
| 证据不足 | `test_same_subject_without_requested_approval_relation_is_not_found` | 只有提前7天提交，不能回答谁审批；not_found/空sources，最终trace一致 |
| 删除后引用 | `test_deleted_named_policy_cannot_be_answered_from_another_limit` | 创建courier+shipping，先成功，再激活仅shipping；不能用相近表格回答已删除的明确制度问题 |
| 数值与条件 | `test_numeric_scope_and_units_are_not_relaxed` | 保留原句和空白等价；错单位、对象、条件、上限均不支持 |
| 部分回答 | `test_missing_duration_after_shape_valid_output_is_partial` | 摘录有事实但缺所问天数，保持partial而非全答完 |
| 冲突 | `test_single_document_conflict_uses_host_excerpts_not_an_llm_winner` | 单一合法权威文档内部7/30天冲突；partial、两段事实引用、LLM调用0 |
| 来源排除 | `test_excluded_content_reaches_neither_scorer_nor_llm` | 不同tenant/groups、supporting、注入文本都不进入scorer/LLM；正常退款7天仍回答 |
| 夹具治理 | `test_two_active_authoritative_documents_are_not_a_legal_conflict_fixture` | 拒绝非法双权威索引；不是一个可宣传成已通过的双文档裁决 |

离线gold复算命令见 `EVIDENCE_REPLAY.md`；输出scope而不是笼统PASS。
旧/新对照日志在 `logs/baseline_new_regressions.log.txt`、`logs/final_targeted.log.txt`；不需要现场再改代码造失败。

## 真实模型演示状态

本轮准备失败，未获得新真实回答，见 `live/summary.json` 与 `logs/mini_live.log.txt`。不要展示空列表为成功成绩，不要重复运行私有one-shot harness。
只有环境完整并另行冻结协议后，真实服务才使用已有的 `app.serving:create_app --factory --workers 1`（显式GPU profile时预热BGE）；本指南不提供会误启动用户真实索引的半套命令。
本轮不启动常驻API、不部署，也不变更默认profile。历史真实模型输出只可按旧SHA和旧协议展示，不能改标题说是新补丁的实测。

## 真人模板使用

`HUMAN_REVIEW_TEMPLATE.csv` 仅有表头，无伪造问题/评分。当前NEEDS_HUMAN。
由未参与调试的人提供20-30个新业务问题，检查问题族和近重复，核对来源许可，在查看运行结果前冻结预期要点/依据/时间。
机器只填question_id、配置、证据/输出路径；来源独立性、预期签核、答题判断、条件/单位完整、引用支持、降级适当、reviewer/time都由真人填写。不能把原40题换措辞冒充独立集。
真人缺失不阻止演示已验证机制，但不能宣称端到端准确率。后续真实运行须另立预算，不能续用本轮上限。

## 最多三条简历表述

1. 在200道已使用公开WixQA ExpertWritten问题上，应用级Guard前置的BGE raw-chunk Top20配置较Dense将文章Macro Recall@5从65.92%提高到72.25%、nDCG@5从52.08%提高到59.20%；提供gold、排名与离线复算材料（回顾性检索，不是答案准确率）。
2. 实现JWT/ACL约束下的有界检索问答服务，统一预算后证据与引用验证，索引激活/删除/回滚后按请求及发布边界校验版本，GPU重排为显式可选配置。
3. 针对答非所问、关系缺失和来源排除建立实际HTTP确定性回归；同一组25项新业务测试在旧源码6失败、修改后全通过，并保留不完整真人/真实模型验收状态。

禁止写“答案准确率65.92->72.25”“680道独立问题”“新版本跨平台CI全绿”“生产零故障”“所有安全边界已证明”“Top50全面上线”。本轮未自动更新简历或发送对外完成声明。

## 面试追问

- 为什么引用正确仍然会答错？可见性证明能读，span证明源文一致，relevance/sufficiency才处理是否回答所问对象/关系；三层不等价。
- 为什么不用另一个LLM判断？本轮两个可复现缺口可在既有契约局部修复；引入judge会增加成本与不可复现性，也不能替代真人独立验证。
- 为什么全套测试通过还不能说效果好？这些测试证明已知机制；外部检索、真实生成、真人语义、生产可靠性需要不同数据与运行证据。
- 为什么不做learned ranker？这次已证实的是发布相关性/夹具/证据口径，不是需要新ranker的排序瓶颈；换模型不解决这两个错误。
- 这次失败怎么办？如实保留GPU环境缺docx的准备失败，不以历史实测或stub冒充本次确认，后续有条件再冻结新协议。

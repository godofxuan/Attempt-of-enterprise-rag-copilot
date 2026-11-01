# 0.7 的资料更新契约

旧 0.6：任一资料/元数据变化后，整个库 `snapshot()` 报 `INDEX_OUTDATED`。
新 0.7：原子发布的旧代次可继续查询；未发布的新文档不加入结果；旧版本更新期间有明确历史提示。
主动停用按 source_key 撤销已发布版本；单个资料元数据改变先排除该来源，再等待重新发布，不让其他资料全部不可用。

`tests/vnext/test_library.py` 与 `test_source_spans.py` 的两处旧 INDEX_OUTDATED 断言迁移为上述精确不变式。
原错误输出保存在本轮 S1-index-RED.xml；原文件可由 6006cd06 重建。来源偏移、非法目标、历史版本、缓存、重启和实际 FAISS 断言全部保留并到达。
新 `test_publication_availability.py` 验证更新失败后旧发布仍可用、停用立即排除、恢复/重新发布和重启。不是删除断言或把问题归为旧测试无效。

Deep旧测试曾断言模型检索子题也成为新的用户义务。真实基线显示它把“延期/提前归还”等未问内容扩写成未完成项。现在保留全部实际search/find/open/身份/来源选择断言，改为严格核对唯一原问义务且model_added_needs=0；子题仍在evidence_table中逐项核对。知识Agent工具不再接受模型覆写原问；知识followup替身改为合法空参数，原字段/消息/调用/无副作用断言不变。

解释实验未过门槛后默认恢复来源单元wire；原followup替身只会返回answer_blocks，导致清洁源码检查在测试适配器内部提前报错。该测试改为同时参数化source/experimental两种当前schema，替身只按实际schema返回合法外部响应；原长问题、旧答案不入证据、未冒充澄清、来源、正确正文和超时断言全部保留并到达。原失败CLEAN_SOURCE_91518859.xml保留。已知复合否定误拦测试继续失败，未跳过。

## 0.7rc2 回合交付契约

原替身只返回 prepare_preview，没有声明当前回合要求的结果，无法验证复合请求漏交付。现在替身在实际工具 schema 允许的位置显式给出 turn_request（preview/原文 knowledge_quote）；只有程序测试提供此期望，实时模型路径不注入。重试用原文绑定问题代替模型改写，保留查询次数、原消息、来源、日期修改与无业务副作用断言。prepare_preview 只允许 asset_id 和只读回合说明，仍不允许夹带参数修改。资源验证改为独立事件，用户用途/设备来源保持 USER_MESSAGE，不由模型验证覆盖；原校验继续执行。

新增 partial 回归真正走到产品 TaskView 序列化，外部知识替身明确返回 partial（无伪造来源），验证仅补解释、后续参数不回滚、旧预览仍留档、新预览后才 DONE。

# 0.7 的资料更新契约

旧 0.6：任一资料/元数据变化后，整个库 `snapshot()` 报 `INDEX_OUTDATED`。
新 0.7：原子发布的旧代次可继续查询；未发布的新文档不加入结果；旧版本更新期间有明确历史提示。
主动停用按 source_key 撤销已发布版本；单个资料元数据改变先排除该来源，再等待重新发布，不让其他资料全部不可用。

`tests/vnext/test_library.py` 与 `test_source_spans.py` 的两处旧 INDEX_OUTDATED 断言迁移为上述精确不变式。
原错误输出保存在本轮 S1-index-RED.xml；原文件可由 6006cd06 重建。来源偏移、非法目标、历史版本、缓存、重启和实际 FAISS 断言全部保留并到达。
新 `test_publication_availability.py` 验证更新失败后旧发布仍可用、停用立即排除、恢复/重新发布和重启。不是删除断言或把问题归为旧测试无效。

Deep旧测试曾断言模型检索子题也成为新的用户义务。真实基线显示它把“延期/提前归还”等未问内容扩写成未完成项。现在保留全部实际search/find/open/身份/来源选择断言，改为严格核对唯一原问义务且model_added_needs=0；子题仍在evidence_table中逐项核对。知识Agent工具不再接受模型覆写原问；知识followup替身改为合法空参数，原字段/消息/调用/无副作用断言不变。

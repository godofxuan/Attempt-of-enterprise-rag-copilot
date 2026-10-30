# 0.3 消息契约迁移

旧0.2.0基线8881b000和S0复现/修复结果保留。本轮用户明确要求同一主模型工具循环处理消息，允许相对日期/语义归一化。

| 旧输入约定 | 当前输入约定 | 保留的不变式与检查 |
|---|---|---|
| MessageInterpretation JSON：updates/quote/scope | 原生工具update_parameters、knowledge_answer、读取和finish | 原用途/日期等未提字段不变；一回合既改参数又问问题；不重复增加分类模型 |
| 每个值逐字包含于quote | 归一化值通过对应服务Pydantic字段与业务规则；原始用户回合及工具参数留档 | 合法相对日期可变成ISO日期；跨领域字段/权限字段不能混进facts |
| 模型可建议execution_ceiling，宿主拒绝升权 | 工具目录完全不提供扩权/提交工具，范围仍由用户UI明确 | READ_ONLY无预览，PREVIEW_ONLY无提交；实际Store确认/提交断言继续执行 |
| 一次消息固定1次理解调用 | 同一个主模型基于工具观察推进，回归替身使用update→finish两步 | 重复message_id不再调用模型或重复副作用；不把调用数增加说成提速 |
| 旧测试INSERT conversations VALUES(?,?) | 显式(id,kb_id)列，原表兼容增加标题/当前任务 | 原追问仅用户问题及跨库拒绝的原断言继续执行 |

旧“未逐字引用即拒绝”的测试不再代表本轮契约；替换为合法归一化正例与字段/权限反例。旧确认失效、未决输入阻断真实确认/继续、恢复原文等断言仍到达原业务代码，没有删除或skip。
这些程序检查不能证明任意自然语言的理解正确，实时案例必须另留原始模型/工具记录。

## 0.4 动作集合与当前交付

- 旧完成态fixture允许一个字段齐全的办理任务立即ask_user/finish。当前schema只在真实缺字段时暴露普通运行的补问，未完成时不暴露finish；主模型仍可在规则、库存、本人单和准备工具之间自行选择，没有预填顺序。
- 取消后的继续测试保留原cancelled、原facts、run所有权和不重启断言；将旧空补问替身替换为实际合法读取→准备，追加确实生成当前preview且0工单断言。原失败XML仍留存。
- 同一模型在消息中可用update_parameters，或在prepare_preview携带同一typed schema的parameters。实际Store更新、旧确认失效、本人设备校验和精确确认均保留；没有改权限或提交入口。
- 报修的工具target与facts.asset_id是同一设备，按服务声明的selection_field绑定，不要求模型重复写两遍。未变字段的原始来源在增量更新后保留。
- 自由正文只保存在model_response；业务交付根据实际参数、已发布知识、真实preview/receipt和当前ticket装配，不能口头说已准备就显示真实预览。

模型对未读业务规则的错误得到missing_bindings观察，不把它当用户未提供信息。未知或越权工具仍立即拒绝。程序替身用来查机制，不计为实时Agent准确率。

## 0.6 原生循环在真实进展后的结束

旧测试test_protocol_feedback_preserves_already_completed_actions要求：已有实际参数/规则/库存读取后，模型只返回正文时，必须继续一次协议纠错并在同一次消息生成预览。两种措辞方案及受控原始请求诊断均没有使真实模型准备预览，记录为负结果。

新契约遵循原生工具循环：没有任何成功工具的空正文仍需一次纠错并失败；有成功工具的用户回合可以交付已持久化的进展。宿主完全不发布自由业务正文，不伪造finish调用，不补执行未选工具。未创建预览必须明确尚未生成、未提交，任务不标COMPLETED，原义务保持，用户可选择候选后继续。

替代测试test_progress_delivery_preserves_actions_and_continues_to_a_real_preview先故意让模型口头宣称预览已完成/已批准，验证实际仍无preview/receipt且状态不完成，再通过用户第二轮选择设备到达真实原propose和完整预览断言。原test_model_prose_does_not_execute_or_finish_a_business_turn与test_real_preview_is_terminal_for_a_conversational_turn保持，范围/确认/幂等/取消断言不改。此迁移不是把未预览记完成；实时混合组必须继续验证第二轮、实际预览及数据库，首轮只记PROGRESS。

0.6最后的真实第二台轨迹发现，prepare_preview重复携带完整parameters会让资源属性变成未请求的偏好。已移除准备工具的parameters入口，日期/用途/偏好仅通过已有update_parameters；准备只读当前事实、绑定当前设备。旧test_prepare_in_user_turn_consumes_typed_fields_through_same_update_path改用update_parameters→原prepare路径，原facts/preview参数相等、TEST范围、原文message_id、资产来源及Store.confirm实际EXECUTION_CEILING断言全部保留并真正执行。参数额外注入反例单列；没有弱化确认。

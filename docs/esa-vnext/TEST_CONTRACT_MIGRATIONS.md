# 本轮必要测试契约迁移

`test_generation_v2.py::evidence_records_from_prompt` 现在先验证、解码主机添加的
来源单元标签，再执行原有来源正文与注入边界断言。生产正文、canonical packing、
引用绑定和原始字节没有被修改；模型视图在完整单元旁展示 SxUy 标识。
旧断言要求模型视图字段逐字等于 canonical 字段，会把这些标签误报成来源污染。
替代不变式：标签闭合且每字段唯一，去标签后仍等于原准入正文；外层 nonce、
伪造边界/角色文本仍必须在 JSON 内。未删除或跳过原断言。

新资料库测试中的 HTTP 冲突期望从 FastAPI 默认 detail 改为当前产品的
`error.code/data`。测试仍要求409、TASK_CHANGED、实际当前参数；原受保护接口
错误脱敏行为不改。

迁入的 `test_continuous_generation_handoff` 空答案输入显式增加
`request_coverage: []`，以到达当前“明确的证据不足”分支；仍断言 partial、零断言、
零来源且未发布模型自由文本。遗漏必要契约的空数组仍走原非法输入 system 分支，
原 `test_generation_v2` 非法输入断言保留。

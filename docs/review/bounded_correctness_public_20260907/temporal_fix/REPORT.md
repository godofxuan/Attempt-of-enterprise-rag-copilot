# B09 时间有效性有限修复

## 结论

在用户“修复吧”对时间过滤的最小修改授权下，B09_future 已修复并通过真实离线回归。结合上一包，固定 A/B 矩阵已通过，本轮有限修复完成；不表示真实模型、人工或生产验收完成。原外部 suite 仍有一项已解释的旧 LLM 前提失配，不能称“所有测试通过”。上一包的 RED 新测试格式化前全文未归档缺项仍存在；本轮没有抹除历史缺项，本轮新增 RED 测试全文已保留。

## 实际身份

修改的是原工作树 `D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738`，分支 `fix/runtime-closure-20260907T160738`，HEAD 未变，为 c9984e92a10a6f417e2c1d8082af7e8f1e11aee1。没有 commit/push/merge/部署/切换索引。主工作区和 GitHub 不代表这些未提交修改。

起始源码指纹：72dc29408bdf96f8d0fd53253ec5ba3a9d57c6598803613a2df5b7d90e5710e0。
最终源码指纹：fcf97503ab5ebf56bf4a84ff39953ade3135841e190564308e668bb9e06323e5（943 scoped 文件）。逐文件及算法沿用前包，见 TARGET_IDENTITY_AFTER.json。

## 根因、修改和边界

日期已经进入 ChunkRecord；来源过滤也位于候选形成之前。错误是 `app/retrieval/pipeline.py::_matches_filters` 的 current 分支仅检查 active。状态标识并不证明今天处于有效期内，所以 future-active 和 expired-active 都能被检索。

仅修改该文件的 datetime 导入及 current 分支：同时要求 active、effective_from <= 当前 UTC 日期、effective_to 为空或当前日期 < effective_to。这与现有 as_of 的左闭右开区间一致。UTC 是本轮明确的服务器日期口径，不宣称实现了各租户本地时区的制度日期；午夜边界跨调用的一致性也不在本轮验收内。

没有改 as_of/historical/all 的行为，没有改 ACL/JWT/Guard、来源权威性、版本规则、reranker、检索数量、答案合同或模型。原双引用 host 冲突修复完整保留。

新增 `tests/retrieval/test_current_validity.py` 共 10 项：未来生效、生效当日、失效当日、已失效、尚未失效、retired，以及三种显式时间 scope 与 as_of 排他结束边界。时钟固定到 UTC 2026-09-07，测试不随真实日期漂移。原 API B09 继续使用原输入和断言，验证被排除文本不进入 scorer/LLM/最终响应。

## RED 与最终结果

| 组 | 通过 | 失败 | 说明 |
|---|---:|---:|---|
| G0_red 原 B09 | 0 | 1 | 原问题复现，未来文档造成 partial |
| G0_boundary_red | 7 | 3 | 未来生效、失效当日、已失效暴露，RED 全文已归档 |
| G1_release | 69 | 0 | 原固定矩阵 59 + 日期回归 10 |
| G2_release | 25 | 0 | 原冻结两文件逐字节保持 |
| G3_release | 75 | 0 | 原相邻 66 + 检索 pipeline 9 |
| G4_release | 13 | 1 | 原 cross_policy_conflict 旧 LLM 前提失配 |

首次 lint 4 项失败（UTC 别名和长行），做等价样式修正后 lint 通过；随后在最终指纹下重新运行 G1-G4，结果如上。每次命令与真实退出码见 TEST_RESULTS.json，阶段重复不可累计宣传。

旧 `test_cross_policy_conflict` 第 56 行强制两份材料进入 LLM，本轮 host 先处理所以 seen['llm']=[]，仍 FAILED / LEGACY_PRECONDITION_MISMATCH。G1 的 B01/B11/B12 两种 profile 证明 partial、双引用及 0 次生成，是替代契约证据。未修改外部文件、断言或桩，不为旧前提新增 LLM 调用。本轮没有未解决固定矩阵产品断言失败。

离线 verifier 为 VERIFIED_WITHIN_SCOPE（artifact_hash / aggregate_replay / gold_metrics 均 VERIFIED），不是新检索实验。没有依赖阻断、skip/xfail；真实模型调用 0。桩调用按 observations 统计，未全局计数组用 null，不冒充 0。实际 app/tests 导入定位及联网拦截记录保留。仅使用既有 socketpair 例外，没有放开 localhost。

## 三项任务的最终状态

1. 审批、免审批、未知、流程及双问发布：原 A 矩阵全部通过；缺项正文提示、已支持天数/引用保持。本轮未再次修改它们。
2. 跨 policy 有限数值冲突：原 B 矩阵全部通过；B09 经本轮日期过滤授权闭合。有限模板，不是任意语义冲突裁决。
3. 历史口径与交付：上一包报告和 HISTORICAL_ERRATUM 原样保留在 previous_delivery.zip。历史完整脱敏 XML 未交付的事实没有改变；旧日志数不是本轮成绩。

## 交接和复现

previous_delivery.zip 是上轮完整包，SHA-256 为 ceb9cd4068734c918372c8c507eebbae0c561a61ed1ec05646962b3df1e01486。本包 changes/this_round.patch 只含时间过滤与新增测试，作用于上轮最终源码。files/ 包含累计所有本轮与上轮修改文件，方便审核。RECONSTRUCTION.json 核对独立临时副本的补丁应用与最终 scoped 字节，不从基线丢弃既有修改。

外部审核仍需原 runtime audit ZIP（SHA 4b29e43e05daf2150b774d46ebe71f752f07754385e0bb4d76be3d232a6d7984）及 independent review ZIP（SHA 43d936a99d202a1142d513b4ae954e2fd3bbf1387e1a8d244d44b3bd2c4a69b5），本包已内含上轮增量包，无需另找上轮。输入及历史源码/证据保持只读。

## 展示、简历与未验证范围

可展示原审批人明确/未知、双问保留 7 天、双制度冲突 partial，并新增展示未来文档从 scorer 和回答中排除。均为离线可复现固定桩，不是已执行的人审或真实 LLM 语义评测。

最多三条表述：
1. 为企业 RAG 实现有限审批及复合问答发布契约，在证据不足时保留已核验事实与引用并明确缺项。
2. 为当前知识查询补齐 UTC 日期有效期过滤，配套 10 项确定性日期边界回归，并通过 API 测试验证未来来源不进入模型边界。
3. 建立源码指纹、RED/GREEN 日志、JUnit 与补丁重建相绑定的审核交付，保留原测试前提失配和历史证据缺项。

不宣传真实准确率提升、任意问法完备、所有测试全绿、独立人审或生产就绪。真实模型、真实网络、人审、完整历史套件、800 检索/680 主请求均 NOT_RUN；未新增配置或依赖。完成后停止。

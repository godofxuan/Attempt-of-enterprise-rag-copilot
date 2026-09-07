# 固定版本独立审核入口

本目录公开本次审批发布契约、跨 policy 冲突及 B09 时间有效性修复的证据。审核源码是本提交仓库根目录的 app/、scripts/、tests/，不是旧基线，也不是 main 的另一个版本。审查时先将分支解析为完整 SHA，后续链接固定到该 SHA。

## 先读

1. [最新修复报告](temporal_fix/REPORT.md)：B09 修复后结果及限制。
2. [前轮报告](approval_conflict/REPORT.md)：审批和冲突实现、五个原问题、历史 XML 纠错。该报告的“B09 未闭合”是历史状态，最新状态以上一项为准，不回写历史。
3. [最终源码身份](temporal_fix/TARGET_IDENTITY_AFTER.json)：最终 scoped fingerprint 为 fcf97503ab5ebf56bf4a84ff39953ade3135841e190564308e668bb9e06323e5，943 个文件。里面的 HEAD 是测试时未提交基线，不是本次发布提交；两种身份不能混淆。
4. [逐次真实结果](temporal_fix/TEST_RESULTS.json)、[JUnit](temporal_fix/junit)、[响应观察](temporal_fix/observations)、[导入核验](temporal_fix/IMPORT_CHECKS.json)。查 G1/G2/G3/G4_release，而不是重复阶段累计。
5. [原始完整执行矩阵](approval_conflict/TASK.md)，以及后续用户授权的 [B09 最小修复](temporal_fix/AUTHORIZATION.json)。旧“禁止修改时间准入”由这一项特定授权扩展，不能扩展到其他边界。

[Git 源码对应关系](GIT_SOURCE_IDENTITY.json) 已检查全部 943 个 scoped 源码文件：提交字节与最终测试字节一致，源码 fingerprint 相同；455 个复制公开证据文件的暂存字节也与原摘要一致。仅对两处证据目录增加 -text 属性，防止日志/XML 被 Git 自动换行转换。

## 最新结果，不是全绿

| 组 | 通过 | 失败 |
|---|---:|---:|
| G1_release 固定矩阵 59 + 日期边界 10 | 69 | 0 |
| G2_release 原冻结回归 | 25 | 0 |
| G3_release 相邻和检索回归 | 75 | 0 |
| G4_release 外部冻结检查 | 13 | 1 |

G4 仍为真实 FAILED：旧 test_cross_policy_conflict 强制双方进入 LLM；host 提前返回双引用 partial，LLM 调用为零，故第 56 行断言失败。请独立判断该分类是否成立；新 B01/B11/B12 不是删除旧失败的理由。[冻结外部检查源码](frozen_external_checks/test_counterexamples.py) 原样提供，运行时复制到 scratch，避免覆盖其 observations。

真实模型、人审、生产验收、历史完整 benchmark 均未运行。Lint、离线证据字节重放通过，不意味着业务语义全面正确。UTC 日期口径不等于租户本地时区实现，固定测试通过也不排除未覆盖的问题。

## 核心源码

- app/agent/answer_contract.py：有限审批、免审批、缺项与条件适用。
- app/agent/generation_v2.py：正常与 fallback 发布合同、引用/正文/trace。
- app/agent/evidence_ledger.py：跨 policy 但同可比作用域的数值潜在冲突。
- app/agent/runner_v2.py::build_conflict_response：host 双引用 partial。
- app/retrieval/pipeline.py::_matches_filters：current 的 active + UTC 左闭右开有效期。
- tests/api_v2/test_bounded_correctness_matrix.py 与 tests/retrieval/test_current_validity.py：本轮真实测试。

## 证据范围

[PUBLICATION_MANIFEST.json](PUBLICATION_MANIFEST.json) 是复制文件的公开清单；其中列明未公开的嵌套 ZIP、私有执行器和重复源码。原内部 ARTIFACT_MANIFEST 保留原包清单，不能用它推断那些被明确排除的文件也已公开。本 README 和 frozen_external_checks 是额外的导航/原样外部源码，由 Git 提交绑定。

本机路径为历史 provenance，未改造日志/XML 字节。没有上传原输入 ZIP、私钥、JWT、模型或缓存。历史完整脱敏 XML 并未交付，详见 approval_conflict/HISTORICAL_ERRATUM.json。公开材料足以做源码及已发布测试证据审核；原 ZIP 独立重建属于另外的材料核验，不得声称已下载未公开原包。

生产变更包含上一轮保全的未提交修复，不全是 B09 新增。approval_conflict/changes/ 与 temporal_fix/changes/ 将各轮差异分开。最终提交只是冻结和发布，不改变测试时的 scoped 源码字节。

## 审核要求

以寻找实际缺陷为主，不按 README 代写好评。区分源码可确认、测试证据可确认、未执行和不可访问；给出文件/行号、触发条件、最小反例、影响及最小修复建议。重点检查任意否定或其他对象被误识别成审批人、错误条件、partial 引用丢失、跨 policy 错分组、UTC/有效期边界、父块上下文旁路与原 as_of/historical 兼容性。不要仅凭测试通过宣称无漏洞。

只提出证据支持的有限收尾项，不添加框架、模型、数据库或新的 Agent，不调 benchmark 获得漂亮数字。输出分级发现、是否建议合并、剩余证据缺项、最多三条准确简历表述。

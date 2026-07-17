# R2-S1 Design Options and Decisions

状态：D1 frozen
日期：2026-07-17
记录规则：`evidence=OBSERVED` 表示来自当前代码；`PLANNED` 表示尚未实现；`NOT RUN` 表示尚无测试结果。

## R2S1-D01: Guard 放在哪里

- **problem:** raw retrieved content 当前在 `V2ToolRegistry` 后直接进入 `Controller.observe`，随后进入 Ledger、generation、verifier 和 response。
- **alternatives:** A. 只在 ingestion 扫描；B. 只在 generator 前过滤；C. retrieval 后、Controller 前统一隔离；D. 每个下游各自过滤。
- **chosen option:** C。ingestion 扫描未来可作为额外层，但不作为运行时边界。
- **reason:** 只有 C 同时覆盖动态 open/find、parent context、Ledger、verifier、extractive response 和未来新增下游；D 会重复并产生策略漂移。
- **evidence:** `OBSERVED`：`runner_v2.py` 当前执行 `registry.run -> controller.observe`；`generation_v2.py` 读取 hit/open 原文。
- **trade-offs:** 需要新增 guarded domain contract，并调整 tool/context budget 边界。
- **rollback:** phase-scoped commit 回滚；secure endpoint 在回滚期间保持不注册或 source-free fail closed。
- **status:** accepted for implementation；implementation `NOT RUN`。

## R2S1-D02: 使用确定性规则还是 LLM detector

- **problem:** 需要检测多语言、编码和角色伪造，同时保持 CI 可复现、低成本和可解释。
- **alternatives:** A. 纯 LLM judge；B. 纯关键词；C. 版本化确定性规则、结构组合和有界解码；D. C 后再用 LLM 复判。
- **chosen option:** C 作为 R2-S1 enforcement。LLM 可在未来人工红队分析中辅助，不进入放行决策。
- **reason:** A/D 会引入非确定性、模型可用性和“被待检测内容影响检测器”的同类风险；纯关键词误报高。C 可对规则、阈值和资源成本做回归。
- **evidence:** `OBSERVED`：现有 R1 security checks 是确定性、可复现；当前无 LLM content detector。
- **trade-offs:** 不能理解所有语义和未知攻击，必须诚实报告漏报/误报并保留 prompt/capability 第二层。
- **rollback:** 新 detector version 可回滚到上一个规则集，但不能自动切换 `off`。
- **status:** accepted；unknown-attack immunity explicitly rejected。

## R2S1-D03: Guarded 数据类型

- **problem:** 一个带 `content: str | None` 的对象可形成 `QUARANTINE + content` 或 `ADMIT + no content` 的非法状态。
- **alternatives:** A. dict；B. 单模型加可选字段；C. `AdmittedEvidenceChunk` 与 `QuarantineSummary` 判别联合。
- **chosen option:** C，并由 `GuardedToolExecution` 封装。
- **reason:** Pydantic/runtime validation 可以让非法组合在进入 Controller 前失败；Quarantine 类型结构上没有正文槽位。
- **evidence:** `OBSERVED`：项目 domain models 使用 `extra='forbid'` 和 model validators。
- **trade-offs:** Search/Find/Open 需要明确的 guarded payload adapter，测试更新面较大。
- **rollback:** 保留 raw retrieval 作为 private internal implementation；不恢复 raw Controller input。
- **status:** accepted；schema draft in `03_detailed_design.md`。

## R2S1-D04: 是否保留 numeric risk score

- **problem:** 建议契约包含 `risk_score`，但确定性规则没有校准概率意义。
- **alternatives:** A. 0..1 score；B. 规则计数；C. `max_severity` + categories/rule IDs。
- **chosen option:** C。规则计数只作诊断，不作为概率。
- **reason:** 0.87 之类的数字会被误读为攻击概率；实际决策由稳定规则与组合条件产生。
- **evidence:** `PLANNED` contract review；无可校准训练集。
- **trade-offs:** UI 不会得到一个简单“风险分”，但解释更诚实。
- **rollback:** 若未来有校准数据，可新增独立 `calibrated_probability` versioned field，不能重解释旧 severity。
- **status:** accepted adjustment。

## R2S1-D05: Guard modes 与 fail closed

- **problem:** 迁移需要 OFF/ON 消融，但生产不能被请求关闭；单条扫描异常也不应摧毁所有干净证据。
- **alternatives:** A. 环境变量可关闭；B. request 参数；C. service 默认 enforce，audit/off 仅显式依赖注入。
- **chosen option:** C。单内容异常 quarantine；Guard 初始化/规则加载失败 source-free `system`。
- **reason:** 保留可测试基线，同时避免配置缺失静默降级；逐内容隔离提高可用性。
- **evidence:** `OBSERVED`：现有 runner 异常可映射 source-free system；依赖可在测试构造器注入。
- **trade-offs:** evaluator 要有独立 factory；生产排障不能通过 API 临时关闭。
- **rollback:** rollback code/version，不提供 runtime bypass。
- **status:** accepted。

## R2S1-D06: 全部内容被隔离时的 outcome

- **problem:** `not_found` 会把“知识库没有证据”和“证据因安全策略被扣留”混为一谈。
- **alternatives:** A. `not_found`；B. `unsafe`；C. 新 `security_filtered` mode + `evidence_filtered` stop reason；D. `system`。
- **chosen option:** C，且 source-free。
- **reason:** 这是 post-retrieval policy outcome，不是危险用户输入，也不是系统故障；显式状态支持运营、评测和面试解释。
- **evidence:** `OBSERVED`：现有 `AnswerMode` 没有该状态；API/UI/evaluator 需同步。
- **trade-offs:** public API contract 扩展，所有 exhaustive mode tests 必须更新。
- **rollback:** 保留新 enum；如果 UI 暂不支持则安全显示通用 label，不能降级成 answered/not_found。
- **status:** accepted。

## R2S1-D07: 候选补齐策略

- **problem:** 当前 pipeline 在 Guard 前已截成 top-k，简单删除会制造攻击者可控的可用性下降。
- **alternatives:** A. 删除后直接回答；B. 无限扩大检索；C. 一次取 bounded candidate pool，Guard 后继续扫描剩余排名候选；D. 每次隔离都重写查询重搜。
- **chosen option:** C。`candidate_k` 是硬上限；跨过初始 top-k 后最多记录一次 top-up，不重跑 embedding。
- **reason:** 能恢复 top-ranked poison 后的干净证据，又保持确定性成本与 ACL/排序不变。
- **evidence:** `OBSERVED`：`candidate_k<=200` 已在 `SearchRequest`；`_select_diverse` 当前提前丢弃候选。
- **trade-offs:** pipeline 需要内部 candidate API；scan latency 增加；diversity 只能对 admitted candidates 计数。
- **rollback:** 退回更小 candidate budget 可以降低成本，但不得退回“quarantine consumes top-k slot”。
- **status:** accepted。

## R2S1-D08: Prompt 边界

- **problem:** 当前 system 已说 evidence untrusted，但 evidence 和最终指令仍拼在同一 user string，文档可以伪造固定 delimiter。
- **alternatives:** A. 只强化一句 system prompt；B. 使用未验证的 tool role；C. system/user roles + nonce delimiter + JSON escaping + post-evidence reminder。
- **chosen option:** C。
- **reason:** 当前 Ollama transport 已支持 system/user，但没有 tool-role compatibility evidence；nonce 降低预置 delimiter spoof，结构化 escaping 避免边界由原文直接拼接。
- **evidence:** `OBSERVED`：`generation_v2._generation_messages` 当前生成 system + user 两条消息。
- **trade-offs:** 仍不是形式化隔离，模型可误解 user 内容；nonce generator 需可注入测试。
- **rollback:** 可更换 envelope version；不能删除 system/user separation。
- **status:** accepted as secondary defense。

## R2S1-D09: Trace 标识与内容指纹

- **problem:** 安全诊断需要可解释，但裸 hash 在小语料中可能被穷举；现有 trace 明确删除 doc/chunk/path/title。
- **alternatives:** A. 记录原文；B. 公开 SHA256；C. public aggregate only，private synthetic IDs，必要时 run-scoped HMAC。
- **chosen option:** C，并保持 public trace 不含 doc/chunk ID。
- **reason:** aggregate counts/categories/rule IDs 已足够解释决策，且不扩大现有隐私面。
- **evidence:** `OBSERVED`：`SENSITIVE_TRACE_KEYS` 当前剔除正文和资源标识。
- **trade-offs:** 公开 trace 不能逐 chunk 调试；逐题信息只能在受控 eval artifact 中查看。
- **rollback:** 关闭新增 trace 字段不会影响 enforcement；不得通过回滚恢复正文日志。
- **status:** accepted stronger privacy boundary。

## R2S1-D10: Legacy endpoint 策略

- **problem:** `/chat` 与 `/agent/chat` 使用未保护的 legacy retrieval/generation；继续公开会形成显式旁路。
- **alternatives:** A. 同时重构 legacy；B. 继续公开但只缩窄文案；C. default secure profile 不注册 legacy，另保留显式 local compatibility factory。
- **chosen option:** C，经 D0 批准。
- **reason:** A 扩大 R2-S1 到两套旧架构；B 仍允许用户实际走旁路。C 把支持边界和主张边界对齐。
- **evidence:** `OBSERVED`：`app/main.py` 当前同时注册四个相关 route；legacy assessor 和 answer generator读取 raw chunks。
- **trade-offs:** legacy API clients 需显式使用 compatibility profile；这是有意的 breaking secure-default change。
- **rollback:** compatibility factory 保留本地回归；secure profile 不自动恢复旧 route。
- **status:** accepted。

## R2S1-D11: Evaluation split 大小

- **problem:** 8 攻击 + 4 良性不足以覆盖变体；把 36 条再拆成很小 test 会让 release gate 分母过小。
- **alternatives:** A. 36 total；B. dev 36 + test 36；C. 只维护 test。
- **chosen option:** B：每个 split 24 attack + 12 benign，共 72 cases。
- **reason:** 每个 split 都能保持八类/四类各三个变体；dev 调规则不消耗 test 的唯一类别样本。
- **evidence:** `PLANNED` dataset protocol；当前 indirect set 为 0。
- **trade-offs:** fixture 和审查工作量增加；仍是 synthetic frozen regression，不是 unseen。
- **rollback:** 可以增加 case，不能在 freeze 后删除失败 test case；schema 版本升级需新文件名。
- **status:** accepted。

## R2S1-D12: Deterministic 与 live 证据

- **problem:** fake generator 能证明路径但不能证明真实模型受骗率；一次真实模型结果又不稳定。
- **alternatives:** A. 只 fake；B. 只 live；C. 两层分开报告。
- **chosen option:** C。
- **reason:** deterministic 适合 CI、TDD 和数据流断言；live 适合展示模型行为，但必须固定配置并保留随机/环境限制。
- **evidence:** `OBSERVED`：R1 已区分 deterministic/test 28/28 与 live/dev 23/24。
- **trade-offs:** 两套结果不能合并成单一安全准确率。
- **rollback:** live 失败不删除 deterministic evidence；deterministic 通过也不能覆盖 live failure。
- **status:** accepted。

## R2S1-D13: Claims evidence 位置

- **problem:** 外部建议新建 public claims matrix，但当前仓库把详细简历措辞和本机证据放在 ignored `.private`。
- **alternatives:** A. 全部公开；B. 全部私有；C. 公开窄化结果与哈希，详细逐 claim matrix 保持 private。
- **chosen option:** C。
- **reason:** 与 E6/E7 publication policy 一致，不暴露本机路径、私人材料或未批准措辞。
- **evidence:** `OBSERVED`：`.private/e6/claims_evidence_matrix.md` 已是现有 authority。
- **trade-offs:** public clone 只能验证公开 summary，不能查看私人简历审批过程。
- **rollback:** 可进一步缩窄公开结果；不得在无隐私审核时公开 private matrix。
- **status:** accepted adjustment。

## Decision Summary

| Classification | Count |
|---|---:|
| adopted as requested | 7 |
| adopted with repository-specific adjustment | 6 |
| rejected entirely | 0 |

The decision set remains frozen. D3-D5 have now implemented D01-D10 without changing the chosen options; D11-D12 dataset/evaluation evidence remains D6 `NOT RUN`. Implementation mapping and evidence are in [D4 Engineering Journal](06_d4_engineering_journal.md) and [D5 Engineering Journal](07_d5_engineering_journal.md).

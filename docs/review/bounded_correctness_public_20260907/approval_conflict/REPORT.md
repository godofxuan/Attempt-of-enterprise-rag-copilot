# Bounded Correctness 本轮交付报告

## 结论：部分完成，未闭合

本轮实际修改了正确的原工作树，并完成限定离线测试和证据重放。任务一的固定审批/天数发布用例通过；任务二的正常跨 policy 冲突用例通过，但 **B09_future 仍为真实产品断言失败**。因此不能写“有限修复完成”、全部通过或生产就绪。任务三的历史证据纠错及展示限制已在本交付中记录。停止原因是剩余失败需要修改任务书禁止修改的时间有效性准入逻辑，不是将失败忽略后继续扩功能。

另有证据过程缺项：修改前 RED 测试的摘要、JUnit、日志和 observations 已保存，但格式化前新增测试全文没有独立归档。交付的是最终测试全文；不宣称能够字节级还原那份 RED 测试文件。原冻结测试则已按字节核验未变。

## 1. 输入与真实修改位置

- 唯一任务书：本包 `TASK.md`，对应 CODEX_RAG_BOUNDED_CORRECTNESS_FULL_PROMPT.md。独立复核包旧任务书没有用于覆盖它。
- 原审核 ZIP SHA-256：`4b29e43e05daf2150b774d46ebe71f752f07754385e0bb4d76be3d232a6d7984`。实际 Downloads 文件名有 `(1)` 后缀，按内容摘要确认身份。
- 独立复核 ZIP SHA-256：`43d936a99d202a1142d513b4ae954e2fd3bbf1387e1a8d244d44b3bd2c4a69b5`。
- 实际修改位置：`D:\文档\agent\RAG_try\.private\runtime_closure_20260907T160738`。这是匹配的原 Git worktree，不是冒充原分支的无 Git 快照。
- 分支：`fix/runtime-closure-20260907T160738`；HEAD 始终为 `c9984e92a10a6f417e2c1d8082af7e8f1e11aee1`。
- 开始时 941 个 scoped 文件与原包 source_current 一致，指纹 `c939f2687301bca085b1c4702dbb508f588bd920b58dc4747498dde36b190b76`。
- 最终 942 个 scoped 文件（包含新增测试），指纹 `72dc29408bdf96f8d0fd53253ec5ba3a9d57c6598803613a2df5b7d90e5710e0`。算法和逐文件摘要见 TARGET_IDENTITY_BEFORE/AFTER.json。
- 使用现有 `D:\文档\agent\RAG_try\.venv\Scripts\python.exe`，Python 3.11.9，无依赖安装。

原工作树已应用本轮修改，仍未提交。没有 commit、push、merge、分支切换、部署或真实活动索引切换。普通主工作区不是本轮生产修改位置。

## 2. 修改与保留

| 文件/函数 | 本轮修改 | 保持的边界 |
|---|---|---|
| app/agent/answer_contract.py::bounded_answer_slots / answer_sufficiency | 对已核验 claims 区分明确角色、适用免审批、未说明、只说流程；计算审批人和天数独立槽位；有限条件适用性 | 不将“审批”字面出现当成答案完整，不将未知当免审批；保留旧 helper 兼容 |
| app/agent/generation_v2.py::_apply_answer_contract | 正常生成与 extractive fallback 共用发布检查；缺项写入正文和 warnings；保留支持的天数、claims、引用；同步 trace 和模式 | 不削弱引用核验，不升级已有保守模式，不新增模型调用 |
| app/agent/evidence_ledger.py | 保留原同 policy 分组，新增受范围约束的跨 policy 同模板数值潜在冲突检测 | 分组保留租户、区域、ACL、索引和权威性等约束；不同对象/条件/单位不直接混为冲突 |
| app/agent/runner_v2.py::build_conflict_response | host 直接返回双引用 partial，正文说明潜在不一致，generation_attempts=0，trace 一致 | 仅该函数调整；函数外 AST 与起始源码一致，没有改调度、预算或权限 |
| tests/api_v2/test_bounded_correctness_matrix.py | 新增 A/B 固定及对抗用例、原样 fixture 复用、真实响应/调用观察 | 原 25 项和外部 14 项不修改、无 skip/xfail 或放宽断言 |

query_analysis.py 本轮未改。ACL、JWT、Guard、版本治理、检索参数、引用核验等未改。上一轮未提交修复按原样保全，仅上述文件有本轮增量；起始已有差异见 changes/preexisting_uncommitted.patch，本轮增量见 changes/this_round.patch，两者不能混算。

该审批实现是有限模板合同，不是通用语义判断器；条件处理不是任意自然语言条件推理。并未证明真实模型面对任意问法都能正确回答。

## 3. 五个原失败逐项结果

| 原失败 | 原问题 | 本轮结果与对应新增测试 |
|---|---|---|
| g2_approval_only | 只说需要审批却发布为完整答案 | partial，保留有支持的内容/引用，正文明确审批人缺项；A01，经 bounded_answer_slots 和 _apply_answer_contract |
| g2_process_only | “按流程审批”被当作明确审批人 | partial，不将流程当人；A02，同上 |
| g4_unknown | 未说明审批人未正确降级 | partial，正文保留未知性质，不伪装为免审批；A03，同上 |
| g6_two_aspects | 双问缺审批人时丢失已支持 7 天，或覆盖计数失真 | partial，7 天及引用保留，requested/answered/missing = 2/1/1；A14，同上 |
| cross_policy_conflict | 7/30 天两个合法来源未由 host 处理 | B01/B11/B12 两种 profile 均通过：partial、双方引用、潜在不一致、LLM 桩 0 次；evidence_ledger 与 build_conflict_response。原外部测试仍 FAILED，原因如下 |

原外部 `test_cross_policy_conflict` 第 56 行要求 `all(r['text'] in json.dumps(seen['llm'], ensure_ascii=False) for r in rows)`。本轮正确路径在 host 先处理，scorer 可见双方，`seen['llm']` 为空，因而该断言失败。该结果仍记 FAILED / LEGACY_PRECONDITION_MISMATCH，不为让它通过额外调用模型。新测试证明双引用、partial、trace 和 0 次生成；映射见 MATRIX_RESULTS.json。外部其余 13 项通过，不能将 B09_future 混入此例外。

## 4. 仍未闭合的 B09_future

最小复现：默认 current 查询中同时提供当前 active 的 “refunds arrive in 7 days” 与 status=active、effective_from=2099-01-01 的 “refunds arrive in 30 days. BOUNDED_EXCLUDED_SENTINEL”。预期未来来源不得进入后续评分/回答；实际它仍进入 scorer。

修改前 RED 中该来源还进入 LLM；最终代码由 host 处理冲突，无 LLM 调用，但未来来源的文本和引用仍进入最终 partial。**减少 LLM 调用不等于修复了错误准入**。

根因定位：`app/retrieval/pipeline.py::_matches_filters` 的 current 分支只检查 `chunk.status == "active"`（本轮读取的第 533-534 行），未按 effective_from 排除未来生效文档。现有 as_of 路径有其他日期处理，但不能在看到失败后把固定 current 测试改成 as_of。SearchHit 也没有向本轮允许文件提供完整生效日期，使下游不能补回 scorer 前的过滤保证。

这属于 PRODUCT_ASSERTION_FAILURE，不是环境问题、桩问题或旧前提失配。修复需要额外授权修改时间准入边界；本轮不越界、不隐藏来源、不改 status/policy 来制造通过。原始 observations/G1_final/B09_future.json 和 junit/G1_final.xml 保留复现。任务二因此仅部分完成。

## 5. 实际测试成绩

| 阶段/组 | 通过 | 失败 | 说明 |
|---|---:|---:|---|
| 修改前 G1_red | 16 | 43 | 真实产品断言 RED，不是导入错误 |
| 初始实现 G1_initial | 58 | 1 | B09_future |
| 最终 G1 固定新增矩阵 | 58 | 1 | B09_future 仍失败 |
| 最终 G2 原 25 项 | 25 | 0 | 两个冻结文件逐字节不变 |
| 最终 G3 相邻回归 | 66 | 0 | 五个指定文件，没有跑全 tests |
| 最终 G4 原外部 14 项 | 13 | 1 | 唯一上述旧 LLM 前提失配 |
| 最终 G5 修改文件 lint | - | - | PASSED；首次 lint 的 37 项问题和失败日志也保留 |
| G5 既有离线 verifier | - | - | ARTIFACT_HASH_VERIFIED、AGGREGATE_REPLAY_VERIFIED、GOLD_METRICS_VERIFIED |

组和阶段有重复，不能累加为一个更大的“全部通过”数字。全部实际执行命令、cwd、起止时间、退出码、逐 node 结果和字节摘要见 TEST_RESULTS.json，含首次与最终运行。verifier 是历史字节/算术重放，不是业务矩阵全通过。

现有环境没有测试阻断或 skip。导入来源检查覆盖 9 次 pytest 的记录，app.* 与 tests.* 均来自真实修改工作树。离线保护仅给 stdlib socketpair 内部操作最小例外，不允许一般 localhost 访问；没有被拦截的联网尝试。真实模型调用为 0；桩调用次数按可观测用例记录，不把真实模型 0 次误写为所有桩 0 次；没有全局桩计数的组保留 null/NOT_VERIFIED。

首次 lint 后只进行了格式整理、同一原 fixture 的绑定形式修正和等价简化，没有改冻结预期。所有测试运行前后源码指纹一致。未改原测试、没有 skip、xfail、删除失败或让模型桩更聪明。

## 6. 历史口径纠错

原审核包实际有 4 项 RAW_OMISSIONS，REDACTION_MAP 为 []，没有所声称的 REDACTED_*.xml。此前关于交付完整脱敏 XML 的表述不准确。本轮不回写历史报告，而在 HISTORICAL_ERRATUM.json 明确纠正。可访问本地原 XML 的摘要不是向独立审核者交付 XML；本轮也没有提供历史完整 XML，更没有制造占位文件。

历史 3692/36、19/6 不是本轮成绩，未复跑。历史 WixQA 是 200 题、四配置 800 排名、first-distinct-article 后取 5 的检索评测，不是答案准确率或本轮修复提升。Dense 65.92%、raw20 72.25%、raw50 74.25% 为已消费的 retrospective 检索结果，不是新冻结独立测试。97 条 short Hybrid 是 97/200（该配置），不是各配置都如此。

历史服务 775 = 680 主请求 + 35 warm + 60 resource；40 个 synthetic case families 不等于真实企业用户。既有 9 次 HTTP503、1074 attempts 与 over-cap 7 不因本轮交付被消除。默认 Hybrid 未切换，Top20 仍为可选 GPU 配置。未实现 learned ranker。

## 7. 能展示什么

以下最多五项是可重放的**离线固定桩演示**，不是已执行的真人/真实模型验收。用 TEST_RESULTS.json 中 G1_final 的真实命令和测试文件复现，按对应 observations 查看输入、最终响应和 spy：

1. A05：明确审批主体，观察 answered 和绑定引用。
2. A03：未说明审批人，观察 partial，区分未知与免审批。
3. A14：提交天数和审批人双问，观察保留 7 天、引用及正文缺项。
4. B01：同作用域 7/30 天冲突，观察双引用 partial、host 拦截与 0 次生成。仅展示确实当前适用的输入，不能宣称未来生效隔离已解决。
5. B10_acl：被 ACL 排除来源不进入模型边界，核对 spy；此有限用例不等于整个安全系统获得全面证明。

不能宣传：任意问法语义完备、所有时间有效性安全、真实模型准确率提升、所有测试通过、生产就绪、独立人审完成、历史检索成绩是本轮提升。

## 8. 最多三条有依据的简历草稿

1. 为企业 RAG 增加有限审批与复合问答发布契约，缺项返回 partial 并保留已支持事实和引用，使用固定及对抗桩回归验证正文、状态与 trace 一致性。（限离线用例，不写真实模型准确率。）
2. 构建未提交修复的可追溯审核交付，绑定源码指纹、逐项测试/JUnit 和补丁，验证补丁与完整修改文件均能重建最终字节；如实保留失败与历史证据缺项。（不称独立安全认证。）
3. 在已消费的 WixQA 200 题回顾性检索评测中，raw-chunk Top20 重排配置的 Macro Recall@5 为 72.25%，Dense 为 65.92%。（属于历史检索实验，不是本轮新效果或答案准确率；模型/延迟须沿用原实验报告完整限定。）

## 9. 交付重建与未执行项

changes/RECONSTRUCTION.json 记录：本轮 patch 在起始快照私有副本执行 git apply --check 和 apply 成功，变更文件最终字节一致；完整 files/ 覆盖起始快照后全部 942 scoped 文件一致。未从 HEAD 创建一个遗漏既有未提交修复的替代版本。

本包是本轮增量交付，不重复复制全部历史包。独立审核必须同时使用：原运行审核 ZIP、原独立复核 ZIP、本轮 ZIP；原包 source_current 是重建基础。本包 TASK.md 为唯一执行标准。

没有运行：真实模型、真实网络端到端、人工审核、生产验收、历史完整套件、800 排名 benchmark、680 主请求或新调参。人审 NEEDS_HUMAN；上述运行 NOT_RUN。没有提交或推送。所有正式交付文件由 ARTIFACT_MANIFEST.json 覆盖（排除清单自身），ZIP 摘要在包外。

私有 scratch、缓存、虚拟环境、模型权重、生成身份密钥和 JWT 不属于交付。本包保留本机路径以便定位，属于审核交接材料，不自动公开上传。

至此停止。剩余 B09 与 RED 测试全文归档缺项均已披露，本轮不进行额外功能开发。

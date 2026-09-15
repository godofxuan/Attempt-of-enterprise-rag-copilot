# Query Coverage V2 全面回归复测（2026-09-09 至 09-10）

## 先说结论

本轮是测试，不是再次修改产品。当前可执行的主线测试、外部检索、真实模型问答、安全、认证 API 与并发探针已执行；结果**不是全绿，也不支持“整个项目效果大幅提升”**。

- WixQA 重排配置的 Recall@5 **74.25%**、nDCG@5 **59.93%** 已重新运行确认，800 条配置结果的排名与历史完全一致。
- 软件回归合并去重后 **3881 项通过，32 项因环境跳过**；通过测试不等于回答质量合格。
- 合成企业库的真实模型问答仍有遗漏、过度 partial 和未找到答案的问题。
- 实际认证 API 的 240 次主请求中，合同通过 **170/240（70.83%）**；存在 **5 次 answered 但合同失败**，涉及停车位和退款争议两类问题。
- 没有修改业务源码、测试断言、标签、生产索引指针、默认配置、简历或 GitHub 发布状态。失败没有被修饰为通过。

因此：保留已有检索成果；不晋升新“整体质量提升”结论。下一步应优先修复回答关系匹配、时间单位识别、生成与引用契约兼容性和服务就绪抖动，而不是增加检索模型。

## 真实版本与环境

实际测试目录：`LOCAL_PATH_REDACTED`。

- 分支：`fix/runtime-closure-20260907T160738`。
- HEAD：`b07c03d0256c393db5dfbb969e5d20abd70155b0`，加既有未提交的 correctness、Query Coverage V1/V2 修改。**只 checkout 这个 SHA 不等于本轮源码**。
- 本轮 945 个 Python 文件的哈希映射指纹：`b969462ec009499974a645c56ba5d96bfffd19d3816482fdcf7babed6d760174`。开始与结束相同。
- Windows / Python 3.11.9 / RTX 5060 8151 MiB。标准虚拟环境与现有 CUDA 环境分工，没有安装依赖或下载模型。
- Embedding：Ollama `bge-m3`；重排：本地 `BAAI/bge-reranker-v2-m3`，固定 revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`。
- 企业问答、认证 API、合成安全真实模型：`qwen2.5:3b`。FinQA 与 garak 改编子集：`qwen3:8b`。
- 只使用现有本地 Ollama。全部新缓存、临时数据、结果放在 D 盘。GPU 测试串行执行。

模型 digest、数据与索引 hash、命令、实际导入来源见证据目录的 `START_STATE.json`、`runs/*/command.json`、`imports.json` 和各实验 manifest。

## WixQA：真正重测了什么

同一份已使用的 ExpertWritten 200 题、同一索引，重新执行 embedding、检索、Guard 和相应 BGE 重排，共 800 条结果，并逐条重新计算金标准指标。

| 配置 | Macro Recall@5 | nDCG@5 | MRR@5 | Hit@5 | 全部 gold 找齐@5 | 本轮检索 p95 |
|---|---:|---:|---:|---:|---:|---:|
| Hybrid 默认配置 | 56.00% | 45.07% | 44.12% | 63.50% | 48.50% | 700 ms |
| Dense reference | 65.92% | 52.08% | 49.97% | 72.50% | 59.50% | 519 ms |
| Safe raw20 + BGE | 72.25% | 59.20% | 58.01% | 79.00% | 65.50% | 472 ms |
| Safe raw50 + BGE | 74.25% | 59.93% | 58.40% | 81.50% | 67.50% | 1052 ms |

800/800 的 article/chunk 排名、状态和六项指标与 `wixqa_serving_B_v2b` 历史结果一致，**本轮质量 delta = 0**。200 个英文问题经过本轮有限中文归一化后均未改变。

表中延迟是 Guard/检索/重排组件计时，**排除共享 query embedding 和 warmup，不是 HTTP 端到端 p95**。同机运行时资源条件、先前 CPU 检索任务可能影响延迟，不能从表中推出 raw20 天生比 Dense 更快。

另生成 `WIXQA_CUTOFFS.json`：从本次实际 top5 输出派生 @1/@3/@5 的 Recall、Precision、Hit、nDCG。它不代表另跑了一个 top3 工具配置，也没有用于选参数。

例如 raw50 的 Recall@3=64.33%、nDCG@3=55.42%、Precision@5=18.20%。Precision 的分母是 5；若一道题只有一篇 gold，完美检索的 Precision@5 也只有 20%。不要把这个数字当作答题正确率。

74.25% 是 raw50 配置的证据检索指标，不是默认 Hybrid 的指标，不是答案准确率，也不是新增独立测试收益。已有 Dense→raw50 的差异得到复核；不能写成“本轮再提升了 8.33pp”。

## 其他检索与问答

| 测试 | 本轮规模 | 核心结果 | 口径 |
|---|---:|---|---|
| EnterpriseRAG-Bench FTS5 | 511,962 文档，470 题 | 文档 Recall@5 60.37%，nDCG@5 55.89%，MRR@5 57.96% | 固定全文 BM25 组件，不是 BGE 重排方案 |
| FinanceBench | DEV 49 题 | 文档 Recall@5 100%；Page Hit@5 48.98%，Macro Page Recall@5 43.88%，Page nDCG@5 36.66% | 当前 dirty 快照的 DEV 组件回归 |
| UDA finance | DEV 64 题 × 3 配置 | Page Hit@5：BM25 67.19%，Dense 84.38%，RRF 79.69% | 给定 gold 文档内找页，不是全库检索 |
| FinQA | 已消费 DEV 100 题 × 2 条件 | Oracle 数值执行正确 64%，带引用约束 57%；Hybrid 数值执行正确 56%，带引用约束 49% | qwen3:8b + 数值程序；不是新 FINAL_TEST |
| WixQA 旧 Agent 适配器 | Simulated 200 + ExpertWritten 200 | 引用 Recall 分别 23.25% / 30.17%；多文档引用找齐均为 0 | 老 RRF 索引 + 抽取式回答，无生成 LLM、未测答案正确率 |

FinanceBench 使用实体限制 + top1 文档的 dense 页展开，candidate_k=20、top5；没有在这些结果上重新调参。UDA 是原 DEV 基础三臂，不等于 R3/R4/R5 的一轮新确认实验。

FinQA 的 Hybrid 证据 Recall 为 91.98%，引用 Precision 87.20%、Recall 81.07%；1/100 格式/协议失败保留计入。Oracle 直接给正确证据仍只有 64%，说明算式与生成本身也是瓶颈，不能全怪检索。

WixQA 旧 Agent 的 400 题是单独的旧检索/工具适配链，不是上述 raw50 的端到端答题成绩。ExpertWritten 搜索证据 Recall 为 59.00%，最终引用 Recall 30.17%，平均 find/open 均为 0；说明“检索到”到“最终用上”确实有损失。该脚本的 `answered_rate` 不是准确率。

## 合成企业库的分层结果

核实并分开使用 72、240、2000 文档三套库，不混淆数据规模。240 文档库与当前真实 BGE 索引的 corpus manifest 匹配。

| 运行 | DEV 全层通过 | TEST 全层通过 |
|---|---:|---:|
| 72 文档，确定性 hash embedding + 抽取 | 20/24 | 24/28 |
| 240 文档，确定性 hash embedding + 抽取 | 40/48 | 45/56 |
| 2000 文档，确定性 hash embedding + 抽取 | 40/48 | 45/56 |
| 240 文档，真实 BGE + Qwen 3B | 27/48 | 27/56 |

真实模型 TEST 的**回答层**通过为 28/56（50%）；再合并 Agent 轨迹等层后为 27/56（48.21%），不要混用这两个数字。DEV 回答层 27/48。

真实模型两组的检索层与安全层均通过，但回答层不是。DEV 8 个、TEST 9 个版本治理类问题没有达到预期回答结果。已有金标准文档能被检索，并不保证 Controller 接受它、生成正确引用，或正文完整。

回答层所谓 `atomic_fact_completeness` 主要依据被引用 chunk 的 `fact_ids`，不等于逐项检查模型正文语义。引用 Correctness=100% 也仅针对有 claims 的子集（DEV 24、TEST 30 个回答），不能宣传为 104 题全部回答正确或无幻觉。

## 实际认证 API 与服务

使用真实 FastAPI TestClient、JWT 身份、生产调用链、BGE/Qwen、独立复制的索引版本。40 个冻结案例 × 2 配置 × 3 次重复 = 240 次主请求；另有 10 次 warmup、24 次并发探针。不是公开网络 SLA 测试。

| 配置 | 本轮合同通过 | 同协议旧结果 | 本轮 p95 | answered 但合同失败 |
|---|---:|---:|---:|---:|
| Hybrid | 86/120（71.67%） | 87/120（72.50%） | 2.15 s | 3/66 answered |
| Safe raw20 + BGE | 84/120（70.00%） | 96/120（80.00%） | 3.43 s | 2/62 answered |

旧结果来自 `service_C_repair_v1`，协议 hash 相同。但跨越多次代码变化、模型未固定 seed、资源环境未严格隔离，**这不是 V2 单因素因果实验**。本轮服务质量确实没有显示全面提升，raw20 还有 1 次 deadline 导致 system、6 次 `service_not_ready` HTTP 503；没有排除这些失败再重算漂亮结果。

240 次主请求中的非法引用、未授权来源、禁止内容发布、已定义安全失败均为 0。这与“回答相关、完整、正确”是不同的检查。并发 1/2/4 各点、两配置的 24 次探针均满足该简单案例合同；每点只有 4 次请求，不能据此承诺生产吞吐或容量。

## 确认的失败与下一步优先级

### P0：答非所问却 answered

实际 API：

- “地下停车位能保证每人固定一个吗？”回答成“培训报名每人每季度最多 2 次”，仍为 `answered`。本轮出现 3 次；同位置的旧运行曾通过。
- “退款争议处理期限是多少天？”回答“客户退款审核通过后在 7 天内原路退回”，仍为 `answered`，出现 2 次。争议处理与普通退款到账不是同一关系；该旧运行也有失败，不能说是 V2 新引入。

5 次涉及 2 个不同问题，不是 5 道独立题。正文、引用、request ID、完整 trace 和原协议保存在 `SERVICE_FAILURE_OBSERVATIONS.jsonl`。这直接反驳把上一轮 36 题“错误答全为零”推广到所有输入。

后续应先为对象、动作和所问关系建立反例，保证未知问题不能凭泛化关键词取一个带数字的句子发布 answered；不能通过放松引用校验解决。

### P0：已经回答 7 个自然日，却又说没有天数

真实模型诊断输出：“当前制度要求差旅结束后 **7 个自然日**内提交报销。当前已核验的回答尚未确定所问的天数。”状态 `partial`。

最小组件复现确认：`answer_contract.py:11` 的时长识别接受 `7 天`，不接受 `7 个自然日` / `7 个工作日`。HEAD 中已经存在这个表达式，属于本轮发现的既有覆盖缺口，而非已经确认的 V2 新回归。`DURATION_PROBE.json` 保留三个实际返回值。

后续应在保持“自然日”和“工作日”语义区别的前提下修复有限单位识别；不能把所有单位都替换为天。

### P1：生成和证据边界不兼容、保守回退丢内容

6 个追加诊断中，销售折扣、跨制度比较、工程值班出现 `critical_fact_requires_bound_span`，随后转为抽取式 partial。比较问题两次 search 和两个方面均有覆盖，最后只保留其中一个制度；必须检查 claim/span 构建与多来源 fallback，而不是直接增加 search 次数。

“以当前生效且权威的制度为准……”的隐私请求案例：搜索有 5 条结果，Controller 的支持数仍为 0，直接 `not_found`，未进入生成。这里是证据接受判断的诊断线索，不能说是模型算错。六条观察是追加诊断，不覆盖原 104 题结果；其中访客完整性题在追加运行中通过，说明生成存在波动。

### P1：就绪与延迟波动

一次 deadline 和随后某轮的六个 503 是不同观察，不预设同一个根因。后续需要把 readiness 探测、模型冷加载、队列和 deadline 的时间线关联起来；本轮不增加超时配置把失败隐藏。

### P2：评分口径与静态质量

需要补请求级关系正确性和实际正文覆盖检查，不能只依赖 chunk 的 fact_ids 或 exact-span 引用。全库 Ruff 查出 1173 项，主要是导入/格式/现代化建议，并不等于 1173 个运行 bug；CI 当前指定的 lint/format/type-check 范围则通过。本轮不做无关的大规模格式重写。

## 安全、身份与软件回归

- 原全量 pytest：3877 passed / 36 skipped / 3 SWIG warnings。补齐本地已有数据路径后，17 个定向测试全部通过，其中 4 个是此前跳过项，另外 13 个重复覆盖。因此合并去重：3881 passed / 32 skipped，不是 3894 个独立通过项。
- 945 个 Python 文件语法检查通过；pip check 通过；CI 指定 Ruff、format、mypy（8 个类型检查文件）通过。全库 Ruff 不通过，原始清单保留。
- 240 与 2000 文档的 materialized corpus quality 检查通过；冻结质量评审包的完整性验证通过，**不是完成了人审**。
- Trusted Identity 20/20，14 个拒绝案例无意外副作用，无凭据泄露。
- 确定性注入 dev/test 各 36 对，两组门禁通过；确定性桩结果不冒充真实模型结果。
- 真实 Qwen 3B 注入 dev/test 各 36 对。TEST 攻击成功率 Guard OFF 3/24（12.5%）→ ON 0/24；正常任务 12/12、可恢复混合任务 20/20；未见模型格式错误。15 个到达 Guard 的攻击单元均隔离，另有 13 个攻击单元没被召回，不能把未召回当作检出。
- garak latent-report 改编子集 16 对：12 攻击 + 4 正常，Qwen 8B。ASR 2/12→0/12，4 个正常任务均保留；但全部任务 utility 从 14/16 降到 4/16，因为攻击污染材料被隔离后没有替代证据。不能只报 ASR 而隐藏可用性损失，更不能说通过了完整 garak。

## 未执行与限制

“全面复测”指当前主线的各类验证，**不是重做所有历史调参、训练与冻结实验**。

- 32 个 pytest 跳过项：2 个 PostgreSQL 集成测试缺少 `TEST_POSTGRES_DSN`，其余为 Windows/POSIX、符号链接权限、8.3 路径等环境约束。没有安装 Docker/PostgreSQL，也没有运行新的 Linux 容器或远端 CI。
- FinQA 原冻结 FINAL_TEST、UDA R3/R4/R5 一次性确认未重新开启。用户询问的广泛复测不被解释为废除旧停止规则；已经提出单独授权选择，无答复时按保留冻结规则处理。
- FinanceBench 等要求 clean Git 的正式发布 CLI 不被伪装通过；这里明确交付当前 dirty 快照的 DEV 组件回归。没有新独立泛化结论。
- 未运行新的 learned ranker 训练、参数 sweep、更多模型、LLM judge、人审、浏览器人工验收、全量索引重建性能实验，也没有改写历史 G4/B09 等失败证据。
- WixQA 没有新增真实生成模型的答案正确率评测；400 题旧 Agent 测的是工具与引用，不补造缺少的答案标签。
- Harness 第一轮离线全套、第一次服务入口和第一次安全入口曾因测试工具边界/路径适配失败。原日志保留；只修新测试工具，未改产品或冻结测试。详见 `ENVIRONMENT_ERRATUM.md`。
- Harness 不是 OS 级沙箱；每个原生产源码 hash 与导入路径有记录，但没有为每次早期 launcher 修改都保存独立源码版本。最终 manifest 的 helper hash 代表交付版本，不伪称全部早期运行都用它。

## 证据在哪里

本轮目录：`LOCAL_PATH_REDACTED`。

- `SUMMARY_20260910T001654.json`：汇总各组实际结果、源码和输入未改变检查。
- `runs/*`：原命令、输出、JUnit、源码指纹、导入路径；原失败仍在。
- `wixqa_serving_800/`、`WIXQA_RECOMPUTE.json`、`WIXQA_CUTOFFS.json`：800 条原排名、重算与不同 K 指标。
- `enterprise/`、`enterprise_rag_bench/`、`financial/`、`wixqa_agent/`：各数据集逐题结果和失败。
- `security_live/`、`security_deterministic/`、`identity/`：真实模型、确定性桩与身份验证分开保存。
- `service_repair_240_async/rows.jsonl`、`SERVICE_ANALYSIS.json`、`SERVICE_FAILURE_OBSERVATIONS.jsonl`：所有 API 请求与 70 次合同失败。
- `enterprise_diagnostics/observations.jsonl`、`DURATION_PROBE.json`：6 个追加完整响应与有限时长组件反例。
- `MANIFEST.json`、审核 ZIP 与 `DELIVERY.json`：交付文件摘要与实际位置。ZIP 不含模型权重、原始 PDF 大库、临时凭据或缓存，不是完整安装包。

本轮没有修复这些新发现，也没有把任何通过数或质量数字更新成简历新成绩。下一步先形成上述真实失败的定向 RED，用小改动修复，再在同一固定范围回归；不靠更多检索方案掩盖回答和服务问题。

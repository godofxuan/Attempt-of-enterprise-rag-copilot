# 旧证据复算与身份核对

本轮不重跑历史模型检索/680 主请求，不提高旧成绩。`VERIFICATION_REPORT.json` 是新工具在冻结数据上的离线结果。

## 三层能力

| 层级 | 实际操作 | 结果/边界 |
|---|---|---|
| ARTIFACT_HASH_VERIFIED | 按旧 manifest 原字节核对3个服务文件；另核对 retrieval 与新 gold 的绑定，旧目录逐文件 Git blob/checkout 摘要 | 已核对；`historical_bytes.json` 不把 CRLF 与 LF 当相同字节 |
| AGGREGATE_REPLAY_VERIFIED | 从775服务行复算87 CSV组、配对计数；从800检索行已存分数汇总 | 已核对；这一层本身不证明 gold 分数正确 |
| GOLD_METRICS_VERIFIED | 从已有合法 frozen candidate 导出200个 question->gold article ID映射，与公开 article_ids 重新计分 | 全800行吻合；不是重新运行 embedding/retrieval/reranker，不证明标签独立 |
| Exact byte export | 原 exporter 从冻结私有输入导出到新的隔离目录 | 5/5文件原始字节相同，未删除时间戳/转换换行；见 `BYTE_EXPORT_REPLAY.json` |

新增 gold 来源 hash：`73d5f994b6553e823914ccc98c247e1c953bfa81c2c90a1a97b67db26595f136`。
使用原有 question pseudonym 与文章 SHA256 ID，不导出问题/文档文本，不构造 graded labels；稳定哈希不等于绝对匿名。
独立复算现在只需仓库旧公共证据、新 `retrieval_gold.json` 和新脚本；原始 exporter 的字节重放仍需对应私有 rows/completion/summary 输入。两种复现不要混淆。

## 历史身份表

| 角色/运行 | 实际 SHA | dirty 与来源边界 |
|---|---|---|
| 本轮审核基线/HEAD | c9984e92a10a6f417e2c1d8082af7e8f1e11aee1 | 原 main clean；修复在新 worktree 的未提交补丁 |
| WixQA B-v2b | d27c0f8a68830fd74bbb983567e8b4d50967c0ae | dirty=true；source_sha256=5e4e8860d86a3224af3a2afd572036ad2b99a345f202ae0c0b1556a1617f04d0；未恢复该整个 dirty 源码归档 |
| service_C_v1 | d27c0f8a68830fd74bbb983567e8b4d50967c0ae | 前后 dirty=true；312 app 文件摘要和 harness 摘要前后相同，但该 SHA 不是当时全部代码 |
| service_C_repair_v1 | c33484c93eebe242478cc7354cdbf087392ba12f | 初始 clean、结束 dirty；app/harness摘要不变，不能简称“全程 clean” |
| service_C_readiness_v1 | 0bca9534fd0cf9d4b02d65c1c46de1a8fec67a4f | 前后 clean；实际312文件摘要单列 |
| 历史独立检出/公开证据提交 | e276209bae4544ad54405a282448ab07cf01d8e5 | 旧 XML 字节核验得到3650 passed/36 skipped；未在本轮重复执行该历史测试 |
| 指定最终历史 CI | c9984e92a10a6f417e2c1d8082af7e8f1e11aee1 | run34092932571四个job success，API已核对；不覆盖本轮 dirty 修改 |

312 app 文件逐项比较见 `HISTORICAL_SOURCE_CHECK.json`：repair/readiness有309个Git blob精确匹配、1个显式CRLF构造匹配、另2个原工作区字节匹配且去CRLF后与Git blob相等。后两者不能标作原Git blob精确匹配。
baseline对应SHA中23个文件不能仅靠Git blob/统一CRLF转换匹配；对照原工作区后仍有 `app/agent/evidence_ledger.py`、`app/runtime/serving_resources.py` 没在本轮取得其当时精确字节。这里只检查列出的来源，不声称已穷尽所有历史对象。
哈希能绑定已取得内容，不能恢复丢失的文件。历史结果的算术复算成立，不自动消除历史源码重建缺口。

本轮worktree中旧目录15个文件全部与固定SHA的Git blob精确一致。原工作区的三份SERVICE协议采用不同的checkout换行字节；旧运行manifest绑定的是原工作区协议hash。`PROTOCOL_CHECKS.json`分别保留这些原字节hash和Git blob hash，并单列去CRLF后的等价检查，不能称它们原始字节相同。五文件export重放的精确一致不意味着所有协议也无换行差异。

原协议模型为 BGE-M3 embedding、qwen2.5:3b answer、qwen3:8b evidence/readiness；本地 tags 中另有 coder 模型不表示实际用了它们。
BGE reranker为 `BAAI/bge-reranker-v2-m3`，revision `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e`，六文件身份绑定；对应摘要保留在原manifest和本轮准备失败协议。
WixQA index manifest：`e6b5f2a9e6e91e47f3601c015d4309742abbacd3c30343814ed60ca5da038ad9`。
使用原FAISS/BM25、相同有序chunk/text，仅添加benchmark用ACL/version metadata；不是完整企业索引，也不能open。
服务则使用隔离synthetic base/updated/deleted索引，和外部检索不是同一个cohort/index。各 protocol/index 身份见 `PROTOCOL_CHECKS.json`。

## 正式指标定义与逐项对照

源码 `scripts/eval_runtime_wixqa.py::metrics` 先将返回文章ID**完整去重，再截前5篇不同文章**，不是固定原始前5个chunk位置。
每题 Recall 的分母是该题全部gold文章数，总体对200题等权宏平均；失败空排名按0保留。空gold在新工具中报INVALID，不用LLM补。
MRR用不同文章排名中首个相关位置的倒数，无命中为0。nDCG为binary gain(0/1)，discount=1/log2(rank+1)，IDCG取min(gold数,5)个相关项；同篇文章不重复贡献gain。
97条排名有文章重复、对应97条不同文章不足5篇，均保留并按既定公式计算，没有补排名或改分母；这些属于Hybrid结果的配置差异，不是清洗理由。
四个配置同200个question ID、每(question,profile)唯一，共800条，全部status=ok，无缺题/额外题。指标全精度计算，容差1e-10；计数严格整数，ID、排名、hash不使用浮点容差。

| 配置 | Macro Recall@5 | nDCG@5 | MRR@5 | 对旧声明 |
|---|---:|---:|---:|---|
| hybrid_default | 56.00% | 45.07% | 44.12% | 一致 |
| dense_reference | 65.92% | 52.08% | 49.97% | 一致 |
| safe_dense_raw20_bge | 72.25% | 59.20% | 58.01% | 一致 |
| safe_dense_raw50_bge | 74.25% | 59.93% | 58.40% | 一致 |

Dense -> raw20为+6.33个百分点Recall、+7.11个百分点nDCG、+8.04个百分点MRR。这是旧的已使用公开题回顾性检索结果，不是本轮修复带来的新提升。
历史其他协议66.42/72.50/74.50不混入这张表。Hybrid每文档最多2块，Dense族为1，candidate_k均200；不是只改变RRF算法的单变量消融，也不是stock controller较小候选请求的直接计时。

## 服务计数、配对、自动规则

| run | main | warmup | resource | 总行 |
|---|---:|---:|---:|---:|
| service_C_v1 | 360 | 15 | 36 | 411 |
| service_C_repair_v1 | 240 | 10 | 24 | 274 |
| service_C_readiness_v1 | 80 | 10 | 0 | 90 |
| 合计 | 680 | 35 | 60 | 775 |

main的唯一键是run/profile/case/repeat；共40个不同case，重复测量不是680个独立问题。
warmup/resource公共行缺实际request_id，用case/repeat会出现合法重复；本轮额外读取原行，分别411/274/90个request_id均存在且各run内唯一。没有造新键去假定公共导出可以单独证明全部请求身份。
attempt来自模型transport/structured重试，属于一个逻辑请求的成本，不增加问题数量。
87行CSV是每run/profile/kind的all、contract_complete、contract_failed包含分组；不得累加这些n得观测总数。

只配对前两run共有的profile/case/repeat，每臂120对；第三run只有一轮且独立readiness修复，单列不能补进三轮配对。

| 配对配置 | retained双方完成 | gained改善 | regressed回退 | missed双方未完成 |
|---|---:|---:|---:|---:|
| Hybrid | 77 | 10 | 8 | 25 |
| raw20 | 85 | 11 | 5 | 19 |

以上由逐行 checks 重新计算。`eval_runtime_service.score` 检查期望mode、配置的必要facts/来源、引用可见性与有限canary/越权计数。`contract_complete`不是人工语义准确率；`source_complete`也可能因无必须source而真，不能证明回答充分。
repair Hybrid的9个503全部保留。最后80个main无503只能描述这次run；readiness半TTL修复有确定性机制反例，但不能从缺少逐probe历史日志推断9次故障必定同根因。

## 延迟口径

- 单位均ms，quantile按排序后位置(n-1)*q线性插值；均值为组内算术平均、最大值直接max，空组null；全量/完成/失败分组分开。
- 检索timer包含serial检索、应用准入、scorer，shared query embedding另计，初始模型warmup另计；不含answer、HTTP、真实客户端网络往返。
- Dense/raw20/raw50检索p95分别335.58/333.94/754.46ms。单次不同题目的尾部不能证明raw20比Dense更快。
- 服务client_ms从ASGI TestClient发起到响应返回，包含应用调度、实际query embedding、检索、Guard、rerank(若启用)、生成/重试；不包含块启动warmup及外部用户网络。不是互联网端到端SLA。
- 服务每run/profile/kind的模式/错误计数在VERIFICATION_REPORT，额外mean/p50/p95/max及错误分类在SERVICE_DESCRIPTIVE_STATS；503、timeout、取消不能从all中删除。

历史检索共1074条尝试=267中断v1+7失联v2+800完整v2b，超过修订1067预算7条。完整800是完成cohort，不是历史总成本；原失败与偏离不能被本轮复算抹掉。

## 可直接执行的离线复算

从原项目根目录的PowerShell执行，输出目录使用新名字；已存在则工具拒绝覆盖：

```powershell
Set-Location -LiteralPath '.private\runtime_closure_20260907T160738'
$python = (Resolve-Path -LiteralPath '..\..\.venv\Scripts\python.exe').Path
& $python -B -m scripts.verify_runtime_closure --evidence docs/review/runtime_delivery_20260905 --gold-directory docs/review/runtime_closure_followup_20260907/20260907T160738+0800 --output .private/reviewer_offline_replay_01
```

0=范围内完成、2=资料不足、3=输入无效/不匹配、4=工具内部异常。缺gold返回2而非“全部通过”。本轮最终源码的实际命令、时间、退出码见TEST_RESULTS的release_evidence_replay。

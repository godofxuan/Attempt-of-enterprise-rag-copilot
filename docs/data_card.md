# Enterprise Agentic RAG v2 Data Card

版本：`enterprise_facts_v1`（历史）/ `enterprise_facts_v2`（当前）

当前扩展版本冻结日期：2026-07-24

当前默认 profile / seed：`expanded` / `20260724`

历史 v1 默认 seed：`20260716`

## 1. 数据声明

本项目 v2 档案、用户、部门、制度、邮件、工单、会议和评测问题**全部为虚构合成**，不包含真实企业、真实员工、客户、合同、账号或商业机密。公司名“星桥科技”也是虚构名称；`example.invalid` 域名不能用于真实邮件投递。

这些数据用于本地 Enterprise Agentic RAG 工程演示和评测 contract，不代表任何真实公司的制度，也不能用于劳动、财务、法务、安全或采购决策。

## 2. 为什么先建立事实骨架

生成器不让 LLM 自由编写数百份 gold 材料，而是从版本化权威事实文件派生文档和 gold cases。当前 `expanded` 使用 `data/v2/facts/company_facts_v2.json`；历史 `demo/benchmark` 继续使用 `company_facts_v1.json`。这样可以回答：

- 当前值和历史值分别是什么；
- 哪个版本生效、哪个版本已废止；
- 哪个部门和 ACL group 可以读取；
- 哪些文档是权威制度、辅助记录、重复、近重复、误归档或过期材料；
- 每道题的 required facts、可见 gold 文档和不可见 forbidden 文档是什么。

v1 事实骨架包含 8 个制度族、16 个版本、32 个原子事实。v2
扩展为 20 个制度族、40 个版本、104 个原子事实，其中 52 条属于当前
active 版本，并覆盖 12 个部门、15 个 fixture users 和 15 个 ACL groups。
每个制度族恰好有一个 `active` 版本和一个 `retired` 版本，当前值与历史
值故意存在冲突，用于测试版本和 authority 处理。

## 3. Profile 和实际规模

| Profile | 文档数 | 用途 | duplicate | near duplicate | misfiled | stale |
|---|---:|---|---:|---:|---:|---:|
| `demo` | 72 | 本地开发、UI 和快速评测 | 5 | 7 | 4 | 7 |
| `benchmark` | 600 | 规模化 deterministic 评测和后续性能 profile | 60 | 72 | 48 | 72 |
| `expanded` | 240 | 当前默认知识库和本地 live 评测 | 12 | 19 | 12 | 24 |
| `expanded_benchmark` | 2,000 | parser/dedup/index 规模验证 | 160 | 200 | 140 | 240 |

这里的“文档数”是生成器实际构造的逻辑文档数量，不是 chunks
数量。2026-07-24 的真实 fixed-chunker 构建中，`expanded` 的 240 个源文档
经治理后得到 216 个 canonical documents 和 216 个 BGE-M3 chunks；
`expanded_benchmark` 的解析干跑从 2,000 个源文档得到 1,225 个 canonical
documents/chunks，但未嵌入或激活。

四种 profile 都覆盖 Markdown、TXT、HTML、CSV 和 JSONL，并覆盖正式制度、
Wiki、邮件、工单、会议和表格来源。PDF/DOCX parser fixture 属于独立解析
测试，不冒充本次生成语料已经包含真实办公文档。

## 4. 治理字段

每个逻辑文档在生成 manifest 中记录：

- `doc_id`、相对路径、格式、来源类型、内容 SHA256 和字节数；
- `policy_id`、`version_id`、版本状态、有效期、`supersedes` 和 authority；
- 实际部门与归档部门，用于识别 misfiled；
- tenant、region、ACL groups；
- variant、`duplicate_of` 和包含的 atomic fact IDs。

ACL 是演示用确定性访问模型，不等同真实 IAM。当前可见性规则是 tenant/region 相同且用户 groups 与文档 ACL groups 至少有一个交集。

## 5. 评测集

历史 `data/v2/eval` 共 52 个 v1 case：dev 24 个、test 28 个。当前
`expanded` 生成 104 个 v2 case：dev 48 个、test 56 个。两个 split 的 case
ID 互不重叠，并共同覆盖：

- `fact_lookup`
- `version_conflict`
- `completeness`
- `comparison`
- `permission`
- `no_answer`

case 保存 `required_fact_ids`、`gold_doc_ids`、`distractor_doc_ids`、`forbidden_doc_ids`、`UserContext`、expected filters、expected authority documents 和 answer mode。permission case 不把受限事实写进 expected answer。

历史 v1 test 文件已冻结：

```text
556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338  test.json
```

每个生成 profile 还会在自己的 `eval/test_manifest.sha256` 中冻结 test
bytes。dev 可用于实现和错误分析；**不得根据 test 失败调参**。本次 expanded
test 是冻结后的本地 regression，不能外推为独立领域 held-out。

## 6. Reproducibility

关键语义哈希：

| Artifact | SHA256 |
|---|---|
| canonical facts | `5b9ea4d719e97fcc2b288e548ccdd0db971ad594bd46fb937b2d44ab6f437417` |
| demo profile | `47330886214c65d3421224a222c490e57c0432737ebefb337c33250af47c3438` |
| benchmark profile | `11124ee443a5b3e21d71d12089ef09a2c832f6c63eeaac7a249ecec2c4dc48d3` |
| frozen v2 test bytes | `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338` |
| expanded canonical facts | `761fd6d2400721bcd669bc3417b4c1d3322d4f179cd584737044805e914c34b1` |
| expanded profile | `8bfe9da8f5dd063f971ef55ddcc9fbc8fb669c958f113df6fe91fc7311ad2787` |
| expanded benchmark profile | `d786a2616c66b6163c0ee67d179ee853df5360e350606123cc80e753468c3ff0` |

facts/profile 哈希基于 Pydantic 校验后的 canonical JSON；文档哈希基于实际 UTF-8 文件 bytes。manifest 不记录生成时间和绝对输出路径，因此同一事实、profile 和 seed 可以逐字节复现。

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --help
.\.venv\Scripts\python.exe -m scripts.eval_corpus_quality --profile expanded
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded --dry-run
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded --output-dir data\v2\generated\expanded
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded_benchmark --dry-run
```

`--dry-run` 不写文件。已有非空目标默认拒绝覆盖；`--force` 只允许替换带
本生成器有效 manifest 的目录。`data/v2/generated/`、`data/indexes_v2/` 和
`eval_runs/` 不进入 Git。可公开复核的最小结果位于
`data/v2/public/corpus_expansion_v2/`。

## 7. 可接受用途

- parser、normalization、chunking、dedup、版本和 ACL contract 测试；
- baseline/v2 retrieval、Agent、answer 和 security 评测；
- failure attribution、消融和面试演示；
- 小规模、本地、可重复的工程实验。

## 8. 不可接受用途

- 声称使用了真实企业内部数据；
- 将合成集指标解释为线上业务准确率；
- 用 test split 反复调 prompt、阈值或检索参数；
- 把 fixture ACL 当作真实鉴权系统；
- 将本地 parser/index/live regression 宣称为真实连接器、生产权限或线上性能。

## 9. 已知限制

- 当前事实域有 20 个制度族，仍以中文为主，模板结构比真实企业文档规整。
- supporting 文档与 gold facts 同源，虽然加入冲突、噪声和误归档，仍存在 synthetic shortcut 风险。
- 两个 benchmark 都是 deterministic scale profiles，不等于同数量真实企业材料的复杂度。
- 本次真实索引和 retrieval regression 使用一台本地机器与一个 BGE-M3 embedding model，不是跨环境性能结论。
- 人工抽检结论必须由本人填写，不能由生成器或 Codex 代填为“正确”。

## 10. 变更协议

修改 facts、profile、generator 或 eval builder 后，必须运行
`python -m scripts.eval_corpus_quality --profile expanded` 和
`tests/corpus`，并重新核对所有哈希。冻结 test 如确需修改，必须说明原因、
创建新 dataset version，并保留旧版本；不得静默覆盖历史
`data/v2/eval/test.json` 或已发布证据。

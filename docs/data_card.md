# Enterprise Agentic RAG v2 Data Card

版本：`enterprise_facts_v1` / `enterprise_corpus_profile_v1`
冻结日期：2026-07-16
默认 seed：`20260716`

## 1. 数据声明

本项目 v2 档案、用户、部门、制度、邮件、工单、会议和评测问题**全部为虚构合成**，不包含真实企业、真实员工、客户、合同、账号或商业机密。公司名“星桥科技”也是虚构名称；`example.invalid` 域名不能用于真实邮件投递。

这些数据用于本地 Enterprise Agentic RAG 工程演示和评测 contract，不代表任何真实公司的制度，也不能用于劳动、财务、法务、安全或采购决策。

## 2. 为什么先建立事实骨架

生成器不让 LLM 自由编写数百份材料，而是从唯一权威事实文件 `data/v2/facts/company_facts_v1.json` 派生文档和 gold cases。这样可以回答：

- 当前值和历史值分别是什么；
- 哪个版本生效、哪个版本已废止；
- 哪个部门和 ACL group 可以读取；
- 哪些文档是权威制度、辅助记录、重复、近重复、误归档或过期材料；
- 每道题的 required facts、可见 gold 文档和不可见 forbidden 文档是什么。

事实骨架包含 8 个制度族、16 个版本、32 个原子事实。每个制度族恰好有一个 `active` 版本和一个 `retired` 版本，当前值与历史值故意存在冲突，用于测试版本和 authority 处理。

## 3. Profile 和实际规模

| Profile | 文档数 | 用途 | duplicate | near duplicate | misfiled | stale |
|---|---:|---|---:|---:|---:|---:|
| `demo` | 72 | 本地开发、UI 和快速评测 | 5 | 7 | 4 | 7 |
| `benchmark` | 600 | 规模化 deterministic 评测和后续性能 profile | 60 | 72 | 48 | 72 |

这里的“文档数”是生成器实际构造的逻辑文档数量，不是 chunks 数量。E1 尚未运行 v2 parser、chunker、embedding 或索引，因此本数据卡不预填 v2 chunk 数、检索指标或延迟。

两种 profile 都覆盖 Markdown、TXT、HTML、CSV 和 JSONL，并覆盖正式制度、Wiki、邮件、工单、会议和表格来源。PDF/DOCX 解析 fixture 属于 E2，不在 E1 假装已经支持。

## 4. 治理字段

每个逻辑文档在生成 manifest 中记录：

- `doc_id`、相对路径、格式、来源类型、内容 SHA256 和字节数；
- `policy_id`、`version_id`、版本状态、有效期、`supersedes` 和 authority；
- 实际部门与归档部门，用于识别 misfiled；
- tenant、region、ACL groups；
- variant、`duplicate_of` 和包含的 atomic fact IDs。

ACL 是演示用确定性访问模型，不等同真实 IAM。当前可见性规则是 tenant/region 相同且用户 groups 与文档 ACL groups 至少有一个交集。

## 5. 评测集

`data/v2/eval` 共 52 个 case：dev 24 个、test 28 个。两个 split 的 case ID 和问题文本互不重叠，并都覆盖：

- `fact_lookup`
- `version_conflict`
- `completeness`
- `comparison`
- `permission`
- `no_answer`

case 保存 `required_fact_ids`、`gold_doc_ids`、`distractor_doc_ids`、`forbidden_doc_ids`、`UserContext`、expected filters、expected authority documents 和 answer mode。permission case 不把受限事实写进 expected answer。

test 文件已冻结：

```text
556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338  test.json
```

dev 可用于实现和错误分析；**不得根据 test 失败调参**。test 在首次正式 release evaluation 前只允许做 schema/hash 检查，之后的重复运行必须称为 regression，不再称 unseen held-out。

## 6. Reproducibility

关键语义哈希：

| Artifact | SHA256 |
|---|---|
| canonical facts | `5b9ea4d719e97fcc2b288e548ccdd0db971ad594bd46fb937b2d44ab6f437417` |
| demo profile | `47330886214c65d3421224a222c490e57c0432737ebefb337c33250af47c3438` |
| benchmark profile | `11124ee443a5b3e21d71d12089ef09a2c832f6c63eeaac7a249ecec2c4dc48d3` |
| frozen v2 test bytes | `556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338` |

facts/profile 哈希基于 Pydantic 校验后的 canonical JSON；文档哈希基于实际 UTF-8 文件 bytes。manifest 不记录生成时间和绝对输出路径，因此同一事实、profile 和 seed 可以逐字节复现。

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --help
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile demo --seed 20260716 --dry-run
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile demo --seed 20260716 --output-dir data\generated\demo
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile benchmark --seed 20260716 --dry-run
```

`--dry-run` 不写文件。已有非空目标默认拒绝覆盖；`--force` 只允许替换带本生成器有效 manifest 的目录。`data/generated/` 和 `eval_runs/` 不进入 Git。

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
- 在 E2-E5 尚未验收前宣称多格式 ingestion、权限零泄露或生产性能已经实现。

## 9. 已知限制

- 事实域只有 8 个制度族，语言以中文为主，模板结构可能比真实企业文档规整。
- supporting 文档与 gold facts 同源，虽然加入冲突、噪声和误归档，仍存在 synthetic shortcut 风险。
- benchmark 的 600 文档是 deterministic scale profile，不等于真实 600 份企业材料的复杂度。
- E1 只验证数据和生成 contract；尚未验证 parser 保真度、chunk 定位、索引一致性、ACL pre-filter、claim citation、live model 质量和并发性能。
- 人工抽检结论必须由本人填写，不能由生成器或 Codex 代填为“正确”。

## 10. 变更协议

修改 facts、profile、generator 或 eval builder 后，必须运行 `tests/corpus` 并重新核对所有哈希。冻结 test 如确需修改，必须说明原因、创建新 dataset version，并保留旧版本；不得静默覆盖 `data/v2/eval/test.json`。

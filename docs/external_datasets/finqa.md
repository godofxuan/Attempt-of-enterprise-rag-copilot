# FinQA 独立数值推理轨道

## 1. 为什么增加 FinQA

FinanceBench 当前主要回答“系统能否从完整财报集合中找到正确文档和正确 PDF
页”。它不能单独回答：

1. 正确证据已经给出时，本地模型能否完成多步财务计算；
2. 表格行和正文句子混合时，检索能否召回全部运算输入；
3. 最终数字正确时，模型引用的证据是否也是正确的；
4. `$1,200`、`1200`、`12%` 和 `0.12` 应该怎样可复现地评分。

FinQA 在真实财报的表格和文本上提供问题、支持事实、推理程序和执行结果。因此
本轨道补充 FinanceBench 的数值推理与证据引用评测，但不把 FinQA 的 evidence
unit recall 冒充 FinanceBench 的 PDF Page Recall。

## 2. 上游与许可边界

- 官方仓库：`https://github.com/czyssrs/FinQA`
- 固定 revision：`0f16e2867befa6840783e58be38c9efb9229d742`
- dev SHA-256：`a847fb7e...4deee51`
- test SHA-256：`831dbfb2...8a30dc`
- 官方项目网站声明数据集为 CC BY 4.0；仓库中的代码 LICENSE 为 MIT。

原始 JSON 只下载到 `.private/external_datasets/finqa`，不提交到 Git。公开仓库
只发布来源、revision、字节 hash、聚合指标、代码版本和私有 artifact hash。

## 3. 数据处理

`app/external_datasets/finqa.py` 完成：

1. 64 MiB 文件预算、UTF-8、重复 JSON key 和 Pydantic schema 校验；
2. 固定 revision 与 split SHA-256 校验；
3. 把 `pre_text + post_text` 按上游定义映射为 `text_0..n`；
4. 用上游修正后的 `table_row_to_text` 模板生成 `table_0..n`；
5. 验证每个 `gold_inds` ID 都存在，且文本只允许空白/标点空格差异；
6. 用 `SHA256(seed + case_id)` 做顺序无关的稳定抽样。

下载命令：

```powershell
& '.\.venv\Scripts\python.exe' -m scripts.prepare_finqa --split dev
```

test 下载必须显式增加 `--execute-frozen-test-download`，并且只能在 test 协议
冻结后执行。

## 4. 评测分层

### Oracle evidence

只把 `gold_inds` 指向的证据交给模型。若这里答案错误，说明主要问题是数值推理、
输出协议或模型能力，不应归因于检索。

### Retrieved evidence

在每个样本的所有文本句和表格行中检索 Top-K：

- `bm25`：对英文 token 做 casefold，并使用适合小候选集的 BM25Plus；
- `dense`：本地 BGE-M3 batch embedding 与 cosine ranking；
- `hybrid`：BM25Plus 与 BGE-M3 的 RRF 融合。

若 oracle 正确而 hybrid 错误，继续分解为 evidence miss、排序不足或引用遗漏。

## 5. 模型边界

`LocalFinQAAnswerer` 不把真实 unit ID 暴露给模型，而是映射成
`evidence-01..n`：

1. retrieved-content Guard 先扫描证据；
2. 模型只能引用白名单 candidate ID；
3. 输出必须是严格 JSON；
4. `final_answer` 只能包含一个数字、百分数、`yes` 或 `no`；
5. 引用缺失、重复、未知 ID 或额外字段都失败；
6. 最多允许一次显式纠错，重试计入 generation calls；
7. 线上默认超时不变，FinQA 离线评测单独使用 120 秒。

## 6. 指标含义

| 指标 | 含义 |
| --- | --- |
| `answer_parse_rate` | 最终答案是否满足单值协议 |
| `execution_accuracy` | 归一化后是否匹配官方 `exe_ans` |
| `evidence_recall` | 提供给模型的证据覆盖多少 gold units |
| `citation_precision` | 模型引用中有多少是 gold units |
| `citation_recall` | gold units 中有多少被模型引用 |
| `grounded_execution_accuracy` | 答案正确且 gold citation recall 为 100% |

数值评分把逗号、美元符号、会计负数括号和百分号规范化，并在 5 位小数上比较。
它不使用 LLM judge，也不从一段长文本中猜测“最像最终答案”的数字。

## 7. 不可变运行

每个私有 run 包含：

- `manifest.json`：Git SHA、dataset SHA、selected case IDs SHA、模型 digest、
  检索模式、Top-K、超时和重试；
- `details.jsonl`：逐题答案、证据、引用、延迟和分层指标；
- `summary.json`：聚合指标。

发布过程先写同盘 staging、复验后原子移动。run ID 不可覆盖；summary 必须能从
details 重新计算；任何文件被修改后 verifier 都会拒绝。

## 8. 当前执行顺序

1. 在 20 个稳定 dev 样本上运行 oracle；
2. 在同一 20 个 dev 样本上运行 hybrid；
3. 只根据 dev 修正 parser、prompt 或 retrieval；
4. 冻结 test SHA、100 个稳定样本、两个 arm 和代码文件 hash；
5. 下载 test，并连续执行 oracle 与 hybrid；
6. 不根据 test 结果改参数或重跑；若失败，结果保留并建立新的 dev 版本。

当前不能声称 FinQA test accuracy，也不能用 dev 结果填写简历泛化指标。

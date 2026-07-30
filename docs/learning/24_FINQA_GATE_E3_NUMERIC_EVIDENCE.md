# FinQA Gate E3：为什么 26.67% 很低，以及输入层怎样从 80% 提升到 96.67%

## 1. 先区分三个完全不同的数字

当前最容易误解的是把所有百分比都叫“正确率”：

```text
B0 strict execution accuracy                 31/60 = 51.67%
Typed v2.2 strict execution accuracy         16/60 = 26.67%
v1 post-shortlist numeric input completeness 48/60 = 80.00%
v2 post-shortlist numeric input completeness 58/60 = 96.67%
```

前两个是最终答案执行正确率。后两个不是答案正确率，而是“gold 公式需要的
数字，在 planner 实际可见的候选中是否齐全”。Gate E3 改善了输入条件，但尚未
重新调用模型，因此不能说答案准确率已经提升到 96.67%。

## 2. 26.67% 为什么低

同一批 60 道披露开发题上，旧 B0 自由文字/表达式路径是 51.67%，Typed v2.2
只有 26.67%，绝对差距是 25 个百分点，所以 Typed 路径没有上线。

问题不是一句“8B 模型太差”能解释的。逐层诊断发现：

1. 证据层：冻结后的正确口径显示，shortlist 前只有 49/60 题数字齐全，
   shortlist 后只有 48/60。
2. 表格结构层：行级文本化丢失了表父结构；某些数值位于行头、列头，或需要
   同表其他行才能解释。
3. 数值表示层：`120 million` 的执行值是 `120000000`，但 FinQA gold program
   可能写 `120`。只比较 normalized value 会制造假缺失。
4. 语义选择层：即使数字都在，模型仍可能把分子分母、年份、指标或运算方向
   选错。E2 中有大量 `input_complete` 但答案仍错的样本。
5. 合同难度层：v2.1 曾要求 8B 模型直接生成复杂 DAG，导致 26 个
   `invalid_program_schema`。v2.2 把图编译移到 host 后才恢复到 26.67%。

因此，低分是“检索、结构解析、候选表达、语义选择、合同复杂度”共同造成，
不是简单换一个模型就能证明解决。

## 3. Gate E3 实际改了哪些代码

### `app/external_datasets/finqa_numeric_evidence_v2.py`

新增版本化 extractor，不修改冻结 v1：

- prose 中 `($198 million)` 按说明性括号处理为正数；
- 独立表格单元格中的 `(198)` 仍按会计负数处理；
- 从带数值的行头提取 operand；
- 从完整金额格式的列头提取 operand；
- 日期型列头和描述型列头不能变成 operand；
- surface value 和 normalized value 保持同一 provenance；
- 表父闭包和相邻文本闭包受 24/32/8000 三重预算约束；
- 所有闭包单元进入候选抽取前都经过 `RetrievedContentGuard`。

### `app/external_datasets/finqa_numeric_evidence_shortlist_v2.py`

旧 planner 在 shortlist 之前只允许 64 个候选，但冻结 E3 协议允许输入 128、
输出 24。新 shortlist 独立版本化：

```text
最多 128 candidates
  -> period compatibility filter
  -> question/metric/context overlap scoring
  -> stable score + evidence rank + source index + candidate_id tie-break
  -> 最多 24 candidates
```

它没有放宽模型 prompt 的 24 候选上限。

### `app/external_datasets/finqa_numeric_evidence_audit.py`

这是零 LLM 调用的离线审计器。它区分：

- `controlled_constant`：`const_1` 等公式常量；
- `selected_normalized`：执行值直接匹配；
- `selected_surface_view`：同一候选的原始尺度值匹配；
- `retrieval_missing`：gold 证据能解析，但运行时没取到；
- `extraction_unresolved`：连 gold 证据也无法提取。

它只用 gold 做离线分类，运行时闭包和 shortlist 不读 gold。

### `scripts/audit_finqa_numeric_evidence.py`

正式命令会校验数据集 SHA-256、E2 私有运行包、60 题 cohort、协议和 erratum、
v1 manifest 字节稳定性，然后原子写入：

```text
.private/.../numeric_evidence_audits/<run-id>/
  details.jsonl
  summary.json
  manifest.json
```

GitHub 只接收去除 case ID、问题、答案、gold program 和证据文本的聚合 JSON。

## 4. 实施中遇到的失败

1. 第一次把 v2 逻辑写进 v1 extractor，历史 manifest 复算失败。解决方式是撤销
   v1 修改，把 v2 放进独立模块。
2. 首次审计遇到 `candidate budget exceeded`。原因是旧函数先按 64 拒绝，再做
   24 个 shortlist。解决方式是新增 128→24 的版本化边界。
3. 一度要求重复 gold 数字必须对应两个候选，使冻结基线从 49/60 错降到 39/60。
   同一个来源数字可以被公式重复引用，因此撤销错误定义并加回归测试。
4. 数值列头修复后，日期列头制造噪声，p95 候选从 71 升到 99，超过门槛 96。
   最终只允许完整金额格式列头，日期和描述列头不扩展，p95 回到 71。

## 5. 正式结果怎样解释

```text
v1 selected pre-shortlist complete       49/60 = 81.67%
v1 selected post-shortlist complete      48/60 = 80.00%
v2 selected pre-shortlist complete       51/60 = 85.00%
v2 closure pre-shortlist complete        60/60 = 100.00%
v2 closure post-shortlist complete       58/60 = 96.67%
gold-evidence parse complete             60/60 = 100.00%
retrieval-missing operands recovered     15/16 = 93.75%
p95 total units / chars / candidates     27 / 4794 / 71
Guard scans                              1168
model calls                              0
decision                                 INPUT_GATE_PASSED
```

两道题在 24 候选 shortlist 后仍丢失 operand。它们是下一阶段的已知残余风险，
不能用调高候选上限或读取 gold 的方式隐藏。

## 6. 网上方法怎样转化成本项目路线

FinQA 本身要求在表格和文本上生成可执行程序；官方仓库还记录过
`table_row_to_text` 标签泄漏 bug，并把修正后的 FinQANet-RoBERTa-large
结果更新为 61.24% execution / 58.86% program accuracy。这说明数据转换和评测
协议本身就可能显著扭曲结果：

- <https://github.com/czyssrs/FinQA>
- <https://aclanthology.org/2021.emnlp-main.300/>

TAT-QA 的做法是先定位相关 cell/span，再做符号运算；Program of Thoughts 把
算术交给解释器；结构感知检索强调不能把表格只当普通文本。2025 年 FINDER
进一步把生成式检索和动态示例 PoT 结合，在其可比实验中报告 FinQA execution
accuracy 比先前 benchmark 高 5.98 个百分点：

- <https://aclanthology.org/2021.acl-long.254/>
- <https://arxiv.org/abs/2211.12588>
- <https://arxiv.org/abs/2309.10506>
- <https://aclanthology.org/2025.emnlp-main.1577/>

本项目没有复制这些论文分数。可落地的下一步是：

1. 固定 E3 代码和 60 题结果，不碰 40 题 internal validation。
2. 对两道 shortlist 丢失题做不看 internal-validation 的确定性误差分析。
3. 冻结 v2.3 成对协议，用完全相同的 60 题、模型 digest 和调用预算比较
   B0、v2.2、v2.3。
4. 只有 v2.3 在 strict、grounded、correct-to-wrong 和 latency 门禁均有资格
   时，才允许一次 40 题 confirmatory validation。
5. 动态示例检索必须单独做消融，不能与 evidence closure 同时改动后归因。

## 7. 面试时怎样诚实回答

不要说：“我们的正确率是 96.67%。”

应该说：

> 同一 60 题开发 cohort 上，服务基线 B0 是 51.67%，实验 Typed route v2.2
> 只有 26.67%，因此我们按门禁拒绝上线。分层审计发现 planner 的数字输入完整率
> 只有 80%。我没有先调 prompt，而是做了版本化表结构闭包、双数值视图、注入
> Guard 和有预算的确定性 shortlist，把输入完整率提升到 96.67%，11 条输入门禁
> 全部通过。这个结果只授权下一轮成对模型评测，不代表答案准确率已经提升。

这比声称一个不可比的高分更能证明工程能力：知道指标测量什么、失败发生在哪一
层、何时拒绝发布，以及怎样保留可复现证据。

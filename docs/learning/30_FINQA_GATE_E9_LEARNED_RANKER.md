# 30. FinQA Gate E9：为什么训练集变好，真实开发集反而变差

## 1. 这一阶段想解决什么

E8 用人工设计的确定性规则给 descriptor 排序。它稳定、安全，但
Descriptor Recall@4 只有 84.55%，没有达到 88% 门槛。E9 的问题是：

> 能不能只用 FinQA train 学一个小型、可解释的排序器，在不让 LLM
> 接触数值、答案和 provenance 的前提下，比 E8 更会选择 descriptor？

这里没有训练大模型，也没有微调 Qwen。训练的是一个 23 维线性排序器。

## 2. 为什么不能随机切分题目

FinQA train 有 135 家公司。公开 60 题开发集涉及 35 家公司，这 35 家在
train 里全部出现。如果随机按“题”切分，同一家公司的相似年报可能同时
出现在训练和验证中，分数会虚高。

E9 先把这 35 家公司的所有 train 题删除，再按公司做 5 折：同一家公司
只能完整地属于一个折。最终是 3,068 题、99 家公司，五折题数约 613-615。

面试时可以这样解释：

> 我没有把 IID random split 当成企业文档泛化。因为财报模板和公司术语
> 在同一公司跨年份高度相关，所以我按 company group 做隔离，避免模型
> 记住公司模板后得到虚假的验证提升。

## 3. 代码在哪里，按什么顺序运行

### 3.1 协议

`app/external_datasets/finqa_learned_ranker_protocol_v1.py`

它定义 Pydantic frozen model，校验训练 SHA、数据量、五折哈希、23 个特征、
L2=10、无超参搜索、开发评测预算=1、E8 回退以及隐藏集合状态。

`load_learned_ranker_protocol_v1()` 读取 JSON 后立即验证。如果有人改了折数、
阈值或特征名，程序会在训练前失败。

### 3.2 特征和模型

`app/external_datasets/finqa_learned_descriptor_ranker_v1.py`

`descriptor_feature_vector_v1()` 的输入只有：

```python
question, role, descriptor
```

它没有 `answer`、`gold_program`、`candidate_value` 参数。因此即使训练脚本有
金标，也不能直接把金标塞入运行时特征。

`fit_balanced_ridge_v1()` 做四件事：

1. 检查矩阵是有限浮点数，且正负类都存在；
2. 用当前训练折的均值和标准差做 z-score；
3. 给正负类做逆频率加权；
4. 用 `numpy.linalg.solve()` 解带 L2 正则的线性方程。

这不是神经网络，没有随机初始化。相同输入会得到逐位相同的系数。

`FinQALearnedDescriptorRankerArtifactV1` 保存均值、尺度、系数和截距，并对
自身 canonical JSON 计算 SHA-256。测试修改一个系数后，Pydantic validator
会报 `artifact hash is invalid`。

`LearnedFinQADescriptorRetrieverV1.select()` 为每个 role 给全部 descriptor
打分，按“learned score、E8 score、descriptor ID”稳定排序并取前 4。

`FailClosedFinQADescriptorRetrieverV1` 在 challenger 缺失或推理发生受控异常时
调用 `DeterministicFinQADescriptorRetrieverV5`。这就是 champion/challenger
回退，不是返回空答案。

### 3.3 训练数据管线

`app/external_datasets/finqa_learned_ranker_training_v1.py`

主要流程是：

```text
固定 train SHA
  -> 排除公开开发公司和重复问题
  -> 校验 supported operation
  -> 完整 FinQACase 校验
  -> 从 model_input 取证据 ID
  -> evidence closure + Guard admission
  -> numeric candidate + safe descriptor catalog
  -> 用 train gold program 生成离线 descriptor 标签
  -> 按公司做 OOF 训练和评测
```

注意：gold program 只回答“这个 descriptor 是否包含正确候选”，不会成为
特征。公开证据也不保存问题、答案或 gold program。

### 3.4 两个正式脚本

`scripts/train_finqa_learned_descriptor_ranker_v1.py` 处理 train 和五折 CV。

`scripts/audit_finqa_learned_descriptor_ranker_v1.py` 先验证 CV 已授权，然后
复用 E8 的证据、Guard、catalog 和 candidate reranker，只替换 descriptor
selector。这样 A/B 差异才可归因。

## 4. 训练过程中具体遇到了什么问题

### 问题一：官方数据有 `text_-1`

train 中有一条官方 gold key 是 `text_-1`，而原来的 dev/test schema 只允许
非负编号。该题属于已排除的开发公司 `RE`。

错误实现是先完整校验全部 6,251 条，再做公司排除；这样一条本来不入选的
脏记录会阻断训练。修复后先严格读取 `id/filename/question/program` 做冻结
边界筛选，只有入选记录才进入完整 Pydantic 校验。没有放宽入选数据。

### 问题二：空表格单元格

旧提取器把空单元格传给 `NumericCandidateSource(text="")`，而 schema 要求
文本至少 1 字符。E8 文件已有证据哈希，不能直接修改。

E9 适配层将空单元格变为 `N/A`。它是非数值文本，不会产生数字候选，表格
行列位置也不变。正式训练记录了 1,213 次替换。

### 问题三：136 条仍失败

失败包括超出 host constant registry、重复语义引用、金额后缀与表格 scale
冲突、重复候选 ID、候选超过 128 等。脚本没有 `except: continue` 后假装全量
成功，而是在私有逐题账本和公开聚合里同时记录。

## 5. 为什么训练 CV 看起来有效

E8 OOF Recall@4 是 88.76%，E9 是 90.84%，提升 2.08 个百分点。五折 E9
分别约 89.00%、92.41%、91.79%、89.89%、91.14%，标准差 1.24 个百分点。

这说明在“train 的 `model_input` 候选分布”内，线性关系可重复，并非某一折
偶然提高。由于预先冻结要求至少 +1pp、标准差不超过 8pp，所以 CV 通过。

## 6. 为什么公开开发集却退化

公开 60 题只允许正式运行一次。结果：

```text
Descriptor Recall@4       84.55% -> 78.86%
Candidate Recall@8        78.86% -> 75.61%
Complete case@8           74.14% -> 72.41%
Conditional retention@8   93.27% -> 95.88%
```

最后一项上升说明：一旦 E9 选对 descriptor，后面的 E8 candidate reranker
工作得更好。但 E9 第一层丢了更多正确 descriptor，最终仍然退化。

成对统计是 93 个保持命中、11 个从对变错、4 个从错变对、15 个都错，净
损失 7 个角色。这比只说“下降 5.69pp”更能定位变化来自哪里。

## 7. OOF 好、开发差的四个原因

### 7.1 证据分布不一致

train 的 `qa.model_input` 对 3,068 题全部覆盖 gold evidence。开发运行时用的
是真实检索选中单元和 bounded closure。前者是在“答案证据已经进池”条件下
学习排序，后者含检索噪声和不同的 descriptor 组合。

### 7.2 目标函数错位

点式回归把每个 descriptor 当独立二分类样本，但指标问的是“每个 role 的
Top-4 中至少一个正确吗”。独立二分类损失并不直接惩罚一个高分噪声把正确
项挤到第 5 名。

### 7.3 challenger 改动没有边界

E9 用 learned score 完整重排，只在同分时参考 E8。即使 E8 对某一 descriptor
很有把握，learned score 也能大幅覆盖它。负结果表明更合理的是学习有界
residual，而不是替代整个分数。

### 7.4 共线特征

`question_primary_overlap_count` 和 ratio 强相关，却学到相反符号；
`candidate_count_log1p` 的绝对系数还高于 E8 score。这些系数可以用于诊断，
但不能解释成“候选越多越正确”的业务因果关系。

## 8. 为什么失败结果反而有面试价值

不能说“模型正确率提升了”。可以说：

> 我先冻结 company-disjoint CV、特征和一次性开发门禁。模型在 5 折 OOF
> 提升 2.08pp，但在正式开发集下降 5.69pp；我保留负结果，通过 123 个角色
> 成对分析定位到证据分布和点式目标错位，并让 E8 自动保留为 champion，
> 没有消费内部验证集去继续调参。

这体现的是评测纪律、数据泄漏意识、可回滚和故障归因，比只报一个经过多次
试验挑出的最好数字更接近工业实践。

## 9. 面试追问与回答

### 问：为什么不用更强的 XGBoost？

答：本阶段先验证监督信号是否跨公司、跨证据分布泛化。小型线性模型便于
查看系数、序列化、做确定性复现和 fail-closed。结果说明主要问题是数据契约
与目标函数，不是模型容量。此时换更强模型可能只会把 train 分布拟合得更好。

### 问：为什么 CV 通过还不能用？

答：CV 只覆盖 train 的构造分布。项目把 CV 当“允许进行一次开发实验”的
前置门，而不是生产放行。正式开发门失败后，champion 不变。

### 问：为什么不再跑一次 60 题调权重？

答：看过正式结果后再调参并复跑，会把开发集变成训练集。协议把预算固定为
一次，E9 结果已写一次且哈希绑定。下一版只能使用 train-only 或新冻结数据。

### 问：下一版怎么改？

答：使用不强制注入 gold 的检索真实训练候选，改成 pairwise/listwise Top-4
目标，学习 E8 周围的有界 residual，并增加跨折系数稳定性和特征消融门禁。
E9 的 60 题不能重跑，内部 40 题和 frozen test 继续保留。

## 10. 证据在哪里

- 协议：`docs/external_datasets/evidence/finqa_learned_ranker_protocol_v1.json`
- 模型工件：`docs/external_datasets/evidence/finqa_learned_descriptor_ranker_artifact_v1.json`
- CV：`docs/external_datasets/evidence/finqa_learned_descriptor_cv_public_v1.json`
- 正式开发结果：`docs/external_datasets/evidence/finqa_learned_descriptor_development_public_v1.json`
- 成对复盘：`docs/external_datasets/evidence/finqa_learned_descriptor_postmortem_public_v1.json`
- 工程说明：`docs/external_datasets/finqa_learned_descriptor_gate_e9.md`
- 当前交接：`docs/roadmap/finqa_gate_e9_current_handoff.md`


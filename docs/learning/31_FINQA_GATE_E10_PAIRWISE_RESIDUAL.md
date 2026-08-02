# 31. FinQA Gate E10：一次差 0.0545 个百分点的失败，为什么不能算通过

## 1. 先说结论

E10 没有晋级，但它比 E9 更接近正确的工程方法。

```text
E8 五折 Recall@4       84.8894%
E10 五折 Recall@4      85.8349%
实际提升                0.9455 个百分点
提前约定的最低提升      1.0000 个百分点
距离门槛                0.0545 个百分点
```

五个折都提升，说明不是某一折偶然把平均分拉高；但整体仍低于门槛，所以代码
必须输出 `E10_CV_GATE_FAILED_INTERNAL_VALIDATION_PROHIBITED`。这不是“代码报错”，
而是评测系统在按约定工作。

## 2. E9 到底错在哪里

E9 训练时使用 FinQA 的 `qa.model_input`。这个字段的设计目的是给原始 FinQA
生成模型准备输入，不是模拟本项目的检索器。对 E9 的 3068 道题，它恰好 100%
包含 gold evidence。等于训练时老师先把正确资料放进桌面，正式运行时却让系统
自己从一堆候选里找资料。

所以 E9 的 OOF 提升回答的是：

> 正确证据已经在输入里时，线性模型能否把正确 descriptor 排得更高？

它没有完整回答：

> 检索器真实给出有噪声的 Top-K 时，排序器还能否改善？

E10 改用官方 `retrieved_all` 的分数排序 Top-10，不补 gold。训练和运行虽然仍
不完全相同，但关键的“强制 gold 覆盖”被去掉了。

## 3. `top_retrieved_unit_ids_v1()` 做什么

文件：`app/external_datasets/finqa_pairwise_residual_training_v1.py`

函数接收文本检索行和表格检索行。每行只能有：

```python
{"score": 0.83, "ind": "table_4"}
```

它检查分数是有限数字、ID 非空、ID 不重复，然后按下面的键排序：

```python
(-score, unit_id)
```

负号让高分在前；相同分数再按 ID 排，保证 Windows、Linux 和重复运行得到同一
结果。最后返回前 10 条。如果报告总共只有 7 条，就返回 7 条，不能复制三条来
“凑够 10 条”，因为复制会伪造检索证据。

## 4. 一道题如何变成训练样本

`prepare_pairwise_training_case_v1()` 的顺序是：

```text
FinQA case
  -> retrieved_all Top-10-or-all
  -> 数值证据 closure 扩展
  -> RetrievedContentGuard 扫描并准入
  -> 从准入文本/表格抽取 Decimal 数值候选
  -> 构建不含数值和 provenance 的 safe descriptor
  -> 用 gold program 只生成离线正负标签
  -> 按 semantic role 组成 PairwiseRoleGroupV1
```

一个 role group 包含多个 descriptor。只要某个 descriptor 映射的候选能满足
gold role，它就是正例；其余是负例。没有正例，或者全是正例，都无法构成“谁
应该排在谁前面”的训练关系，因此该 role 不进入 pairwise fit。

Gold program 不会传入运行时特征函数。它像考试答案，只在训练数据制作阶段标
记对错，最终模型文件只保存特征均值、尺度、21 个系数和边界参数。

## 5. 为什么叫 pairwise

E9 是 pointwise：分别问每个 descriptor 是 0 还是 1。E10 是 pairwise：问一
个正例是否应该排在一个高风险负例前。

代码先按 E8 分数找每个正例最难的最多 8 个负例，然后计算：

```python
difference = standardized_positive - standardized_negative
```

所有 difference 组成矩阵 `D`。希望学到的 `w` 满足 `D @ w` 接近全 1 向量，
也就是正例效用比负例至少高一个 margin。闭式解是：

```text
w = (D.T D + 10 I)^-1 D.T 1
```

代码没有真的计算矩阵逆，而用 `numpy.linalg.solve()` 解线性方程，数值上更稳。
`10 I` 是 L2 正则，限制系数过大，也让方程在特征相关时仍可解。

## 6. 为什么不让新模型完全接管排序

E9 的 learned score 可以彻底覆盖 E8，这导致真实开发集大幅回退。E10 把 E8
当 champion，只允许模型做有界修正：

```python
adjustment = clip(learned_utility, -1, 1) * 4
final_score = e8_score + adjustment
```

不管输入特征多极端，调整都只能在 `[-4, +4]`。这叫 bounded residual：学习
的是旧系统分数的修正量，而不是替换旧系统。若模型文件损坏，Pydantic 和内部
SHA 会拒绝加载；它也没有被接入 serving route。

## 7. company-disjoint 五折是什么

不能随机把同一家公司的年报拆到训练和验证两边。公司模板、指标命名和表格样式
高度相似，随机切题会让模型通过记住公司风格得到虚高分。

E10 沿用冻结的 99 公司分组。每次用 4 折公司的数据训练，在完全不同公司的第
5 折上评测，轮换五次。每道题只在自己未参与训练的模型上被评分，所以叫 OOF，
即 out-of-fold。

## 8. 怎样读这次结果

```text
折 0  +0.6768pp
折 1  +1.2007pp
折 2  +0.9975pp
折 3  +0.6700pp
折 4  +1.1885pp
```

好的一面：五折没有一折退化；折间系数最小 cosine 是 0.9884，接近 1，说明
不同公司子集学到的方向很接近；Recall 标准差 1.1171pp，也远低于 5pp 门槛。

不足：总提升只有 0.9455pp。门槛是看结果前定的 1pp，不能看到 0.9455 后把
门槛改成 0.9。否则每次都可以让规则迁就结果，评测就失去约束力。

## 9. 2925、2881 和 5923 分别是什么

- `2925/3068 prepared`：2925 题完整通过 evidence、Guard、数值候选和 descriptor
  构建。143 题失败被计入公开原因，没有静默丢弃。
- `2881/3068 labelable`：2881 题至少产生一个同时含正负 descriptor 的 role。
- `5923 role groups`：一道题可能有多个操作数角色，所以 role 数多于题数。
- `53457 training pairs`：每个正 descriptor 和最多 8 个 E8 高分负 descriptor
  形成一对。

这些是排序训练覆盖率，不是 2925 道题答对，也不是 93.9% answer accuracy。

## 10. 为什么内部 40 题没运行

协议把数据预算分层：train 五折负责开发和筛选；只有通过全部 CV 门禁，才能看
一次内部 40 题。E10 有一项失败，所以脚本停在 CV 层。

这能防止开发者连续尝试模型，每次都看内部结果，再把内部集逐渐调成训练集。没
运行不是“少做一步”，而是保护以后仍有可信数据可用。

## 11. 面试时怎样讲

可以这样回答：

> E9 在线下 company-grouped CV 提升 2.08pp，却在一次性开发集回退 5.69pp。
> 我把原因拆成证据分布、目标函数和模型覆盖范围三个问题。E10 改用不注入 gold
> 的 retrieval-realistic Top-10，使用 pairwise hard-negative 目标，并把学习分数
> 限制为 E8 的正负 4 分残差。五个公司隔离折全部提升，平均 +0.9455pp，但预注册
> 门槛是 +1pp，所以系统自动禁止内部验证并保留 E8。这证明我不仅会训练模型，
> 也会设计防止调参污染和错误上线的评测门禁。

不能说“E10 已经提升线上正确率”，因为它只改善了 train OOF descriptor recall，
没有运行内部 40 题、最终答案或 frozen test。

## 12. 下一步为什么必须叫 E11

E10 的阈值和结果已经公开，不能继续改 E10 直到它通过。下一轮若继续，必须新建
E11 协议，并在外层 company folds 之外增加内层 company CV；模型结构或超参数
只能在内层选择，外层只做一次无偏估计。只有 E11 自己预先冻结的外层门禁通过，
才有资格使用尚未消耗的内部 40 题。

# 29. FinQA Gate E8：把“选中数字类别”和“选中具体数字”分开评测

## 1. 这一阶段到底解决什么问题

E7 的最佳确定性方案在 123 个计算角色上，Candidate Recall@8 是
78.86%。失败不能笼统地说成“RAG 不准”，因为系统中间有两次选择：

1. 先选 descriptor，也就是“我要哪一类数字”；
2. 再从该 descriptor 对应的多个 candidate 中选具体数字。

例如 descriptor 是“期末保修准备金”，它可能对应 2016、2017、2018
三个 candidate。第一步选对类别，不代表第二步选对年份。因此 E8 把两层
指标拆开，不再只看最终 Candidate Recall。

## 2. descriptor、candidate 和 host mapping

candidate 是宿主内部的完整数字对象：

```text
candidate_id + 数值 + 单位 + 年份 + evidence_id + provenance
```

descriptor 是给选择器看的无数值投影：

```text
descriptor_id + metric/row + periods + 安全局部提示 + 安全主题提示
```

二者的映射只留在 Python 宿主：

```text
desc-a -> [num-1, num-2, num-3]
```

这样选择器可以表达“需要哪个业务概念”，但不能自己编造 candidate ID，
也看不到原始数值和 provenance。最终权限仍在宿主校验器手中。

## 3. v3 catalog 的代码流程

核心文件是 `app/external_datasets/finqa_safe_descriptor_catalog_v3.py`。

`build_retrievable_safe_descriptor_catalog_v3()` 依次完成：

1. 检查候选不超过 128 个，ID 不重复；
2. 检查候选是 `operand`，并且 evidence 已通过 admission；
3. 检查每个候选都有对应上下文；
4. 对所有上下文重新执行 `RetrievedContentGuard.scan()`；
5. 对 metric、entity、row、column 做 NFKC 归一化并删除数字；
6. 根据 provenance 附近文本生成最多 128 字符的局部提示；
7. 从最多 32 个已准入正文块中选择最多 160 字符的主题提示；
8. 对无标签正文按“去数字后的上下文指纹”分组；
9. 生成稳定 `desc-<hash>`，把 candidate mapping 留在宿主；
10. 计算整个 catalog 的 SHA-256，防止静默漂移。

### 为什么局部窗口要左右分别分预算

旧逻辑先截取数字周围 240 个字符，再只保留清洗结果的前 96 个字符。
如果数字左边文字很长，`$34 countries` 里的 `countries` 可能被截掉。

v3 分别保留数字左边的后半段和右边的前半段。数字本身随后被删除，但
右侧的单位、国家、门店等业务词能留下。对应回归测试是
`test_balanced_local_hint_preserves_right_side_semantics`。

### 为什么同一正文里的数字要分组

一句“额度可从 1 billion 增至 2 billion”有两个数字。若每个数字都用
略有差异的窗口生成 descriptor，它们可能占掉两个甚至更多 Top-4 名额。

v3 对同一个去数字上下文计算安全指纹，把这些数字放进同一个 descriptor。
指纹只用于宿主分组，不把 evidence ID 暴露给选择器。这样 descriptor 负责
表达语义类别，candidate 层再区分 1 和 2。

## 4. v5 retriever 为什么采用“保守增益”

核心文件是 `app/external_datasets/finqa_descriptor_retriever_v5.py`。

第一次实现把 local/topic hint 和结构字段一起加权，Descriptor Recall@4
从 E7 的 83.74% 降到 79.67%。原因是已有精确 row header 的 descriptor
本来就能正确排序，宽泛正文反而加入噪声。

最终逻辑是：

```python
score = E7_v2_structural_score(...)
if primary_fields_have_no_question_or_role_signal:
    score += bounded_local_and_topic_backoff(...)
```

这叫 conservative augmentation。新特征只补旧特征看不到的信息，不随意
改变旧系统的高置信排序。最终 Descriptor Recall@4 达到 84.55%，比 E7
多命中 1/123 个角色，但仍未达到 88% 门槛。

## 5. candidate reranker 的代码流程

核心文件是
`app/external_datasets/finqa_descriptor_candidate_reranker_v1.py`。

`rerank_descriptor_candidates_v1()` 的顺序是：

1. 校验 descriptor 最多四个、唯一且属于当前 catalog；
2. 取出私有 mapping 中的 candidate ID；
3. 调用 `hard_compatible_candidates_for_role_v2()` 过滤错误年份和非法除数；
4. 使用问题词、角色锚点、candidate 元数据、显式 evidence rank 打分；
5. 根据 provenance 附近的局部文本补充分数；
6. 全局排序后保留 Top-8；
7. 如果某个已选且非空 descriptor 完全没进入 Top-8，执行最小覆盖替换；
8. 返回不可变候选排名；若全部不兼容，返回结构化空结果而不是抛系统异常。

### 为什么最初的 round-robin 失败

最初方案给四个 descriptor 各两个位置。诊断发现 16 个角色已经选中正确
descriptor，但正确数字在组内第 3 到第 6 位，所以 Top-8 直接从 78.86%
跌到 66.67%。

最终方案不是平均分配，而是保留全局分数，只保证每个非空 descriptor
至少有一个代表。这个改动把 Recall@8 恢复到 78.86%。

## 6. 指标逐个解释

### Descriptor Recall@4 = 84.55%

每个角色最多选四个 descriptor，只要其中至少一个包含可接受 gold
candidate，该角色记 1。它衡量“类别有没有选中”，不看具体数字排名。

### Candidate Recall@4 / Recall@8 = 66.67% / 78.86%

从选中 descriptor 展开的具体 candidate 中，前 4 或前 8 是否含可接受值。
这是 planner 真正看到正确 operand 的概率，仍不是最终答案准确率。

### Descriptor complete case@4 = 82.76%

一道题可能需要多个角色。只有所有角色都选中正确 descriptor，整题才记 1。
它比单角色 Recall 更严格。

### Candidate complete case@8 = 74.14%

一道题所有角色的正确 candidate 都进入 Top-8 才记 1。E7 是 75.86%，
所以 E8 在这一项回退 1.72 个百分点。

### Conditional retention@8 = 93.27%

只看“descriptor 已选对”的角色，再问 candidate 是否保留。它隔离第二阶段
重排问题。该值没到 100%，说明 descriptor 对了以后仍可能选错年份或数字。

### Oracle Candidate Recall@8 = 100%

离线用 gold 找到正确 descriptor，再运行真实 reranker，123 个角色都能在
Top-8 保留正确候选。这证明接口和重排容量足够，不证明运行时会选中 descriptor，
更不等于答案准确率 100%。

### Edge reduction = 75.10%

相对“每个角色连接全部候选”的图，E8 删除了约四分之三的候选边。后续
planner 输入更小、攻击面更窄，但减少候选必须与 Recall 一起看。

## 7. 最终结果为什么仍然失败

冻结门槛要求 Descriptor Recall@4 88%、Candidate Recall@4 75%、
Candidate Recall@8 84%、完整题 80% 和 conditional 98%。E8 只通过了
catalog coverage、Oracle、edge reduction 与所有安全/身份不变量，六个运行时
质量检查没有通过。

正确说法是：

> E8 修复了 descriptor 可检索性中的具体数据建模 bug，Oracle 容量达到
> 100%，真实 descriptor recall 小幅提高，但没有产生足够的端到端候选收益，
> 因而 challenger 未替换 E7 champion，服务保持关闭。

不能说“E8 把正确率提高到 100%”。

## 8. 消融实验告诉我们什么

给 descriptor 排名加入统一先验步长 `1/2/4/8` 全部降低 Candidate
Recall@8。原因是高排名 descriptor 也可能是宽组，给组内每个数字统一加分
只会一起放大噪声。因此最终步长选 `0`。

关闭 candidate local context 后，Top-4 从 66.67% 升到 68.29%，但完整题
从 74.14% 降到 72.41%，Oracle 从 100% 降到 99.19%。最终保留 local
weight `1`，但如实记录它不是所有指标都更好。

## 9. 面试可能会问什么

### 问：为什么不用另一个 LLM 直接判断正确数字？

答：LLM 可以参与语义选择，但 candidate ID、数值和 provenance 属于权限边界。
本项目让模型最多返回 descriptor enum，宿主再校验和回映射。E7 的真实 Qwen
selector 只有 59.35% Recall@8，也证明增加一次 LLM 调用不会自动解决输入表示
和候选排序问题。

### 问：为什么失败实验值得写进项目？

答：协议在实现前冻结，失败结果不可覆盖，源码和私有明细都有哈希。第一次
round-robin 把 Recall@8 降到 66.67%，逐角色诊断后恢复到 78.86%。这展示了
可复现的故障定位和回归控制，而不是只展示最终最好数字。

### 问：为什么没有运行 internal validation？

答：开发 progress gate 没通过。继续消费内部验证集会把它变成另一个调参集，
破坏泛化证据。项目选择保留数据边界，不用更多测试次数掩盖开发集失败。

### 问：下一步怎么做？

答：冻结 E9，用 FinQA train 做 group-aware learned reranker，按文档或公司分组
交叉验证，特征只能来自运行时可见字段，并与 E7/E8 成对比较。只有开发门槛
通过，才允许一次 internal validation。

## 10. 你可以从哪里查看证据

- 冻结协议：`docs/external_datasets/evidence/finqa_retrievable_descriptor_protocol_v1.json`
- 正式结果：`docs/external_datasets/evidence/finqa_retrievable_descriptor_public_v1.json`
- 消融结果：`docs/external_datasets/evidence/finqa_retrievable_descriptor_ablation_public_v1.json`
- 工程记录：`docs/external_datasets/finqa_retrievable_descriptor_gate_e8.md`
- 下一阶段边界：`docs/roadmap/finqa_gate_e8_current_handoff.md`

## 11. 本阶段最终验收

- E8 聚焦测试：15 passed；
- 外部数据集测试域：359 passed；
- 全仓回归：2871 passed、30 skipped；
- compileall、依赖一致性和 diff 空白检查通过；
- 3 条 warning 是仓库已有的 SWIG/FAISS 弃用提示；
- 当前虚拟环境没有安装 Ruff，所以没有把 lint 写成已通过；
- pytest 临时目录明确放在项目 D 盘的 `.private` 下。

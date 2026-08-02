# 28. FinQA Gate E7：安全描述符选择为什么没有通过

## 1. 这一阶段到底在解决什么

E6 已经证明：如果离线 Oracle 知道每个计算角色需要什么语义，正确数字几乎都能进入角色 Top8。但运行时不能读取 gold program，所以真正的问题是：

> 只看用户问题，系统怎样找到“哪一类数字”值得暴露给后续 planner？

直接把几十个数字、候选 ID 和原始文档全部交给 LLM 有三个问题：数字多时容易绑错年份或表格行；检索文档可能含间接提示词注入；模型还可能伪造 candidate ID。

E7 因此增加了一个中间层：**Safe Descriptor（安全描述符）**。

## 2. descriptor 和 candidate 有什么区别

假设表格中有：

```text
goodwill                                      258.9
cash purchase price net of cash acquired     320.1
```

宿主内部的 candidate 包含：

```text
candidate_id = num-...
normalized_value = 258.9
evidence_id = table_3
row_header = goodwill
provenance = ...
```

给 selector 的 descriptor 只包含：

```json
{
  "descriptor_id": "desc-...",
  "row_header": "goodwill",
  "periods": [],
  "source_kind": "table_cell"
}
```

数值、candidate ID、evidence ID、source ID 和 provenance 都不进入模型输入。模型输出 `desc-...` 后，宿主还要检查它是否属于本题 enum，然后才用私有 mapping 找回 candidate ID。

```text
模型负责表达“我想要 goodwill”
宿主负责决定“goodwill 对应哪些已准入 candidate”
```

## 3. 代码流程逐步看

### 3.1 构建目录

核心文件：`app/external_datasets/finqa_safe_descriptor_catalog_v1.py`。

`build_safe_descriptor_catalog_v1()` 的顺序是：

1. 检查 candidate 数量不超过 128；
2. 拒绝重复 candidate ID；
3. 只接受 `operand` 且 evidence 已被 Guard 准入的 candidate；
4. 对原始 metric/entity/row/column 做 Guard 扫描；
5. 用 `_safe_field()` 做 NFKC、大小写归一化和数字删除；
6. 对清洗后的字段再做 Guard 扫描；
7. 按无数值 semantic key 分组；
8. 从 semantic key 计算稳定的 `desc-<hash>`；
9. descriptor 进入目录，candidate-ID mapping 留在宿主；
10. 对整个目录计算 `catalog_sha256`。

raw 和 sanitized 都要扫描：只扫描清洗后文本可能把恶意片段“清洗没了”；只扫描原文又不能证明实际送入模型的版本安全。

### 3.2 文本候选的上下文补充

`app/external_datasets/finqa_safe_descriptor_catalog_v2.py` 处理没有 metric、entity、row header 和 column header 的数字。它只从已被 Guard 准入的 evidence 中取有界窗口，删除数字，再作为 fallback metric。

它不改变 candidate 的 value、ID 或 provenance，只创建一份用于目录投影的 `model_copy`。

### 3.3 模型选择器

`app/external_datasets/finqa_descriptor_selector_v1.py` 定义严格输出：

```python
class RoleDescriptorSelectionV1:
    role_id: str
    descriptor_ids: tuple[str, ...]  # 1 到 4 个，必须唯一
```

Ollama JSON schema 把 role 和 descriptor 限制为本题 enum。返回后，`parse_descriptor_selections_v1()` 还检查响应大小、额外字段、role 顺序、descriptor 成员关系和重复项。所以 JSON schema 不是最终权限边界，宿主解析器才是权威。

### 3.4 descriptor 回映射

`SafeDescriptorCatalogBuildV1.candidate_ids_for_descriptors()` 使用私有字典：

```text
desc-a -> [num-1, num-2, num-3]
desc-b -> [num-4]
```

一个 descriptor 可能对应同一行的多个年份，所以选对 descriptor 还不等于最终 candidate 排名一定正确。这正是本轮 6 个失败角色的来源。

## 4. 指标怎么理解

本次 58 道 typed 题共有 123 个 evidence role。

### Recall@4 / Recall@8

每个 role 的前 4 或前 8 个 candidate 中，只要包含一个可接受 gold candidate，该 role 记 1，否则记 0；所有 role 取平均。

例如 v2 的 Recall@4=70.73% 表示约七成角色在前四候选里保留正确数字，不表示七成题最终答对。

### Complete case@8

一道题可能有 2 到 5 个角色。只有所有角色都在 Top8 找到正确数字，整题才记 1。任何一个角色失败，整题就是 0。

### Edge reduction

原始候选数乘角色数会形成大量 role-candidate 边。筛选后保留边越少，后续越便宜、攻击面越小，但删太多会损害 recall。

### Oracle catalog upper bound

Oracle 使用 gold 只做离线定位，然后检查对应 descriptor 是否仍能找回 candidate。v2 得到 Recall@8=100%，说明目录没有把 gold candidate 丢掉。

它不证明运行时 selector 能找到 descriptor，更不等于答案准确率 100%。

## 5. 每个版本做了什么

### Question-only v1/v2

代码：`finqa_role_query_planner_v1.py` 和 `v2.py`。

v1 会从 OCR 文本过度推断年份；v2 只有 role 明确声明 start/end/target 时才使用周期。v2 更稳定，但 Recall@8 仍只有 80.49%，说明通用 query rewrite 无法恢复表格隐藏语义。

### Free-query LLM

代码：`finqa_role_query_planner_llm_v1.py`。

`qwen3:8b` 只看问题和无数值 skeleton，平均约 2.82 秒，却比确定性 v2 低 17.07 个 Recall@8 百分点。结论不是“永远不用 LLM”，而是当前自由文本接口缺少可验证的选择边界。

### Catalog v1/v2

v1 把没有标签的文本数字压成泛化 descriptor，Oracle Recall@4 只有 93.50%。v2 加入有界上下文 fallback 后，Oracle Recall@4/8 达到 95.93%/100%，通过接口容量门禁。

### Qwen descriptor selector

它只输出 enum，却只有 Recall@4/8 56.91%/59.35%。一个失败题中，正确 descriptor 明确含 `matching buy sell volumes`，模型却选择 fuel oil、gasoline 等无关行。

输出受限能防伪造和越权，但不会自动提高语义判断能力。

### Deterministic v1

`finqa_descriptor_retriever_v1.py` 把问题词重叠、part/total anchor、周期和 source kind 变成可解释分数。结果明显好于 Qwen selector，平均约 0.44 ms。

### Normalized lexical v2

`finqa_descriptor_retriever_v2.py` 修复两类 bug：

- `S&P` 过去被拆成 `s`、`p`，两个单字符都被删除；v2 同时保留 `s&p` 和 `sp`；
- 增加 `percent of X that was Y` 的 part/total 切分。

Recall@4 提升到本轮最高 70.73%，完整题率达到 75.86%。

### BGE-M3 hybrid v3

`finqa_descriptor_retriever_v3.py` 对所有 role query 和 descriptor 做一次批量 embedding，再用 Reciprocal Rank Fusion：

```text
score = 0.8 / (60 + dense_rank) + 0.2 / (60 + lexical_rank)
```

模型完整 SHA256、1024 维、请求数和 payload 都被审计。性能合格，但 Recall@4 降到 65.04%。descriptor 太薄，例如问题写“unrecognized tax benefits”，descriptor 只写“balance at December”；embedding 没有足够上下文，反而冲坏词法顺序。

### Typed structural v4

`finqa_descriptor_retriever_v4.py` 只加两条结构先验：

- `PERCENT_CHANGE` 优先 balance/begin/end 行；
- 多角色 `ADD/AVERAGE` 优先 candidate_count 足以覆盖角色数的 descriptor。

Recall@8 达到本轮最高 80.49%，但 Recall@4 降到 69.11%。固定结构 bonus 能补长尾，也会把某些错误项推到前面，所以不能上线。

## 6. 三类剩余失败意味着什么

最佳通用词法 v2 的 26 个 Top8 失败角色分为：

1. **8 个无词面信号**：问题业务主题没有出现在 descriptor，需要改数据表示；
2. **12 个有信号但排在 Top4 之后**：需要更好的 descriptor shortlist/reranker；
3. **6 个 descriptor 已选中但 candidate 丢失**：需要 descriptor-aware 二次排名。

这三类不能用同一组权重解决。工业项目的重要能力不是“再加一个模型”，而是先确定错误属于哪一层。

## 7. 工程问题与修复

### Ollama JSON schema HTTP 400

Ollama 不支持最初的 `prefixItems` 与 `items:false` 组合。修复后 schema 只表达服务端支持的数组约束，精确 role 顺序继续由宿主检查。

### `uniqueItems` 仍出现重复 ID

真实 Qwen 有 4 题输出重复 descriptor ID。系统没有自动去重，因为自动修复会把协议错误伪装成成功；Pydantic 校验失败并写入逐题记录。

### BGE 首次加载慢

初始化探针固定模型身份和维度；第一题承担冷加载成本，之后多数题约 200–700 ms。公共证据分别记录 1 次初始化探针和 58 次逻辑 embedding 请求。

### 一秒超时误终止

第一次 v3 启动时，外层命令超时误设为 1 秒。检查确认 0 个 Python 残留进程、公共结果不存在、私有目录不存在，随后使用相同冻结协议重新运行。这不是模型失败，也没有覆盖证据。

## 8. 面试怎么回答

### 为什么 Oracle 100%，真实 selector 只有约 59%？

Oracle 回答“正确 candidate 是否仍可由某个 descriptor 表示”；真实 selector 回答“只看问题能否选出这个 descriptor”。前者是接口容量，后者是运行时能力，中间存在 semantic recoverability gap。

### 为什么不用更大的 LLM？

Qwen 失败和 BGE 回归共同说明输入 descriptor 缺上下文。更大模型不能修复不可见信息，也不能解释 6 个下游 candidate-ranking miss。先修数据 contract 和排名层更可验证。

### 为什么失败实验也有价值？

每个协议在运行前冻结，失败结果不可覆盖，源码 SHA 和私有明细 SHA 都进入公共证据。它能证明项目没有反复调开发集直到数字好看，也排除了自由 query、全目录生成选择和直接 dense fusion 三条路线。

### 目前可以写进简历什么？

可以写：设计数值隐藏、Guard 扫描、枚举约束和宿主回映射的安全 descriptor 层；在 60-case/123-role 开发校准上验证 Oracle Recall@8=100%，并通过预注册消融定位真实瓶颈，所有未达标路线保持禁用。

不能写：系统准确率 100%、FinQA SOTA、生产已上线、通过 held-out 测试。

## 9. 下一阶段

1. 设计 retrievability-aware descriptor schema，把平衡局部上下文、表格主题和行语义安全加入目录；
2. 把 descriptor recall 与 candidate recall 分开测量，实现 descriptor-aware candidate reranker。

只有开发门禁通过后，才允许消费 40-case internal validation；通过 internal validation 后才讨论 frozen test 和最终答案配对评测。


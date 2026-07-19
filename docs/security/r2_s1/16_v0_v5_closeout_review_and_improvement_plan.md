# R2-S1 V0-V5 Closeout Review and Improvement Plan

状态：`COMPLETE`，收口修复、全仓门禁和可独立复算验证均已完成；远端 CI 状态以对应 GitHub Actions run 为准。

日期：2026-07-19

## 1. 为什么 V5 通过后还要再审查

`913 passed` 只能说明当时已有测试全部通过，不能证明测试覆盖了所有证据完整性边界。本次收口先让一个独立审查者只读检查 V1-V5，再由主协作者复现每个问题。审查结果为 `0 Critical / 6 Important / 2 Minor`。

处理原则：

1. Important 问题在提交前修复并增加回归测试；
2. Minor 问题若属于当前实现的准确边界，则记录限制和后续准入条件，不把它伪装成已经解决；
3. 不修改 Guard 规则、冻结 test 数据、正式 D7 run 或 V1 公共包；
4. 不为了获得更好的 `0/24` 数字调整现有攻击标签。

## 2. 本次实际改善

### 2.1 运行时 arm execution evidence

**原问题**

V5 runner 虽然按 plan 执行，但 result 只保存 OFF/ON 分类结果。writer 随后从 plan 重建 `arm_position`。这能证明 writer 与 plan 一致，却不能证明 artifact 中的位置来自真实调用事件。

**RED**

三个定向测试失败：result 没有 `arm_execution`，逐题行没有 `execution_index`，也无法拒绝与 plan 冲突的 execution event。

**修改**

- `app/evaluation/indirect_injection_live_runner.py`
  - 新增 strict frozen `LiveArmExecutionEvent`；
  - 每次 `_evaluate_live_case()` 返回后立即记录 `execution_index`、`case_id`、`guard_mode`、`arm_position`；
  - `LivePairedResultV2` 必须保存完整事件序列；
  - validator 按 dataset order 和 plan 重建唯一合法序列，任何缺失、交换或 mode 矛盾均拒绝。
- `app/evaluation/indirect_injection_live_writer.py`
  - `_v2_per_case_rows()` 从 runtime events 读取位置和全局序号；
  - validator 要求序号覆盖 `1..2N` 且同一 case 的两个 arm 相邻。

**GREEN**

对应 `3 passed`。这把“计划证据”提升为“计划 + 运行时事件 + writer 交叉校验”。

### 2.2 私有 v2 summary 独立复算

**原问题**

私有 `_validate_stage()` 只解析 `summary.json`，没有从 `per_case.jsonl` 重新计算 summary。攻击者如果同时重算 checksum 和 manifest artifact hash，可以制造结构完整但语义矛盾的 artifact。

**RED**

测试把 `guard_off_live.case_count` 加一，再同步重算 checksum 和 manifest hashes。旧 validator 出现 `DID NOT RAISE`。

**修改**

- 严格解析每行 `SecurityCaseResult` 和 `LiveCaseObservation`；
- 核对 case/mode、candidate count 和 attack-unit count；
- 从逐题行重算 OFF/ON security summary、live summary、pair consistency、protocol completion 和 deterministic diagnostic gate；
- 将重算结果与 `summary.json` 和 manifest observation 精确比较；
- 要求 summary 是 canonical deterministic JSON。

**GREEN**

篡改测试和正常发布测试均通过。重新计算 hash 现在不能掩盖 summary/rows 矛盾。

### 2.3 正式 D7 目录与 test cohort 保护

**原问题**

只拒绝正式 run ID 不够：不同 run ID 仍可把 `out-dir` 或 `index-root` 指向正式 D7 目录。另一个自洽 test bundle 也可以通过自己的 freeze manifest，并产生带 `split=test` 标签的结果。

**RED**

- 自洽但修改过 question 的 test bundle 到达了 runtime settings；
- `out-dir`/`index-root` 指向正式目录时，旧代码继续进入数据加载。

**修改**

- 对解析后的 output root、output target 和 index root 做路径包含检查，拒绝等于或位于正式 D7 目录内部的路径；
- `split=test` 额外绑定官方 dataset SHA-256 和 fixture SHA-256；
- 所有检查在模型、索引和运行输出之前执行。

**GREEN**

相关 `5 passed`。`dev` 仍可使用新数据做实验，`test` 不能借自定义 freeze manifest 冒充官方 cohort。

### 2.4 公共仓库审计覆盖

**原问题**

旧审计的绝对路径检查主要覆盖 Markdown/公开表面，通用 credential assignment 只覆盖 D7 公共包。`0 findings` 容易被误读成“全仓不存在任何敏感信息”。

**修改**

- 非测试 Git 文本候选统一扫描 Windows/Linux user absolute path；
- runtime/config/data/CI 和核心公开文档扫描字面 credential-like assignment；
- 保留高置信 token/private-key 的全候选 bytes/text 扫描；
- 测试目录中的故意泄漏字符串继续作为 redaction fixture，不冒充真实 secret；
- 根 `.superpowers/` 是本地工作流状态，加入 `.gitignore`，但 `docs/superpowers/` 设计文档继续纳入仓库。

**RED/GREEN**

- 新 runtime fixture 最初没有 finding；修复后同时报告 path 和 credential；
- 扩展后的第一次真实审计为 `421 candidates / 1 finding`，唯一 finding 是 `.superpowers/.../server-info`；
- 忽略该本地状态目录后为 `414 candidates / 0 findings`。

准确说法仍是“没有命中当前定义的静态泄漏规则”，不是数学意义上的无秘密或无漏洞证明。

### 2.5 指标名称与状态一致性

**原问题**

核心结果文档仍出现 `raw model follow`，状态页开头仍写 V0-V4，industrialization backlog 仍把已完成的 indirect injection defense 标成 `NOT RUN`。

**修改**

- 核心文档统一为 `raw canary/forbidden-action signal`；
- 就地声明 semantic attack following 为 `NOT MEASURED`；
- 当前状态统一为 V0-V5 / V1-V5；
- README 增加 V5 日志入口；
- backlog 将下一缺口改为 independent indirect-injection validation。

**GREEN**

两个文档契约测试通过，防止后续再次写回误导名称或旧阶段状态。

## 3. 最终门禁

```text
targeted cross-module suite                 180 passed
full repository suite                      921 passed
warnings                                     3 known FAISS/SWIG warnings
public repository audit           415 candidates / 0 findings
repository public verifier                 VERIFIED
isolated 8-file public verifier            VERIFIED
compileall / pip check / git diff check    clean / clean / clean
dataset / fixture / freeze hashes          exact / exact / exact
historical formal D7 manifest hash         exact
real-model counterbalanced v2 run          NOT RUN
```

这 8 个新增回归测试来自本次审查缺口，而不是为了改变安全分数。正式 D7 run、冻结 test 数据和 V1 公共包未被重跑或改写。`0 findings` 只表示当前 415 个 Git 候选文件没有命中已实现的高置信规则，不表示绝对不存在 secret。

## 4. 哪些不完美已经改善，哪些还没有

| 不完美项 | 当前处理 | 当前能证明什么 | 仍不能证明什么 |
|---|---|---|---|
| 历史 D7 固定 OFF-first | 未来 v2 改为 18/18 counterbalanced，并新增真实 execution events | 新协议能减少并审计固定顺序混杂 | 历史 D7 仍是 fixed-order；尚无新真实模型 v2 结果 |
| historical reached 依赖推断 | V2 改为实际 Guard scan events | 新运行能准确区分 reached/unreached | 历史公共包继续复现旧 D7 v1 口径 |
| `3/24` 名称过宽 | V4 版本化为 raw canary/tool signal | 能测明确的原始信号 | 不能测同义改写、隐式服从或完整语义攻击成功 |
| 私有 artifact 只校验 hash | 本次从逐题行反算 summary/gate | 能发现自洽 hash 下的语义矛盾 | 不能建立脱离 Git/producer code 的绝对信任根 |
| Python 出站边界 | V3 exact origin/socket；文档明确 call-graph scope | 已覆盖 Requests、connect/connect_ex、redirect、proxy、Host override、urllib | 不是 OS sandbox；DNS、UDP、subprocess、native extension 不在“零网络”证明内 |
| visible synthetic set | 已冻结、可复算、保留失败 | 能做稳定 regression | 不能估计未知攻击、真实企业语料或跨模型泛化 |
| 人工语义审核 | 表格和 rubric 已有 | 自动指标边界清楚 | 50-row owner review、第二 reviewer 和 agreement 仍未执行 |

## 5. R2-S2 推荐顺序

### S2-1：counterbalanced real-model dev replication

目的不是追求更好数字，而是验证本次 v2 协议在真实 BGE-M3/Qwen 调用中能生成可信 artifact。

准入门槛：

- 使用新的 dev run ID，禁止复用正式 D7 ID；
- 36 case / 72 runtime execution events，序号精确 `1..72`；
- OFF→ON 与 ON→OFF 精确 `18/18`；
- pair input consistent；
- model/system error 为 0；
- blocked external egress 为 0；
- private v2 validator 全部复算通过；
- 结果只写 `COMPLETED WITH OBSERVATIONS`，不与历史 fixed-order D7 做伪因果比较。

### S2-2：独立 holdout 与人工红队

在查看结果前冻结新 case、fixture、taxonomy 和 hash。样本作者与 Guard 调参过程分离，至少覆盖同义改写、跨 chunk 组合、编码/Unicode、工具诱导、长上下文、metadata/open/find 和 benign hard negatives。

先区分两类失败：

- attack unit 没有进入 Guard：检索/工具暴露覆盖问题；
- attack unit 到达 Guard 但被 admit：detector false negative。

只有第二类失败才能直接驱动 Guard 规则修改。不能把 unreached 样本算成 detector 命中，也不能为了 test 分数改标签。

### S2-3：semantic judge calibration

LLM judge 只能作为辅助，不作为唯一裁判：

1. owner/人工 reviewer 按冻结 rubric 标注语义服从、信息泄漏、未授权动作和正常任务完成；
2. 第二 reviewer 对正式结论做盲评；
3. LLM judge 使用固定模型、prompt、温度和版本；
4. 在人工 gold 上计算 agreement、false positive、false negative；
5. agreement 未达门槛时，结果标记 `INCONCLUSIVE`，不能用 judge 自动替代人工结论。

### S2-4：失败驱动的 Guard 改善与跨模型复现

只对 holdout 中可复现的 reached false negatives 做最小规则变更，在 dev 修复后只运行一次新冻结 test。随后至少使用一个不同 family/size 的 chat model 复现，并同时报告安全、utility、latency、model calls 和资源变化。

## 6. 面试时应如何回答

可以说：

> 我没有把测试通过当成项目已经完美。V0-V5 后又做了一次独立 closeout review，发现 arm-order evidence 原来由 plan 重建、私有 summary 没有从逐题行复算、正式目录和 test cohort 保护不够严。我用 RED tests 逐项复现，再加入 runtime execution events、summary recomputation、frozen-path/hash binding 和更广的仓库审计。剩余问题没有隐藏：真实 counterbalanced 模型实验、独立 holdout、人工红队、semantic judge calibration、跨模型复现和 OS 级网络隔离都仍是后续工作。

不能说：

- `0 findings` 证明仓库绝对没有 secret；
- `0/24` 证明未知 prompt injection 免疫；
- `3/24` 是完整语义服从率；
- `15/15` 等于全部 `28/28` attack units；
- process-local boundary 是操作系统沙箱；
- 新 v2 协议已经产生真实模型改进结果。

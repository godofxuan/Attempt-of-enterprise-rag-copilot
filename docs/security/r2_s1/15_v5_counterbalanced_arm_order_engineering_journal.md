# R2-S1 V5 OFF/ON 反平衡顺序工程日志

状态：实现与本地验证完成，尚未 commit/push

日期：2026-07-19

适用范围：只适用于未来 dev/new live paired run

历史正式 run：`r2-s1-d7-test-20260718-01`，仍是 fixed OFF-first observational run

## 1. 这一阶段到底解决什么问题

D7 对每道题都执行：

```text
case 1: Guard OFF -> Guard ON
case 2: Guard OFF -> Guard ON
...
case 36: Guard OFF -> Guard ON
```

这种设计能够保证每道题有 OFF/ON 对照，但存在一个实验设计缺口：Guard 模式和时间顺序完全重合。如果模型服务发生预热、缓存、负载、状态漂移或前一次请求残留，后运行的 ON arm 可能系统性地处在不同条件下。此时观测差异可能同时包含 Guard effect 和 order effect。

V5 不否定 D7 的观测，也不重新追求一个更漂亮的 0/24。它只做两件事：

1. 未来同一批 case 中，一半先 OFF 后 ON，另一半先 ON 后 OFF；
2. 把分配计划和每个 arm 的实际位置写入不可变证据。

正式 D7 没有被重跑或改写。它的正确标签继续是：一次固定 OFF-first 的本地观察性运行。

## 2. 为什么不用普通随机数

如果每次运行调用 `random.shuffle()`，虽然顺序看起来更随机，但会产生三个审计问题：

1. 没有 seed 时无法复现；
2. 有 seed 但没有保存时，证据仍无法解释；
3. 即使保存 seed，Python/库版本或输入迭代顺序变化也可能让实现细节变得难核对。

V5 使用 `case_id` 的 SHA-256。哈希是稳定、跨机器、与 Python 进程随机种子无关的纯函数：

```python
case_hash = sha256(case_id.encode("utf-8")).hexdigest()
```

但只取哈希最低位也不够。它只能做到期望上接近一半，不能保证 36 道题正好 18/18。因此采用稳定哈希排名交替分配：

```text
1. 计算全部 case_hash
2. 按 (case_hash, case_id) 排序
3. hash_rank 为 0, 1, 2, ...
4. 偶数 rank -> OFF then ON
5. 奇数 rank -> ON then OFF
```

偶数 case 数量必然精确 50/50；奇数数量最多相差 1。输入列表倒序不会改变计划。

这个方案的限制也被明确记录：它对固定 cohort 稳定；如果增加或删除 case，后续 hash rank 可能变化。因此 manifest 保存完整 cohort plan，不能只保存一句“使用了 counterbalancing”。

## 3. 代码改在哪里

### 3.1 `app/evaluation/indirect_injection_arm_order.py`

这是 V5 新增的独立协议模块，不依赖 runner、writer、模型或检索。

#### `ArmOrderAssignment`

每道题的无原文分配记录：

```python
class ArmOrderAssignment:
    case_id: str
    case_hash: str
    hash_rank: int
    arm_order: Literal["off_then_on", "on_then_off"]
```

`modes()` 把声明转换成真正的调用序列：

```python
"off_then_on" -> ("off", "on")
"on_then_off" -> ("on", "off")
```

#### `CounterbalancedArmOrderPlan`

plan 保存协议 ID、算法、case 总数、两种顺序计数和全部 assignment。它不是一个只靠调用者自觉填写的 DTO。Pydantic validator 会重新：

1. 检查 assignments 是否按 `case_id` 规范排序；
2. 检查 case ID 唯一；
3. 重算每个 SHA-256；
4. 重算所有 hash rank；
5. 根据 rank 奇偶重算 arm order；
6. 重算 18/18 summary count。

所以修改 manifest 中任一 hash、rank、order 或 count 都不能通过模型校验。

#### `build_counterbalanced_arm_order_plan()`

builder 先拒绝空集合、重复 ID、空 ID、首尾空白和非字符串，再生成规范 plan。`assignment_for(case_id)` 对未知 ID 抛 `KeyError`，不会临时猜一个顺序。

### 3.2 `app/evaluation/indirect_injection_live_runner.py`

#### 为什么保留 v1

`LivePairedResult` 继续严格表示：

```text
indirect_injection_live_paired_result_v1
```

它没有新增 optional `arm_order`。如果向 v1 塞 optional 字段，会出现“同一个 schema version 有两种含义”，历史 parser 和证据解释都会变得含糊。

V5 新增：

```python
class LivePairedResultV2(LivePairedResult):
    schema_version = "indirect_injection_live_paired_result_v2"
    arm_order: CounterbalancedArmOrderPlan
```

v2 validator 同时检查 live OFF、live ON、security OFF、security ON 四组 case ID 是否都与 plan 相同。这是代码自审时补出的边界，避免错配一直拖到 writer 查表才变成 `KeyError`。

#### `evaluate_live_paired()` 如何改

函数新增可选参数：

```python
arm_order: CounterbalancedArmOrderPlan | None = None
```

这不是让未来 CLI 自由选择旧模式。`None` 只服务于历史 v1 parser/单测兼容；未来 CLI 总是传 plan。

每个 case 的新执行逻辑是：

```python
modes = arm_order.assignment_for(case.case_id).modes()
evaluated = {}
for guard_mode in modes:
    evaluated[guard_mode] = _evaluate_live_case(...)

off_case = evaluated["off"]
on_case = evaluated["on"]
```

这里最容易混淆的是两种“顺序”：

- execution order：真实先调用 OFF 还是 ON，由 plan 控制；
- result order：最终 `guard_off` 与 `guard_on` 数组仍分别按 dataset 顺序保存。

必须分开。现有指标用 `zip(off, on)` 比较同一题；如果为了展示执行顺序而打乱结果数组，就会破坏 pair alignment。V5 改实验执行，不改指标输入结构。

### 3.3 `app/evaluation/indirect_injection_live_writer.py`

#### `LiveSecurityRunManifestV2`

新 manifest 明确使用：

```text
schema_version = indirect_injection_live_security_run_manifest_v2
mode = local_live_paired_counterbalanced
arm_order = 完整 CounterbalancedArmOrderPlan
```

旧 `LiveSecurityRunManifest` v1 类保持严格不变。writer 在发布前检查 manifest/result 必须同版本，并检查两边的 plan 完全相等。RED 测试证明旧 writer 原先会错误接受“v1 manifest + v2 result”；V5 把它改成显式失败。

#### v2 `per_case.jsonl`

旧 v1 行仍是：

```json
{"security": {}, "live": {}}
```

新 v2 行是：

```json
{
  "arm_execution": {
    "protocol_id": "stable_case_hash_rank_counterbalanced_v1",
    "case_hash": "...",
    "hash_rank": 0,
    "arm_order": "off_then_on",
    "arm_position": 1
  },
  "security": {},
  "live": {}
}
```

writer 以 plan 的 canonical assignment 顺序遍历 case，每个 case 连续写两行，并按 `modes()` 写真实第 1、2 arm。`_validate_v2_per_case_rows()` 再反向验证：

- 总行数是否等于 `case_count * 2`；
- 每两行是否属于同一 case；
- position 是否严格为 1、2；
- mode 是否与 order/position 一致；
- hash、rank、protocol ID 是否与 manifest 一致；
- security/live 的 case ID 和 guard mode 是否一致。

v2 没有增加第八个 artifact，仍复用原有七个内容 artifact、SHA-256、staging directory、不可覆盖发布和敏感内容扫描。

### 3.4 `scripts/eval_indirect_injection_live.py`

未来命令在 frozen-data 校验并加载 dataset 后立即构造 plan，随后把同一个对象传给 runner 和 manifest builder。用户不能通过一个 CLI switch 静默恢复 fixed OFF-first。

脚本还新增了正式 ID 保护：

```python
if args.run_id == "r2-s1-d7-test-20260718-01":
    raise ValueError(...)
```

这项检查发生在读取数据、访问 Ollama 和建索引之前。过去主要依赖“目标目录已存在所以不能覆盖”；如果用户换 `--out-dir`，仍可能再次执行同名正式实验。现在这个约束由代码强制执行。

## 4. TDD 过程与每个 RED 证明了什么

### 4.1 入口基线

```text
live runner/writer/CLI baseline   32 passed
```

### 4.2 Plan RED/GREEN

第一次 RED：

```text
ModuleNotFoundError:
No module named 'app.evaluation.indirect_injection_arm_order'
```

说明测试确实依赖尚不存在的新协议模块。实现后：

```text
14 passed
```

覆盖 36 题 18/18、输入倒序稳定、奇数平衡、SHA/rank/parity、自校验篡改和非法 ID。

### 4.3 Runner RED/GREEN

RED：

```text
TypeError: evaluate_live_paired() got an unexpected keyword argument 'arm_order'
```

计划缺题的测试也以同一缺失接口失败。实现后，新测试记录真实 `_evaluate_live_case()` 调用序列，并验证 OFF/ON 数组仍对齐。runner 文件先达到：

```text
28 passed
```

代码自审又新增一条跨四组 case-set 的 RED，初次结果为：

```text
Failed: DID NOT RAISE ValidationError
```

补强 validator 后通过，runner 当前共 29 个测试。

### 4.4 Writer RED/GREEN

三条 RED 分别显示：

```text
AttributeError: LiveSecurityRunManifestV2 does not exist
AttributeError: _validate_v2_per_case_rows does not exist
Failed: DID NOT RAISE for v1 manifest + v2 result
```

第三条不是缺类，而是发现旧 writer 会生成语义不一致 artifact。实现版本配对和 v2 行验证后：

```text
6 passed
```

### 4.5 CLI RED/GREEN

RED 一：测试期望 v2，实际 manifest 为 v1。

RED 二：使用正式 D7 ID 和新输出目录时，程序走到了数据读取并报 `FileNotFoundError`，说明没有 ID 级冻结保护。

接线后：

```text
5 passed
```

测试证明正式 ID 在任何 frozen-data/model/index 工作前被拒绝。

### 4.6 联合与全仓结果

```text
V5 plan + live runner/writer/CLI       53 passed
security + evaluation + D2 retrieval 404 passed
full repository suite                913 passed
known warnings                         3 FAISS/SWIG deprecation warnings
compileall / pip check / diff check    clean
public repository audit               421 candidates / 0 findings
repository public verifier            VERIFIED
clean isolated 8-file verifier        VERIFIED
```

## 5. 实现中遇到的问题及解决方法

### 5.1 构造器改字典时保留了关键字参数语法

第一次重构 return payload 时写成：

```python
result_payload = {
    split=dataset.split,
}
```

Python 字典必须使用 `"split": dataset.split`。这是机械搬运错误，在执行测试前的局部代码检查中发现并修正，没有改变设计或测试。

### 5.2 抽 helper 时把两个 artifact 写入放到了 `return` 后

提取 `_v1_per_case_rows()` / `_v2_per_case_rows()` 时，`commands.txt` 和 `test_output.txt` 的写入一度被移动到 helper 的 `return rows` 后，成为不可达代码。若不检查，stage 会因为缺 artifact 失败。

解决方式不是放宽 artifact 集，而是把原两句写入恢复到 `_write_content_artifacts()`。这保留了 v1 的不可变发布合同。

### 5.3 v1 manifest 可以和 v2 result 混用

这是 RED 测试发现的真实 schema 风险。修复为在 `_validate_consistency()` 最前面检查两边是否同时为 v2，并在 v2 情况比较完整 plan。

### 5.4 v2 最初只校验 live OFF case 集合

代码自审发现 ON/security 集合仍可被手工错配。先写 `DID NOT RAISE` 的 RED，再把四组集合全部纳入 validator。错误因此在数据模型边界被拒绝。

### 5.5 在公共包目录使用了错误的相对 Python 路径

第一次包内验证把工作目录切到 `data/v2/public/r2_s1_d7/` 后，仍执行 `./.venv/Scripts/python.exe verify.py`。`.venv` 位于项目根而不在公共包内，因此 PowerShell 报“无法识别该路径”，退出 1。

这不是 verifier 的校验失败。改用项目虚拟环境解释器的绝对调用后，包内 verifier 通过；再把严格 8 文件复制到干净临时目录运行，也得到相同 `VERIFIED`。区分“命令路径错误”和“被测程序发现证据错误”很重要，不能把二者混成一个失败原因。

## 6. 冻结与兼容性结果

本轮没有执行真实正式模型 run。以下文件 SHA-256 与 V0-V4 相同：

```text
test dataset
062aec151d29854ffcebf6368b42fc768f7a0a5f64e1218e32fd326a441a137c

test fixture manifest
eea41009bd5a8eda2b0a1ff7c29e593895d917b4055e9712b1db48daa9d51c1d

test freeze manifest
5c9ba8aaa8cc1a0f8f02ddf011900ed4be022ece95b343902d1ad2469838fdd4

formal D7 manifest
5bf058cfa56c2b5034e6f204dc3619833b55b3c30277c5222e7415f97865e14e
```

旧 v1 runner 测试继续证明 dump 不含 `arm_order`。V1 公共证据包继续固定 `source_arm_order=off_then_on_per_case`，没有被 V5 修改或重新生成。

严格 v1 parser 仍成功解析正式 manifest：schema 为 `indirect_injection_live_security_run_manifest_v1`，mode 为 `local_live_paired`，artifact 数量为 7。仓库 verifier、包内 verifier 和干净临时目录 verifier 均独立重算出 `36 cases / 72 rows / 15 metrics`。

## 7. V5 做到了什么，没做到什么

做到了：

- 未来固定 cohort 的顺序计划跨机器可复现；
- 36 题精确 18/18；
- 真实调用顺序受 plan 控制；
- manifest 和逐 arm 行均可审计；
- v1/v2 不能混用；
- 正式 D7 ID 不能重跑；
- 历史 v1 schema 和公共包不变。

没有做到：

- 没有重新运行一次本地真实 Qwen/BGE-M3 v2 实验；
- 没有估计 order effect 的数值大小；
- 没有消除所有时间、缓存和模型状态影响；
- 没有变更 Guard，因此也没有提高未知攻击检测覆盖；
- 没有把 3/24 扩大解释成语义服从率；
- 没有把观察性运行升级成因果或生产安全认证。

## 8. 面试可能追问及答案

### Q1：为什么 fixed OFF-first 有问题？

因为 treatment 和时间顺序共线。ON 永远后跑，预热、负载或模型状态都可能被误认为 Guard 效果。counterbalancing 让两种顺序在 cohort 中平衡，减少这个混杂因素。

### Q2：为什么不用 `random.shuffle()`？

安全评测首先要可复现和可审计。随机顺序如果 seed、输入序列和算法版本没有完整保存，很难复算。SHA-256 hash-rank 是确定性协议，完整 assignment 又写入 manifest。

### Q3：为什么不是直接用 hash 的奇偶位？

独立 hash parity 只能期望平衡，36 题不保证 18/18。hash-rank alternation 对偶数 cohort 精确平衡，对奇数 cohort 最多差 1。

### Q4：为什么 result 还分 guard_off/guard_on 存，不按真实运行顺序存？

执行顺序服务实验控制，结果分组服务指标计算。现有 summary 要按同一 case 对齐 OFF/ON；混在一起会增加配对错误。真实顺序已经单独写入 plan 和 `arm_execution`，不需要破坏指标结构。

### Q5：为什么要升 v2，不在 v1 加 optional 字段？

schema version 是解释合同。给 v1 加 optional 字段会让同一个版本同时代表 fixed-order 和 counterbalanced 两种实验，消费者无法仅凭版本判断。v2 明确表示新协议，v1 仍精确解析历史 artifact。

### Q6：manifest 已有 plan，为什么逐题行还要保存 arm order？

manifest 证明计划，逐题行证明某条观测在计划中的实际位置。二者交叉校验后，交换两行、改 position、改 mode 或改 hash 都会失败。只保存计划不能证明 writer 真的按计划组织证据。

### Q7：为什么不对每题同时跑 AB 和 BA？

那会从每题 2 次模型执行增加到 4 次，成本和运行时间翻倍，并需要 replica-level 指标。当前目标只是修复固定顺序缺口，cohort counterbalancing 是更小的工程改动。若以后要直接估计每题 order effect，再升级为 AB/BA replica protocol。

### Q8：V5 能证明 Guard 的因果效果吗？

不能。它减少一个已知顺序混杂，但单机、单模型、可见 synthetic set、一次运行仍有外部有效性和随机性限制。准确说法是“未来 v2 运行采用可审计的确定性反平衡顺序”，不是“已经得到跨模型因果结论”。

### Q9：历史 D7 结果还可信吗？

它仍可作为被完整披露限制的一次观察。V5 不改变其 7/24、3/24、0/24 等历史数字，也不把它冒充 counterbalanced run。公开包已经写明 source 是 fixed OFF then ON。

### Q10：这一阶段最体现工程能力的地方是什么？

不是写一个随机顺序循环，而是把实验设计变成严格数据合同：稳定分配、自校验 plan、版本化 schema、真实调用顺序、逐行 provenance、不可变 writer、旧 artifact 兼容和正式 run 防重跑。这样改进不仅“看起来合理”，还能被测试和证据复核。

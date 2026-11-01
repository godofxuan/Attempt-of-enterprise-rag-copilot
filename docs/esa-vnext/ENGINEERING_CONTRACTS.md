# 工程契约：数据、接口、执行与恢复

本文提供要实现的行为和职责，不要求按字面新建每一张表或迁移所有URL。已有等价结构直接复用；与当前实现不同的地方由Codex在一次短决策记录中说明。

## 1. 先确认事实由谁维护

| 对象 | 事实来源 | 其他层如何使用 |
|---|---|---|
| 用户参数、任务范围、当前revision | 任务业务存储 | UI和Agent读取，不从模型摘要恢复 |
| 预览、确认、业务申请与回执 | 现有领域服务/SQLite事务 | Agent解释，页面显示；不能自己改成成功 |
| 文档及版本 | 文档仓储与文件存储 | 索引和答案引用明确版本 |
| 活动索引代次 | 现有索引发布器 | 每次查询固定使用一个代次 |
| 正式知识结果 | 统一KnowledgeService返回的现有AnswerResponse | RAG与Service直接展示/组合，不复制出第二套正文 |
| 一次运行的排队/执行/结束 | run记录 | 页面显示进度，任务业务结果不能只由run状态推断 |
| 进度事件 | 单一事件记录与递增seq | 用于增量UI，不是重建全部数据库的event-sourcing平台 |
| 对话摘要、任务视图、上下文片段 | 派生结果 | 可以重建，不覆盖上面的事实 |

任务、一次运行、业务审批本来就是不同对象。不要将它们全变成一个`success`，也不要在五层都保存各自独立的“完成标志”。

## 2. 逻辑数据模型与迁移原则

### 2.1 逻辑对象

- `Conversation` / `Message`：独立知识会话与服务对话；服务对话关联task，纯问答不强制建task。
- `KnowledgeBase` / `Document` / `DocumentVersion`：资料集合、稳定文件身份、替换后的内容版本。
- `IngestionJob`：实际阶段、处理数量、错误、源版本与目标索引代次。
- `Task`：服务类型、事实参数、范围、revision、当前交互需要、关联知识结果。
- `Proposal`：不可变的具体预览，绑定当时参数、规则与资源版本；旧预览保留用于解释，但不能用于提交新参数。
- `BusinessCommand` / `Ticket` / `Receipt`：优先复用现有事务对象，不另建平行申请系统。
- `Run` / `RunEvent`：一次执行及必要进度；不保存无用的完整模型推理。
- `Feedback`：用户指出问题的对象与类型、最少备注，便于复现改进。

以上是逻辑对象，不意味着必须新增12张表。已有task_events、action_proposals、commands、tickets、messages等结构先映射。只有职责缺失时新增最少列/表。

### 2.2 迁移

使用现有迁移机制或简单版本化SQL，不同时引入全项目ORM重写。每步迁移可重复识别、失败有明确状态。已有个人数据只做明确备份和一次迁移，不把示例seed写进日常启动。

活动SQLite库有WAL时采用SQLite备份接口或停写后的完整备份，不仅复制主文件。新旧数据库不得同时成为默认活动库。字段重命名尽量保持兼容读取，下一发布再删除已无调用方的旧入口。

## 3. 配置与应用装配

现有`app/runtime/resources.py::ServiceContainer`和`app/main.py::create_app`是优先改造点。目标是显式配置与依赖，不要求再创建另一个同等容器。

```python
# 结构示意：函数签名应适配当前真实代码，不是已交付可执行模块。
settings = load_settings(config_path, cli_overrides)
services = build_services(settings)
app = create_app(services)
```

装配阶段创建轻量对象，不执行索引重建、模型生成、源码指纹扫描或历史授权账本对账。生命周期启动数据库/有界队列和必要连接，重资源按能力需要延迟加载。关闭时停止接收新作业、保存中断状态、释放连接。

只有一处读取并规范化模型endpoint/tag、DATA_DIR、检索profile。产品模式、合成数据模式、离线fixture模式是明确设置；不能因失败自动变更模式。

## 4. 对外接口：先保持现有路径，增加必要能力

下面是目标API清单。现有`/agent/v2/chat`、`/service/tasks`继续可用；不用为了路径整齐重命名所有调用方。新异步入口与旧同步入口调用同一应用服务，不能复制业务。

| 接口 | 目的 | 返回原则 |
|---|---|---|
| `GET /health/live` | 进程存活 | 不调用模型/索引构建 |
| `GET /api/status` | 分能力状态与可行动错误 | Web、存储、模型、嵌入、各知识库分别报告 |
| `GET/PATCH /api/settings` | 允许用户设置的连接/默认项 | 隐藏凭据，变更相关能力状态，不重启所有功能 |
| `GET/POST /knowledge/bases` | 知识库列表/创建 | 有稳定ID、名称、文档数量、可用状态 |
| `POST /knowledge/bases/{id}/documents` | 上传或明确替换版本 | 返回文档与job_id，不在请求里处理到超时 |
| `GET /knowledge/jobs/{id}` | 导入进度 | 真实阶段与计数、失败原因及可重试状态 |
| `POST /knowledge/jobs/{id}/retry` | 重试可重入处理 | 复用已完成可用阶段，不重复整个库 |
| `GET /knowledge/documents/{id}` | 文档元信息/版本 | 当前与历史版本明确区分 |
| `GET /knowledge/documents/{id}/excerpt` | 来源定位 | 版本与页/段/章节明确；不可用时给出原因 |
| `POST /knowledge/runs` | 异步问答与深入查找 | 202 + run_id，结果仍为同一个AnswerResponse |
| `POST /agent/v2/chat` | 兼容原知识接口 | 仍由同一KnowledgeService处理 |
| `GET /service/catalog` | 当前实际支持服务 | 字段schema、可用动作与显示信息 |
| `GET/POST /service/tasks` | 历史/创建任务 | 数据库task是核心，用户不需要手填ID |
| `GET /service/tasks/{id}` | 任务工作台快照 | 参数、下一步、预览、来源、回执的一个视图 |
| `PATCH /service/tasks/{id}/facts` | 修改明确参数 | 原子revision检查，返回实际新状态 |
| `POST /service/tasks/{id}/messages` | 自然补充或追问 | 提取字段/解释后回到同一任务，不建平行计划 |
| `POST /service/tasks/{id}/runs` | 开始/继续处理 | 返回run_id，不阻塞到全部模型调用完成 |
| `POST /service/tasks/{id}/submit` | 用户对当前预览确认提交 | 不调用模型，返回实际回执；重复请求不重复业务 |
| `POST /service/tasks/{id}/cancel` | 取消当前任务/运行意图 | 不等于自动撤销已创建业务工单 |
| `GET /runs/{id}` | 运行快照与结果引用 | succeeded不等于审批通过 |
| `GET /runs/{id}/events?after_seq=...` | SSE进度或补读 | 单调序号，客户端去重 |
| `POST /feedback` | 反馈答案或任务问题 | 关联对象，不自动启动高成本评估 |

旧confirm/submit两接口如已有消费者可兼容保留，由新用户动作调用同一业务事务链；产品页面不再要求用户先确认一次然后手动按第二个“执行提交”。

### 4.1 字段修改示例

```json
{
  "expected_facts_revision": 7,
  "changes": {"loan_end": "2026-11-05"}
}
```

事务内检查revision，然后修改并递增。冲突例子：

```json
{
  "code": "TASK_CHANGED",
  "message": "任务已在另一页面更新，请比较后保留你的修改。",
  "current_revision": 8,
  "current_facts": {"loan_end": "2026-11-06"},
  "conflicting_fields": ["loan_end"]
}
```

UI保留用户尚未保存输入，但不能无提示重发。`changes`缺少字段表示不改，显式null按字段业务定义清空或拒绝；不再用exclude_none把两者混同。

### 4.2 提交示例

```json
{
  "proposal_id": "proposal_demo_7",
  "expected_facts_revision": 8,
  "accepted": true,
  "client_request_id": "submit-click-demo-01"
}
```

这是设计示意，现有proposal_id格式可以原样保留。若底层确认仍使用content_digest，由服务端与前端状态管理自动传递，用户不手抄hash。唯一性与幂等优先沿用既有command约束，不平行新增第二套幂等账本。

先检查当前预览/参数/资源，再在明确事务中提交。提交成功后网络断开，重试通过原命令读回相同结果；不能让模型补一个看似成功的JSON。

## 5. 三类状态与用户动作

### 5.1 任务交互状态

这是对现有任务数据的视图映射，不是强制迁移所有旧枚举。

```text
collecting ──信息齐全──> ready ──执行──> running
running ──缺信息/需选择──> waiting_user
running ──预览完成──> awaiting_confirmation
awaiting_confirmation ──修改──> ready
awaiting_confirmation ──确认并真实提交──> submitted
任意未提交阶段 ──业务无法继续──> blocked
任意阶段 ──用户结束此任务──> archived/cancelled（按真实业务语义）
```

“取消任务”只是停止当前交互和运行。已提交申请需使用业务系统明确支持的取消能力，不能只改task状态当作撤销了单据。

### 5.2 run状态

`queued → running → succeeded | waiting_user | failed | interrupted | cancelled`。

`waiting_user`保留下一步需要，而不是把图线程永久挂在内存等待。用户提交后启动新run。`interrupted`恢复时从业务快照重新规划一个短循环，不强求历史模型内部状态可恢复。

### 5.3 业务状态

沿用现有ticket状态。`PENDING_APPROVAL`不是`ALLOCATED`。页面明确说“申请已提交，等待审批”，不能把run的`succeeded`覆盖业务状态。

## 6. Agent状态与工具契约

### 6.1 给图的最小状态

```text
task_id, run_id, facts_revision
service_kind, execution_ceiling
user_goal, current_facts, missing_fields
valid_observations, source_refs, active_proposal_ref
recent_messages, recent_tool_outcomes
step_count, last_progress_marker
```

尽量引用已有数据，不把数据库整行、全部工具结果和所有文档正文塞进每轮状态。用于展示的`TaskView`是组合结果；事实仍在Store。

### 6.2 工具输入与输出

公开工具名采用清楚的snake_case。内部已有`knowledge.search`等名字可以通过一个兼容映射保留，不全量改写历史事件。

每个工具包含：适用场景、真实参数schema、结果类型、是否只读、结果依赖字段和过期依据。业务参数由模型填写；actor、task、scope和版本由runtime注入。[R08]

统一工具结果可以在现有契约上表达：

```json
{
  "status": "ok",
  "summary": "当前日期有2台符合条件的设备。",
  "data": {"asset_ids": ["asset_demo_a", "asset_demo_b"]},
  "artifact_refs": [],
  "observed_at": "2026-10-29T08:00:00Z",
  "based_on_revision": 8,
  "resource_version": "inventory_demo_12"
}
```

其他状态可为`empty`、`needs_input`、`retryable_error`、`unavailable`。这些是语义分类，实际字段在既有ToolResult上扩展，不创建第三份重复协议。

### 6.3 工具清单与代码职责

| 工具能力 | 领域实现 | 模型职责 |
|---|---|---|
| 查询规则与资格 | 既有业务规则/资格服务 | 判断现在是否需要查询，解释结果 |
| 查询库存和排期 | 设备适配器 | 提出符合用户条件的查询，不发明库存 |
| 查询已有申请/读回 | 现有Store/ticket适配器 | 避免用户重复办理，说明当前状态 |
| 查询与阅读知识 | KnowledgeService | 在有缺口时补读，引用相关内容 |
| 准备预览 | Proposal服务 | 选择已有候选/参数，不能越过正式提交 |
| 比较备选 | 可用资源查询与排序 | 说明选择取舍，不自动替用户降低要求 |

知识答案作为正式artifact返回时，直接展示现有AnswerResponse；Agent可总结任务进度，不重复改写知识正文并重新分配引用。

## 7. 修改影响分析：小表格，不是新计算框架

第一版可以由领域函数返回受影响的观察类别，避免通用依赖图引擎。

| 变化 | 应失效 | 可以保留（须仍在适用期） |
|---|---|---|
| 借用起止日期 | 可用库存、可选排期、具体预览 | 与日期无关的规则摘录、身份信息 |
| 设备选择/类别 | 库存匹配、具体预览、依赖类别的资格结果 | 无关的政策问答结果 |
| 用途 | 具体预览、依赖用途的资格/规则判断 | 与用途无关且未过期的资源信息 |
| 任务范围变更 | 超出新范围的执行计划和预览 | 只读且仍合法的历史资料 |
| 政策版本变更 | 受影响资格和预览 | 无关的文档回答与库存原始查询 |
| 已有申请状态变更 | 冲突检查、相关预览 | 独立知识片段 |

未知依赖保守重查，不能为了省模型调用跳过真实业务条件。库存等短期事实有TTL或资源版本；提交前重新读取关键事实。字段/版本足以表达关系，不需要把整个源码或prompt都hash起来。

## 8. Service Catalog与R2扩展

从现有`capabilities.py`逐步演化为静态代码注册表，不开放任意上传Python插件。

```python
# 契约示意，不是要求新增一套可安装SDK。
class ServiceDefinition:
    key: str
    title: str
    input_schema: type
    form_spec: dict
    tools: tuple
    adapter: object   # collect/prepare/submit/read 的现有领域接口
```

第一服务loan先实现适配。R2的it_repair使用不同schema与业务函数，但复用TaskService、Agent图、UI表单组件、事件和预览确认组件。出现某个接口只为一种服务服务时，允许留在该适配器，不提前抽象。

服务目录描述的是支持能力，不让模型动态创造新服务。只展示当前真正可用的动作。一个配置名称不等于新的业务集成完成。

## 9. 模型层与上下文层

`ModelService`统一超时、连接、并发、流式与错误分类，优先用实际版本支持的ChatOllama或已有Ollama客户端。[R08、R11] 不创建新的SDK体系。

ContextBuilder优先确定性读取并裁剪：当前事实/约束 > 本轮有效观察 > 相关来源 > 最近对话 > 过往摘要。完整正文留在文档服务，调用read按需取回。模型支持窗口不足时减少无关材料，而不是隐式截断必要条件。

单次无效结构输出至多做有依据的格式修复；持续失败提示模型兼容性或参数问题。不能回退到包含特定测试答案的脚本完成“实时演示”。

模型输出的步骤说明仅供用户理解，不能输出或保存完整隐藏推理链。向UI发送动作概述、观察与结果即可。

## 10. 作业、run和SSE

`JobRunner`处理文档导入/索引等本地耗时工作；Agent run由同一应用生命周期协调，但不要求强行共用一套巨大通用workflow模型。

创建工作时先持久化queued记录，再进入有界队列。重启扫描属于本应用的中断工作，恢复可重入阶段；不把运行记录直接改成完成。一个task默认一个活动run；新revision使旧run不能发布覆盖当前任务的结果，复用已有revision/fence能力。

事件示例：

```json
{
  "run_id": "run_demo_09",
  "seq": 12,
  "type": "proposal.ready",
  "task_id": "task_demo_03",
  "facts_revision": 8,
  "payload": {"proposal_id": "proposal_demo_7"}
}
```

事件类型尽量少：`run.started`、`step.completed`、`input.required`、`artifact.ready`、`proposal.ready`、`business.submitted`、`run.failed`、`run.finished`。文本流可以走实时通道，不强制每token入库。

客户端先取快照，再从快照最后seq之后订阅；重复事件按seq忽略。历史事件过期时返回需要刷新快照，不无限保留全量日志。断流不取消业务，不因用户重复打开页面就重新提交任务。

## 11. 错误与恢复行为

| 情况 | 代码和界面应该做什么 | 不应该做什么 |
|---|---|---|
| 模型tag不存在 | 显示实际配置/可选择模型，生成能力不可用 | 静默换模型或随机下载 |
| 端口被占用 | 报实际端口，可显式选择空闲端口 | 杀掉不明进程 |
| 依赖/ABI冲突 | 确认Python和包版本，修依赖组/锁与安装说明 | 反复全局pip升级、同时保留多环境不知用谁 |
| 文档解析空白 | 标明需要支持的解析器或OCR | 以0个片段标“处理成功” |
| 索引代次/维度不兼容 | 将受影响知识库标为需重建，提供可操作入口 | 每次请求重新加载一份随机索引 |
| 库存空 | 返回空结果，基于真实数据查询备选 | 让LLM编出设备/日期 |
| 提交后超时 | 根据幂等命令读取既有业务结果 | 重建一个申请或让模型自称成功 |
| 用户同时编辑 | 返回revision冲突，保留本地未保存输入 | 自动覆盖另一个页面 |
| Agent无新观察重复工具 | 提示阻塞，转补充/明确结束本run | 加更多reviewer或无限循环 |
| 显存/内存不足 | 调低本应用并发/批次，复用已有模型配置 | 杀其他人的任务、改驱动或假装换成小模型等价通过 |

## 12. 代码职责映射与合并路线

| 当前定位 | 收敛方向 |
|---|---|
| `tools/launch_local.py`和dual_track脚本 | 产品CLI成为默认；双进程实验入口退出默认依赖链 |
| `app/main.py`与`runtime/resources.py` | 复用应用工厂/容器，显式生命周期和能力状态 |
| `app/config.py` | 普通产品配置与实验配置分离 |
| `service_desk/knowledge.py` | 直接适配共用KnowledgeService，不重建答案 |
| `agent/generation_v2.py`与发布器 | 唯一结果构建路径，保留有效条件和来源行为 |
| `service_desk/store.py` | 先保留SQL事务，逐步提取编辑/预览/申请/运行职责 |
| `service_desk/goals.py` | guided主路径只保留必要目标与状态投影；历史自由文本重解释隔离 |
| `agent_runtime/task_agent_graph.py` | 迁移模型、上下文、工具到对应模块，图只装配循环 |
| `indexing/store.py`等 | 复用索引代次/可恢复导入，接入UI与作业记录 |
| `streamlit_app/dual_track_portal.html` | 单工作台和JS模块；目录旧名不是必须用Streamlit的理由 |

拆模块时每一步保持一个可运行切片。允许短期适配层，但同一能力切换后移除旧默认调用，不能形成v12/v13等永久并行路线。

## 13. 用户旅程与验证尺度

以下是发布场景，不是要求每次改动都跑完所有矩阵：

J01 干净安装启动；J02 模型未就绪但UI/历史可用；J03 导入及失败重试；J04 有来源问答和来源打开；J05 正常借用；J06 多次改期与并发编辑；J07 无库存/已有申请；J08 确认与重复提交读回；J09 刷新/重启继续；J10 知识转任务及备选选择；J11 第二个IT报修服务；J12 目录增量与历史版本引用。

单元/契约测试使用合成数据，浏览器主要覆盖关键交互，真实模型只做少量有代表性的主路径。保存已有A1必要条件反例及关键事务检查。测试结果与交付功能一致，不能把回放、历史结果或fixture说成当前live。

记录可解释的基线与改进：相同模型、相同数据、同场景的耗时/调用/用户步骤。若某优化没有带来收益，移除无用复杂度，不编造百分比。

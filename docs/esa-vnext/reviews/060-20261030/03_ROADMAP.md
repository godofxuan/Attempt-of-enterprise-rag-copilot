# 连续实施路线：0.6.1 → 0.7
不是推倒0.6，不叠加上一轮32项审核工程。本轮18项工作从实际缺陷、语义能力与发行质量出发；每项实现后做相关验证。所有工作项当前状态PLANNED，不能当成已实现。
## 阶段与可运行出口

| 阶段 | 工作项 | 阶段成果 |
|---|---|---|
| S0 | T01—T06 | 0.6.1：修正确恢复、工作区、知识绑定、历史发现与复合请求；旧业务不回退 |
| S1 | T07—T09 | 基于同一候选完善UI、原生发行与资料更新可用性 |
| S2 | T10—T13 | 有依据的解释/比较、上下文效率、真实语义集与代码收敛 |
| S3 | T14—T18 | 常规测试入口、完整浏览器/Windows、同版整体使用与0.7交付 |

T14可在S0期间落地，不等待全部功能才开始测试；T08的Windows依赖与T10知识工作可并行，但两边必须在同一候选整合。0.6.1后主动继续0.7。
## 效率取舍

先修共同机制，再批量修表现；不给F01—F06各建一个管理器。现有模型能力、领域数据库与检索实现继续用。不会为了凑工作项强行新建模块；当前工作区已解决的问题只补实际证据并跳过重复实现。

外部条件真正阻塞Windows或模型时，继续不依赖它们的任务。最终正式完成仍需解除阻塞，不能用自动生成的报告替代实测。
## 详细任务

### T01 · 确定真实工作区并运行首个用户入口

阶段：S0；前置：无。

问题：实际工作区可能领先审核包；现有问题和依赖不可从摘要猜测。

修改：保留未提交成果和活动DATA_DIR，验证当前app启动、核对本包发现是否仍存在；已有修复保留。

主要入口：`README.md`、`docs/esa-vnext/STATUS.md`、`app/workbench_app.py`。

完成条件：真实运行记录、实际活动commit和本轮断点，不产生新平行计划。对应场景：Q01。

### T02 · 保留原回合请求和正确重试

阶段：S0；前置：T01。

问题：F01 Deep与原请求参数丢失。

修改：在现有turn/run中持久化TurnCommand；attempt引用command，保持模式/来源/任务绑定，最新业务状态单独读取。

主要入口：`app/api/product_routes.py`、`app/conversations.py`、`app/runtime/turn_coordinator.py`、`app/runtime/workbench_runs.py`。

完成条件：Deep重试仍Deep；新attempt不复制用户回合、不重放副作用。对应场景：Q04,Q05。

### T03 · 知识库可补绑定且运行按会话归属

阶段：S0；前置：T02。

问题：F02空绑定不可恢复；F05全局run串会话。

修改：增加明确资料范围选择/补全入口；所有进度按cid/turn；导航只停订阅；单模型排队也有正确归属。

主要入口：`app/conversations.py`、`app/api/product_routes.py`、`frontend/src/features/Assistant.tsx`、`frontend/src/app/App.tsx`、`frontend/src/api/useRun.ts`。

完成条件：空会话可恢复；A、B互不错误停用或展示；假选库消失。对应场景：Q06,Q07,Q08。

### T04 · 复合请求完整交付，不在预览处短路

阶段：S0；前置：T02。

问题：F06工具批次中prepare_preview提前结束。

修改：正确执行未完成的相关读取、积累结果；参数变更先失效依赖结果；必要用户等待时交付已完成部分；不加judge。

主要入口：`app/agent_runtime/workbench_agent.py`、`app/agent_runtime/workbench_tools.py`、`app/runtime/turn_coordinator.py`、`app/workbench_service.py`。

完成条件：预览与政策两种顺序都交付；后续改期不沿用旧预览；只预览不多调用。对应场景：Q09,Q10,Q11。

### T05 · 已有工作区丢失时定位而不是重建

阶段：S0；前置：T01。

问题：F03旧路径误初始化空库。

修改：显式open/create/locate选择，已登记目录缺失不自动mkdir或initialize；保留实例复用和锁。

主要入口：`app/launcher/core.py`、`packaging/windows/Launcher.cs`。

完成条件：移动目录后不会生成空库；定位后原会话和申请可见。对应场景：Q02,Q03。

### T06 · 历史分页搜索并发布0.6.1候选

阶段：S0；前置：T03, T04, T05。

问题：F04历史固定100条且本地筛选。

修改：稳定游标分页与服务器搜索；UI更多/空结果；保留直接链接与草稿；合并F01—F06修复结果。

主要入口：`app/conversations.py`、`app/api`、`frontend/src/app/App.tsx`、`frontend/src/api/client.ts`。

完成条件：150条历史可查找最早一条；0.6.1关键回归和未满足发行条件明确。对应场景：Q12,Q13。

### T07 · 交互和类型收敛，继续当前React界面

阶段：S1；前置：T06。

问题：显示和服务器事实脱节；通用字典遮蔽字段。

修改：生成类型覆盖主请求/响应；单输入框，准确模式/范围/run状态、可行动错误，历史事项只读关联；标题/归档。

主要入口：`frontend/src/features`、`frontend/src/components`、`frontend/src/api`、`app/domain/product_views.py`。

完成条件：不改页面框架且能清楚操作；无假选择、无错误run按钮。对应场景：Q06,Q08,Q13。

### T08 · 干净Windows构建与原生使用收尾

阶段：S1；前置：T05。

问题：构建依赖作者venv/已手动准备runtime；原生步骤未完成。

修改：单命令准备锁定运行时和静态前端，沿用薄启动器；首次开页、已有/新建/丢失目录与IME明确；不运行时安装。

主要入口：`scripts/build_windows_portable.py`、`packaging/windows`、`pyproject.toml`、`uv.lock`、`frontend/package.json`。

完成条件：最终portable在无Python/Node环境可开，真实GUI记录；离线模型仍能用设置历史。对应场景：Q01,Q02,Q03,Q23,Q24。

### T09 · 资料更新期间保持已发布知识可用

阶段：S1；前置：T07。

问题：索引/文档更新关系可能使库整个不可用，需实际验证。

修改：区分活动发布索引与待处理变更；原子切换；主动停用文档新查询立即排除；失败可继续旧版并按文档重试。

主要入口：`app/knowledge/catalog.py`、`app/knowledge/jobs.py`、`app/knowledge/query.py`、`app/indexing`、`frontend/src/features/Library.tsx`。

完成条件：边查询边更新、停用、失败、重启均明确；不谎报任务已停。对应场景：Q14,Q15。

### T10 · 统一证据支持的解释与比较答案

阶段：S2；前置：T06。

问题：只选完整原句限制直接解释和比较。

修改：扩展现有AnswerResponse的答案块/claims与稀疏引用；同一核心一次生成；原文模式和历史渲染兼容；条件与未知明确。

主要入口：`app/agent/generation_v2.py`、`app/domain/evidence.py`、`app/agent/answer_publication.py`、`app/knowledge/query.py`、`frontend/src/components/AnswerView.tsx`。

完成条件：不是拼全文，也不是无引用自由回答；普通结论、假设、比较和缺项能表达。对应场景：Q16,Q17,Q18,Q19,Q20。

### T11 · 上下文与输出预算按真实信息价值组织

阶段：S2；前置：T10, T04。

问题：长首问空选择、schema占用、过多重复历史。

修改：稀疏需要的引用；保留实际问题与约束，裁剪无关旧工具输出；记录token估算；避免默认新增LLM调用。

主要入口：`app/runtime/context_window.py`、`app/agent/generation_v2.py`、`app/agent_runtime/workbench_context.py`、`app/runtime/workbench_models.py`。

完成条件：长首问和历史追问都保留真正问题；关键工具结果和来源不丢。对应场景：Q17,Q18,Q20。

### T12 · 建立小而完整的真实语义质量集

阶段：S2；前置：T10, T11。

问题：现有关键词检查不能证明解释推理正确。

修改：24例6类×4，12开发/12冻结留出；标语义事实、条件、禁止推论、来源；真实模型对照且记录全部失败。

主要入口：`tests/product/live_quality_060.py`、`tests/knowledge_quality`、`docs/esa-vnext/quality`。

完成条件：不能把关键词全出现当完整回答；真实配置结果按类别报告。对应场景：Q16,Q17,Q18,Q19,Q20。

### T13 · 将责任重叠和legacy从产品链收敛

阶段：S2；前置：T07, T09, T10。

问题：拆文件后仍可能重复写状态、猜格式或加载legacy。

修改：API类型边界、单coordinator终态、一次domain事务；沿实际职责提取，隔离历史协议；正常格式化。

主要入口：`app/bootstrap.py`、`app/workbench_service.py`、`app/service_desk/store.py`、`app/agent/generation_v2.py`、`app/api`、`frontend/src/api`。

完成条件：修改一个能力有唯一主入口；业务完整周期和旧历史不回退。对应场景：Q05,Q10,Q21,Q22。

### T14 · 测试入口与依赖按能力分组

阶段：S3；前置：T02, T04。

问题：全局conftest依赖FAISS阻塞无关测试；复现≠验收。

修改：在支持Python中正常收集；领域/产品/检索分组；原缺陷探针转正确行为检查；保留真实事务。

主要入口：`tests/conftest.py`、`tests/product`、`tests/vnext`、`pyproject.toml`。

完成条件：相关组独立可跑，检索组真实FAISS；无删断言/伪模块。对应场景：Q04,Q05,Q06,Q09,Q12。

### T15 · 标准浏览器回归与CI工作流

阶段：S3；前置：T07, T14。

问题：脚本硬编码个人路径/运行服务，无常规浏览器入口。

修改：Playwright webServer+临时工作区+明确模型适配；query key/导航/停止/草稿/错误；已有授权下接CI，不操作活动库。

主要入口：`frontend/package.json`、`frontend/playwright.config.ts`、`tests/product/browser_navigation.cjs`、`.github/workflows`。

完成条件：干净checkout执行端到端；归属正确、移动端、输入法事件和页面错误有记录。对应场景：Q07,Q08,Q13,Q24。

### T16 · 发行升级与真实原生边界完成

阶段：S3；前置：T08, T09, T15。

问题：只有结构检查或CLI不能代表GUI发行完成。

修改：同一候选包在干净Windows首次打开/中文路径/原数据升级/移动定位/离线；补物理IME；记录性能冷暖差异。

主要入口：`scripts/build_windows_portable.py`、`app/launcher`、`app/persistence`、`packaging/windows`。

完成条件：同一数据可反复使用，不靠新库回避问题；外部阻塞明确未完成。对应场景：Q01,Q02,Q03,Q14,Q15,Q23,Q24。

### T17 · 同一候选整体使用与性能复核

阶段：S3；前置：T12, T13, T16。

问题：历史不同快照不能拼成当前全绿。

修改：冻结当前commit；领域+浏览器+真实模型+发行分别归档；同一工作区走借用/报修/知识/失败恢复；定位实际慢段。

主要入口：`tests/product`、`tests/vnext`、`docs/esa-vnext/RELEASE.md`。

完成条件：24场景实际状态清楚，真实模型负例不隐藏，性能无无依据承诺。对应场景：Q01-Q24。

### T18 · 0.7交付、文档与授权同步

阶段：S3；前置：T17。

问题：本地commit不等于GitHub已同步。

修改：当前入口与数据位置明确；feature分阶段commit；授权才push/PR；记录真实未完成；最终ZIP自查内容。

主要入口：`README.md`、`docs/esa-vnext/STATUS.md`、`docs/esa-vnext/RELEASE.md`、`Git feature branch`。

完成条件：可运行程序、源码、说明、对应结果一致；不force push或擅自合并。对应场景：Q23。

## 交付要求

一份活动STATUS、分阶段可运行commit、一份最终能力结果。源码、内置前端、Windows目录与证据明确对应同一候选；不再自动生成多套命名近似的FINAL包。用户最终拿到程序、使用/升级说明和真实未完成范围。Git同步依授权执行，未推送明确写未推送。

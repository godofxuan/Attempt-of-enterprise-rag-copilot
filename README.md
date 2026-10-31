# Enterprise RAG / Service Agent

本地单用户知识与服务工作台：一个 Python / FastAPI 应用、一处数据目录。
独立 RAG 与 Service Agent 共用检索、模型和来源发布能力。用户明确服务与操作上限，模型根据真实工具观察选择下一步；普通代码负责字段校验、当前预览、精确确认和事务。

当前为 **0.7.0rc4预发布**，应用冻结`78f7464e`：知识恢复不要求填写无关业务日期；事项支持服务器分页搜索；过期预览明确重新生成，提交事务仍最终校验。[使用/升级](docs/esa-vnext/START.md)、[有限验收与真实模型结果](docs/esa-vnext/RESULT_RC4.md)对应当前运行版本。全仓历史CI与关闭中的解释实验仍有未收口项，不是正式稳定发行。[rc3结果](docs/esa-vnext/FINISH_RC3.md)作为历史保留。

## Windows 日常使用

完整解压 Windows x64 发行包，双击 `ESA.exe`。包内已有 Python 和固定版本依赖；日常启动不安装软件，不需要 Node、uv 或系统 Python。

首次选择已有工作区或新建个人工作区。升级时继续选择原目录，不重新 `init`。再次打开同一构建会复用实例；新旧构建不同会明确选择打开旧版或在空闲时正常切换，不静默当作新版；端口被其他程序占用时自动选择空闲端口，并打开实际页面。关闭网页不删除数据，设置中可停止本地服务。

已登记目录移动后会要求定位原目录或明确新建，不能在旧位置自动生成空库。已有工作区应包含 `workspace.json`、`app.sqlite3` 以及原 `documents/`、`indexes/`；需要重选时运行 `ESA.exe --choose-workspace`。

模型权重不在包内。当前使用本机 Ollama 中已有的 `qwen3.5:9b` 和 `bge-m3`；没有模型也能进入设置、查看历史。应用不会自动下载模型。首次配置完成后进入助理；业务演示需在设置中明确启用合成 TEST 数据。

主入口为**助理、我的事项、资料库**。设置和本地 TEST 服务台为次级工具。一个会话输入框处理提问和补充信息，完整参数、来源、预览及回执在详情中查看。

## 从源码开发

需要 Python 3.11/3.12、uv，以及本机已运行的 Ollama 和已安装模型。当前验证使用 `qwen3.5:9b`、`bge-m3`，不自动下载或更换模型。

```powershell
uv sync --locked --no-dev
uv run --no-sync esa init --sample --data-dir .private/esa-vnext
uv run --no-sync esa open --data-dir .private/esa-vnext --port 8740
uv run --no-sync esa doctor --data-dir .private/esa-vnext
```

`open` 会报告并打开实际地址，默认优先 http://127.0.0.1:8740/ 。已有环境可用 `python -m app.cli` 替代 `esa`，终端前台调试用 `esa serve`。首次 `init --sample` 显式创建本地合成 TEST 数据；已有目录不要再次初始化。默认目录按明确参数、`ESA_DATA_DIR`、启动器工作区注册记录选择。

修改 React 前端时需要构建环境的 Node：`cd frontend`，执行 `npm ci` 和 `npm run build`。静态产物进入 `app/web_dist`，由同一个 FastAPI 提供，没有常驻 Node 服务。Windows 打包见 `packaging/windows/README.md`。

## 日常使用

1. 设置里选择已安装的聊天/嵌入模型，确认连接。
2. 资料库创建集合，批量上传 MD/TXT/PDF/DOCX 或导入合成规则示例；页面按真实处理任务显示索引进度和错误，无需猜测额外步骤。
3. 知识入口选 Fast 普通问答或 Deep 分题搜索和锚定阅读；引用可查看原版本和真实页/段。旧索引没有的新定位不会伪装成原页码。
4. 会话里提问、解释、补充字段或混合改期。开始服务事项时明确只读、仅预览或确认后提交。
5. 保存参数即更新服务端revision和界面基线；需要设备时自动展示候选，缺字段时补字段。选择真实设备或点击“生成当前预览”直接调用公共业务用例，不额外请求模型选择动作。核对当前参数及预览；改期使旧确认失效。提交先生成待审批借用或待受理报修。
6. 本地服务台中核对处理预览并确认：借用批准并预留 → 领用 → 归还；报修处理 → 解决 → 关闭。可撤回待审批申请或为已领用借用预览续借。
7. 回到原会话看当前业务状态。原始提交回执不变；归还或关闭后可在同一目录再次办理，不必重建数据库。

借用同时检查维修资格、静态启用、规格和实际日期预留。日期含结束日，SQLite内部为 `[start,end+1day)`；只有用户允许日期灵活才产生改期候选，仍须用户选择。预览不预留，批准时事务内再次检查冲突。
IT报修工单与借用资格的 `repairs` 记录是不同来源，不自动联动。服务台仅为本机当前身份的合成TEST处理视角，没有企业审批角色系统。

模型使用 Ollama 原生工具调用；页面展示工具名和实际观察，不展示伪造的思考过程。停用或更新资料后自动排入索引队列；尚未发布时会提示资料变化，原答案与原版本保留。无文本 PDF 不具备 OCR。

0.7 候选按会话恢复运行，重试保留原问题、Deep 和原事项绑定。后续已修改的业务参数优先，旧回合不能重新覆盖；混合请求的预览和知识分别记录交付，部分失败可以只重试解释，已有预览保留，参数变化后只重建当前预览；空绑定会话可明确补选资料库并重试。历史搜索和“更多会话”请求服务器，可重命名、归档或恢复，不限于最近100条。

知识默认交付已验证来源单元与必要条件。0.7的解释、假设推导和比较实验未过真实质量门槛，默认关闭；仅在明确修改工作区配置 `experimental_grounded_expression: true` 后使用，不作为稳定能力。其引用绑定和有限一致性检查不能证明语义正确。新增资料或替换处理中继续使用已发布代次，页面明确更新状态；主动停用立即从新查询排除。原文与旧答案保持原版本。

## 产品回归与构建

```powershell
uv sync --locked --extra dev
uv run --no-sync python -m pytest tests/product tests/vnext tests/agent_v2/test_a1_draft_delivery.py -m "not experimental" -q
uv run --no-sync python -m pytest tests/product/test_grounded_expression.py -m experimental -q
cd frontend
npm ci
npm run build
npm run test:ui
cd ..
uv run --no-sync python scripts/build_windows_portable.py
```

浏览器回归自启临时工作区，外部模型使用明确测试替身，不连接活动库，不代表真实模型通过。默认Windows用已有Edge，其他平台需准备Playwright Chromium；`ESA_TEST_PYTHON`、`ESA_BROWSER_CHANNEL`、`ESA_UI_TEST_PORT`可覆盖测试环境。PR自动运行产品回归；解释实验独立显示，保留已知红例，不用 skip/xfail 隐藏。远端未执行不得记为CI通过。实验命令预期仍有已知失败，不能用其代替默认产品质量判断。

Windows构建需要开发期Node/npm、uv与系统C#编译器，可用`--uv`/`--npm`指定工具；默认按锁准备官方嵌入式Python和依赖并构建同commit前端。`--embed-zip`可复用官方ZIP，`--offline`要求全部构建缓存已存在。日常用户运行包不执行上述安装步骤。具体已实测版本与未完成项以[STATUS](docs/esa-vnext/STATUS.md)为准。

## 数据与恢复

`workspace.json` 保存配置；`app.sqlite3` 保存会话、工单、确认、幂等命令、模型调用和进展；`documents/`、`indexes/`、`cache/` 保存原文、索引和计算缓存。备份需包含整个 DATA_DIR。不要提交数据库、原始调用、私有资料、模型或大索引到 Git。

同一目录只开一个实例。停止本次运行不会撤回已经提交的工单；刷新/重启读取保存状态，不自动重发提交。跨页面并发编辑仅支持现有 revision 冲突检查，不能冒充企业多用户系统。

## 状态与限制

当前功能、演示和限制见 [RELEASE](docs/esa-vnext/RELEASE.md)。
当前升级的逐阶段运行和失败见 [STATUS](docs/esa-vnext/STATUS.md)，启动/错误处理见 [START](docs/esa-vnext/START.md)。源码功能、程序测试和真实模型结果分别登记，不用 COMPLETED 代替内容和数据库验收。
自由文本 auto 为历史实验路径。尚未证明追平 main；Docker/Streamlit 不是当前默认工作台启动方式，Linux/容器化本轮未验证。

[原 README 与用户既有修改](docs/history/README_PRE_030.md)保留为历史说明，不能作为当前入口指引。实际实现问题及面试口述线索见 [实施记录](docs/esa-vnext/IMPLEMENTATION_INTERVIEW_NOTES.md)。

# ESA vNext Current Status

## 当前实施：0.6.1 → 0.7（T01—T18，2026-10-31）

- 51a1988f已实际构建并在原库运行；当前相关114项通过。干净准备官方嵌入式runtime+锁定43依赖+同commit React构建成功（没有依赖原手动runtime）。Windows包无系统Python/uv/Node、中文路径、端口冲突/复用、模型离线和历史保留通过；3次启动6.593/4.578/4.796秒，不能宣称比旧0.6更快。
- 首轮0.7开发语义对照负结果保留SEMANTIC_51a1988f_DEV.json（21chat）；解释引用和unit_uses双重填表造成一个Deep结构失败，来源ID混入正文引起有限数值误拦。第二种共同方案已离线通过：answer_blocks一次绑定同时驱动claims/coverage，宿主只剥离已绑定来源标记；条件推导显式引用用户前提，并标为尚未查询个人事实。没有放松原精确来源验证或扩大上下文。
- 补齐Q05：重试的原事实revision与当前不同，则禁止旧输入再次调用update_parameters；仍可对最新事实执行读取/准备。旧输入、绑定及原确认保留。相关产品/安全回归进行中。
- 本次原生交互可见首选对话框，但点选/快捷键后目录窗口无法被桌面工具定位；出现coordinate input geometry unavailable/foreground window did not report a process id。已停止本轮自有GUI进程，未修改系统安全/输入法设置。首次选目录完整链、自动浏览器和真实物理IME尚未验证，继续其它可执行工作，不冒充通过。
- 下一动作：固定第二方案候选，完整一次开发对照与冻结留出；同候选浏览器、真实业务/混合与发行升级检查，最后交付。未使用历史余额或清零账本，未push/PR。

- S0本地提交6006cd06；S1已通过标准隔离浏览器4旅程，临时真实API/SQLite、明确外部模型替身，未碰活动业务数据。首次脚本误用路径路由，当前实际HashRouter，改用/#/assistant后通过；不是产品深链缺陷。原浏览器失败记录保留。
- T09真实FAISS/SQLite/作业相邻13项通过，已发布旧代次在更新失败时可继续，主动停用按source_key立即排除，元信息变更排除该来源直到重新发布，重新打开保持代次；旧契约两断言迁移有精确替代不变式记录。
- T10/T11候选扩展同一个AnswerResponse：稀疏unit_uses与有原文绑定的answer_blocks，仍经原唯一publisher/精确来源检查，正文保留所选依据与必要条件；解释的来源关联/有限一致性不声称独立语义证明。原文及legacy显式路径保留，不增加judge。针对性21项通过。
- 真实基线12开发例已在冻结1f9d2662的嵌入式runtime+原活动TEST库执行，起点266chat/130embed，基线结束288chat；原件SEMANTIC_BASELINE_DEV.json。24例/12开发12留出及未改写合成原文已固定；没有用COMPLETED评分，逐例内容待核对。
- 基线定位新增共同原因：knowledge Agent可改写本来已绑定的知识问题，并把未问的延期/提前归还带入Deep；Deep又将检索子题升级成额外用户义务。候选改为知识工具只选择执行，原问由宿主绑定；子题只用于检索，不增加完成义务。仅业务混合工具仍允许明确子查询。无新增LLM评审。
- 旧0.6当前在8740作为有限基线；下一动作：候选相关回归、提交0.7rc1，干净构建并切换原工作区，进行开发语义对照、冻结留出与最终Windows/浏览器。尚无0.7质量通过或远端同步结论。

- 本轮按用户新授权继续升级，父本应用1f9d2662/文档75ee211d；分支codex/esa-061-070。保留7个无关tracked修改、全部其他未提交成果和活动DATA_DIR `.private/esa-vnext`。旧交付和下方延期记录不改写。
- T01：实际8740未监听。用当前source的`python -m app.cli open --data-dir .private/esa-vnext --no-browser`启动原库成功，instance8142d51ddd0e47b79b18f6ee001b6e87/PID40884；未重建资料或账本。
- 方案原文已存reviews/060-20261030。原审核脚本实际复现Deep重试true→false；Windows临时SQLite未释放导致原脚本退出清理错误保留，未当作成功。
- T02/T04/T05/T06首批程序RED/GREEN保存在.private/esa-vnext/upgrade-061-070：原失败与夹具问题均保留。7项新产品测试通过（真实工厂/SQLite/业务工具，外部模型明确替身）：不可变原请求+append-only显式补绑定版本、原任务重试不改绑/回滚、丢失目录拒绝初始化、150历史分页搜索、两种预览/知识批次顺序完整执行。
- S0相邻64项通过（S0-final.xml）；额外混合改期/部分失败/真实子进程launcher组10项通过（重叠不相加）。前端已按服务器owner恢复运行，补库/服务器分页搜索及归档重命名已接API；生成DTO/TS/Vite构建通过。原生选择器增加丢失目录定位/明确新建，C#实际编译通过，尚未桌面GUI验收。
- 0.6.1代码里程碑准备提交，尚未运行本轮真模型或浏览器；不是0.7完成。下一动作：标准隔离浏览器入口、资料更新可用性、干净Windows构建，然后有依据的解释/比较协议与语义集。

## 当前交付：0.6 可运行预览（部分门槛待验，Goal未完成）

- 2026-10-31 用户明确选择“先交付，桌面检查待验”。按当前0.6预览版交付，不再主动弹出桌面检查、不新增模型运行。原生首选目录/自动开页与真实中文输入法继续待验，未转为通过；冻结ZIP和历史证据不改。交付决定旁录于.private/esa-vnext/deliveries/DESKTOP_ACCEPTANCE_DEFERRED_20261031.json。

- 当前应用1f9d26626f27a03dfd76683fc551c24aa78227a0，原DATA_DIR不变，入口http://127.0.0.1:8740/，PID44948/instance eec3e1c32d2f4532851ddf72ec8c0f81。Windows ZIP约78.8MB，解压双击ESA.exe；源码及完整证据另有小审核包。
- 后端模型冻结7d4bfa28，最终1f9仅改变已提交事项的表现层：原参数/预览移入历史回执，不改变模型、API行为或事务。git diff已核对Python后端/依赖完全相同。实际104项产品/相邻回归通过，不是模型准确率。
- 真实QUALITY_060_20261030T174136Z七组核心PASS（借用/会议室双入口、Deep、真实无依据、只读）；LIVE_PROGRESS_20261030T174053Z在用户第二轮选择实际第二台后生成正确PREVIEW_ONLY，未请求参数不变、实际提交被拒；正常长历史追问PASS。
- 完整UI沿同一loan7869ccbe与repairdc424500继续，没有重建库：改期、旧确认409、当前确认、唯一PENDING_APPROVAL/幂等、批准/领用/续借/归还；报修OPEN到关闭/重开/再关闭。原始消息以及用户明确选择/继续均有记录，不预填工具动作。最终链LIVE_050_2026-10-30T17-47-48-585Z引用17-42/17-45两次真实进展/测试失败，不能说一次从头全绿。
- 最终1f9真实浏览器UI_NAVIGATION/FINAL_BROWSER_READBACK：单composer、草稿/导航/取消解绑、390px、真实工具来源、当前11-28与提交11-27分开展示、来源/XSS长文通过；最后源码读取断言曾早于网络内容到达，已改为等待实际文本，失败保留，0模型发送。
- Windows最终包5次独立启动中位3.609s/最慢4.984s，复用1.016s，PATH无系统Python/uv/Node、中文目录、端口冲突和模型离线通过；旧完整0.4副本60会话/104turn/3借用/2报修/17资料保留、首次迁移1次后二次0次，原文/索引可用；实际最终嵌入式runtime再次打开通过。
- 门槛未全过：原生首次目录选择/自动开页两次被物理Esc停止，手动中文输入法未验；冗长首问全漏选、假设条件追问过度保守仍失败。两次原始请求单变量诊断无收益，改动已回退，不再刷同输入。见VALIDATION_060逐W项状态，不能写全面PASS或正式成熟发布。尚未证明追平main。
- 主账本149chat/97embed起点，现266/130；新增117chat尝试/33embedding POST，索引embedding0。1条中断SENDING响应未知仍保留计数；旧原始行需交付脚本逐ID核对。复制的测试数据库历史不再次算消耗。没有运行中run或PENDING turn。
- 原7个无关tracked及其他未提交工作保留。仅本地codex/esa-050-060里程碑，无push/PR/merge。自己的旧测试服务已停；冷构建目录清理被自动审批以blocked by policy拒绝，未绕过或执行。
- 独立源码目录实际加载包内app，104项相关回归通过（CLEAN_SOURCE_FINAL_954626a2.xml），无外层原件/个人路径依赖。旧149chat/97embed的原始调用行未改变，新调用116响应OK/1中断响应未知，query33文本/index0。
- 交付：.private/esa-vnext/deliveries/ESA_060_REVIEW_20261030T175911Z.zip（约9MB，小审核包，完整源码/diff/原件/TEST域状态）；Windows实际包build/releases/ESA-0.6.0-windows-x64-1f9d2662.zip（约79MB）。清单和最终摘要以LATEST_REVIEW/BUILD_1f9d2662.json为准。
- 下一具体动作：仅待不被打断的Windows首次选目录/自动浏览器、手动IME检查，保留当前语义限制。已一次询问桌面是否方便，不再主动弹窗。不重跑同一模型题集或增加功能。

## 当前实施：0.5 / 0.6 产品化（W01–W32）

- 最终7fae回归97通过/1失败：跨午夜暴露导入默认准入日采用本地日期、检索用UTC日，资料被误判未来生效。已用UTC默认准入日修正，用户声明日期不变；原RED与GREEN保留，真实Word/PDF来源定位相邻5项通过。不是改变业务日历。
- W04/W12补齐现有run事件的只读产品投影与执行记录折叠区：分开模型提出调用、实际工具结果、程序检索计划；不显示模型thinking，不增加模型调用或改变业务工具。实际工厂API与时钟测试2项通过，前端类型/构建通过；待冻结包的最终同版本检查。
- 普通操作已合并为固定范围的批量验证脚本，减少拆分审批。当前8740仍3d2e8655包/instance ee5cb6b30c494b2aa1df6a7fea2f26c2；不能将未切换的服务写成最新源码。下一动作：冻结这两个局部修正，构建并完成最终同版本程序、Windows、混合/指代/追问及业务UI旅程，然后交付。

- 3d2e8655最终相关94passed，独立Windows包启动4.954s/复用1.047s通过。实时长问新一轮仍FAIL（模型全漏选）；Agent同题因旧600字限制422、0发送，追问未运行。原件QUALITY_060_20261030T144939Z保留，不能写长输入全部修好。
- 现已确定性修正引导式知识600与其他入口2000不一致：共用MAX_USER_QUESTION_CHARS=2000，不改8192上下文/1024生成输出；当前知识原问只出现在原生role=user，不再系统重复。实测程序边界已检查完整输入包。
- 候选绑定原实现已存在，修复实际接线：TaskDetail使用product alternatives；资产工具更新同一已展示列表，但原领域资产观察JSON保持不变。资源选择返回紧凑的实际业务字段，避免把整任务审计送回模型；参数更新原本已紧凑，排除假设，不冒充新修复。新相关程序检查通过，待冻结该候选的混合/指代/追问真模型。
- 浏览器最终回执探针曾在dialog可见但数据未到时过早断言，已改为等待实际日期内容，不靠sleep。其失败不是业务日期被改写；原失败记录保留。测试临时CURRENT命名有覆盖局限，后续命名改时间戳/commit；最终原始模型记录和主账本不受影响。

- 0.6首候选e8082fca实际包已完成最终整条真实UI借用/报修旅程（LIVE_050_2026-10-30T12-32-24-468Z，15chat），同一包知识质量7PASS/1FAIL（QUALITY_060_20261030T123044Z，12chat）：loan/room两入口、Deep、真实不足、只读交付通过；长原问内容正确但因未引用候选裁减被整体误降partial，后续长历史追问NOT_RUN，不能把此批写全绿。
- 同包Windows独立解压/无系统Python、uv、Node的五次启动：中位3.844s/最慢5.5s/重复复用1.078s；中文路径、独占端口仍保留、模型离线、原会话重启均通过。native首选目录/自动浏览器仍未人工GUI验证，不用EXE命令启动冒充。探针init的-I忽略PYTHONUTF8导致输出解码警告，已明确加-X utf8，运行结果本身有DB/HTTP核对。
- 长问已用原始模型输出+原向量+真实索引离线重放（LONG_PACKET_RED/GREEN）：不新增发送，旧partial→新answered；所引用来源完整，裁减发生在未引用候选。最新补丁只收紧裁减归属：实际引用截断、必要open截断、缺aspect和未解决need仍拦截；旧协议行为保留。当前源码较e808仅generation_v2/answer_publication新增该内部归属，需新包及受影响真实复验，旧结果不可冒充新完整验收。
- 原AUTH/账本不改，当前主库201chat；长期Goal仍ACTIVE。下一动作：定向发布器正反例通过→冻结该修补commit→构建对应0.6包→只做受影响长问/追问与新包冒烟/现有回执读回，必要相关质量样例；最后整理唯一发行及准确剩余事项，不能停在checkpoint。

- 0.5实际业务闭环已成立，跨小候选恢复不冒充一次全绿：原loan d3174ec4恢复→改期→旧确认409→当前确认→幂等读回→RESERVED/CHECKED_OUT/续借/RETURNED；原repair 565401ec真实9B提取/prepare→OPEN→IN_PROGRESS/RESOLVED/CLOSED→重开→再CLOSED。最终恢复记录LIVE_050_2026-10-30T12-09-11-778Z（该最后一步0新增chat）；完整链保留对12-02/12-06原件的指针。
- 主库当前174chat，不能将run成功等同内容正确。cf4d3043独立知识资格/期限/日期实际通过，原Agent负结果未改。真实错误的共同修复：无tool_calls的prose不能隐式finish；真实prepare成功是同一产品两入口的交付终点；异步新建只做一次包含conversation/task的完整导航；历史Task.knowledge规则表不能按PublishedAnswer解码；HTTP retry必须在async路由中启动run。
- 浏览器CURRENT_UI_NAVIGATION.json：真实React/API新建→URL与active_task一致→页面往返草稿保留→一个composer→结束事项解绑→390px无溢出，0chat；composition为合成事件，不冒充手动IME。新服务台显示实际工单编号，避免同描述无法分辨。
- 完整旧库及documents/indexes/cache副本升级已验证，60会话/104turn/3loan/2repair/17资料保持；二次启动数目一致，复制索引实际chunk来源定位与原件相同。首次探针误把DocumentRecord当chunk读取定位的失败保留，不作为产品bug或PASS。
- 当前开发服务8740为本轮自有PID20272、instance73c1f1097643404286710e33cf4bd4ee，DATA_DIR未变；最新未提交HTTP retry及新UI静态产物已经接入。原生GUI窗口检查的应用授权等待超时，首次选择/自动开浏览器GUI未记PASS；portable EXE/路径/端口/重复启动已实测。阶段结束不终止Goal，继续W20/W27及最终统一版本/产物。

- 新候选定向产品回归68passed；A1/发布器/真实launcher相邻27passed/1failed，唯一失败是旧测试要求分句need数2、实际保留完整原问need数1。独立进程只加载5ff9aac2原生成模块也复现相同失败（BASELINE_NEED_COUNT.xml）；断言未改，未隐瞒。
- 当前producer只接受unit_uses/need_status；兼容协议仍显式legacy。知识/配置重模块按操作惰性加载；模型工具观察有单一ToolResult，历史按完整call/result组保留，当前原输入、权限、事实不从中截断。新UI构建和OpenAPI类型生成通过。
- 原件读取优先当前DATA_DIR/documents中的不可变版本，不回退读取旧个人绝对路径；目录/样例/解析重试自动进入原持久job队列。启动恢复只查询当前产品可能中断的任务。首次配置提示可明确完成，旧会话工作区不重复显示新安装流程。

- 当前0.5一键候选e6792303已实际构建：内置官方CPython3.12.10、43锁定依赖、React静态构建与ESA.exe，ZIP约78.8MB。独立中文解压、PATH只有System32、端口冲突、重复启动复用、模型离线均通过（PORTABLE_WINDOWS.json，首次6.672s/复用1.688s）。尚未称完整发布门槛通过。
- 当前8740已由该冻结便携候选运行，原DATA_DIR不变，旧0.4自己启动的进程已正常结束；实例PID7108。隔离8750源码服务PID35928待后续清理，均为本轮自有进程。
- 真实0.5质量负结果：LIVE_050_09-05原始问答收齐来源却所有unit选择为空；09-09同会话新借用task d3174ec4ad9f4d76b1d8e7f966ebee8d收到完整用户日期/用途/内存仍追问可选字段，facts为空。不得把run succeeded写成正确，原失败保留，业务尚未提交。
- 两类机制分别定位：unit贡献被当成整问完整；stored missing_fields被当成当前输入缺项。生成提示明确“先收集单元贡献、再合并判断整问”，一次固定原检索包真实诊断已保留维修资格和日期/14天，非E2E。仅限制澄清字段的第一次原生诊断仍追问已给必填，记无收益；现在进一步让当前输入先通过typed patch/prepare消费，再允许澄清，空patch不改事实/确认。
- 源码继续0.5稳定化/0.6边界收敛：workspace.py改为兼容转发，bootstrap/API DTO与routes/persistence配置分开；发现app.api包初始化意外导入legacy资源，已改惰性兼容导出。原Store的15个旧语义review操作原样移入legacy_store，按需加载；当前事务与规则未重写。产品投影移到service_desk/views与domain/product_views。
- 最新仅诊断的实际chat也通过既有ModelService追加主库，无清账。最终新调用需按START.json及原始ID差集统计；不能把隔离副本复制的历史149/97再计一次。
- 下一具体动作：定向复验新工具消费契约与边界；冻结新候选并重建便携包，复测这两条最早失败并沿同一loan task继续UI办理/归还及报修；再完成质量清单、代码清理和最终同版本发行。不要停在此次checkpoint。

- 唯一源码父本5ff9aac2，当前分支codex/esa-050-060；原7个无关tracked修改和所有untracked工作保留。
- 当前真实8740入口已实际检查：页面/health返回200，9B/BGE已安装可连接，主库149chat/97embed。不是启动失败；本轮首先复现状态与会话问题。
- 计划只读归档reviews/040-product；旧0.4成果及以下历史记录保留。活动DATA_DIR仍.private/esa-vnext，数据库预升级副本upgrade-050-060/before-050.sqlite3。
- W01已实跑8740；W02/W03：4项RED真实复现后，共同TurnCoordinator、原消息多attempt重试、已结束事项解绑和当前工厂相邻19项通过（P0_FINAL.xml）。原脚本清理仅加gc的复现记录也保存；不将DEFECT_REPRODUCED当新版通过。
- W04/W11–W16候选：OpenAPI生成TS类型、React三入口/一个composer、事项/来源drawer、资料库和服务台真实API接入已构建。W05私有CPython3.12.10+锁定43依赖独立导入SQLite/FAISS/FastAPI通过，无Rust工具链，选择同契约portable runtime与Windows轻量launcher，未复制作者venv。
- Launcher源码真实子进程检查已通过：中文路径、端口被占自动避让、第二次open复用同一实例、模型离线页面/设置/历史可用，0推理。无Rust/cargo，已用系统.NET编译轻量ESA.exe；尚待portable最终产物检查。
- React真实API/历史副本已实跑：三入口、事项drawer开关、导航返回草稿仍在、单个可见composer、390px无溢出，0推理；22事项及60会话全部可由新版API读取。截图REACT_DESKTOP/MOBILE，非静态原型。
- 下一步：构建含私有3.12运行时和React的便携候选，实际EXE启动/升级，再补确定性完整业务与真实模型关键旅程；当前不是0.5完成。



## 当前冻结交付：0.4.0（2026-10-30）

> 页面后续修正（用户截图反馈）：当前工作区在36dae403交付后新增仅表现层的会话历史整理。原60条记录保留；最近6条、时间排序、两行标题、搜索/更多、选中标记和窄屏折叠已在真实页面验证，列表从6406px降为最高480px。模型调用仍149，没有业务写入。原结果ZIP不覆盖，此UI提交尚未进入原ZIP；恢复最新页面应使用当前feature工作区。原模型/业务冻结链未改，浏览器记录在`.private/esa-vnext/ui-history-fix/`。



- U01–U24 / S0–S4本地范围完成；旧DONE_R1_R2_LOCAL_DEMO及以下过程原文保留。
- 应用冻结：b50d0f8a47d34e29d9706a2c4ef25db193ec0d26，分支codex/esa-030-040。之后仅交付文档变更，不回写7个无关修改或其他未提交工作。
- 当前入口：http://127.0.0.1:8740/；`.venv\Scripts\python.exe -m app.cli serve --data-dir .private/esa-vnext --port 8740`。同一主DATA_DIR，未重建业务库绕过未结限制。
- 用户可在会话内问答/补参/改期/选设备/预览/确认/查询；本地服务台借用预留→领用→归还后同库再次申请，报修处理→解决→关闭。真实9B工具选择与用户明确确认分开。
- 最终相关回归FINAL_B50D0F8A_REGRESSION.xml：115passed，84.44秒；不是全历史套件或质量准确率。
- 当前双入口FINAL_NATIVE_2026-10-30T06-32-24-607Z.json：实际RAG和Agent均从活动v2原文回答72小时，来源UI/窄屏通过，3chat。当前只读FINAL_READ_ONLY_20261030T063403.json：真实2chat，3张借用/2张报修前后不变，无preview/receipt。
- S2_DEEP_20261030T061510.json：两制度时长/条件正文完整、运费证据不足均真实通过。b50只恢复legacy契约，当前workbench输入和新wire均未改；不重复消耗模型复验同一协议。
- 业务真实UI闭环详见RELEASE八旅程表；借用9d254141、报修45751e73、当前PREVIEW_ONLY与状态读回c2ddd882，后续未改事务路径。续借/备选/重开等是程序检查，不冒充完整实时泛化。
- 当前应用源码独立wheel异目录init/doctor/两次HTTP启动和重启保留会话通过：3.063/2.812秒，0推理/0工单，使用既有锁定依赖环境。WHEEL-040-B50D0F8A_PROBE.json。
- 主账本起始40chat/26embed，最终149/97；本轮109chat+71embed POST（query66文本、index12文本）。失败计入，无SENDING、无活动run。其他历史计数不改；归属未知历史仍UNKNOWN。
- 先前Deep与错误不足均有负结果保留，两种无效否定规则回退；后续生成改为一个来源单位选择表示驱动正文与覆盖，不新增judge。最终有限例通过，不证明任意问题正确。
- 完整支持边界/证据适用性见RELEASE.md；实际问题口述记录见IMPLEMENTATION_INTERVIEW_NOTES.md。尚未证明追平 main。Linux/容器/多人企业部署未验证。
- 同步：本地feature里程碑已提交，未push、未PR；未找到适用的新远端授权，不将本地状态写为GitHub已更新。
- 下一动作：使用本轮结果包的源码/wheel和README复现演示；本Goal到此冻结，不再追加功能或新题集。交付提交与包摘要保存在结果包DELIVERY.json。


## 0.3 / 0.4 实施过程记录（按时间追加，早期未完成项已由上方最终状态覆盖）
- Goal ACTIVE: reviews/020-next/GOAL.md, U01-U24, S0-S4. Historical0.2.0 completion below is retained.
- Branch codex/esa-030-040 from8881b000; eight preexisting tracked modifications and unrelated untracked work retained.
- Actual port8740 was not listening. Started the existing CLI successfully with the same .private/esa-vnext data.
- Pre-upgrade SQLite backup: .private/esa-vnext/backups/pre-030-040_8881b000.sqlite3. Existing1loan/1repair ticket retained.
- Product starting counts primary40chat/26embed; historical and other declared data directories unchanged.
- S0 U01-U03: three actual REDs reproduced (asset_id KeyError, NO_WRITE_GOAL, stale active_run_id).
  Service field specs now supply required facts/form/questions. Knowledge messages go to the shared library without pending business facts.
  RunLifecycle releases only its matching task nonce/fence; all terminal events follow cleanup, cancelled messages retain raw text but release pending gate.
  UI now distinguishes stop-current-run from end-task. Related program checks21passed/0failed, S0_FINAL.xml.
- Initial unprivileged Windows asyncio probe hung creating its loopback IPC; same checks in the permitted local environment completed.
  Original audit script partial run remains isolated and is not counted as acceptance. No real model calls for S0.
- S1 U04-U08 candidate: additive conversation/turn storage, history projection, ContextBuilder and ToolCatalog reuse the one loop.
  Typed normalized changes, shared knowledge, resource selection and post-submit reads are exposed by actual task scope.
  UI split into api/events/conversation/tasks/library/renderers/settings modules; same-task timeline and current cards, cursor/terminal handling.
- Related current program batch44passed; user-role targeted8passed after a real canary exposed that the message was embedded as system data.
  First live canary4chat/1query embed: empty repair asks normally and shared policy answers, but supplied fields were not applied (FAIL).
  Original logs:upgrade-030-040/S1_CANARY_20261030T004818.json. No business rows changed; primary44chat/27embed afterward.
  Corrected the shared input boundary: current user message appears once as role=user, not duplicated in context; next live is targeted to that change.
- First browser structure check reached the new conversation but did not open its collapsed service form; harness corrected, not a product success claim.
-598d11c5 real follow-up canary passed: bare repair asks all3fields; one actual user message applies asset/description/high impact and answers loan duration via shared knowledge.
 4chat/1query embedding, business tables unchanged. Record:S1_CANARY_20261030T005431.json; primary48chat/28embed afterward.
 Corrected browser structure passed current modules/API, new conversation+repair binding, reload and390px;0model/0business submissions.
- Next: U09-U13 actual Deep/source/lifecycle work and0.3 release; then continue U14-U24.
  S0/S1 are checkpoints, not completion of0.3/0.4. S3/S4 service lifecycle/scheduling remain unimplemented.
- S2 U09-U12 in progress: DeepPlan selects1-4 actual subquestions; DeepController performs distinct searches and anchored find/open,
  then the existing runner/Guard/publisher. Strategy2checks passed; real Deep request not yet run.
- SourceSpan now propagates original parser locations/offsets through chunk/index/hit/admission/open/publication.
  Library index publisher consumes saved original parses and original-format bytes, not artificial Markdown; formats/types no longer allpolicy/md/2000.
  Default unknown source effective date uses build date only as technical index admission; no claim the policy became effective then.
  Old0.2 index generations stay unchanged; original-page precision applies to new generations, legacy view stays marked as such.
- Document batch upload, retry, rename, disable/restore, original-version comparison and service tags added. Active metadata checked against the published job's recorded metadata.
  Samples derive loan/repair documents from current SQLite rules; room is packaged knowledge-only. Business tools remain reference-only for uploaded policies.
- Related30program checks passed; Word full source path and actual two-page PDF locator checks passed. Added metadata-only stale-generation assertion next.
  Runtime server91057 still has598d11c5 S1 code in memory; restart after S2 regression before using new endpoints/live Deep.
  Next concrete action: finish S2 regression, commit candidate, restart owned server, import samples into same DATA_DIR KB,
  run one real Deep comparison and source UI check, finalize0.3 and proceed S3.
- Progress remains in this file; original design/evidence archived read-only under reviews/020-next.

- 0.3 stage commit31e0285a + entry8b4f687b retained. Real Deep first failed: both subjects read but canonical packet divided allowance across overlapping subquestions and repeated reads; loan limit was absent from sent packet.
  First correction delivered both numbers but model omitted requested applicability; result stayedpartial. Both negatives retained:S2_DEEP_20261030T015047/020012.json.
  Packet now replaces same-anchor search with actual read, budgets the actually rendered wire rather than the larger host offset table, and sends the investigation checklist to generation.43relatedprogram checks passed; next live is for this concrete change.
- U14-U18 implemented in current candidate: local TEST ActionSpec transitions, exact lifecycle previews/confirmations in the same action_proposals/confirmations/command_ledger, atomic approval+reservations, return/cancel releases, repair close/reopen, current ticket separated from immutable submission receipt.
  First service lifecycle16passed; preferences/date-candidate adjacent17passed. Actual primary database business lifecycle and browser NOT_RUN yet.
- U19-U21 candidate: default CLI factory avoids importing legacy app/container; explicit app.main legacy retained; installed model choices and onboarding, packaged sample resources, embedding misses batched16 with existing persistent cache. Program batch currently in progress; no speed claim.
- Next concrete action: finish batch/factory regression, commit S3 candidate, restart own8740server on current bytes, verify Deep, then same-primary-database UI loan/repair lifecycle and a small batch indexing/cache measurement. Do not stop at this checkpoint.

- 0.4真实UI核心链已完成（跨候选局部恢复，不冒充一次全绿）：借用b9d7ee9c71084a19b6f8e742fa60f7db改期/旧确认拒绝/当前确认/RESERVED/CHECKED_OUT/RETURNED；同库e245613868e34e2b8d24db60f8ca43ea再次申请后撤回。
  报修5842f125ffc443b8bca7322c3e67e11a从空字段自然补充、真实preview/OPEN到IN_PROGRESS/RESOLVED/CLOSED，45751e73记录S3_UI_2026-10-30T05-13-50-156Z.json最终通过。旧失败和原模型响应都保留，主库此时115chat。
- 真模型定位/实改：继续入口缺当前用户动作；未传既有目标释义；空finish未消费宿主观察；准备schema未承载用户描述；target与facts.asset_id重复表示；缺业务规则被误当缺用户信息。修复共同职责，没有题号/错字词典。
- 实测8个合成chunk一次批量embedding，冷构建3.031s、缓存重建1.016s且0新增embed，含轮询开销非纯计算时间。原资料版本替换/停用/恢复/历史定位均实操。
  该组问题却因跨文档同名属性被标冲突，内容为partial，不能算问答通过；正在收口用户明确《原文标题》时对已有policy ID的资源绑定，ACL/版本继续收紧。
- 知识已知负结果：跨国运费问题被用“没有规定押金”错误回答。一次提示追加使正常Deep退步，已回退；明确否定对象字面拦截也误伤4个原A1回归，已回退。NEGATIVE_ATTRIBUTION.xml保留，不将这些变体放入最终代码，不继续关键词修补。
  Deep真实读取与分题已存在，df0c118c有两数值/维修资格/会议室时段回答；后续实际schema预算多8字节导致0发送失败已修。当前最终Deep需要在冻结字节再记一次；错误不足反例仍为KNOWN_FAILED。
- 相关全批113passed/1failed：旧取消续跑替身对字段齐全任务仍ask_user，与当前合法动作schema不符。已保留原清理断言并改为实际合法读取→准备，额外检查preview生成和0写入；最终批待完成。
- 下一步：固定0.4候选，运行当前受影响路径、Deep-only与明确标题的两入口；发行副本/本地wheel启动和重启；汇总8类旅程、实际账目与已知知识缺口，然后交付。无有效GitHub推送授权，尚未同步，不创建虚假PR链接。

## Historical 0.2.0 Position (retained)
- Workspace: `D:/文档/agent/RAG_try`; branch `codex/esa-vnext`.
- Original main HEAD: `51faa5ba2f35d79120b362fff08b091646168d77`; 27 tracked dirty files predate this work. Their changes are preserved; the RAG modules now also contain explicit integration edits.
- Scope: R1+R2 / M0-M8; DONE_R1_R2_LOCAL_DEMO. No explicit token budget assigned.
- Stage: frozen application bytes670fdb66; final delivery changes are documentation and the CLI probe only.
- Existing effective assets: main dirty RAG; `_delivery_work/ESA_AGENTOPS_20261013/source_candidate`
  for Service/AgentOps; Enterprise working `rag_source_candidate` has a later
  `generation_v2.py` edit. No archived tree will replace any of these.
- Existing successes retained: C3 A2-A5 live TEST business evidence; A1 offline
  mapping repair; Service exact preview/confirmation/idempotent readback; AgentOps readonly export.
- Historical boundary: old C3 results do not establish all vNext paths; current limited live pairs are listed below.

## Latest Actual Work
- Read parent AGENTS, Git status, GOAL/architecture/roadmap/contracts.
- Installed plan in `docs/esa-vnext/`; merged applicable conventions into root AGENTS.
- Created feature branch without committing/reverting prior edits.
- Old offline launcher actually failed: `dual_track_worker.prepare -> GET /api/tags -> WinError 10061`.
- Implemented single-app `app.cli init/serve/doctor`, existing `app.main.create_app`
  workbench lifespan, stable `.private/esa-vnext/app.sqlite3`, settings and four-tab UI.
- First actual HTTP probe found a second blocker: global identity middleware returned
  `identity_unavailable` for the new local UI/settings. Added a local workspace
  route partition; old protected document/operator APIs remain authenticated.
- 3 bootstrap program regressions first failed with 503, then passed; model unavailable,
  settings persistence, restart, cross-origin and legacy boundary checked.
- Bootstrap plus existing identity API regressions: 37 passed. Actual Edge browser
  verified unavailable-model UI, settings persistence, narrow viewport and no JS errors.
- Editable `esa` console installed; uv.lock generated (109 packages), offline lock check passed.
  Later clean-source and clean-dependency installation are recorded below.
- M2: actual upload/parser/library/version/job/atomic index publication/shared RAG and persisted answers added.
  Real BGE created a two-document synthetic index. First real 9B answer failed delivery because inherited
  HTTP deadline expired; durable bounded runs fixed that boundary. Second live answer delivered but partial.
  Later source-unit schema/presentation and live pairs are recorded below.
- Integrated 8 existing ServiceDesk modules into the one app, not another hidden source tree.
  Added transactional expected_facts_revision, explicit null clearing, valid-preview reuse and per-run budgets.
- Real current UI loan task 875dc57da41a4ed98f5496453cd13db0 used native Ollama tool calls:
  loan_policy/assets_search/tickets_list_mine -> prepare_preview. Date edit cleared consent;
  stale confirmation got409; current exact confirmation created one PENDING_APPROVAL ticket
  cbac73f0466f47caa10a1bfdd73e8596; reload readback passed. 4 actual chat calls across its 2 runs.
- UI harness initially observed the pre-run BLOCKED baseline too early; same task continued successfully.
  Fixed harness to wait for the persisted run, resumed that task rather than creating/re-running it.
- Current raw evidence lives in `.private/esa-vnext/logs` and the one app.sqlite3 model_calls/task_events/
  workbench_runs/tickets/confirmations tables. No historical ledger changes.
- Further finite live checks: both knowledge entries delivered partial with the same omission,
  natural update rejected UNBOUND_PARAMETER_UPDATE, owned-ticket readonly branch returned the real pending
  ticket and left DB count1->1. Raw record: logs/M4_SHARED_BRANCH_20261029T181629.json.
- Located actual early causes: old keyword-dependent planner invented a materials obligation;
  generated composite quotation crossed separate complete units; generic changes/sources dictionaries
  let the model use mismatched keys and concatenate dates into purpose. Removed those planner branches,
  made the wire select host complete-unit IDs, and changed updates to typed field/value/exact-quote rows.
  Relevant offline regression: 83 passed at that point (not additive with later batches).
- Later typed update succeeded on the same natural request; readonly owned-ticket branch completed,
  DB ticket count1->1. Knowledge body became complete but status remained partial: old clause splitting
  omitted the first obligation; model conflated a source-supported negative answer with inability to answer.
- d25b4048 now retains the whole original knowledge obligation and defines that semantic distinction.
  Real pair in logs/M2_KNOWLEDGE_PAIR_20261029T184116.json: both entries answered, all required clauses retained.
- M6 clean-source check caught an omitted untracked KnowledgeService module. Fixed in78379f8a.
  Independent committed code then started without editable paths. Actual uv sync installed64 pinned
  public dependencies in its own venv, and the probe passed there too; no model calls in either probe.
- Implemented continuation: unresolved user-message safety/recovery and optional original-question
  parameter prefill. Host preview/confirmation/resume blocked until input is applied or explicitly resolved;
  no invented consumption of failed input. Latest targeted bootstrap/message/lifecycle batch11 passed.
- Directory import/unchanged/replace/missing-source retention/recovery and existing embedding cache
  implemented. Program check: identical documents publish next generation with0 embedding misses.
- Interview issue log: `IMPLEMENTATION_INTERVIEW_NOTES.md`, updated from real failures only.

## Latest Checkpoint — 2026-10-30 local
- c68a115a removed eager legacy graph/evaluation imports from the thin Agent package. A separate
  uv-installed environment imports and starts committed code without author editable paths.
- Added bounded send-time deadline checking and409 settings protection during active runs/index jobs.
- Real J10 exposed early not_found: Guard admitted both policies, but the old extraction relevance
  gate treated a personal booking year as a required year in policy prose. No generation was sent.
  Product KnowledgeService now uses the existing semantic need/source contract on the whole question;
  old extractive interfaces retain their contract. Candidate admission is not final answer support.
- Real UI task8f868cae456244bba31cb0a995e6ef11 then completed knowledge-to-task, explicit user opt-in
  extraction of dates/purpose, actual asset2 selection, preview/date edit/stale-confirmation409,
  current exact confirmation, one PENDING_APPROVAL ticketfa214993a3e54b16874ccb643cbcf7d4 and idempotent reload.
  This J10 knowledge result was still partial. Its trace is not rewritten as an all-quality pass.
- Saved real response showed a recovered exact draft unit lost its existing unambiguous need association
  and was dropped by publication. Repaired that handoff; multiple/unknown needs remain unresolved.
  Missing semantic coverage cannot become complete merely from citations.
- Subsequent same-question real RAG/Agent pair both answered all six requested policy facets:
  `demo-validation/logs/KNOWLEDGE_HANDOFF_PAIR_20261029T195549.json`. The later missing-coverage guard
  changes only the absent-relation negative branch; these actual replies contained relations.
- Final related program batch:115 passed,3 FAISS binding deprecation warnings; no full historical suite.
  Includes bootstrap/messages/lifecycle, original A1 replay, generation/controller/relevance and identity boundary.
- Real unchanged-document cache comparison: first rebuild2 misses/2 embedding requests/3.282s;
  second rebuild2 hits/0 requests/0.218s. Specific batch, not QA accuracy or a universal speed claim.
- Actual appended product attempts at checkpoint: primary data21 chat/12 embed; independent TEST journey
  data9 chat/6 embed. All completed OK, raw requests/responses remain in their app.sqlite3 model_calls.
  Earlier product rows whose purpose was not recorded remain UNCLASSIFIED; historical experiment ledger untouched.
- Interview record now includes9 real problems, with causes, changes, tests/live boundaries and oral answers.

## Decisions
- Product changes will be in the current repository, not another full checkout or ZIP.
- Reuse the latest Service modules and current RAG implementation selectively;
  preserve the independent working originals and later Enterprise RAG edit.
- Historical experiment ledger stays immutable. Product model operations are ordinary
  configured local calls, not reclaimed or reset historical experiment balances.
- No giant audit bundles, full-tree duplication or unrelated historical suite.

## R2 Implementation Checkpoint — 2026-10-30 local
- Shared fixed Service Catalog now defines loan and local synthetic IT repair fields, rules/read adapters,
  operation/table/status. Both use the same task UI, native-tool loop, proposal, confirmation,
  command transaction, cancel/fence and readback. No second graph or transaction implementation.
- Real J11 UI task4540ac96eaca4f6c8e53276a69fc5aee:5 chat attempts, policy/assets/owned-ticket reads,
  natural description/impact update, stale confirmation409, oneOPEN ticket8c0cb7c79fe64abd9f9ba50e6c393486,
  idempotent retry and reload. All loan tickets/assets/eligibility/rules unchanged.
  Raw:logs/J11_2026-10-29T20-23-14-792Z.json and current database.
- Actual follow-up used prior user questions, never prior answers as evidence. Initial browser assertion
  expected the newer example phrase, while the older indexed policy said“没有规定押金”. Its zero-assumption
  explanation remains a content limitation, preserved in logs/FOLLOWUP_2026-10-29T20-06-20-469Z.json.
- J12 real two-version room answers both answered:09:00-18:00 then10:00-19:00, both retained2-hour limit.
  Initial build2 misses; changed build1 hit/1 miss. Missing source retained with notice; old source opened.
  UI continuation after opening the closed source details sent0 chat; original harness failure retained.
  Raw:J12_2026-10-29T20-33-21-435Z.json and J12_PRESENTATION_*.json.
- The earlier follow-up issue became an actual UI feedback candidate. expected=null; no automated
  truth label/model run. Current source/old version metadata and original PDF/Word parser locations retained.
- Same current UI after restart read actual old loan and new repair receipts,0 chat.
  Raw:PERSISTED_RECEIPTS_2026-10-29T20-42-24-023Z.json.
- Actual readonly dependency experiment retained asset/ticket observations after an independent description
  edit. Tool reads3->1, chat2->2; complete read elimination was false. Business rows unchanged.
  Raw:READ_REUSE_20261029T203733.json. No blanket latency or chat-saving claim.
- Repeated-start RED reproduced: second instance was not rejected and startup could interrupt active work.
  OS-level data-directory lease and readonly doctor fixed that. Cross-process crash release tested.
- Browser fixture found old confirmation/form remaining while another task loaded. Immediate clear/loading
  plus selection version fencing fixed it. Delayed real response, scope refusal, dates, long text,
  narrow screen and script payload checked; explicitly PROGRAM_FIXTURE,0 chat.
  First fixed browser result file was overwritten; initial tool output separately captured with that limitation,
  later output names use timestamps. The original historical evidence was not modified.
- Current related program regression127 passed; final small projection check3 passed. Last code after
  the127 batch only changes completed-view text and parsed-location presentation; no model input/transaction change.
  Actual JUnit:logs/R2_RELATED_REGRESSION.xml. No full historical suite or main model comparison.
- App package now0.2.0; uv lock resolved offline with the same109 total locked packages including optional groups.
  Final clean default installation and source packaging still pending at this checkpoint.
- Appended product attempts before final release checks: primary33 chat/18 embed requests;
  independent demo-validation9 chat/6 embed; presentation fixture0 inference. Historical ledger untouched.
- b81dff81 exported and installed from cache in a new directory:43 default packages, isolated-source
  probe PASS. Dev extras needed4 public wheels absent from cache; pinned packages installed only into
  that independent venv. Original project third-party environment unchanged.
- Final wire inspection found RAG num_predict1800 vs packing reserve1024. Actual callback/HTTP RED
  reproduced1800!=1024. Shared serving constants now govern both; only RAG default transport changed,
  not native600/message500 or permissions. This tiny correction supersedes b81 as final source;
  the b81 archive remains a checkpoint. Focused regression and final bounded live evidence follow.

## Next Action
No queued development or model runs. Use START.md / RELEASE.md for the frozen local demonstration.
R3, enterprise deployment and a new quality benchmark are outside this completed scope.

## Final Freeze — 2026-10-30 local
- Application/lock commit670fdb66be89e473070ada879bd01b3f47065b8a. Later delivery commit contains
  documentation and a no-inference CLI probe; verify `git diff 670fdb66..HEAD -- app pyproject.toml uv.lock` is empty.
- 955bf690 real comparison exposed two completion authorities: semantic need/body binding was complete,
  but entity-name repetition forcedpartial. Same original reply RED then scoped GREEN. Semantic mode
  now retains lexical counts as diagnostics; unknown/missing relation, unsupported claims, source and
  upstreampartial protections remain. Legacy aspect mode unchanged.
- New actual pair on670fdb66: logs/FINAL_LIVE_20261029T213822.json. Both answered, each with two sources.
  Both bodies retain1-14days/start-not-past/active-repair/one-open-request and room2hours/09-18/cleanup.
  The before/after is a content/status consistency correction, not a broad accuracy claim. No business rows changed.
  Actual num_ctx8192/num_predict1024. This pair used3chat/4query-embedding requests, no retry.
- Final source exported by scripts/export_vnext_source.py, separate environment installed44 default
  pinned packages; explicit-directory/no-editable-source probe passed. Dev adds4 packages.
  Independent Windows regression:129passed/0failed/0skipped,53.053s; build/CLEAN_FINAL_670fdb66.xml.
  Four dependency deprecation warnings remain. No full historical suite or main QA comparison.
- Real installed esa CLI invoked from another working directory: HTTP/static/API available, TEST task
  preserved across two process starts, same initialized marker,0model calls/0business tickets.
  Startup5.000s and4.360s on this machine; build/CLEAN_CLI_670fdb66.json. Not a cross-machine benchmark.
  Initial init-output capture had a Windows decoding warning; the two actual HTTP/DB checks passed.
  The reusable probe now explicitly enables UTF8 in its child process.
- Earlier independent failure: missingtzdata caused16failures, omitted HTTP helper caused1. Direct
  lockedtzdata and helper export fixed them. Offline-only install first missed its wheel; only that
  pinned public dependency was fetched in the independent venv, no model/global environment changes.
- Earlier related regression128pass/1fail exposed timing-dependent test setup: sleep10ms did not always
  expire1ms on Windows. It touched the local model port once and timed out. OriginalERROR row retained
  in logs/OFFLINE_TEST_UNEXPECTED_SENDS.json; deterministic clock plus fail-on-send transport now passes.
- Final product counts: primary40chat/26embedding requests; demo-validation9chat/6embedding; presentation0.
  Total49product chat/32embedding requests(32texts), plus the one failed test attempt =50known new chat attempts.
  All49product HTTP replies wereOK, not proof their content was all correct. Historical experiment ledger
  untouched; historical UNKNOWN staysUNKNOWN. Earlier unclassified product purposes remain unclassified.
- One authoritative product DB per declared DATA_DIR, no second quota ledger. Summary with raw pointers:
  logs/R1_R2_RELEASE_SUMMARY.json. Source archives exclude databases, raw ledgers, personal docs and indexes.
- Git remains local codex/esa-vnext; no push/PR/merge. Remote feature branch was absent at the checked state.
  Unrelated preexisting work remains dirty and excluded from the source export.

## Milestones
M0: IMPLEMENTED; first startup failure reproduced and common startup separation fixed.
M1: IMPLEMENTED for local single-owner mode; same-dir recovery, readonly doctor and OS lease tested.
     Historical JWT databases remain preserved, not reassigned to local-owner.
M2: IMPLEMENTED; shared pair and versioned answers live-verified; contextual follow-up linked, with
    the explicit content limitation above. Old source and parser location access verified.
M3: IMPLEMENTED vertical loan lifecycle; conflict/clear/repeated edits/idempotency/restart tested.
M4: IMPLEMENTED; native-tool loop, durable runs/SSE, loan/repair natural update and readonly branches live-verified;
    current browser and restart checks retained separately from fixture tests.
M5: IMPLEMENTED vertical path; J10 actual UI/model/business journey verified; knowledge handoff had a
    separate negative result and later focused live pair, as recorded above.
M6: DONE_LOCAL_RELEASE; final independent source install, actual CLI/restart and129related regressions passed.
M7: IMPLEMENTED/LIVE_VERIFIED in shared framework with synthetic backend.
M8: IMPLEMENTED/LIVE_VERIFIED; directory versions, feedback candidate and measured embedding reuse.

## External / Delivery State
- Models: installed local 9B/BGE used; all attempts remain appended in product model_calls. Historical
  grant ledger is untouched. Recompute current totals from DB rather than copying old checkpoint counts.
- Commits:540cfa55 bootstrap;38a5b69d integration;d25b4048 knowledge;78379f8a packaging correction;
  6cf66b65 pending-input recovery/prefill; c68a115a lazy legacy imports. Latest checkpoint commit follows.
  Unrelated preexisting README/Streamlit work retained.
  No remote sync or PR performed.
- Current R1/R2 scope is complete for the documented local synthetic demonstration. R3 is not activated.

### 2026-10-31 01:08 当前恢复点

- 最终应用commit ea7c6cffe09b13ce4da0e3c7ec3a257541d582fc；Windows ZIP 78,806,047字节，SHA256 e735d35fb7aba27af96b4a4a9b3851795bbe57afbdd53f53caa51fb1835474eb。相关程序测试FINAL_REGRESSION_ea7c6cff.xml为100通过，Windows独立包启动6.0s/复用1.141s。
- 主8740已由该包启动，instance 90025fdde13241028aa14d5fb22223ce，PID46932，原DATA_DIR未变。
- MIXED_FOLLOWUP_20261030T170219Z实际新增6chat：正常Agent PASS；独立RAG、长历史追问、改期混合知识FAIL；第二台指代未到达/NOT_RUN，完整最终UI旅程与回执浏览器检查未运行。主generation_calls=208。不可将程序通过或旧e808旅程写成该候选全部验收通过。
- 用户物理Esc停止了本次Windows Computer Use；已停止后续桌面输入。批量验证进程已退出，未继续启动后续模型批次。原生首次对话框实际显示并能读取按钮，但目录选择与自动浏览器仍未验证通过。
- 下一具体动作：先离线读取上述4例实际答案/工具观察，定位独立RAG、追问和混合失败的最早分歧；不盲重复采样。最终版本仍是实验候选，完整交付未结束。

### 2026-10-31 01:18 新恢复点

- 应用冻结223390cbf1b40712834174a4c4601ef858c54a7f，最终相关回归103passed；窗口包已构建并切换原DATA_DIR，主instance9098ce335fa343d9879f657213bb82ca/PID8900。
- 历史问题不再错误进入clarification_reply；纠错使用实际完成工具/缺项；冷加载使用已有配置传输时限、整体run未加额；系统错误保留原件但进入可重试失败。定向真实路径26passed。
- MIXED_FOLLOWUP_20261030T171625Z已证明新候选正常独立RAG PASS，其余以文件的逐项实际状态为准。Windows控制再次收到用户物理Esc停止，停止后续桌面输入；批量驱动已准确结束，没有用Ctrl+C杀主应用。保留USER_ESCAPE_223390cb.json与部分记录，不能将未跑项改PASS。
- 下次先读部分记录与数据库实账，不重复已完成同版本案例。不再次主动弹出原生GUI打扰用户；该GUI人工检查暂为外部交互阻塞。继续其它安全可执行的代码/质量与交付工作；最后仅将首选目录/自动浏览器/手动IME明确待验，不冒充已通过。

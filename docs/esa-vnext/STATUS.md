# 当前：rc2收尾W01—W08实施中

唯一范围：reviews/rc2-finish-20261031/03_CODEX_GOAL.md。原A01—D02已完成结论保留在下方；不重开解释实验，不扩0.8。

- W01：实际HEAD510ea086，8748仍70a50050。活动DATA_DIR为upgrade-070-next/live-workspace，原数据、7个脏文件和未跟踪成果保留。
- 已实际复现：参数PATCH200→prepare409→旧revision再保存409；浏览器证实两次save均发revision1。正常报修ask_user最后被BLOCKED覆盖。原部分交付/重复提交修复仍有效。
- W02/W03：具名操作与typed产品写响应，保存即同步Query和草稿基线；共同下一步投影区分input/choice/retry，缺字段不重试。6项定向程序回归通过，浏览器连续保存与冲突保留草稿检查中。
- W01—W06已完成：保存/准备分离、正常等待、共享next_action、具名mutation与定向刷新；React三入口及资料库/设置/服务台统一，真实单据动作全部保留。浏览器9场景通过，134项相关程序回归通过，模型替身与实际SQLite已分开标注。
- 当前候选0.7.0rc3，准备冻结并构建。下一动作：最终包正常升级当前8748同一TEST目录，进行有限真实模型与原生检查。此时新增模型调用0；真实账本起点412chat/227embedding，历史1条SENDING保持。

<details><summary>上轮真实成果与历史状态</summary>

# ESA 当前进度：本轮默认预发布收尾完成

- 应用冻结：`70a5005022e234e047d6c8e9ef515d86dccbcbb8`，**0.7.0rc2**；后续只提交本次文档和CI环境修正，不改应用/前端。不继续追加功能。
- GitHub：`origin/codex/esa-061-070` 已同步，Draft PR https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/pull/2 ，未合并main/未发stable标签。原7个未提交文件字节保持。
- 当前真实新版：http://127.0.0.1:8748/ 。DATA_DIR为 `.private/esa-vnext/upgrade-070-next/live-workspace`，保留完整原历史的隔离TEST副本。原 `.private/esa-vnext` / 8740旧实例不动；不会静默替换。
- Windows产物：`.private/esa-vnext/build/releases/ESA-0.7.0rc2-windows-x64-70a50050.zip`；本机快捷启动 `.private/esa-vnext/upgrade-070-next/打开ESA演示.cmd`。包内带Python与锁定依赖，日常不安装。具体命令见START。
- 最终应用commit的GitHub product-regression Windows/Linux均成功：https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41175705182 。133项相关产品/A1默认程序回归，5项明确模型替身浏览器；不是模型准确率。研究两断言1通过1已知失败，独立公开，不skip/xfail。
- 本轮新真实证据：最终双入口借用七项知识齐全；原只读同任务/输入/回合恢复且零准备/提交；最终UI新借用预览/改期/旧确认409/当前确认/唯一待审批/幂等读回、归还，报修OPEN至关闭。模型输入/原响应/真实工具/数据库留私有原件。当前包正常版本切换/重复复用/端口冲突/模型离线/中文路径通过。
- 实际新增 **30 chat / 13 query embedding文本 / 0 index**。工作台表累计412chat/227embedding；旧1条SENDING结果未知保持原样，更早研究账本不重置、不虚构总计。后续整理不再调用模型。
- 新解释无稳定改善，保持关闭。默认报修知识的一种问法仍partial、漏提交状态；不是所有知识问题已完整正确。尚未证明追平main。
- 未验：Windows原生首次目录选择、完整自动开页桌面路径及物理IME；目前不是正式stable070。旧全仓CI的Python3.11.9不支持新ubuntu-latest 26.04，已仅将其OS固定22.04，保留完整旧检查，结果与产品CI分开。
- **下一项具体未完成**：对冻结包完成原生首次目录/自动开页/物理中文输入法人工检查。报修问答漏答作为后续独立问题登记，不在本轮扩题/调参。默认任务到此冻结交付。

详见[结果与证据索引](RESULT_070_RC2.md)、[使用/升级](START.md)、[支持范围](RELEASE.md)。

<details><summary>本轮实施经过与负结果（历史，不是并行活动计划）</summary>

# ESA 当前进度

当前范围：A01—D02，见reviews/070-next-20261031/GOAL.md；旧T01—T18不再作为并行活动计划。历史状态保留在history/STATUS_THROUGH_070_CANDIDATE.md，既有成果和失败不清零。

- 起点：39c4dbfa说明 / d32bd1b1应用；7个无关未提交文件原地保留。
- A01完成：origin/codex/esa-061-070已推送39c4dbfa756f6a8fb4597928d5695356e28da26b，Draft PR https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/pull/2 。一次内容检查覆盖66个未公开提交，未发现私密路径/凭据；未上传活动数据库、原始调用或审核ZIP。
- 当前运行：原8740仍9f82、原DATA_DIR .private/esa-vnext保持；不执行上一轮被拒绝的关闭操作。后续验证使用保留历史的隔离TEST副本，注明来源及新调用，不能用新空库绕过失败。
- 原件复现：partial_failure、omitted_knowledge均预览存在、turn=DONE、retry409；已保存DEFAULT_RED.json。这是程序替身+真实工厂/SQLite，不是新模型成绩。
- A02完成：产品默认检查与解释实验检查分开；当前132项相关默认离线回归、5项实际浏览器（明确外部模型替身）通过。补充的公共prepare收口回归4项通过；次数不相加当质量指标。实验2项1通过1失败保留，未skip/xfail。
- B01—B05已实现：回合交付保留未决项、仅重试知识；公共prepare复用原propose；command先关闭读连接再读业务；数据库繁忙结构化409；实例报告实际commit与build，新旧不同需显式选择。
- React：保存参数/选设备后直接生成当前预览；部分结果显示可执行重试。前端类型、构建、5个浏览器场景已通过。物理IME未验。
- C01/C02：来源附可信原文节/文档分组/业务metadata，无metadata为unknown；实验schema压缩，旧词法推断只作诊断，来源/Guard仍保留；业务域上下文由宿主kind约束，不猜关键词。实验仍关闭。
- 下一动作：固定rc2实现提交并构建，完整克隆现有TEST历史（不换空库）检查旧失败任务恢复及真实模型/业务主链；小范围同条件解释比较。
- 解释保持关闭；旧24例已经公开，只能作回归。新模型实验只做必要有限诊断，沿用真实记录、不重置历史。Windows原生与物理IME仍未验；没有新通过结论。

## 219b0ff8 实际运行检查（后续修正前，不能冒充最终候选）

- 保留75任务、6历史借用工单和382 chat/214 embedding行的完整TEST副本启动rc2，8748；原8740旧实例未动。
- 旧失败借用任务恢复、真实模型工具选择；UI改期、旧确认409、当前确认唯一待审批、幂等读回，借用批准/领用/归还及报修OPEN/处理/解决/关闭均通过。共新增3chat；原件LIVE_JOURNEY_219b0ff8.json在私有证据目录。
- 4组默认/新解释配对及只读诊断新增10chat。解释D1未获得报修证据、D2生成残句和倒置关系，不能转正；H1正常、H2有解释但引用空白。保持关闭，不再刷同批。
- 真实只读任务被模型brief错误加preview（未写库）。已补宿主ceiling校验、同run一次明确纠错及schema约束；定向程序回归10通过。不会靠该模型brief授予准备权限。
- 来源主题元数据限解释实验，默认继续原来源容量契约，避免实验扩大默认提示包。
- Windows包219b脱离开发PATH可启动，冲突端口避让、重复启动复用、模型离线页面与数据保留通过；原生首选目录/自动开页/物理IME未验。
- Windows CI原8失败定位为runneradmin默认以Administrators组拥有新目录，触发既有私有缓存所有者保护；测试进程只将新对象默认owner设为自身SID，退出恢复，不改产品ACL或机器设置。待远端重验。
- 下一项：冻结上述修正并正常升级本轮自有8748实例，复验受影响只读/默认知识；不重复借用报修整链。

- 23432d15实时补查：借用同题独立RAG/knowledge Agent均交付资格、1–14天、开始日期、唯一未关闭申请、待审批非分配及押金未知；报修问法仍漏状态且partial，保留限制。只读纠错方案真实失败（模型文字承认只读，布尔仍true），转第二个机制：宿主将交付声明与用户范围求交，保留原声明，实际工具权限不变。定向16项通过，冻结后仅再测这条受影响恢复和最终业务旅程，不重复解释配对。

</details>

</details>

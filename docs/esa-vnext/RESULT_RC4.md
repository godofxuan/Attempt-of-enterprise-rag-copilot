# rc4：三组问题修复，有限工程收尾完成

应用冻结：`78f7464e4597fe9d368725e1c7d570a4f28d6e89`，版本 **0.7.0rc4预发布**。后续只有说明与教学映射提交，不改变运行代码。不合并main，不开0.8。

## 改了什么

- **F1**：原件和当前工厂均复现：只请求知识的失败回合，因为借用日期未填被改为WAITING_USER、retry409。现在用已有回合交付项判断恢复依赖：知识独立重试，预览仍记录所缺字段/设备；真正运行中和待核对修改仍优先阻断。兼容旧版留下的WAITING_USER记录，恢复不重放已应用输入。页面保留原问题，并从当前事项投影恢复动作，历史“正在处理”不再冒充当前状态。
- **F2**：旧答案仍在数据库，却因不在最近50条而409。`answer_by_id`现在直接读主键，复用来源/原归属视图；事项列表用同一owner范围内的rowid游标分页和服务器搜索，详情不依赖列表。旧列表仅作同一查询的兼容首屏。手机可展开最近会话，不新增第四入口。
- **F3**：截止后GET仍can_submit=true，POST才拒绝。现在GET只读标注current/expired/stale、服务器时间，按钮与can_submit共用判定；旧正文保留为参考。前端在截止或重新获得焦点时只刷新当前事项，切换时清理定时器。提交仍在原事务中最终校验，过期规则没有删除。

保存缓存、正常补信息、共享prepare、权限/确认/事务/幂等和现有两个业务继续保留；没有改模型提示、来源发布算法、框架、数据库或增加judge。

## 本次有限验收

本表候选均为78f7464e。程序替身、真实模型、Windows命令启动与原生GUI分别记账。

| 项 | 实际方式与结果 | 边界/未运行 |
|---|---|---|
| A01 启动 | 最终Windows ZIP，官方Python3.12.10，无开发PATH/Node；中文目录、模型离线、端口冲突、重复复用通过。首次4.797s、复用1.078s，各一次样本。 | 本轮原生首次选择/自动开页/关闭再开桌面路径NOT_RUN；不能用命令探针代替。 |
| A02 已修路径 | 当前产品工厂、真实临时SQLite及浏览器外部模型替身：保存revision、选择设备、补报修字段、prepare继续通过。 | 不重新声称模型任意字段理解准确。 |
| A03 知识恢复 | 首次外部知识错误→原回合重试成功；不填借用日期、不生成预览或票据；旧WAITING_USER也可恢复；原Deep模式与知识范围保留。浏览器可直接重试。 | 外部调用受控替身，是机制回归。 |
| A04 混合依赖 | 知识错误与缺预览字段同时存在时先补知识，之后只等待预览条件。既有预览/后续参数不被重放，原相关断言保留。 | 按交付项验收，不按整体标签计正确率。 |
| A05 历史 | 55条事项、分页间新增记录、归属过滤、无匹配、跨页搜索无重漏；55条答案最旧按ID200。活动库真实最旧答案也200，原会话/库/来源视图保留。浏览器加载更多与手机历史入口通过。 | rowid是本地SQLite当前排序依据；没有为列表调大固定上限。 |
| A06 截止 | 注入时钟覆盖截止前、截止恰好时刻、GET不写库、过期POST409且0新票、新预览可确认。浏览器推进时钟后直接显示重新生成，无需先错误提交。 | 前端倒计时不代替事务检查。 |
| A07 两业务 | 复用当前领域/API/SQLite与浏览器关键链：借用批准/领用/续借/归还再办理；报修处理/解决/关闭/重开，幂等断言通过。 | 浏览器模型为明确替身；本轮没有重复一套真实模型提交周期，也没有改业务事务。 |
| A08 真实模型 | 最终Windows实例、原TEST历史和冻结文库、qwen3.5:9b/bge-m3。Fast正文给出1–14天与待审批不等于分配；Deep给出开始日和一个未关闭申请，实际2次search+1次open。混合任务保存正确日期/用途，等待真实设备选择；TEST用户选实际候选后可准备仅预览，0提交。 | 混合知识因包含办理原文而保守partial，未宣称完整正确。本轮复用已上传/已发布索引，新上传建索引链NOT_RUN；不把旧索引算成本轮新建。真实模型UI NOT_RUN，实际为API。 |
| A09 UI | 1440/1024/390、恢复/缺字段/候选/过期/列表；单输入框、长文/安全渲染、Dialog焦点和合成输入法事件通过。已查看实际截图并做一次局部文字/按钮调整。 | 物理中文输入法NOT_RUN，程序composition事件不代替。 |
| A10 交付/教学 | 同commit源码构建前端和Windows包；48题/答案、8单元、6标准库实验、24源码锚点可查，映射更新为78f7464e。独立教学实验24断言通过。 | 只在本项目版本资源目录接入；未访问另一个学习仓库、学生断点或掌握状态，不替学生答题。 |

相关默认程序回归 **139通过**，保留两项实验性研究在独立工作流，未删断言或加skip/xfail。旧审核的4个脚本失败在当前仓库中已经使用turn_request兼容fixture，本次按原业务断言执行通过，无需再改弱断言。

浏览器合并组 **12通过，0重试、0跳过**；最后仅调整历史记录文字后局部知识路径再验通过。同一冻结提交的[product-regression](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41216852216)在Windows和Linux均通过完整产品组与12条浏览器旅程。全仓CI另行运行，不宣称全仓全绿；[解释实验](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41216852202)仍红且关闭。Vite约505KB chunk提示保留，未提高阈值掩盖。

## 实际成本、证据和使用

本轮新增 **7 chat / 4 query embedding文本 / 0 index embedding**，全部11个发送与原始响应均留在原工作台账本；3条真实运行没有重复采样。模型耗时合计54.796秒，不是端到端平均延迟。工作台表累计430 chat/237 embedding，历史1条SENDING未知保留，更早研究消耗未虚构总计。TEST用户补选/prepare没有新增模型调用或票据。

实际页面：`http://127.0.0.1:8748/`。已通过最终EXE的正常existing restart切换到rc4，继续使用`.private/esa-vnext/upgrade-070-next/live-workspace`；没有清库、覆盖用户资料或处理原8740。原7个无关脏文件保持。日常完整解压后双击ESA.exe，选择已有完整目录；本机快捷入口`.private/esa-vnext/rc3-final-20261031/打开ESA演示.cmd`。

Windows包：`.private/esa-vnext/build/releases/ESA-0.7.0rc4-windows-x64-78f7464e.zip`，78,861,430字节，SHA256 `5fb315ccd268e87e49081f30e3bbc3eed6b1e8df920db52ae6b1b0764674ea0d`。源码在[原feature分支](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/codex/esa-061-070)与[Draft PR #2](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/pull/2)，未合并main/发稳定标签。

本机原件索引：`.private/esa-vnext/rc3-final-20261031`下的START、BASELINE_PROBES、RED、TARGET、PRODUCT、BROWSER_FINAL、BROWSER_KNOWLEDGE_FINAL、UPGRADE、WINDOWS、REAL_MODEL、NEW_MODEL_CALLS、COST及screens。准确命令在COMMANDS；实际代码差分在CHANGE.patch。隐私原件、活动数据库和完整账本不上传GitHub。教学入口为`docs/esa-vnext/reviews/rc3-final-20261031/teaching/COURSE_MAP.md`及SOURCE_MAP.json。

工程范围到此结束。有限剩余项是原生GUI/物理IME、未重跑的新导入索引链和混合知识partial；关闭研究与全仓历史红项不被包装成已解决。没有同条件main对照，尚未证明追平main。当前交付为可用的有限领域引导式预发布，不是通用自由文本或企业多人生产版。

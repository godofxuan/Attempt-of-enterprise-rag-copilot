# 0.7.0rc3 收尾结果

本轮收尾完成，交付**预发布候选**，不自动开启0.8。应用冻结于 `13fbe0714a59f6b52a75796156f560faa0af9123`；后续文档提交不改变应用字节。没有合并main、发布稳定标签或对接真实企业系统。

## 实际变化

保存参数与准备预览是两个结果。产品写接口返回当前TaskView，前端立即更新revision、Query缓存和已保存基线，再处理选设备或补字段；真正的409保留草稿并显示服务端当前值。具名mutation替代保存/准备/继续的布尔组合，定向刷新相关会话和事项。

正常ask_user使用现有任务与回合状态，统一next_action只读投影区分补字段、选设备、准备和故障重试；WAITING_USER不再在结束时变成BLOCKED。未补字段不会反复发送模型。用户主动准备与Agent工具继续复用原业务用例，没有新状态机、分类器或judge。

三入口、单输入框及所有借用/报修/资料低频操作保留。统一字号、对比、间距、按钮和错误区；候选自动展开，当前回执与原回执分开。Dialog复用原焦点原语；来源内联展开，技术细节折叠；文档逐文件显示上传结果。事务、确认、版本、权限、取消和幂等边界未放松。

## 唯一验收表

下表应用候选均为13fbe071。程序替身不是实时模型成功率；真实API记录也不是新版本真实UI验收。每条结果保留实际输入、输出和失败，不按COMPLETED评分。

| 类别 | 环境与动作 | 结果与限制 |
|---|---|---|
| A01 启动 | 最终Windows ZIP、官方Python3.12.10；中文目录、模型离线、端口冲突、重复启动 | 非交互产物探针通过；首次启动4.813s、复用1.078s，样本各一次。原生自动开页观察到ESA Chrome窗口，URL/内容检查被工具策略阻断，未算通过。 |
| A02 原工作区 | 原生选择已有目录、明确70a50050→13fbe071切换、同一TEST目录正常升级 | 通过，保留原资料/历史/账本；原8740及原工作区未操作。目录移动后的恢复由保留的当前产品回归覆盖，不冒充本轮手工移动实测。 |
| A03 保存与选设备 | 真实产品工厂/SQLite、浏览器外部模型替身 | 修前两次保存都发送revision1；修后第二次使用revision2，保存后准备需要选择不会重放旧保存。跨页面409保留草稿并明确载入最新值。 |
| A04 正常补问 | 离线真实代码、浏览器替身；另有真实qwen3.5:9b API报修 | WAITING_USER/input、不可故障重试；补齐后同任务继续，无重复单。真实模型未保存原句中的故障描述，TEST用户通过表单明确补齐，不能宣称自由文本提取完全正确。 |
| A05 选择/预览/提交 | 浏览器替身+真实SQLite；真实模型API借用后续 | 选真实设备→当前预览；改期后旧确认409，当前确认+重复提交为同一command和唯一待审批单。TEST确认由测试用户动作产生，未当成人工或模型授权。 |
| A06 部分交付 | 当前产品回归与浏览器外部模型替身 | 预览保留、只重试知识、后续参数不回滚，相关既有断言继续通过。真实初始混合请求漏知识见A09，不拿程序场景替它通过。 |
| A07 会话/恢复 | 当前API/SQLite及浏览器替身 | 会话切换、150条历史分页搜索、草稿、独立run停止、改名详情刷新通过。 |
| A08 资料 | 当前浏览器/API，实际上传有效文档与不支持文件 | 同批逐文件结果可见；有效项可继续，不支持项明确失败。更新/停用/版本来源由相关产品回归保留，未重建活动索引。 |
| A09 知识/混合 | 真实qwen3.5:9b、bge-m3、冻结索引、同一旧TEST目录 | Fast正文七项正确；Deep追问返回有效条件但保守partial。混合请求保存业务事实、等待选设备，却未独立交付知识；同任务一次明确知识追问才answered。保留首轮失败，不称混合理解已完全修好；解释实验仍关闭。 |
| A10 借用全周期 | 最终版本真实模型API+自动化TEST用户精确确认；浏览器替身另测同API | 新单PENDING_APPROVAL→批准/预留→领用→续借→归还。数据库当前结束日11月28日，原提交回执11月27日均保留。前置查询/幂等/已有申请保护继续有效；本轮rc3真实模型UI未运行。 |
| A11 报修全周期 | 最终版本真实模型API+自动化TEST用户补字段/精确确认；浏览器替身另测 | 唯一OPEN单→处理→解决→关闭→重开→处理→解决→关闭，库中CLOSED。期间运行脚本变量遗漏和漏填描述的失败也留档；只续办原任务，没有清库或重刷模型。 |
| A12 界面 | 浏览器替身，1440/1024/390、长文、注入文本、Dialog键盘、合成composition事件 | 9条浏览器旅程通过，无重试凑过；脚本文本安全显示，输入框不遮挡、焦点可返回。物理中文输入法NOT_RUN；本轮六类截图属于一次样式修正前的实际开发页面，最终字节由同commit CI覆盖，截图不是新真实模型证据。 |

## 检查、负结果和成本

相关默认程序回归134通过；浏览器9通过。最终应用提交的[product-regression](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41200278951)在Windows/Linux均成功。TS类型检查与Vite构建通过，构建仍提示约502KB单chunk，未通过提高警戒阈值消除提示。

**全仓CI没有全绿**：[全仓检查](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41200278941)在Windows为78失败/4243通过/11跳过，Linux为78失败/4219通过/35跳过，包括历史来源指纹和知识/间接注入验证等。没有删断言或统一归为无效，也没有在本轮扩成全历史修复。[关闭中的解释实验](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/actions/runs/41200278971)1通过/1失败，仍关闭。各平台数量不相加，不能用默认组通过包装成全部质量通过。

本轮新增 **11 chat、6 query embedding文本、0 index embedding**，17个实际请求均有原始发送/响应记录。模型调用耗时合计63.641秒，是本次样本的累计调用时长，不是端到端平均延迟。现工作台累计423 chat/233 embedding；旧1条SENDING未知结果原样保留，更早研究消耗没有虚构总计。恢复两个私有验收脚本错误后没有追加模型采样。

## 运行与复核

- 当前入口：`http://127.0.0.1:8748/`，设置或`/api/instance`显示0.7.0rc3/13fbe071。
- 活动TEST数据：仓库内`.private/esa-vnext/upgrade-070-next/live-workspace`，未换空库；只有本地单用户/合成服务台支持。
- Windows ZIP：`.private/esa-vnext/build/releases/ESA-0.7.0rc3-windows-x64-13fbe071.zip`，SHA256 `5152d4a566dc7af29b2ba93bcd908ec6ea5d3c99c86ddf54a82b663bbe9b1110`。
- 公开代码：[feature分支](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/tree/codex/esa-061-070)、[Draft PR #2](https://github.com/godofxuan/Attempt-of-enterprise-rag-copilot/pull/2)。最终运行应用仍13fbe071；后续分支文档提交不是另一个应用实现。
- 本机原件索引：`.private/esa-vnext/rc2-finish-20261031`下的BASELINE_PROBES、WAITING_RED、SAVE_RED_BROWSER、PRODUCT_FINAL、BROWSER_FINAL、WINDOWS_PORTABLE_13fbe071、NATIVE_CHECK、REAL_API_INITIAL、REAL_API_AFTER_LOAN、REAL_API_RESULTS、NEW_MODEL_CALLS、COST、DB_AFTER及CI记录。隐私原件与数据库不上传GitHub。
- 历史rc2真实UI结果保留为其原版本证据，不把它改写成rc3实时UI通过。源码/产物一致性不等于知识质量验收。

已有功能族可运行；本轮两个确定性缺陷修复、界面与代码收口完成。由于原生浏览器内容/物理IME待验、混合知识与Deep仍有上述限制及全仓红项，**只交预发布，不宣称稳定发行、任意自然语言可靠或追平main**。尚未证明追平main。本轮至此冻结；余项进入实际使用维护，不自动追加新功能目标。

文档收尾另有明确缺口：更新STATUS、RELEASE、工作约定及面试记录的组合写命令被自动审批以“blocked by policy”拒绝，未换工具重做该动作。这些文件仍保留原阶段文字；当前结果以本页和已更新的START为准。它不是代码或模型结果通过的证据，也不把未完成回写写成完成。

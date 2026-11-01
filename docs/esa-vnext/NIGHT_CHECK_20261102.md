# 夜间检查结果：2026-11-02

本轮是用户授权的当前产品模拟检查和有限修复，不开启0.8。应用候选 **0.7.0rc4 / b8291ff7be9fe50b8ee47c4f08bbdb9315365204**。不启动或修改原工作区，不操作用户桌面窗口，不发新的真实模型/embedding请求。

## 实际发现与修复

1. **迟到的重试/选库错误串会话，选库等待也锁住别的会话。** 原来发送/创建的归属保护已存在，但retry/binding的error与pending仍直接读共享mutation状态。A会话请求延迟时切到B，B会看到A错误或选库被禁用。修复将重试目标cid随操作捕获，反馈与等待态按当前会话归属显示。A的响应仍更新A缓存，回A仍能看到原错误，B草稿不丢。
2. **真实工单已读回，顶部仍一直“正在读回”。** 操作提示优先级高于TaskView服务端事实，成功后从未过期。现在存在当前工单时使用服务端next_step；未读回期间仍显示等待，读回失败不会被伪装成功。未改确认、提交、事务、权限或模型输入。
3. **整批浏览器测试被搜索测试的未结单污染。** 新搜索测试创建了一张借用和一张报修，但没有结束自己的测试工单，后续正常路径被EXISTING_TICKET正确阻止。已在finally中通过实际公共生命周期接口撤回/关闭本例自己的工单；保留数据库历史，不清库、不重seed、不删除或放宽原断言。
4. **本机快捷脚本的中文路径编码。** UTF-8批处理在Windows936代码页下无法读取中文路径。只读标记探针原格式exit17，加入脚本内`chcp 65001 >nul`后exit0；当前两个本机快捷入口已指向新候选并加上切换。官方ESA.exe启动逻辑未改。

## 实际检查

| 层次 | 结果 | 说明 |
|---|---|---|
| 当前产品程序回归 | 145通过，2项关闭的解释实验未选取 | 改前执行；本次Python/API/事务源文件未改，不能说重跑全历史套件 |
| 原合并浏览器基线 | 14通过/5失败 | 五项失败是未结测试工单的级联影响，原始记录保留 |
| 新增页面复现 | 修前3失败，修后3通过 | A→B重试错误、选库等待归属、提交提示滞留；真实产品API/临时SQLite，外部模型明确替身 |
| 最终合并浏览器 | 22通过、0跳过/重试/偶然通过 | 包含搜索、分页、手机、预览期限、旧确认、恢复、借用报修及新故障；提交回读测试故意延迟GET，确认等待阶段保留，实际结果到达后再替换提示 |
| TS/Vite | 通过 | 实际TS构建，未手改压缩JS；约508KB chunk警告保留 |
| Windows中文快捷/最终包 | 见WINDOWS_SMOKE.json | 最终EXE、936→UTF8中文路径、启动/实例复用、模型离线可看页面、静态资源逐字节一致、0模型调用、正常停止；不是原生GUI/IME验收 |
| 活动资料与原修改 | 保留 | 原8项dirty文件哈希一致；两个原工作区数据库写入时间均早于本轮开始，用户工单仍RESERVED |

测试脚本首次Windows探针用C# launcher的stdout判断复用失败；实际launcher不转发子进程JSON。改为比较两次真实/api/instance的instance_id和pid，保留首次脚本断言记录。这是测试夹具修正，不是修改产品制造通过。

## 没有宣称修好的问题

用户前次“最长借多久/提交等于分配吗”原始响应已只读核查：模型选中了正确期限与审批原文单元，却把N1标为evidence_insufficient、attribute_matches=false。主机据此交付partial，未发现这条响应在映射时静默删掉必要正文。此为仍在的语义判定不一致；本轮没有通过字面/数字捷径强制升级完整回答，没有新增真实模型实验，不宣称回答质量改善。

原生首次目录选择、自动开页完整GUI和物理IME仍NOT_RUN；更早自由文本漏字段/知识need等限制仍保留。没有同条件main对照，尚未证明追平main。

## 启动与恢复

检查开始时8748与8752都未运行，本轮保持原服务未启动。当前快捷：`.private/esa-vnext/night-check-20261102/打开ESA演示.cmd`；原`.private/esa-vnext/rc4-finish-20261101/打开ESA演示.cmd`也已更新。双击后沿用原DATA_DIR `.private/esa-vnext/upgrade-070-next/live-workspace`，打开实际地址，通常为http://127.0.0.1:8748/。不重新init或清数据。用户已使用的8752副本不清理。

Windows包：`.private/esa-vnext/build/releases/ESA-0.7.0rc4-windows-x64-b8291ff7.zip`。其他机器完整解压后选择自己的工作区。仍为预发布，无正式标签或main合并。

小型证据目录`.private/esa-vnext/night-check-20261102`：START、BASELINE_PRODUCT.xml、BASELINE_BROWSER、RED_UI、TARGET_UI、FINAL_BROWSER、KNOWN_PARTIAL及诊断、SHORTCUT_ENCODING_FINAL、WINDOWS_SMOKE、WORKSPACE_READ_ONLY_CHECK、FREEZE、CHANGE.patch。程序测试、旧原件回放与新真实模型验收分开；本轮真实chat/query/index均0。原始私有记录不推送Git。

本轮至此结束，不后台常驻测试或继续扩题；恢复开发先读唯一STATUS。若继续手动演示，用户借用单仍是已预留待领用，可按原流程登记领用、归还。

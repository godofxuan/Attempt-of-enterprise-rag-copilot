# 本地运行与身份续签

以下命令在PowerShell执行，运行目录是候选版，不是main。它们只绑定127.0.0.1；若端口被占用请改为另一对空闲端口，不要停止其他服务。

```powershell
Set-Location -LiteralPath 'LOCAL_PATH_REDACTED'
.\scripts\local_candidate.ps1 -Action Start -PythonPath 'LOCAL_PATH_REDACTED' -IndexRoot 'LOCAL_PATH_REDACTED' -ApiPort 8012 -UiPort 8512
```

启动后打开`http://127.0.0.1:8512`。脚本会等待API并续签；若启动失败，错误日志位置在`.private/local_candidate/`下本次时间目录。它不会重建或激活索引。

过一段时间提示Bearer无效，执行：

```powershell
.\scripts\local_candidate.ps1 -Action RenewIdentity -PythonPath 'LOCAL_PATH_REDACTED'
```

然后重新提交问题。无需等待token“自己恢复”，不需要重启API；浏览器也不会自动重放上次POST。若probe失败，应检查正在连接的API端口和key快照，不要用`init --force`代替续签。

状态和停止：

```powershell
.\scripts\local_candidate.ps1 -Action Status
.\scripts\local_candidate.ps1 -Action Stop
```

Stop只处理本脚本记录的PID与启动时间匹配的进程。受管工具可能需要进程控制权限，拒绝时不绕过权限边界。

默认：hybrid_default、bge-m3、qwen2.5:3b、task advisor OFF。`-EnableTaskAdvisor`是实验选项，本轮没有收益，因此不推荐日常演示启用。

本轮验证的服务已经停止，避免后台常驻占用资源；上述启动命令会运行当前候选源码。代码未推送GitHub，旧GitHub网址不代表这里的未提交版本。

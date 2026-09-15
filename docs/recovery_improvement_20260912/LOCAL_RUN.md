# 使用新缺项恢复候选版

本说明替代旧 flow_mainline 文档中对 LLM 收益的概括。旧文件作为历史保留，完整诊断见本目录 REPORT.md。

## 运行位置

业务代码改在候选树，不是主目录旧 main，也没有推送 GitHub。以下命令使用已有 Python、已有 Ollama 和已有索引，不会下载新模型。

```powershell
Set-Location -LiteralPath 'D:\文档\agent\RAG_try\.private\release_candidate_20260910'
.\scripts\local_candidate.ps1 -Action Start -PythonPath 'D:\文档\agent\RAG_try\.venv\Scripts\python.exe' -IndexRoot 'D:\文档\agent\RAG_try\data\indexes_v2' -ApiPort 8012 -UiPort 8512 -EnableTaskAdvisor
```

先确认所选端口未被使用。脚本有端口与进程归属检查；不要为腾端口终止未知程序。此轮收尾没有执行上面的 Start，因而不声称已替你启动页面。

`-EnableTaskAdvisor` 现在选择“先检索，缺项时最多一次模型恢复”，不是旧的每问主动规划。省略这个选项就是结构化规则 OFF 对照。默认配置没有偷偷改成 ON。

若 token 过期，使用本地身份续期，不关闭身份验证：

```powershell
.\scripts\local_candidate.ps1 -Action RenewIdentity -PythonPath 'D:\文档\agent\RAG_try\.venv\Scripts\python.exe'
```

## 可以看哪些行为

- 普通已覆盖的问题不会为了显得 agentic 增加恢复调用。
- “月度发漂最迟哪天交？”等已保留的开发案例，可在合法证据中找回所问内容，但标明 partial 和适用性提示。
- task trace 中 `recovery_calls` 最多 1；`model_relevance_used` 说明是否使用了模型建议关联的资料。
- `wire_claim_ids_rebound` 只说明重复的回答标签被主机重编号，不表示来源核验放宽。
- 请求被权限或 Guard 拦截时，不能通过重写再尝试绕过。

实验中的用户显式拥有多组权限以测量各部门资料，不是演示页面默认普通用户。页面身份看不到某部门资料时不应获得实验里的相同答案；这属于权限差异，不能给页面用户追加组来伪装复现。

## 测试与证据

本轮新测试 27/27；扩大套件 1414 passed、2 failed、9 skipped。两项历史证据绑定失败的明细、原始日志和 JUnit 均在审核 ZIP。没有声明整库全绿或公网生产部署。

最后真实模型对照是 44 道开发探针，不是新的 WixQA/FinanceBench 评测。缺项恢复 ON 的要点与引用检查为 34/40，OFF 为 29/40；首轮检索 gold 文档覆盖均已是 100%。请不要把这个数字说成检索 Recall 或人工准确率。

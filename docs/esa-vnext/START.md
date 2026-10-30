# 当前工作台入口

在源码根目录，使用Python3.11/3.12、uv与已运行的本地Ollama：

```powershell
uv sync --locked --no-dev
uv run --no-sync esa init --sample --data-dir .private/esa-vnext
uv run --no-sync esa serve --data-dir .private/esa-vnext --port 8740
uv run --no-sync esa doctor --data-dir .private/esa-vnext
```

已安装环境也可用 `python -m app.cli` 替代 `esa`。浏览器打开
`http://127.0.0.1:8740/`。init 是显式且幂等的操作；serve 不重置数据。
不指定目录时使用 `ESA_DATA_DIR`，否则是用户目录中的 `.esa`。

本版包括知识、资料库、借用和合成IT报修；演示和逐项证据见RELEASE.md。
实测模型为qwen3.5:9b与bge-m3。新目录首次init明确创建TEST数据；serve不seed。
模型断开不会阻止页面启动。模型设置只接受本机 endpoint；不自动下载模型。
当前仅支持本地单用户，不是企业多人共享部署。

## 首次使用与恢复

资料库中点击“导入本地合成示例（由当前业务规则生成）”，或批量上传自己的MD/TXT/PDF/DOCX；点击建立索引后提问并打开来源。
“继续追问”才带入同会话的用户问题，旧答案不当证据。服务任务先明确服务与操作上限，
保存参数再运行；范围确认不等于提交确认。精确确认只针对当前预览。
同一目录已有未结申请时先读取原单。通过本地服务台批准、领用、归还（或撤回待审批申请）后可再次办理；报修可处理、解决、关闭。无需重建数据库绕过未结限制。

重启使用同一serve命令和DATA_DIR，不必重新init。中断运行显示interrupted/待继续，
不会自动重发业务提交。doctor只读检查，不推理、不启动恢复。一个目录只允许一个实例。
已安装项目环境也可用`.venv\Scripts\python.exe -m app.cli`。

## 常见错误

- WORKSPACE_ALREADY_RUNNING：使用原页面，或正常结束原实例。崩溃后操作系统释放锁，不用删锁文件。
- MODEL_UNAVAILABLE：检查Ollama和已有模型名称；不自动下载或替换模型。
- INDEX_OUTDATED：文档更新了，先更新索引；历史答案及原文仍保留。
- INDEX_EMBEDDING_MODEL_CHANGED：当前查询模型与索引模型不同，需要更新该库索引。
- TASK_CHANGED：另一页面修改了参数，比较服务端当前值后重新保存；失败时不丢自己的输入。
- USER_UPDATE_PENDING：检查解释失败的原文和参数，明确范围后恢复，这不代表确认提交。
- EXISTING_TICKET：先读本人原单。在本地服务台按当前状态处理、归还或撤回；续借必须核对新预览。
- SCHEDULE_CONFLICT：当前日期已有真实预留。明确允许改期或改选匹配设备，不会自动扩大日期。
- MODEL_ACTION_REQUIRED / NO_PROGRESS：原任务、参数和工具观察保留；查看最后实际结果后修正输入或继续，不应无目的反复运行。
- PDF无可提取文字：没有OCR，保留解析错误，不用空文本生成答案。
- 历史单问超过500字或追问合并检索超过1000字：请用完整问题开始新话题，不截掉旧条件硬跑。

旧JWT候选、原索引和实验账本保留原位，没有把历史企业身份记录改属local-owner。
旧部署API保留在legacy配置路径；工作台同步/异步知识入口都使用当前共享知识服务。
历史Streamlit和Docker不是本轮默认入口；Linux与双入口容器部署未做本轮验收。

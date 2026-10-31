# 当前工作台入口

## 当前本机演示

当前验证页面：http://127.0.0.1:8748/ ，0.7.0rc2 / `70a50050`。
DATA_DIR 为本轮完整历史TEST副本 `.private/esa-vnext/upgrade-070-next/live-workspace`。
原 `.private/esa-vnext` 和8740旧实例保留，不能把它当成新版。使用发行包 `ESA.exe` 选已存在的完整目录；在别的电脑明确选自己的工作区。

本机可重复启动（先完整解压当前包）：

```powershell
.\ESA.exe --data-dir "你的完整TEST工作区" --port 8748
```

也可在已配置的源码环境用 `esa open --data-dir "你的完整TEST工作区" --port 8748`。
`/api/instance` 与设置展开区显示真实commit/build。原生首次对话框和物理IME仍待验。

## Windows 发行包

完整解压后双击 `ESA.exe`，首次明确选已有工作区或新建，随后自动打开实际地址。用户不安装Python/uv/Node；模型离线也可以进入设置及历史。重复打开复用相同实例，端口冲突自动避让。设置中可停止本地服务。

升级只替换程序目录，继续关联原完整 DATA_DIR。需要重新选择目录时使用 `ESA.exe --choose-workspace`。程序包不含模型、个人资料或业务数据。构建与具体检查边界见 `packaging/windows/README.md`。

同一构建重复打开会复用。新旧构建不同会显示实际版本并询问继续旧版或在空闲时正常切换；忙碌实例拒绝切换。很老的实例缺少版本/忙碌信息时，需用户在原页面正常停止再启动新包，不强杀。不能仅凭打开网页认定版本已更新。当前候选与实际运行实例的区别见STATUS顶部。工作区使用本地SQLite WAL，备份前停服务复制完整目录或使用SQLite backup API；运行时不能只复制app.sqlite3。新增解释实验默认关闭，未达到稳定语义质量门槛。

## 源码入口

在源码根目录，使用Python3.11/3.12、uv与已运行的本地Ollama：

```powershell
uv sync --locked --no-dev
uv run --no-sync esa init --sample --data-dir .private/esa-vnext
uv run --no-sync esa open --data-dir .private/esa-vnext --port 8740
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

资料库中导入由当前业务规则生成的合成示例，或批量上传自己的MD/TXT/PDF/DOCX；自动进入真实索引任务，发布后可提问并打开来源。失败项可以针对性重试。
“继续追问”才带入同会话的用户问题，旧答案不当证据。服务任务先明确服务与操作上限，
保存参数再运行；范围确认不等于提交确认。精确确认只针对当前预览。
同一目录已有未结申请时先读取原单。通过本地服务台批准、领用、归还（或撤回待审批申请）后可再次办理；报修可处理、解决、关闭。无需重建数据库绕过未结限制。

重启使用同一serve命令和DATA_DIR，不必重新init。中断运行显示interrupted/待继续，
不会自动重发业务提交。doctor只读检查，不推理、不启动恢复。一个目录只允许一个实例。
已安装项目环境也可用`.venv\Scripts\python.exe -m app.cli`。

## 常见错误

- WORKSPACE_MISSING：旧登记目录丢失或不完整。选择定位原工作区；不要为了恢复而在旧位置新建空库。
- KNOWLEDGE_BASE_REQUIRED：在原会话右上角明确补选资料库后重试。显示值与服务器绑定一致；普通业务只读不强制选库。
- 历史重试早于后续参数变更：仍保持原事项，以最新参数继续未完读取/准备；旧消息不能回滚新值，需要原修改时发送新的明确消息。

- WORKSPACE_ALREADY_RUNNING：使用原页面，或正常结束原实例。崩溃后操作系统释放锁，不用删锁文件。
- MODEL_UNAVAILABLE：检查Ollama和已有模型名称；不自动下载或替换模型。
- 更新处理中/失败：可继续查询已发布代次，尚未发布的新资料不加入答案；主动停用立即排除。首次无成功代次时需完成索引，不能伪装有可用知识。
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

部分交付：详情保留当前预览，点击“重试解释”只补缺项；若期间改过参数，需要重新生成当前预览。保存参数/选设备可直接生成预览；普通继续仍由模型选择工具。范围确认和当前精确提交确认是两个不同动作。STORAGE_BUSY表示当前数据库繁忙，保留输入后再试；不会自动重发业务提交。

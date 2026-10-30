# Enterprise RAG / Service Agent

本地单用户知识与服务工作台：一个 Python / FastAPI 应用、一处数据目录。
独立 RAG 与 Service Agent 共用检索、模型和来源发布能力。用户明确服务与操作上限，模型根据真实工具观察选择下一步；普通代码负责字段校验、当前预览、精确确认和事务。

## 安装与启动

需要 Python 3.11/3.12、uv，以及本机已运行的 Ollama 和已安装模型。当前验证使用 `qwen3.5:9b`、`bge-m3`，不自动下载或更换模型。

```powershell
uv sync --locked --no-dev
uv run --no-sync esa init --sample --data-dir .private/esa-vnext
uv run --no-sync esa serve --data-dir .private/esa-vnext --port 8740
uv run --no-sync esa doctor --data-dir .private/esa-vnext
```

打开 http://127.0.0.1:8740/ 。已有环境可用 `python -m app.cli` 替代 `esa`。
首次 init 显式创建本地合成 TEST 数据。再次启动使用同一 serve 命令，**不重置数据库**。默认目录由 `ESA_DATA_DIR` 指定，否则为用户目录的 `.esa`。

## 日常使用

1. 设置里选择已安装的聊天/嵌入模型，确认连接。
2. 资料库创建集合，批量上传 MD/TXT/PDF/DOCX 或导入合成规则示例，建立索引。
3. 知识入口选 Fast 普通问答或 Deep 分题搜索和锚定阅读；引用可查看原版本和真实页/段。旧索引没有的新定位不会伪装成原页码。
4. 会话里提问、解释、补充字段或混合改期。开始服务事项时明确只读、仅预览或确认后提交。
5. 选择真实设备，核对当前参数及预览；改期使旧确认失效。提交仅生成待审批借用或待受理报修。

模型使用 Ollama 原生工具调用；页面展示工具名和实际观察，不展示伪造的思考过程。关闭/停用文档后须更新索引；原答案与原版本保留。无文本 PDF 不具备 OCR。

## 数据与恢复

`workspace.json` 保存配置；`app.sqlite3` 保存会话、工单、确认、幂等命令、模型调用和进展；`documents/`、`indexes/`、`cache/` 保存原文、索引和计算缓存。备份需包含整个 DATA_DIR。不要提交数据库、原始调用、私有资料、模型或大索引到 Git。

同一目录只开一个实例。停止本次运行不会撤回已经提交的工单；刷新/重启读取保存状态，不自动重发提交。跨页面并发编辑仅支持现有 revision 冲突检查，不能冒充企业多用户系统。

## 状态与限制

当前升级的逐阶段运行和失败见 [STATUS](docs/esa-vnext/STATUS.md)，启动/错误处理见 [START](docs/esa-vnext/START.md)。源码功能、程序测试和真实模型结果分别登记，不用 COMPLETED 代替内容和数据库验收。
自由文本 auto 为历史实验路径。尚未证明追平 main；Docker/Streamlit 不是当前默认工作台启动方式，Linux/容器化本轮未验证。

[原 README 与用户既有修改](docs/history/README_PRE_030.md)保留为历史说明，不能作为当前入口指引。实际实现问题及面试口述线索见 [实施记录](docs/esa-vnext/IMPLEMENTATION_INTERVIEW_NOTES.md)。

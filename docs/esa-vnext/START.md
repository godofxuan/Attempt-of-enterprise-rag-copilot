# 当前工作台入口

在仓库根目录（Python 3.11 或 3.12）：

```powershell
uv sync --locked --no-dev
uv run --no-sync esa init --sample --data-dir .private/esa-vnext
uv run --no-sync esa serve --data-dir .private/esa-vnext --port 8740
uv run --no-sync esa doctor --data-dir .private/esa-vnext
```

已安装环境也可用 `python -m app.cli` 替代 `esa`。浏览器打开
`http://127.0.0.1:8740/`。init 是显式且幂等的操作；serve 不重置数据。
不指定目录时使用 `ESA_DATA_DIR`，否则是用户目录中的 `.esa`。

资料导入、索引代次、问答历史、共享知识工具和电脑借用生命周期已接通；
真实双入口知识回答及一条模型/UI借用闭环已有证据。R1仍需完成余下旅程和最终演示整理；
R2报修尚未实施，不能宣称整个Goal完成。
模型断开不会阻止页面启动。模型设置只接受本机 endpoint；不自动下载模型。
当前仅支持本地单用户，不是企业多人共享部署。

2026-10-30 已在现有 Windows/Python 3.11 环境安装 editable console entry；
锁文件离线一致性检查通过。M6已从提交导出的独立源码目录按锁安装64个依赖，
在其独立虚拟环境中验证页面、任务与资料API启动，无模型调用、无外层证据依赖。
后续代码仍需相应复验，不能自动继承早期检查。

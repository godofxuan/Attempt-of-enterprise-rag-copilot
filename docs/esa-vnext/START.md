# 当前工作台入口

在仓库根目录（Python 3.11 或 3.12）：

```powershell
uv sync --locked
uv run esa init --sample --data-dir .private/esa
uv run esa serve --data-dir .private/esa --port 8740
uv run esa doctor --data-dir .private/esa
```

已安装环境也可用 `python -m app.cli` 替代 `esa`。浏览器打开
`http://127.0.0.1:8740/`。init 是显式且幂等的操作；serve 不重置数据。
不指定目录时使用 `ESA_DATA_DIR`，否则是用户目录中的 `.esa`。

当前 M1 只证明启动、设置、连接状态和固定存储位置；资料与任务接线仍在实施。
模型断开不会阻止页面启动。模型设置只接受本机 endpoint；不自动下载模型。
当前仅支持本地单用户，不是企业多人共享部署。

2026-10-30 已在现有 Windows/Python 3.11 环境安装 editable console entry；
锁文件离线一致性检查通过。全新环境按锁安装尚待 M6 独立验证。

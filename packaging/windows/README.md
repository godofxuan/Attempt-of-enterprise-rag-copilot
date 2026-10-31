# Windows x64 构建与使用

用户完整解压发行目录后双击 `ESA.exe`。不要单独移动 EXE；旁边的 `runtime/` 是官方 CPython 3.12.10 embeddable 和锁定依赖，不是作者虚拟环境。首次原生对话框可明确选择已有工作区；已有注册记录则直接打开。需要重新选择时运行 `ESA.exe --choose-workspace`。

启动器只识别相同工作区、应用 ID 和实例随机标识的服务。重复打开复用实例；默认端口被其他程序占用时绑定空闲端口。不杀旧服务或其他进程。模型离线时仍可读历史和设置。失败日志位于 `<DATA_DIR>/logs/launcher.log`。

构建机需要 Python3.11/3.12、uv、Node/npm 和 Windows .NET Framework C# 编译器。将待发行源码提交到本地 feature 分支。

一个构建命令从指定commit准备官方 Windows Python3.12.10 embeddable、按uv.lock哈希安装依赖、执行npm ci/build、构建wheel及薄启动器。缓存用于加速，不要求预先手动准备runtime，也不依赖作者.venv目录结构。运行时不安装依赖、不下载模型。

```powershell
python scripts/build_windows_portable.py --ref HEAD --output-dir <发行输出目录>
# 纯离线重建（工具与包缓存已经准备好）
python scripts/build_windows_portable.py --ref HEAD --offline --embed-zip <官方CPython嵌入式ZIP> --uv <uv可执行文件> --npm <npm可执行文件>
```

脚本只从指定 commit 导出产品，构建 wheel、安装到私有运行时、编译薄 C# 启动器并生成 ZIP。产物包含 `release.json` 的 commit/版本；不含数据库、私有资料、模型和索引。不得将个人 `.venv` 替代运行时目录。新工作区可在设置显式启用 TEST 数据和导入示例；升级使用原完整 DATA_DIR。

实际安装检查应记录：Windows/运行时版本、中文空格路径、无系统 Python/uv/Node 的 PATH、端口冲突、重复打开、模型离线和完整工作区升级。命令启动、原生 GUI 与浏览器各自登记，不能互相代替。

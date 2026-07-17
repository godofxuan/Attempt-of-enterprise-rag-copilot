# Reproducibility Guide

最后更新：2026-07-17

## 1. 两类可复现性

本项目不把所有测试混成一个“能不能跑”：

| 类型 | 依赖 | 用途 | CI |
|---|---|---|---|
| deterministic | checked-in fixtures、stable hash embedding、extractive/fake model、Python 3.11 | schema、ACL、Agent 状态机、评估器、artifact contract | 必须运行 |
| live local | Ollama、bge-m3、qwen2.5:3b、active FAISS index、本机硬件 | 真实模型行为、延迟、并发、内存 | 不在 CI 运行 |

deterministic 通过不等于真实模型质量好；live 本机一次通过也不等于任意机器稳定。二者解决不同问题。

## 2. 已验证环境

```text
OS                         Windows
Python                     3.11
FastAPI                    0.136.0
Uvicorn                    0.44.0
Pydantic                   2.13.2
requests                   2.33.1
faiss-cpu                  1.13.2
numpy                      2.4.4
pytest                     9.0.3
embedding                  bge-m3, 1024 dimensions
chat                       qwen2.5:3b
active index               20260716T135632Z_7aec4b9_live_bge_m3_fixed
indexed chunks             64
Historical run base HEAD   7aec4b950e012d3f24b8e1877d6391201e9b8f90
```

`requirements.txt` 精确固定 15 个直接依赖。它比无版本 requirements 稳定，但不是带 transitive wheel hash 的完整 lockfile。更严格供应链控制留给后续阶段。

## 3. 新环境安装

PowerShell：

```powershell
cd <repo-root>
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

不要先无条件升级所有包再比较结果；那会改变实验条件。需要升级时应新建依赖变更，跑完整回归并记录版本差异。

## 4. Deterministic 门禁

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_repository_config.py -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app scripts streamlit_app tests
.\.venv\Scripts\python.exe -m pytest -q
```

阶段全量测试记录：

```text
E5 stage entry    526 passed, 3 warnings
E6 final          569 passed, 3 warnings
E7 final local    573 passed, 3 warnings
```

E7 比 E6 增加 trace idempotency、两个反向 conflict-priority 案例和全 Markdown 绝对路径审计。3 条 warning 均来自 FAISS SWIG deprecation；完整全量测试不依赖正在运行的 Ollama。

pytest 使用 `--import-mode=importlib`，避免不同目录同名 `test_metrics.py` 被当成同一个顶层模块。旧的 repository-shared `--basetemp=data/eval_outputs/pytest_tmp` 已移除，因此并行 pytest 不再互删同一目录。

## 5. Frozen test hash

冻结测试文件：

```text
data/v2/eval/test.json
data/v2/eval/test_manifest.sha256
```

期望 SHA256：

```text
556ffed812cdde0ba7ddc7d625782b3b3bbdbcd4753670a199bd0c3c05743338
```

验证：

```powershell
.\.venv\Scripts\python.exe -c "from pathlib import Path; from scripts.eval_enterprise_v2 import verify_frozen_test_hash; print(verify_frozen_test_hash(Path('data/v2/eval')))"
```

CI 只校验 hash 和 deterministic suite，不用 frozen test 继续调参。

## 6. GitHub Actions

`.github/workflows/ci.yml`：

1. `actions/checkout@v6`；
2. `actions/setup-python@v6`，固定 Python 3.11、pip cache；
3. 安装精确直接依赖；
4. `pip check`；
5. `compileall`；
6. frozen hash；
7. full pytest。

workflow 权限只有 `contents: read`，没有 secrets、Ollama service、live evaluator、uvicorn 或 load profile。GitHub 官方文档建议用 setup-python 明确 Python 版本，以避免 runner 默认版本变化：[Building and testing Python](https://docs.github.com/en/actions/how-tos/use-cases-and-examples/building-and-testing/building-and-testing-python)。当前 action 主版本依据官方仓库示例：[checkout](https://github.com/actions/checkout)、[setup-python](https://github.com/actions/setup-python)。

本地 E7 CI-equivalent gate 退出 0 不等于 GitHub Actions 已运行。远端状态只有在功能分支推送后取得与 commit SHA 对应的 run URL 才能从 `NOT RUN` 改为 `PASS` 或 `FAIL`。

## 7. Live 前置检查

模型：

```powershell
ollama list
```

至少需要：

```text
bge-m3
qwen2.5:3b
```

active index：

```powershell
Test-Path data\indexes_v2\ACTIVE.json
.\.venv\Scripts\python.exe -c "from app.config import get_settings; from app.retrieval.snapshot import V2IndexSnapshot; s=V2IndexSnapshot.load(get_settings().v2_indexes_dir); print(s.version.manifest.run_id, len(s.chunks), s.version.manifest.embedding)"
```

如果 active index 不存在或 embedding model/dimension 不匹配，先按 E2 的 `scripts.build_indexes_v2` 流程重建；不要让 live evaluator 静默回退 stable hash。

## 8. 启动服务

开发调试可以：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

负载证据不要使用 reload：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

FastAPI 官方推荐用 lifespan 管理共享资源的启动和清理；本项目在 lifespan 中创建目录并启动/关闭 readiness resources，而不是 import 时做 IO。参考：[FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)。

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

`live=200` 只说明进程能响应；只有 `ready=200` 才说明 database/index/models 三项均可用。

## 9. Live smoke

```powershell
$body = @{
  question = '当前制度每周最多允许远程办公几天？'
  user_context = @{
    user_id = 'smoke-user'
    tenant_id = 'starbridge-cn'
    region = 'cn'
    groups = @('all_employees')
    roles = @()
  }
  top_k = 5
} | ConvertTo-Json -Depth 6

$response = Invoke-WebRequest `
  -Method Post `
  -Uri http://127.0.0.1:8000/agent/v2/chat `
  -ContentType 'application/json; charset=utf-8' `
  -Body $body

$data = $response.Content | ConvertFrom-Json
$response.Headers['X-Request-ID']
$data.trace.request_id
```

两个 ID 必须一致。第一次 Ollama cold load 可能触发 5 秒 search tool timeout；应记录为 source-free `system`，再检查 trace，不要隐藏失败。

## 10. Live load

每个 run ID 不可覆盖：

```powershell
$RUN_ID = '20260716T165304Z_7aec4b9_demo_load_r2'
.\.venv\Scripts\python.exe -m scripts.load_profile `
  --base-url http://127.0.0.1:8000 `
  --profile demo `
  --concurrency 1,5,10 `
  --requests-per-level 10 `
  --run-id $RUN_ID `
  --timeout-seconds 30
```

产物默认在 `load_runs/<run-id>`，该根目录被 `.gitignore` 忽略。运行结束后必须停止自己启动的 uvicorn，不要停止用户已有的 Ollama。

E7 在 trace 幂等性修复后的 final-code authority 为：

```text
run ID                 20260717_e7_demo_load_rc02
requests               31/31, failed 0
warm p95 c=1/5/10      1.115 / 4.244 / 8.218 seconds
model calls/retries     62 / 0
manifest SHA-256        db08c920834261b1e1766e288efdd5f87d45eacb1a5070cc10464c14b08bfe4f
```

这些是单台 Windows、单进程、64 chunks、每档 10 个 warm requests 的小样本值；不得写成生产 SLO、吞吐上限或跨硬件 benchmark。

checked-in `data/v2/public/demo_snapshot.json` 是较早的 E4/E5 离线演示批次，保留 load r2 的 1.136/4.406/8.633 秒及其 source hashes。它和 E7 final-code rc02 是两个明确批次，不能把旧 snapshot 当作 E7 rc02 provenance。

## 11. Artifact hash 验证

```powershell
$dir = 'load_runs\20260716T165304Z_7aec4b9_demo_load_r2'
$manifest = Get-Content "$dir\manifest.json" -Raw -Encoding utf8 | ConvertFrom-Json
foreach ($name in @('summary.json', 'details.csv')) {
  $actual = (Get-FileHash "$dir\$name" -Algorithm SHA256).Hash.ToLowerInvariant()
  $expected = $manifest.artifacts.$name.sha256
  [pscustomobject]@{ file = $name; match = ($actual -eq $expected) }
}
```

不要编辑已经发布的 artifact。代码或环境修复后使用新 run ID，并在文档中说明旧 run 为什么保留。

## 12. Windows 已知问题

### Ollama 路径/模型

若 `/api/embed` 报模型 blob path 错误，先核对 `OLLAMA_MODELS=<ollama-model-dir>`、服务实际环境和 `ollama list`。复制文件不等于服务已加载新目录，需确认 Ollama 进程环境。

### localhost IPv4/IPv6

本项目 live 命令固定 `127.0.0.1`，减少 `localhost` 先解析 IPv6、服务只监听 IPv4时的等待歧义。

### pytest TEMP ACL

E5 移除 shared basetemp 后，本机遗留 `%TEMP%\pytest-of-xuan` 曾关闭 ACL 继承，造成所有 `tmp_path` setup WinError 5。确认路径确实位于用户 TEMP 后恢复继承，full suite 恢复。不要把这种本机 ACL 修复放进 CI 或业务代码。

## 13. 结果复述边界

可以说：在记录的 Windows/Ollama/index 条件下，31 请求 local profile 全部业务完成，并测得 concurrency 1/5/10 的 p50/p95、model calls 和 RSS；deterministic CI 不依赖 Ollama。

不可以说：这些数字是跨硬件 benchmark、生产吞吐、SLA、容量上限，或 31/31 证明回答 factuality。负载 profile 测的是服务行为和延迟，不替代 E4 的质量评估与人工抽检。

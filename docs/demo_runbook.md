# Demo Runbook

## R2-S5 identity setup (run before the historical steps below)

All commands run from the repository root. The generated files are ignored by
Git and remain under `.private/identity`.

```powershell
# Create a fresh 15-minute persona bundle, operator credential, HMAC key,
# private signing key, and public JWKS snapshot.
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity init --force

# Confirm only non-secret keyring metadata is printed.
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity status

# Start only the secure application on numeric loopback.
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Start Streamlit in another terminal. It reads the ignored persona bundle for
Ask/Feedback and the separate operator token for Trace. It never loads the
private signing key.

```powershell
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py `
  --server.address 127.0.0.1 --server.port 8501
```

For the load profile, configure two file-backed credentials. The script
rejects missing, duplicate, or ambiguous raw-token/file sources, disables
environment proxies, refuses redirects, and writes no token to artifacts.

```powershell
$env:RAG_BEARER_TOKEN_FILE = '.private\identity\load_user_token.txt'
$env:RAG_OPERATOR_BEARER_TOKEN_FILE = '.private\identity\operator_token.txt'
.\.venv\Scripts\python.exe -m scripts.load_profile `
  --base-url http://127.0.0.1:8000 --profile demo
```

Rotation is a staged handoff because the API loads an immutable JWKS snapshot:

```powershell
# Stage a pending public key. Existing persona/operator tokens remain unchanged.
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity rotate

# Restart the API so its immutable snapshot contains old + pending public keys.
# Read pending_kid from the rotate/status JSON, then prove that snapshot before
# publishing any new client token.
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity activate `
  --kid <pending-kid> --api-base-url http://127.0.0.1:8000

# Read retire_not_before from status. Normal retirement fails before that epoch.
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity status
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity retire --kid <old-kid>
# Restart once more and run valid/new plus invalid/retired token smoke tests.
```

After `rotate`, `pending_kid` is non-null and `restart_required=true`; the old
API and old token files continue working. `activate` refuses to change token
files unless `/identity/me` accepts a short pending-key probe and returns the
same `key_id`. A successful activation clears `pending_kid` and does not need
another immediate restart because the restarted snapshot already contains both
keys. Never delete a journal or manifest manually; run `status` so bounded
recovery can finish.

Activation persists a conservative old-key window: the maximum permitted
900-second demo-token lifetime plus the maximum allowed verifier clock skew
(120 seconds). It intentionally does not use the current 30-second default,
because the API setting may be raised after activation. Do not estimate it from
when the shell command started; use `status.retirement_not_before`. A
compromised old key can be revoked early only with the explicit, audited
break-glass form:

```powershell
.\.venv\Scripts\python.exe -m scripts.manage_demo_identity retire `
  --kid <old-kid> `
  --emergency-revoke `
  --confirm-emergency-revoke RETIRE_ACTIVE_TOKENS_NOW
```

This records the emergency retirement and removes the old key from the next
API snapshot. The currently running immutable verifier can still accept that
key, so restart the API before treating still-live old tokens as invalid.
`status.emergency_revocation_count` is incremented for audit.

The production module no longer exports `create_compatibility_app`; legacy
`/ingest`, `/chat`, and `/agent/chat` cannot be restored by a deployment flag
or wrapper. Historical comparisons run below the HTTP layer and are not a
rollback path.

最后更新：2026-07-23

用途：从一个新 PowerShell 终端准备并演示当前 R1 Enterprise Agentic RAG。所有命令都从仓库根目录运行。服务使用前台进程，演示后明确停止；不要使用 `--reload` 做性能或截图验收。

## 1. Prerequisites

- Windows PowerShell 5.1+；
- Python 3.11；
- Ollama 正在本机运行；
- 可容纳 BGE-M3 与 Qwen 2.5 3B 的本机内存；
- 仓库 checkout；
- 端口 8000 与 8501 可用。

当前 live profile 使用：

```text
embedding  bge-m3
chat       qwen2.5:3b
```

`qwen3:8b` 是 legacy evidence assessor 配置，V2 controller/evidence ledger 不依赖它做主控制决策。

## 2. One-time environment setup

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
Copy-Item .env.example .env
```

`.env` 被 Git 忽略。保留 `LLM_BASE_URL=http://127.0.0.1:11434/v1`，避免某些 Windows 环境把 `localhost` 优先解析为未监听的 IPv6 loopback。

准备模型：

```powershell
ollama pull bge-m3
ollama pull qwen2.5:3b
ollama list
```

`ollama list` 只证明模型存在，不证明模型可加载；readiness 会实际做模型依赖检查。

## 3. Generate the current synthetic corpus

先执行知识覆盖门禁和无写入验证：

```powershell
.\.venv\Scripts\python.exe -m scripts.eval_corpus_quality --profile expanded
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded --dry-run
```

发布当前 240-document expanded profile：

```powershell
.\.venv\Scripts\python.exe -m scripts.generate_enterprise_corpus --profile expanded --output-dir data\v2\generated\expanded
```

目标存在时生成器默认拒绝覆盖。只有目录带本生成器有效 manifest 且明确要重建时才使用 `--force`；不要手工删除未知目录来绕过 provenance 检查。

历史 72-document `demo` profile 仍可用于兼容回归，但不再是默认知识库。

## 4. Build and activate the V2 index

创建 UTC run ID。`Get-Date -AsUTC` 在部分 Windows PowerShell 版本不可用，通用 fallback 是 `(Get-Date).ToUniversalTime()`：

```powershell
$utc = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$runId = "${utc}_local_expanded"
```

先 dry-run parser/governance/chunking：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --input-dir data\v2\generated\expanded --profile expanded --chunker fixed --dry-run
```

再调用真实 BGE-M3 构建并激活：

```powershell
.\.venv\Scripts\python.exe -m scripts.build_indexes_v2 --input-dir data\v2\generated\expanded --output-dir data\indexes_v2 --profile expanded --run-id $runId --chunker fixed
```

构建器写 staging、验证 artifact/hash/维度后再 promote；active pointer 只指向完整版本。不要在模型或维度变化后继续使用旧 active index。

## 5. Deterministic preflight

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m compileall -q app scripts streamlit_app tests
```

Deterministic tests 不需要启动 FastAPI，也不证明真实 Ollama 输出质量。它们先排除 schema、状态机、ACL、artifact 和 UI contract 回归。

## 6. Start the API in terminal A

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另开终端检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

解释：

- `/health/live` 200：进程能响应；
- `/health/ready` 200：database/index/models 全部可用；
- live 200 + ready 503：进程活着，但至少一个依赖未就绪。这不是矛盾；先读 `checks`，不要盲目重启所有组件。

性能、load 与截图验收不使用 `--reload`，因为 reload supervisor 会增加额外进程并污染 PID、内存和延迟证据。

## 7. Start Streamlit in terminal B

```powershell
$env:RAG_API_BASE_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run streamlit_app/ui.py --server.address 127.0.0.1 --server.port 8501
```

打开 `http://127.0.0.1:8501`。页面首屏离线可渲染；只有点击 Check service、Run Agent、Fetch 或 Feedback 才调用 API。

## 8. Demo sequence

推荐按业务复杂度演示：

| Order | Scenario | Expected mode | What to inspect |
|---:|---|---|---|
| 1 | Single policy lookup | answered | visible source、claim citation、request ID |
| 2 | Cross-policy comparison | answered | separate searches、2 required aspects、2 sources |
| 3 | Current-version conflict | answered | active/authority selection，retired value not used |
| 4 | Multi-condition completeness | answered | ledger required=2、supported=2 |
| 5 | Grounded not found | not_found | source-free terminal response |
| 6 | ACL permission boundary | permission | forbidden doc/source absent |
| 7 | Direct instruction override | unsafe | zero retrieval tool calls、source-free refusal |

Ask 完成后切到 Trace：核对 request ID、intent、stop reason、evidence coverage、action sequence、budget、model calls 和 spans。再切到 Evaluation：核对 frozen `28/28`、live `23/24`、load `31/31`，以及两个 `NOT RUN`。

第 7 项是 direct user prompt injection，不是 document/indirect injection。当前 retrieved-content injection 没有 fixture，不能用这条案例冒充已经验证。

## 9. Direct API smoke request

```powershell
$userToken = (Get-Content .private\identity\load_user_token.txt -Raw).Trim()
$headers = @{
  Authorization = "Bearer $userToken"
  "X-Request-ID" = "demo.smoke-001"
}
$body = @{
  question = "当前远程办公需要提前多久申请？"
  top_k = 5
} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8000/agent/v2/chat -Method Post `
  -ContentType "application/json" -Headers $headers -Body $body
```

响应 header `X-Request-ID` 应与 body `trace.request_id` 相同。

## 10. Failure recovery

### Ready check reports models error

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
ollama list
```

若 `/api/embed` 返回 model load 500，先读 Ollama error。模型目录迁移后必须保证 Ollama 当前进程使用的新目录可读；复制 blob 不等于进程已切换。必要时停止并重新启动 Ollama，再单独验证 embedding 请求，不能靠无限重试掩盖加载失败。

### Request appears stuck after jieba initialization

Jieba 的 prefix/cache 日志只表示 BM25 tokenizer 初始化完成。后续可能正在做 embedding 或 generation。先检查 API/Ollama 请求与进程，而不是删除 jieba cache。配置使用 `127.0.0.1` 可避免 `localhost` 解析到 IPv6 `::1`、而 Ollama 只监听 IPv4 时产生的连接等待。

### Ready check reports index error

确认 `data/indexes_v2/active.json` 指向存在且完整的 version；重新运行 index build 或用 `--activate-existing <run-id>` 激活已验证版本。不要手工编辑 pointer 或 FAISS artifact。

### Trace returns 404

Service trace 是有界内存 buffer。进程重启、buffer 淘汰或错误 request ID 都会返回 safe `trace_not_found`。Agent trace 仍随回答保存在当前 Streamlit session；长期追踪属于 R2。

## 11. Stop and verify cleanup

首选在 terminal B、terminal A 分别按 `Ctrl+C`，等待各自返回 PowerShell prompt。不要停止 Ollama，除非本次演示由你临时启动且你明确需要关闭它。

核对监听端口：

```powershell
Get-NetTCPConnection -LocalPort 8000,8501 -State Listen -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess
```

如果曾经把服务放到后台，只停止你在启动时记录并核对 command line 的 PID：

```powershell
Get-CimInstance Win32_Process -Filter "ProcessId = <recorded-pid>" | Select-Object ProcessId,Name,CommandLine
Stop-Process -Id <recorded-pid>
```

不要使用按 `python` 名称批量停止的命令；它可能终止 Ollama helper、IDE、测试或其他项目。

## 12. Evidence and boundaries

- Raw eval/load runs 默认不可覆盖且被 Git 忽略。
- Public Evaluation 页读取 [sanitized snapshot](../data/v2/public/demo_snapshot.json)。
- Screenshot 规范见 [assets README](assets/README.md)。
- E7 已按仓库所有者授权推送 `codex/rag-eval-system` 并取得远端 CI 证据；本 runbook 不自动 push、merge、tag 或修改默认分支。

param(
    [ValidateSet('Start', 'Status', 'Stop')][string]$Action = 'Status',
    [string]$PythonPath,
    [string]$IndexRoot,
    [switch]$RefreshDemoIdentity,
    [ValidateRange(1024, 65535)][int]$ApiPort = 8000,
    [ValidateRange(1024, 65535)][int]$UiPort = 8501
)
$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$StateRoot = Join-Path $Root '.private/local_candidate'
$StatePath = Join-Path $StateRoot 'processes.json'

function Get-OwnedProcess($Record) {
    $Process = Get-Process -Id $Record.pid -ErrorAction SilentlyContinue
    if ($Process -and $Process.StartTime.ToUniversalTime().Ticks -eq ([datetime]$Record.started).ToUniversalTime().Ticks) {
        return $Process
    }
    return $null
}

if ($Action -ne 'Start') {
    if (-not (Test-Path -LiteralPath $StatePath)) { Write-Output 'No local candidate process record.'; exit 0 }
    $State = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    foreach ($Record in $State.processes) {
        $Process = Get-OwnedProcess $Record
        if ($Action -eq 'Stop' -and $Process) {
            & taskkill.exe /PID $Process.Id /T /F | Out-Null
            if ($LASTEXITCODE -ne 0) { throw 'Could not stop the recorded candidate process tree.' }
        }
        [pscustomobject]@{ name=$Record.name; pid=$Record.pid; running=[bool]$Process; action=$Action }
    }
    exit 0
}
if (Test-Path -LiteralPath $StatePath) {
    $Previous = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
    if (@($Previous.processes | Where-Object { Get-OwnedProcess $_ }).Count -gt 0) {
        throw 'Candidate is already running. Use Status or Stop first.'
    }
}
if (-not $PythonPath -or -not $IndexRoot) { throw 'Start requires -PythonPath and -IndexRoot.' }
$Python = (Resolve-Path -LiteralPath $PythonPath).Path
$Index = (Resolve-Path -LiteralPath $IndexRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $Index 'active.json'))) { throw 'Index requires an existing active.json.' }
if ($ApiPort -eq $UiPort) { throw 'API and UI ports must differ.' }
foreach ($Port in @($ApiPort, $UiPort)) {
    $Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
    try { $Listener.Start() } finally { $Listener.Stop() }
}
New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
$Run = Join-Path $StateRoot (Get-Date -Format 'yyyyMMddTHHmmssfff')
New-Item -ItemType Directory -Path $Run | Out-Null
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = 'false'
$env:TEMP = Join-Path $StateRoot 'tmp'
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
$env:DATA_DIR = Join-Path $StateRoot 'data'
$env:V2_INDEXES_DIR = $Index
$env:LIFECYCLE_PRIVATE_ROOT = Join-Path $StateRoot 'lifecycle'
$env:RUNTIME_CACHE_DIR = Join-Path $StateRoot 'cache'
$env:LLM_BASE_URL = 'http://127.0.0.1:11434/v1'
$env:V2_RETRIEVAL_PROFILE = 'hybrid_default'
$env:CHAT_MODEL = 'qwen2.5:3b'
$env:EVIDENCE_MODEL = 'qwen3:8b'
$env:EMBEDDING_MODEL = 'bge-m3'
$Identity = Join-Path $Root '.private/identity'
$env:IDENTITY_JWKS_PATH = Join-Path $Identity 'jwks.json'
$env:IDENTITY_FEEDBACK_HMAC_KEY_PATH = Join-Path $Identity 'feedback_actor_hmac.key'
$env:RAG_API_BASE_URL = "http://127.0.0.1:$ApiPort"
Push-Location $Root
try {
    if ($RefreshDemoIdentity -or -not (Test-Path -LiteralPath $env:IDENTITY_JWKS_PATH)) {
        $IdentityArgs = @('-m','scripts.manage_demo_identity','--directory',$Identity,'init')
        if ($RefreshDemoIdentity) { $IdentityArgs += '--force' }
        & $Python @IdentityArgs
        if ($LASTEXITCODE -ne 0) { throw 'Identity initialization failed.' }
    }
    $Api = Start-Process -FilePath $Python -WindowStyle Hidden -PassThru -WorkingDirectory $Root `
        -ArgumentList @('-m','uvicorn','app.serving:create_app','--factory','--host','127.0.0.1','--port',"$ApiPort",'--workers','1') `
        -RedirectStandardOutput (Join-Path $Run 'api.out.log') -RedirectStandardError (Join-Path $Run 'api.err.log')
    try {
        $Ui = Start-Process -FilePath $Python -WindowStyle Hidden -PassThru -WorkingDirectory $Root `
            -ArgumentList @('-m','streamlit','run','streamlit_app/ui.py','--server.address','127.0.0.1','--server.port',"$UiPort",'--server.headless','true','--browser.gatherUsageStats','false') `
            -RedirectStandardOutput (Join-Path $Run 'ui.out.log') -RedirectStandardError (Join-Path $Run 'ui.err.log')
    } catch {
        & taskkill.exe /PID $Api.Id /T /F | Out-Null
        throw
    }
    $State = [ordered]@{
        scope='LOCAL_LOOPBACK_ONLY'; root=$Root; index_root=$Index; logs=$Run;
        api_url="http://127.0.0.1:$ApiPort"; ui_url="http://127.0.0.1:$UiPort";
        processes=@(
            @{name='api';pid=$Api.Id;started=$Api.StartTime.ToUniversalTime().ToString('o')},
            @{name='ui';pid=$Ui.Id;started=$Ui.StartTime.ToUniversalTime().ToString('o')}
        )
    }
    $State | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $StatePath -Encoding UTF8
    $State | ConvertTo-Json -Depth 5
} finally { Pop-Location }

[CmdletBinding()]
param(
    [switch]$Online,
    [ValidateRange(60, 1800)]
    [int]$BackendTimeoutSeconds = 900
)

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '未找到项目虚拟环境。请先运行 .\初始化项目环境.ps1。'
}
$pythonVersion = & $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $pythonVersion.Trim() -ne '3.13') {
    throw "项目要求Python 3.13，当前虚拟环境为Python $pythonVersion。请重新运行 .\初始化项目环境.ps1。"
}
& $pythonPath -c "import fastapi, uvicorn, yaml"
if ($LASTEXITCODE -ne 0) {
    throw '项目运行依赖不完整。请先运行 .\初始化项目环境.ps1。'
}
$env:PYTHONPATH = Join-Path $projectDirectory 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:ELECTRICAL_TOOLS_OFFLINE_UNUSED_KEY = ''
$configuration = if ($Online) { 'configs/settings.example.yaml' } else { 'configs/settings.offline.yaml' }
if ($Online -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $envFile = Join-Path $projectDirectory '.env'
    if (Test-Path -LiteralPath $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            if ($line -match '^\s*DEEPSEEK_API_KEY\s*=\s*(.+?)\s*$') {
                $env:DEEPSEEK_API_KEY = $Matches[1].Trim()
                break
            }
        }
    }
}
if ($Online -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','Machine')
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
    }
}
if ($Online -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw '在线模式需要在项目根目录.env、当前进程、用户变量或系统变量中配置DEEPSEEK_API_KEY。'
}
Write-Output ('[启动] Python环境检查通过：' + $pythonVersion.Trim())
foreach ($port in @(8000,5500)) {
    $probe = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $probe.BeginConnect('127.0.0.1',$port,$null,$null)
        if ($pending.AsyncWaitHandle.WaitOne(300) -and $probe.Connected) { throw "端口${port}已占用，请先关闭自己此前启动的实验服务。" }
    } finally { $probe.Dispose() }
}
if ($Online) {
    Write-Output '[启动] 正在检查DeepSeek接口连通性'
    & $pythonPath -m standard_knowledge_service_v2.decomposition.check_remote --config (Join-Path $projectDirectory $configuration)
    if ($LASTEXITCODE -ne 0) {
        throw '在线接口预检查未通过，未启动新的服务。网络权限拒绝时，请从有外网权限的PowerShell启动，不要关闭防火墙或绕过安全限制。'
    }
}
$logDirectory = Join-Path $projectDirectory 'artifacts\local_demo'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$pythonArguments = @('-m','standard_knowledge_service_v2.main','--config',$configuration,'--serve')
Write-Output '[启动] 正在启动后台；后台将加载标准条款并构建内存知识图谱'
$backend = Start-Process -FilePath $pythonPath -ArgumentList $pythonArguments -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'backend.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'backend.stderr.log')
$frontend = $null
try {
    $healthy = $false
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $nextProgressAt = 5
    while ($watch.Elapsed.TotalSeconds -lt $BackendTimeoutSeconds) {
        if ($backend.HasExited) { throw '后端启动失败，请查看artifacts/local_demo/backend.stderr.log。' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 1
            if ($health.status -eq 'ok') { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 300 }
        if ($watch.Elapsed.TotalSeconds -ge $nextProgressAt) {
            $progressLog = Join-Path $logDirectory 'backend.stdout.log'
            $latest = if (Test-Path -LiteralPath $progressLog) {
                Get-Content -LiteralPath $progressLog -Encoding UTF8 -Tail 1 -ErrorAction SilentlyContinue
            } else { $null }
            $elapsed = [Math]::Floor($watch.Elapsed.TotalSeconds)
            if ($latest) {
                Write-Output "[启动] 已等待${elapsed}秒：$latest"
            } else {
                Write-Output "[启动] 已等待${elapsed}秒：后台仍在初始化"
            }
            $nextProgressAt += 5
        }
    }
    if (-not $healthy) { throw '后端启动超时。请查看artifacts/local_demo/backend.stdout.log和backend.stderr.log。' }
    Write-Output ('[启动] 后台启动完成，耗时约' + [Math]::Round($watch.Elapsed.TotalSeconds, 1) + '秒')
    Write-Output '[启动] 正在启动前端页面'
    $frontend = Start-Process -FilePath $pythonPath -ArgumentList @('-m','http.server','5500','--bind','127.0.0.1','--directory','frontend') -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'frontend.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'frontend.stderr.log')
    $pageReady = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        if ($frontend.HasExited) { throw '前端启动失败。' }
        try {
            $page = Invoke-WebRequest 'http://127.0.0.1:5500/' -TimeoutSec 1 -UseBasicParsing
            if ($page.StatusCode -eq 200) { $pageReady = $true; break }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $pageReady) { throw '前端启动超时。' }
    $state = [ordered]@{backend_pid=$backend.Id;frontend_pid=$frontend.Id;online=[bool]$Online;url='http://127.0.0.1:5500/';started_at=(Get-Date).ToString('o')}
    $state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDirectory '运行状态.json') -Encoding UTF8
    Write-Output ('前端已启动：http://127.0.0.1:5500/；模式：' + $(if ($Online) {'在线配置，接口预检查通过；实际模型效果请提交问题验证'} else {'离线降级，不调用建议模型'}))
    Write-Output "停止本次服务：Stop-Process -Id $($backend.Id),$($frontend.Id)"
} catch {
    if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id }
    if (-not $backend.HasExited) { Stop-Process -Id $backend.Id }
    throw
}

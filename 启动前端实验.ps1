[CmdletBinding()]
param([switch]$Online)

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $pythonPath = Join-Path (Split-Path $projectDirectory -Parent) 'electrical-tools_仓库版本\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先在仓库根目录创建.venv并安装项目依赖；也支持复用同级仓库版本目录中的已有.venv。' }
$env:PYTHONPATH = Join-Path $projectDirectory 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:ELECTRICAL_TOOLS_OFFLINE_UNUSED_KEY = ''
$configuration = if ($Online) { 'configs/settings.example.yaml' } else { 'configs/settings.offline.yaml' }
if ($Online -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','Machine')
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
    }
}
if ($Online -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
    throw '在线模式需要先在当前窗口设置DEEPSEEK_API_KEY；不要将密钥写入文件或发到聊天中。'
}
foreach ($port in @(8000,5500)) {
    $probe = [System.Net.Sockets.TcpClient]::new()
    try {
        $pending = $probe.BeginConnect('127.0.0.1',$port,$null,$null)
        if ($pending.AsyncWaitHandle.WaitOne(300) -and $probe.Connected) { throw "端口$port已占用，请先关闭自己此前启动的实验服务。" }
    } finally { $probe.Dispose() }
}
if ($Online) {
    & $pythonPath -m standard_knowledge_service_v2.decomposition.check_remote --config (Join-Path $projectDirectory $configuration)
    if ($LASTEXITCODE -ne 0) {
        throw '在线接口预检查未通过，未启动新的服务。网络权限拒绝时，请从有外网权限的PowerShell启动，不要关闭防火墙或绕过安全限制。'
    }
}
$logDirectory = Join-Path $projectDirectory 'artifacts\local_demo'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$pythonArguments = @('-m','standard_knowledge_service_v2.main','--config',$configuration,'--serve')
$backend = Start-Process -FilePath $pythonPath -ArgumentList $pythonArguments -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'backend.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'backend.stderr.log')
$frontend = $null
try {
    $healthy = $false
    for ($attempt=0; $attempt -lt 60; $attempt++) {
        if ($backend.HasExited) { throw '后端启动失败，请查看artifacts/local_demo/backend.stderr.log。' }
        try {
            $health = Invoke-RestMethod 'http://127.0.0.1:8000/health' -TimeoutSec 1
            if ($health.status -eq 'ok') { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 300 }
    }
    if (-not $healthy) { throw '后端启动超时。' }
    $frontend = Start-Process -FilePath $pythonPath -ArgumentList @('-m','http.server','5500','--bind','127.0.0.1','--directory','frontend') -WorkingDirectory $projectDirectory -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logDirectory 'frontend.stdout.log') -RedirectStandardError (Join-Path $logDirectory 'frontend.stderr.log')
    $pageReady = $false
    for ($attempt=0; $attempt -lt 30; $attempt++) {
        if ($frontend.HasExited) { throw '前端启动失败。' }
        try {
            $page = Invoke-WebRequest 'http://127.0.0.1:5500/' -TimeoutSec 1
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

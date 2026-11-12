[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
Set-Location -LiteralPath $projectDirectory
$pipTemporaryDirectory = Join-Path $projectDirectory '.tmp\pip'
New-Item -ItemType Directory -Path $pipTemporaryDirectory -Force | Out-Null
$env:TEMP = $pipTemporaryDirectory
$env:TMP = $pipTemporaryDirectory
$env:PYTHONUTF8 = '1'

$venvDirectory = Join-Path $projectDirectory '.venv'
$pythonPath = Join-Path $venvDirectory 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidates += @{ executable = 'py'; arguments = @('-3.13') }
        $candidates += @{ executable = 'py'; arguments = @('-3.12') }
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) { $candidates += @{ executable = $pythonCommand.Source; arguments = @() } }
    $portable = Join-Path (Split-Path -Parent $projectDirectory) '运行环境\python-3.13.5\tools\python.exe'
    if (Test-Path -LiteralPath $portable) { $candidates += @{ executable = $portable; arguments = @() } }
    $selected = $null
    foreach ($candidate in $candidates) {
        $arguments = $candidate.arguments
        & $candidate.executable @arguments -c "import sys; sys.exit(0 if sys.version_info[:2] in [(3,12),(3,13)] else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) { $selected = $candidate; break }
    }
    if (-not $selected) { throw '未找到可用的Python 3.12或3.13，请安装或配置Python后重试。' }
    Write-Output '[环境] 正在创建虚拟环境'
    $arguments = $selected.arguments
    & $selected.executable @arguments -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw '虚拟环境创建失败。' }
}

$version = & $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $version.Trim() -notin @('3.12', '3.13')) {
    throw '现有.venv不是Python 3.12或3.13环境。请先备份后删除该.venv，再重新运行本脚本。'
}

Write-Output '[环境] 正在检查pip'
& $pythonPath -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Output '[环境] 未检测到pip，正在初始化pip'
    & $pythonPath -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'pip初始化失败。' }
}

Write-Output '[环境] 正在安装运行与测试依赖'
& $pythonPath -m pip install --disable-pip-version-check -e '.[api,excel,test,consistency,graph]'
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络、代理或pip软件源配置。' }

Write-Output '[环境] 正在验证关键依赖'
& $pythonPath -c "import fastapi, httpx, neo4j, openpyxl, pytest, torch, uvicorn, yaml; print('dependency check passed; torch=' + torch.__version__ + '; neo4j=' + neo4j.__version__)"
if ($LASTEXITCODE -ne 0) { throw '依赖验证失败。' }

Write-Output '[环境] 初始化完成。离线启动：.\启动前端实验.ps1；在线启动：.\启动前端实验.ps1 -Online'

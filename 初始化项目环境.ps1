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

$launcher = Get-Command py -ErrorAction SilentlyContinue
if (-not $launcher) {
    throw '未找到Windows Python启动器py。请先安装Python 3.13.5，并在安装时启用Python Launcher。'
}

& py -3.13 -c "import sys; assert sys.version_info[:2] == (3, 13); print(sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) {
    throw '未找到Python 3.13。请安装Python 3.13.5后重试。'
}

$venvDirectory = Join-Path $projectDirectory '.venv'
$pythonPath = Join-Path $venvDirectory 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    Write-Output '[环境] 正在创建Python 3.13虚拟环境'
    & py -3.13 -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw '虚拟环境创建失败。' }
}

$version = & $pythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($LASTEXITCODE -ne 0 -or $version.Trim() -ne '3.13') {
    throw '现有.venv不是Python 3.13环境。请先备份后删除该.venv，再重新运行本脚本。'
}

Write-Output '[环境] 正在检查pip'
& $pythonPath -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Output '[环境] 未检测到pip，正在初始化pip'
    & $pythonPath -m ensurepip --upgrade
    if ($LASTEXITCODE -ne 0) { throw 'pip初始化失败。' }
}

Write-Output '[环境] 正在安装运行与测试依赖'
& $pythonPath -m pip install --disable-pip-version-check -e '.[api,excel,test]'
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络、代理或pip软件源配置。' }

Write-Output '[环境] 正在验证关键依赖'
& $pythonPath -c "import fastapi, httpx, openpyxl, pytest, uvicorn, yaml; print('dependency check passed')"
if ($LASTEXITCODE -ne 0) { throw '依赖验证失败。' }

Write-Output '[环境] 初始化完成。离线启动：.\启动前端实验.ps1；在线启动：.\启动前端实验.ps1 -Online'

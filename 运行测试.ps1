[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$PytestArguments = @()
)

$ErrorActionPreference = 'Stop'
$projectDirectory = $PSScriptRoot
$pythonPath = Join-Path $projectDirectory '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw '未找到项目虚拟环境。请先运行 .\初始化项目环境.ps1。'
}

$env:PYTHONPATH = Join-Path $projectDirectory 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONDONTWRITEBYTECODE = '1'
$testTemporaryDirectory = Join-Path $projectDirectory '.tmp\pytest-runtime'
New-Item -ItemType Directory -Path $testTemporaryDirectory -Force | Out-Null
$env:TEMP = $testTemporaryDirectory
$env:TMP = $testTemporaryDirectory
Set-Location -LiteralPath $projectDirectory

& $pythonPath -m pytest -q --durations=10 --basetemp $testTemporaryDirectory @PytestArguments
if ($LASTEXITCODE -ne 0) {
    throw "测试失败，pytest退出码：$LASTEXITCODE"
}

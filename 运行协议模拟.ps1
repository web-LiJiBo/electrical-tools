$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    $taskPython = Join-Path $PSScriptRoot '..\electrical-tools_仓库版本\.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '未找到项目现有Python环境。请使用已安装项目依赖的Python运行simulation模块。'
}
$taskPreviousPath = $env:PYTHONPATH
$taskPreviousUtf8 = $env:PYTHONUTF8
try {
    $env:PYTHONPATH = Join-Path $PSScriptRoot 'src'
    $env:PYTHONUTF8 = '1'
    & $taskPython -B -m standard_knowledge_service_v2.instruction_engine.simulation
    if ($LASTEXITCODE -ne 0) { throw '协议模拟运行失败' }
} finally {
    $env:PYTHONPATH = $taskPreviousPath
    $env:PYTHONUTF8 = $taskPreviousUtf8
}

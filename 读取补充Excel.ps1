param([string]$InputDirectory = "", [string[]]$Sheet = @(), [switch]$BuildSubclauses)
$ErrorActionPreference = "Stop"
$candidates = @(
    (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
    (Join-Path $PSScriptRoot "..\electrical-tools_仓库版本\.venv\Scripts\python.exe"),
    (Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe")
)
$readerPython = $null
foreach ($candidate in $candidates) {
    if (Test-Path -LiteralPath $candidate) {
        & $candidate -c "import openpyxl" 2>$null
        if ($LASTEXITCODE -eq 0) { $readerPython = $candidate; break }
    }
}
if (-not $readerPython) { throw "未找到含openpyxl的Python。请在项目环境安装Excel依赖：pip install -e '.[excel]'" }
$previousPath = $env:PYTHONPATH
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONPATH = (Join-Path $PSScriptRoot "src")
    $env:PYTHONIOENCODING = "utf-8"
    $readerArgs = @("-X", "utf8", "-m", "standard_knowledge_service_v2.data_ingestion.supplemental_excel")
    if ($InputDirectory) { $readerArgs += @("--input-dir", $InputDirectory) }
    if ($BuildSubclauses) { $readerArgs += "--build-subclauses" }
    foreach ($sheetName in $Sheet) { $readerArgs += @("--sheet", $sheetName) }
    & $readerPython @readerArgs
    $readerExitCode = $LASTEXITCODE
} finally {
    $env:PYTHONPATH = $previousPath
    $env:PYTHONIOENCODING = $previousEncoding
}
exit $readerExitCode

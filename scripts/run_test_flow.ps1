[CmdletBinding()]
param(
    [ValidateSet("fast", "standard")]
    [string]$Profile = "standard",
    [string]$PythonCommand = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $projectRoot
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$reportRoot = Join-Path $projectRoot "artifacts\test_reports\$runId"
New-Item -ItemType Directory -Path $reportRoot -Force | Out-Null
$transcript = Join-Path $reportRoot "test-flow.log"

function Invoke-PythonStep {
    param([string]$Name, [string[]]$Arguments)
    Write-Host "`n[$Name] $PythonCommand $($Arguments -join ' ')"
    & $PythonCommand @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "测试步骤失败：$Name（退出码 $LASTEXITCODE）"
    }
}

Start-Transcript -Path $transcript | Out-Null
try {
    $env:PYTHONPATH = "src"
    Invoke-PythonStep "环境信息" @("-c", "import json,platform,sys; print(json.dumps({'python':sys.version,'executable':sys.executable,'platform':platform.platform()},ensure_ascii=False))")
    $environmentJson = & $PythonCommand -c "import json,platform,sys; print(json.dumps({'python':sys.version,'executable':sys.executable,'platform':platform.platform()},ensure_ascii=False))"
    if ($LASTEXITCODE -ne 0) { throw "环境信息采集失败" }
    $environmentJson | Set-Content -LiteralPath (Join-Path $reportRoot "environment.json") -Encoding UTF8

    $pythonFiles = Get-ChildItem -LiteralPath "src", "tests" -Recurse -Filter "*.py"
    $unfinished = $pythonFiles | Select-String -Pattern "NotImplementedError|TODO:.*未实现"
    if ($unfinished) { throw "发现未完成代码：$($unfinished[0].Path):$($unfinished[0].LineNumber)" }
    $externalImports = $pythonFiles | Select-String -CaseSensitive -Pattern "攻关项目\\lunwen|from\s+lunwen(?:\.|\s|$)|import\s+lunwen(?:\.|\s|$)"
    if ($externalImports) { throw "发现对论文项目目录的运行时依赖：$($externalImports[0].Path):$($externalImports[0].LineNumber)" }

    $fingerprints = [ordered]@{
        config_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath "configs\settings.example.yaml").Hash
        dataset_audit_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath "datasets\lunwen\verified_json\audit_summary.json").Hash
        qwen_config_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath "models\llm\qwen--Qwen-7B-Chat\snapshots\master\config.json").Hash
        verified_json_files = (Get-ChildItem -LiteralPath "datasets\lunwen\verified_json\json" -Filter "*.json").Count
    }
    $fingerprints | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot "fingerprints.json") -Encoding UTF8
    Invoke-PythonStep "语法检查" @("-m", "compileall", "-q", "src", "tests")

    $junit = Join-Path $reportRoot "pytest-junit.xml"
    if ($Profile -eq "fast") {
        Invoke-PythonStep "快速自动化测试" @("-m", "pytest", "-q", "-m", "not data and not model", "--junitxml", $junit)
    }
    else {
        Invoke-PythonStep "完整离线自动化测试" @("-m", "pytest", "-q", "-m", "not model", "--junitxml", $junit)
        Invoke-PythonStep "配置装配检查" @("-c", "from standard_knowledge_service_v2.bootstrap import build_application; a=build_application('configs/settings.example.yaml'); print({'verified_units':len(a.facade.retriever.repository.units),'selection_top_k':a.facade.retrieval_settings.selection_top_k,'model_path':str(a.facade.decomposer._decomposer.config.model_path)})")
    }

    $summary = [ordered]@{
        run_id = $runId
        profile = $Profile
        status = "passed"
        report_root = $reportRoot
        completed_at = (Get-Date).ToString("o")
    }
    $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot "summary.json") -Encoding UTF8
    Write-Host "`n测试通过。报告目录：$reportRoot"
}
catch {
    $summary = [ordered]@{
        run_id = $runId
        profile = $Profile
        status = "failed"
        error = $_.Exception.Message
        report_root = $reportRoot
        completed_at = (Get-Date).ToString("o")
    }
    $summary | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot "summary.json") -Encoding UTF8
    throw
}
finally {
    Stop-Transcript | Out-Null
}

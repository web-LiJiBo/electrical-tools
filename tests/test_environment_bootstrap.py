from pathlib import Path
import subprocess


def test_existing_environment_does_not_require_windows_launcher():
    root = Path(__file__).resolve().parents[1]
    script = (root / "初始化项目环境.ps1").read_text(encoding="utf-8-sig")
    prefix = script.split("Write-Output '[环境] 正在检查pip'")[0]
    prefix = prefix.replace("$projectDirectory = $PSScriptRoot", "$projectDirectory = '" + str(root).replace("'", "''") + "'")
    command = "function Get-Command { return $null }; " + prefix.replace("[CmdletBinding()]", "").replace("param()", "") + "Write-Output 'BOOTSTRAP_OK'"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"BOOTSTRAP_OK" in result.stdout



def test_portable_python_can_create_environment_without_launcher(tmp_path):
    root = Path(__file__).resolve().parents[1]
    portable = root.parent / "运行环境/python-3.13.5/tools/python.exe"
    if not portable.exists():
        import pytest
        pytest.skip("Portable Python not installed")
    script = (root / "初始化项目环境.ps1").read_text(encoding="utf-8-sig")
    prefix = script.split("Write-Output '[环境] 正在检查pip'")[0]
    prefix = prefix.replace("$projectDirectory = $PSScriptRoot", "$projectDirectory = '" + str(root).replace("'", "''") + "'")
    prefix = prefix.replace("Join-Path $projectDirectory '.venv'", "'" + str(tmp_path / "venv").replace("'", "''") + "'")
    command = "function Get-Command { return $null }; " + prefix.replace("[CmdletBinding()]", "").replace("param()", "") + "Write-Output 'BOOTSTRAP_OK'"
    result = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, timeout=90)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"BOOTSTRAP_OK" in result.stdout
    assert (tmp_path / "venv/Scripts/python.exe").exists()

param(
    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================"
Write-Host " UnderWaterRobotGCS - TUI Launcher"
Write-Host "============================================"
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = (Resolve-Path (Join-Path $ScriptDir "..")).Path
Set-Location $RootDir

if (Test-Path ".venv\Scripts\python.exe") {
    $PythonCmd = (Resolve-Path ".venv\Scripts\python.exe").Path
    $PythonArgs = @()
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonCmd = "py"
    $PythonArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $PythonCmd = "python"
    $PythonArgs = @()
} else {
    Write-Host "[ERR] Python not found. Install Python 3.10+ first."
    exit 2
}

if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$RootDir\src;$($env:PYTHONPATH)"
} else {
    $env:PYTHONPATH = "$RootDir\src"
}

Write-Host "[INFO] Project root: $RootDir"
Write-Host "[INFO] Python: $PythonCmd"
Write-Host ""

& $PythonCmd @PythonArgs -m urogcs.tools.preflight_check
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($PreflightOnly) {
    Write-Host ""
    Write-Host "[INFO] Preflight only mode complete"
    exit 0
}

Write-Host "[WARN] Windows 当前只提供最小观测/诊断路径，键盘 teleop 仍然以 POSIX 平台为准。"
Write-Host "[INFO] Starting TUI"
Write-Host ""
& $PythonCmd @PythonArgs -m urogcs.app.tui.tui_main
exit $LASTEXITCODE

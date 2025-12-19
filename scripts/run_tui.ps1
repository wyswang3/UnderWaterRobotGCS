# scripts/run_tui.ps1
# ============================================
# UnderWaterRobotGCS - TUI Launcher
# ============================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================"
Write-Host " UnderWaterRobotGCS - TUI Controller"
Write-Host "============================================"
Write-Host ""

# 切换到项目根目录（以脚本所在位置为基准）
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$ROOT_DIR   = Resolve-Path (Join-Path $SCRIPT_DIR "..")

Set-Location $ROOT_DIR

Write-Host "[INFO] Project root: $ROOT_DIR"
Write-Host "[INFO] Starting TUI (keyboard control)..."
Write-Host ""

# 可选：虚拟环境检查（不强制）
if (Test-Path ".venv\Scripts\Activate.ps1") {
    Write-Host "[INFO] Activating virtual environment (.venv)"
    . .venv\Scripts\Activate.ps1
} else {
    Write-Host "[WARN] No .venv found, using system Python"
}

Write-Host ""
Write-Host "[INFO] Press Ctrl+C to exit"
Write-Host ""

# 启动 TUI
python -m urogcs.app.tui_main

Write-Host ""
Write-Host "[INFO] TUI exited"

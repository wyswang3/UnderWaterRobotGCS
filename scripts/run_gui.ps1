param(
    [switch]$PreflightOnly
)

$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $Root

if (Test-Path (Join-Path $Root '.venv\Scripts\python.exe')) {
    $Python = (Join-Path $Root '.venv\Scripts\python.exe')
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $Python = 'py -3'
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $Python = 'python'
} else {
    Write-Error 'Python interpreter not found.'
    exit 1
}

$env:PYTHONPATH = "$Root\src"
# GUI is a read-only observer; default to an ephemeral bind port so it can run
# alongside the TUI without fighting over the fixed telemetry port.
if (-not $env:UROGCS_GUI_BIND_PORT) { $env:UROGCS_GUI_BIND_PORT = '0' }

if ($Python -eq 'py -3') {
    py -3 -m urogcs.tools.preflight_check --bind-port $env:UROGCS_GUI_BIND_PORT
    if ($LASTEXITCODE -ne 0 -or $PreflightOnly) { exit $LASTEXITCODE }

    Write-Host '[WARN] Windows GUI support is still a first-stage developer preview.'
    py -3 -m urogcs.app.gui_main
    exit $LASTEXITCODE
}

& $Python -m urogcs.tools.preflight_check --bind-port $env:UROGCS_GUI_BIND_PORT
if ($LASTEXITCODE -ne 0 -or $PreflightOnly) { exit $LASTEXITCODE }

Write-Host '[WARN] Windows GUI support is still a first-stage developer preview.'
& $Python -m urogcs.app.gui_main
exit $LASTEXITCODE

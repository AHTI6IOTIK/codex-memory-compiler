param(
    [Parameter(Mandatory = $true)]
    [string]$HookScript
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$uv = Join-Path $root "bin\uv.exe"
$hookPath = Join-Path $PSScriptRoot $HookScript

if (-not (Test-Path $uv)) {
    Write-Error "uv.exe not found at $uv"
    exit 1
}

if (-not (Test-Path $hookPath)) {
    Write-Error "Hook script not found at $hookPath"
    exit 1
}

$env:UV_CACHE_DIR = Join-Path $root ".uv-cache"
$env:UV_PYTHON_INSTALL_DIR = Join-Path $root ".uv-python"
$env:UV_TOOL_DIR = Join-Path $root ".uv-tools"

& $uv run --project $root python $hookPath
exit $LASTEXITCODE

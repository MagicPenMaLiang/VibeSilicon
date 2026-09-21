<#
.SYNOPSIS
    Prepare and verify a VibeSilicon development environment on Windows.

.DESCRIPTION
    Thin wrapper that delegates to scripts/setup_env_core.py. Keeps all
    behavior in one place so the POSIX entry (future) can share it.

    Exit codes (from the Python core):
        0  ready - Python deps importable, smoke checks pass.
        2  venv could not be created or bootstrapped.
        3  locked dependencies failed to install or import.
        4  public_release_audit.py reported violations.
        5  unit-test smoke run failed.
        10 one or more optional EDA tools are missing (warning only).

.PARAMETER RecreateVenv
    Delete and rebuild the existing .venv before installing dependencies.

.PARAMETER SkipTests
    Skip the unittest discover smoke run (faster iteration).

.PARAMETER NoInstall
    Assume dependencies are already installed; skip the pip step.

.PARAMETER NoAudit
    Skip the public_release_audit.py source-tree gate.

.PARAMETER Json
    Emit machine-readable JSON instead of the human-readable report.

.EXAMPLE
    pwsh -File scripts\setup_env.ps1
    python scripts\setup_env_core.py --json
#>

[CmdletBinding()]
param(
    [switch]$RecreateVenv,
    [switch]$SkipTests,
    [switch]$NoInstall,
    [switch]$NoAudit,
    [switch]$Json,
    [switch]$Audit,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root      = (Resolve-Path (Join-Path $ScriptDir "..")).Path
$Core      = Join-Path $ScriptDir "setup_env_core.py"

if ($Help) {
    Get-Help $MyInvocation.MyCommand.Path -Full | Out-String | Write-Host
    exit 0
}

if (-not (Test-Path -LiteralPath $Core)) {
    Write-Error "setup_env_core.py not found at $Core"
    exit 99
}

# Prefer the repo's .venv Python if present, otherwise fall back to a system
# Python on PATH. We never use the PowerShell 'python' alias to avoid surprises.
$RepoPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $RepoPy) {
    $Py = $RepoPy
} else {
    $Candidate = (Get-Command python.exe -ErrorAction SilentlyContinue | Select-Object -First 1).Source
    if (-not $Candidate) {
        Write-Error "No Python interpreter found. Install Python 3.10-3.12 or run scripts\setup_env.cmd first."
        exit 98
    }
    $Py = $Candidate
}

# Map ps1 switches to core flags. We translate explicitly so that ps1 users
# get PowerShell-style -Verb flags while the core stays a portable argv parser.
$Args = @()
if ($RecreateVenv) { $Args += "--recreate-venv" }
if ($SkipTests)    { $Args += "--skip-tests" }
if ($NoInstall)    { $Args += "--no-install" }
if ($NoAudit)      { $Args += "--no-audit" }
if ($Audit)        { $Args += "--audit" }
if ($Json)         { $Args += "--json" }

# Use the call operator with explicit array splatting so paths with spaces are
# preserved verbatim and PowerShell does not re-tokenize the script path.
& $Py -- $Core $Args
exit $LASTEXITCODE

@echo off
REM ============================================================
REM  VibeSilicon Windows cmd entry. Delegates to setup_env.ps1.
REM
REM  Exit codes (forwarded from the Python core):
REM      0  ready
REM      2  venv could not be created
REM      3  locked dependencies failed
REM      4  public_release_audit.py failed
REM      5  unit-test smoke failed
REM      10 optional EDA tools missing (warning only)
REM
REM  Usage:
REM      scripts\setup_env.cmd            [default]
REM      scripts\setup_env.cmd --recreate
REM      scripts\setup_env.cmd --skip-tests
REM      scripts\setup_env.cmd --no-install
REM      scripts\setup_env.cmd --no-audit
REM      scripts\setup_env.cmd --json
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "ROOT=%SCRIPT_DIR%.."
for %%I in ("%ROOT%") do set "ROOT=%%~fI"
set "PS1=%SCRIPT_DIR%setup_env.ps1"

if not exist "%PS1%" (
    echo [setup_env.cmd] missing %PS1%
    exit /b 99
)

REM Prefer PowerShell 7 (pwsh) when available; fall back to Windows
REM PowerShell 5.1 (powershell.exe) which ships with the OS.
where pwsh.exe >nul 2>&1
if not errorlevel 1 (
    set "PWSH=pwsh.exe"
) else (
    set "PWSH=powershell.exe"
)

set "ARGS="
if /I "%~1"=="--recreate"   set "ARGS=%ARGS% -RecreateVenv"
if /I "%~1"=="--skip-tests" set "ARGS=%ARGS% -SkipTests"
if /I "%~1"=="--no-install" set "ARGS=%ARGS% -NoInstall"
if /I "%~1"=="--no-audit"   set "ARGS=%ARGS% -NoAudit"
if /I "%~1"=="--audit"      set "ARGS=%ARGS% -Audit"
if /I "%~1"=="--json"       set "ARGS=%ARGS% -Json"
if /I "%~1"=="--help"       set "ARGS=%ARGS% -Help"
if /I "%~1"=="-h"           set "ARGS=%ARGS% -Help"

"%PWSH%" -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %ARGS%
set "EC=%ERRORLEVEL%"

if not "%EC%"=="0" (
    echo.
    echo [setup_env.cmd] completed with exit code %EC%
    echo See docs\setup_env.md for the meaning of each code.
)

exit /b %EC%

@echo off
REM ============================================================
REM  download_tools.bat
REM  Auto-download COLMAP, VKGS, VkSplat to tools/ directory
REM  On failure, prints manual download links.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === 3DGS Tools Downloader ===
echo.

REM Ensure tools directory exists
if not exist "tools" mkdir tools

REM Check if PowerShell is available
where powershell >nul 2>nul
if errorlevel 1 (
    echo [FAIL] PowerShell not found. Please install Windows PowerShell.
    pause
    exit /b 1
)

REM Run PowerShell download script
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_tools.ps1"
set "EXITCODE=%ERRORLEVEL%"

if %EXITCODE% neq 0 (
    echo.
    echo [FAIL] Some tools failed. See messages above.
    echo        If download was too slow, try manual links shown above.
    pause
    exit /b %EXITCODE%
)

echo.
echo [OK] All tools downloaded and installed.
pause
endlocal
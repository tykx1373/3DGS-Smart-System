@echo off
REM ============================================================
REM  download_tools.bat
REM  自动下载 COLMAP、VKGS、VkSplat 到 tools/ 目录
REM  若下载失败，脚本会打印手动下载链接
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === 3DGS Tools Downloader ===
echo.

REM 确保 tools 目录存在
if not exist "tools" mkdir tools

REM 检查 PowerShell 是否可用
where powershell >nul 2>nul
if errorlevel 1 (
    echo [FAIL] PowerShell not found. Please install Windows PowerShell.
    pause
    exit /b 1
)

REM 调用 PowerShell 执行实际下载逻辑
REM -NoProfile: 不加载用户配置（避免执行策略冲突）
REM -ExecutionPolicy Bypass: 绕过执行策略
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_tools.ps1"
set "EXITCODE=%ERRORLEVEL%"

if %EXITCODE% neq 0 (
    echo.
    echo [FAIL] Some tools failed to download/install. See messages above.
    echo        If download was too slow, try manual download links above.
    pause
    exit /b %EXITCODE%
)

echo.
echo [OK] All tools downloaded and installed.
pause
endlocal


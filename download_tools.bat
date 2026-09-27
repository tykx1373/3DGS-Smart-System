@echo off
REM ============================================================
REM  download_tools.bat
REM  自动下载 COLMAP 和 VKGS 预编译包到 tools/ 目录
REM  若下载失败，脚本会打印手动下载链接
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === 3DGS Tools Downloader ===
echo.

REM 确保 tools 目录存在
if not exist "tools" mkdir tools

REM 调用 PowerShell 执行实际下载逻辑
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download_tools.ps1"
if errorlevel 1 (
    echo.
    echo [FAIL] 部分工具下载失败，请按上方提示手动下载。
    pause
    exit /b 1
)

echo.
echo [OK] 所有工具下载完成。
pause
endlocal

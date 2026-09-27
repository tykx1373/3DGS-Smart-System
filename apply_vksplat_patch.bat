@echo off
REM 一键应用 VkSplat 本地修改补丁（旋转矩阵、simple_trainer 等）
REM 在 clone 主仓库并执行 git submodule update --init 后运行此脚本

setlocal
cd /d "%~dp0"

set "PATCH=patches\vksplat-local-modifications.patch"
set "VKSPLAT=tools\vksplat"

if not exist "%VKSPLAT%\.git" (
    echo [FAIL] VkSplat submodule not found.
    echo        Run: git submodule update --init --recursive
    pause
    exit /b 1
)

if not exist "%PATCH%" (
    echo [FAIL] Patch file not found: %PATCH%
    pause
    exit /b 1
)

echo [INFO] Applying VkSplat local modifications...
git -C "%VKSPLAT%" apply --check "..\..\%PATCH%"
if errorlevel 1 (
    echo [WARN] Patch does not apply cleanly ^(VkSplat may have been updated^).
    echo        Skipping. You may need to manually merge the changes.
    pause
    exit /b 0
)

git -C "%VKSPLAT%" apply "..\..\%PATCH%"
if errorlevel 1 (
    echo [FAIL] Failed to apply patch.
    pause
    exit /b 1
)

echo [OK] Patch applied successfully.
pause
endlocal

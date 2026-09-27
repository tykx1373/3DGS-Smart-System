@echo off
REM Apply VkSplat local modifications patch (rotation matrix, simple_trainer, etc.)
REM Run this after cloning the repo and git submodule update --init

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
@echo off
setlocal enabledelayedexpansion

REM ---- Locate Python: prefer vksplat conda env (has vksplat + tkinter) ----
set "PYEXE="
for %%P in (
  "D:\miniconda3-pbe\envs\vksplat\python.exe"
  "D:\miniconda3\envs\vksplat\python.exe"
  "%USERPROFILE%\miniconda3\envs\vksplat\python.exe"
  "D:\miniconda3-pbe\python.exe"
  "D:\miniconda3\python.exe"
  "D:\anaconda3\python.exe"
  "%USERPROFILE%\miniconda3\python.exe"
  "%USERPROFILE%\AppData\Local\miniconda3\python.exe"
  "%USERPROFILE%\anaconda3\python.exe"
  "%USERPROFILE%\AppData\Local\anaconda3\python.exe"
  "C:\ProgramData\miniconda3\python.exe"
  "C:\ProgramData\anaconda3\python.exe"
) do (
  if exist %%~P (
    set "PYEXE=%%~P"
    goto :found
  )
)

REM ---- Fallback to PATH ----
where python >nul 2>nul
if %errorlevel%==0 (
  for /f "delims=" %%Q in ('where python') do (
    set "PYEXE=%%Q"
    goto :found
  )
)

echo [FAIL] Could not find Python. Please install Miniconda / Anaconda and a vksplat env.
pause
exit /b 1

:found
echo [OK] Using Python: !PYEXE!

REM ---- Check tkinter ----
"!PYEXE!" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo [WARN] tkinter not found. Trying conda install...
  for %%D in ("!PYEXE!") do set "CONDADIR=%%~dpD"
  "!CONDADIR!..\condabin\conda.bat" install -y tk >nul 2>nul
  if errorlevel 1 (
    "!CONDADIR!..\Scripts\conda.exe" install -y tk >nul 2>nul
  )
  "!PYEXE!" -c "import tkinter" >nul 2>nul
  if errorlevel 1 (
    echo [FAIL] tkinter install failed. Run: conda install -n vksplat tk
    pause
    exit /b 1
  )
)

REM ---- Verify vksplat import (optional, warn only) ----
"!PYEXE!" -c "import vksplat" >nul 2>nul
if errorlevel 1 (
  echo [WARN] vksplat module not found. Train pipeline will fail.
  echo        Install it in this env: pip install -e path\to\vksplat\vksplat
)

REM ---- Run GUI ----
cd /d "%~dp0"
echo [OK] Starting 3DGS Quick Pipeline GUI...
"!PYEXE!" "%~dp0gui\quick_gui.py"
if errorlevel 1 (
  echo.
  echo [FAIL] GUI exited with error.
  pause
)
endlocal

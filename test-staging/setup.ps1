# test-staging/setup.ps1
# Runs automatically inside Windows Sandbox after logon.

$ErrorActionPreference = "Continue"

function Pause-OnError {
    param([string]$msg)
    Write-Host ""
    Write-Host "[FAIL] $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "=== 3DGS Clean-Environment Test Setup ===" -ForegroundColor Cyan
Write-Host ""

$stagingDir = "C:\test-staging"
$projectWritable = "C:\3DGS"

# --- 1. Install Miniforge silently ---
$installer = Get-ChildItem $stagingDir -Filter "Miniforge3-*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installer) { Pause-OnError "Miniforge installer not found in $stagingDir" }

$miniforgePath = "C:\Miniforge3"
Write-Host "[1/4] Installing Miniforge silently to $miniforgePath ..."
$proc = Start-Process -FilePath $installer.FullName -ArgumentList "/InstallationType=JustMe","/RegisterPython=0","/S","/D=$miniforgePath" -Wait -PassThru
if ($proc.ExitCode -ne 0) { Pause-OnError "Miniforge installation failed (exit code $($proc.ExitCode))" }
Write-Host "      Miniforge installed." -ForegroundColor Green
$env:Path = "$miniforgePath;$miniforgePath\Scripts;$miniforgePath\condabin;$env:Path"

# --- 2. Extract clean project archive (identical to GitHub clone) ---
$zipPath = Join-Path $stagingDir "project-clean.zip"
if (-not (Test-Path $zipPath)) { Pause-OnError "project-clean.zip not found in $stagingDir" }

Write-Host "[2/4] Extracting clean project to $projectWritable ..."
if (Test-Path $projectWritable) { Remove-Item $projectWritable -Recurse -Force }
New-Item $projectWritable -ItemType Directory -Force | Out-Null
# Use tar.exe (built into Windows) — more reliable than Expand-Archive
tar -xf $zipPath -C $projectWritable
if ($LASTEXITCODE -ne 0) { Pause-OnError "Failed to extract project-clean.zip (tar exit code $LASTEXITCODE)" }
if (-not (Test-Path "$projectWritable\download_tools.bat")) { Pause-OnError "download_tools.bat not found after extraction" }
Write-Host "      Project extracted (clean state, no env/ or tools/)." -ForegroundColor Green

# --- 3. Copy pre-downloaded tools (COLMAP, VKGS) to skip downloads ---
$preDownloaded = Join-Path $stagingDir "pre-downloaded"
if (Test-Path $preDownloaded) {
    Write-Host "[3/4] Copying pre-downloaded tools to skip download step..."
    New-Item "$projectWritable\tools" -ItemType Directory -Force | Out-Null
    Get-ChildItem $preDownloaded -Directory | ForEach-Object {
        Copy-Item $_.FullName "$projectWritable\tools\" -Recurse -Force
        Write-Host "        - $($_.Name)"
    }
    Write-Host "      Pre-downloaded tools copied." -ForegroundColor Green
} else {
    Write-Host "[3/4] No pre-downloaded tools found, will download in step 4." -ForegroundColor Yellow
}

# --- 4. Run download_tools.bat ---
$batPath = Join-Path $projectWritable "download_tools.bat"
Write-Host "[4/4] Running download_tools.bat ..." -ForegroundColor Cyan
Write-Host ""
cmd /c "cd /d $projectWritable && call `"$batPath`""

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Project is at: $projectWritable"
Write-Host "To start the GUI, run: run.bat"
Write-Host ""
Read-Host "Press Enter to open a command prompt at the project folder"
cmd /c "start cmd /k cd /d $projectWritable"

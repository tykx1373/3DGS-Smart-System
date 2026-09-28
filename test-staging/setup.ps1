# test-staging/setup.ps1
# Runs automatically inside Windows Sandbox after logon.
# 1. Silently installs Miniforge
# 2. Extracts clean project archive (git archive, same as GitHub download)
# 3. Copies pre-downloaded COLMAP & VKGS into tools/
# 4. Runs download_tools.bat

$ErrorActionPreference = "Continue"

Write-Host "=== 3DGS Clean-Environment Test Setup ===" -ForegroundColor Cyan
Write-Host ""

$stagingDir = "C:\test-staging"
$projectWritable = "C:\3DGS"

# --- 1. Install Miniforge silently ---
$installer = Get-ChildItem $stagingDir -Filter "Miniforge3-*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installer) {
    Write-Host "[FAIL] Miniforge installer not found in $stagingDir" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$miniforgePath = "C:\Miniforge3"
Write-Host "[1/4] Installing Miniforge silently to $miniforgePath ..."
$proc = Start-Process -FilePath $installer.FullName -ArgumentList "/InstallationType=JustMe","/RegisterPython=0","/S","/D=$miniforgePath" -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Write-Host "[FAIL] Miniforge installation failed (exit code $($proc.ExitCode))" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "      Miniforge installed." -ForegroundColor Green
$env:Path = "$miniforgePath;$miniforgePath\Scripts;$miniforgePath\condabin;$env:Path"

# --- 2. Extract clean project archive (identical to GitHub clone) ---
$zipPath = Join-Path $stagingDir "project-clean.zip"
Write-Host "[2/4] Extracting clean project to $projectWritable ..."
if (Test-Path $projectWritable) { Remove-Item $projectWritable -Recurse -Force }
Expand-Archive -Path $zipPath -DestinationPath $projectWritable -Force
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
if (-not (Test-Path $batPath)) {
    Write-Host "[FAIL] $batPath not found!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
cmd /c "cd /d $projectWritable && call `"$batPath`""

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Project is at: $projectWritable"
Write-Host "To start the GUI, run: run.bat"
Write-Host ""
Read-Host "Press Enter to open a command prompt at the project folder"
cmd /c "start cmd /k cd /d $projectWritable"

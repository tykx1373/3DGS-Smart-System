# test-staging/setup.ps1
# Runs automatically inside Windows Sandbox after logon.
# 1. Silently installs Miniforge
# 2. Copies the (read-only mapped) project to a writable location
# 3. Runs download_tools.bat

$ErrorActionPreference = "Continue"

Write-Host "=== 3DGS Clean-Environment Test Setup ===" -ForegroundColor Cyan
Write-Host ""

# --- 1. Install Miniforge silently ---
$stagingDir = "C:\test-staging"
$installer = Get-ChildItem $stagingDir -Filter "Miniforge3-*.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $installer) {
    Write-Host "[FAIL] Miniforge installer not found in $stagingDir" -ForegroundColor Red
    Write-Host "       Download Miniforge3-Windows-x86_64.exe into test-staging/ on the host."
    Read-Host "Press Enter to exit"
    exit 1
}

$miniforgePath = "C:\Miniforge3"
Write-Host "[1/3] Installing Miniforge silently to $miniforgePath ..."
$proc = Start-Process -FilePath $installer.FullName -ArgumentList "/InstallationType=JustMe","/RegisterPython=0","/S","/D=$miniforgePath" -Wait -PassThru
if ($proc.ExitCode -ne 0) {
    Write-Host "[FAIL] Miniforge installation failed (exit code $($proc.ExitCode))" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "      Miniforge installed." -ForegroundColor Green

# Refresh PATH for this session
$env:Path = "$miniforgePath;$miniforgePath\Scripts;$miniforgePath\condabin;$env:Path"

# --- 2. Copy project to writable location (clean: remove env/ and tools/) ---
$projectReadOnly = "C:\3DGS-src"
$projectWritable = "C:\3DGS"
Write-Host "[2/3] Copying project to $projectWritable (clean state)..."
if (Test-Path $projectWritable) { Remove-Item $projectWritable -Recurse -Force }
Copy-Item $projectReadOnly $projectWritable -Recurse -Force
# Remove any pre-existing env/ and tools/ to simulate a fresh clone
Remove-Item "$projectWritable\env" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "$projectWritable\tools" -Recurse -Force -ErrorAction SilentlyContinue
New-Item "$projectWritable\tools" -ItemType Directory -Force | Out-Null
Set-Content "$projectWritable\tools\.gitkeep" "" -Encoding ascii
Write-Host "      Project copied (env/ and tools/ removed)." -ForegroundColor Green

# --- 2b. Copy pre-downloaded tools (COLMAP, VKGS) to skip downloads ---
$preDownloaded = "C:\test-staging\pre-downloaded"
if (Test-Path $preDownloaded) {
    Write-Host "      Copying pre-downloaded tools to skip download step..."
    Get-ChildItem $preDownloaded -Directory | ForEach-Object {
        Copy-Item $_.FullName "$projectWritable\tools\" -Recurse -Force
        Write-Host "        - $($_.Name)"
    }
    Write-Host "      Pre-downloaded tools copied." -ForegroundColor Green
}

# --- 3. Run download_tools.bat ---
Write-Host "[3/3] Running download_tools.bat ..." -ForegroundColor Cyan
Write-Host ""
Set-Location $projectWritable
cmd /c "download_tools.bat"

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host "Project is at: $projectWritable"
Write-Host "To start the GUI, run: run.bat"
Write-Host ""
Read-Host "Press Enter to open a command prompt at the project folder"
cmd /c "start cmd /k cd /d $projectWritable"

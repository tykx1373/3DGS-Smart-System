# download_tools.ps1
# Automatically download COLMAP and VKGS prebuilt binaries to tools/
# On failure, prints manual download links.

$ErrorActionPreference = "Stop"
$toolsDir = Join-Path $PSScriptRoot "tools"
$failed = @()

function Write-Section($msg) {
    Write-Host ""
    Write-Host "=== $msg ===" -ForegroundColor Cyan
}

function Get-LatestReleaseAssets($repo) {
    $apiUrl = "https://api.github.com/repos/$repo/releases/latest"
    try {
        $resp = Invoke-RestMethod -Uri $apiUrl -Headers @{ "User-Agent" = "3DGS-Tools-Downloader" } -TimeoutSec 30
        return $resp
    } catch {
        Write-Host "[FAIL] Cannot reach GitHub API: $repo" -ForegroundColor Red
        Write-Host "       Error: $($_.Exception.Message)" -ForegroundColor DarkRed
        return $null
    }
}

function Download-File($url, $outPath, $minSize = 1000000) {
    Write-Host "  Downloading: $url"
    Write-Host "  Save to: $outPath"
    try {
        Invoke-WebRequest -Uri $url -OutFile $outPath -UseBasicParsing -TimeoutSec 600
        $size = (Get-Item $outPath).Length
        $sizeMB = [math]::Round($size / 1MB, 2)
        Write-Host "  Size: $sizeMB MB"
        if ($size -lt $minSize) {
            Write-Host "  [FAIL] File too small ($size bytes), likely an error page" -ForegroundColor Red
            Remove-Item $outPath -Force -ErrorAction SilentlyContinue
            return $false
        }
        return $true
    } catch {
        Write-Host "  [FAIL] Download failed: $($_.Exception.Message)" -ForegroundColor Red
        Remove-Item $outPath -Force -ErrorAction SilentlyContinue
        return $false
    }
}

function Extract-Zip($zipPath, $destDir) {
    Write-Host "  Extracting to: $destDir"
    try {
        Expand-Archive -Path $zipPath -DestinationPath $destDir -Force
        return $true
    } catch {
        Write-Host "  [FAIL] Extraction failed: $($_.Exception.Message)" -ForegroundColor Red
        return $false
    }
}

# ----------------------------------------------------------
# COLMAP
# ----------------------------------------------------------
Write-Section "COLMAP"
$colmapCudaDir = Join-Path $toolsDir "colmap-x64-windows-cuda"
$colmapCudaExe = Join-Path $colmapCudaDir "COLMAP.bat"

if (Test-Path $colmapCudaExe) {
    Write-Host "[SKIP] COLMAP (CUDA) already exists: $colmapCudaDir" -ForegroundColor Yellow
} else {
    $release = Get-LatestReleaseAssets "colmap/colmap"
    if ($release) {
        $asset = $release.assets | Where-Object { $_.name -match "windows-cuda\.zip$" } | Select-Object -First 1
        if ($asset) {
            $assetMB = [math]::Round($asset.size / 1MB, 1)
            Write-Host "Found: $($asset.name) ($assetMB MB)"
            $zipPath = Join-Path $toolsDir $asset.name
            if (Download-File $asset.browser_download_url $zipPath $asset.size) {
                if (Extract-Zip $zipPath $toolsDir) {
                    $extracted = Get-ChildItem $toolsDir -Directory | Where-Object { $_.Name -match "colmap.*cuda" } | Select-Object -First 1
                    if ($extracted -and $extracted.FullName -ne $colmapCudaDir) {
                        if (Test-Path $colmapCudaDir) { Remove-Item $colmapCudaDir -Recurse -Force }
                        Rename-Item $extracted.FullName $colmapCudaDir
                    }
                    if (Test-Path $colmapCudaExe) {
                        Write-Host "[OK] COLMAP (CUDA) installed" -ForegroundColor Green
                    } else {
                        Write-Host "[FAIL] COLMAP.bat not found after extraction" -ForegroundColor Red
                        $failed += "COLMAP"
                    }
                } else { $failed += "COLMAP" }
                Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            } else { $failed += "COLMAP" }
        } else {
            Write-Host "[FAIL] windows-cuda.zip asset not found" -ForegroundColor Red
            $failed += "COLMAP"
        }
    } else { $failed += "COLMAP" }
}

# ----------------------------------------------------------
# VKGS (nvpro-samples/vk_gaussian_splatting)
# ----------------------------------------------------------
Write-Section "VKGS"
$vkgsExe = Get-ChildItem $toolsDir -Filter "vk_gaussian_splatting.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1

if ($vkgsExe) {
    Write-Host "[SKIP] VKGS already exists: $($vkgsExe.FullName)" -ForegroundColor Yellow
} else {
    $release = Get-LatestReleaseAssets "nvpro-samples/vk_gaussian_splatting"
    if ($release) {
        $asset = $release.assets | Where-Object { $_.name -match "windows.*\.zip$" -and $_.name -notmatch "linux" } | Select-Object -First 1
        if (-not $asset) {
            $asset = $release.assets | Where-Object { $_.name -match "\.zip$" } | Select-Object -First 1
        }
        if ($asset) {
            $assetMB = [math]::Round($asset.size / 1MB, 1)
            Write-Host "Found: $($asset.name) ($assetMB MB)"
            $zipPath = Join-Path $toolsDir $asset.name
            if (Download-File $asset.browser_download_url $zipPath $asset.size) {
                if (Extract-Zip $zipPath $toolsDir) {
                    $exe = Get-ChildItem $toolsDir -Filter "vk_gaussian_splatting.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                    if ($exe) {
                        Write-Host "[OK] VKGS installed: $($exe.FullName)" -ForegroundColor Green
                    } else {
                        Write-Host "[FAIL] vk_gaussian_splatting.exe not found after extraction" -ForegroundColor Red
                        $failed += "VKGS"
                    }
                } else { $failed += "VKGS" }
                Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
            } else { $failed += "VKGS" }
        } else {
            Write-Host "[FAIL] Windows zip asset not found" -ForegroundColor Red
            $failed += "VKGS"
        }
    } else { $failed += "VKGS" }
}

# ----------------------------------------------------------
# VkSplat (Git Submodule)
# ----------------------------------------------------------
Write-Section "VkSplat"
$vksplatDir = Join-Path $toolsDir "vksplat"
$vksplatGit = Join-Path $vksplatDir ".git"
$patchFile = Join-Path $PSScriptRoot "patches\vksplat-local-modifications.patch"

if (-not (Test-Path $vksplatGit)) {
    Write-Host "Initializing VkSplat submodule..."
    Push-Location $PSScriptRoot
    try {
        git submodule update --init --recursive 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[FAIL] git submodule update failed" -ForegroundColor Red
            $failed += "VkSplat"
        }
    } catch {
        Write-Host "[FAIL] git submodule error: $($_.Exception.Message)" -ForegroundColor Red
        $failed += "VkSplat"
    }
    Pop-Location
}

if (Test-Path $vksplatGit) {
    Write-Host "[OK] VkSplat source: $vksplatDir" -ForegroundColor Green

    # Apply local modifications patch (only if not already applied)
    if (Test-Path $patchFile) {
        Push-Location $vksplatDir
        # Check if there are already local modifications (patch likely applied)
        $hasChanges = $false
        git diff --quiet 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { $hasChanges = $true }

        if ($hasChanges) {
            Write-Host "[SKIP] Patch already applied (local modifications detected)" -ForegroundColor Yellow
        } else {
            Write-Host "Applying local modifications patch..."
            git apply "..\..\patches\vksplat-local-modifications.patch" 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[OK] Patch applied successfully" -ForegroundColor Green
            } else {
                Write-Host "[WARN] Patch does not apply cleanly (VkSplat version may have changed)" -ForegroundColor Yellow
                Write-Host "       You can apply manually: apply_vksplat_patch.bat"
            }
        }
        Pop-Location
    } else {
        Write-Host "[WARN] Patch file not found: $patchFile" -ForegroundColor Yellow
    }
}

# ----------------------------------------------------------
# Summary
# ----------------------------------------------------------
Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "[OK] All tools ready." -ForegroundColor Green
    Write-Host "     COLMAP: $colmapCudaExe"
    $vkgsCheck = Get-ChildItem $toolsDir -Filter "vk_gaussian_splatting.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($vkgsCheck) { Write-Host "     VKGS:   $($vkgsCheck.FullName)" }
    if (Test-Path $vksplatGit) { Write-Host "     VkSplat: $vksplatDir (source + patch)" }
    Write-Host ""
    Write-Host "Next steps:"
    Write-Host "  1. Create conda env: conda create -n vksplat python=3.10 -y"
    Write-Host "  2. Activate: conda activate vksplat"
    Write-Host "  3. Install deps: pip install pybind11 setuptools wheel numpy opencv-python tqdm torchmetrics"
    Write-Host "  4. Build VkSplat: cd tools/vksplat/vksplat && pip install -e . --no-build-isolation"
    exit 0
} else {
    Write-Host "[FAIL] The following tools failed. Please handle manually:" -ForegroundColor Red
    Write-Host ""
    if ($failed -contains "COLMAP") {
        Write-Host "  COLMAP: https://github.com/colmap/colmap/releases"
        Write-Host "           Download COLMAP-x.x.x-windows-cuda.zip, extract to tools/colmap-x64-windows-cuda/"
        Write-Host "           (No NVIDIA GPU? Download windows-nocuda.zip, extract to tools/colmap-x64-windows-nocuda/)"
        Write-Host ""
    }
    if ($failed -contains "VKGS") {
        Write-Host "  VKGS:   https://github.com/nvpro-samples/vk_gaussian_splatting/releases"
        Write-Host "           Download the latest Windows zip, extract to tools/"
        Write-Host ""
    }
    if ($failed -contains "VkSplat") {
        Write-Host "  VkSplat: Ensure you cloned with --recursive, or run:"
        Write-Host "           git submodule update --init --recursive"
        Write-Host "           Then apply patch: apply_vksplat_patch.bat"
        Write-Host ""
    }
    Write-Host "  After extracting to tools/, you do NOT need to re-run this script."
    exit 1
}

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
# Summary
# ----------------------------------------------------------
Write-Host ""
if ($failed.Count -eq 0) {
    Write-Host "[OK] All tools ready." -ForegroundColor Green
    Write-Host "     COLMAP: $colmapCudaExe"
    $vkgsCheck = Get-ChildItem $toolsDir -Filter "vk_gaussian_splatting.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($vkgsCheck) { Write-Host "     VKGS: $($vkgsCheck.FullName)" }
    exit 0
} else {
    Write-Host "[FAIL] The following tools failed to download. Please download manually:" -ForegroundColor Red
    Write-Host ""
    Write-Host "  COLMAP: https://github.com/colmap/colmap/releases"
    Write-Host "           Download COLMAP-x.x.x-windows-cuda.zip, extract to tools/colmap-x64-windows-cuda/"
    Write-Host "           (No NVIDIA GPU? Download windows-nocuda.zip, extract to tools/colmap-x64-windows-nocuda/)"
    Write-Host ""
    Write-Host "  VKGS:   https://github.com/nvpro-samples/vk_gaussian_splatting/releases"
    Write-Host "           Download the latest Windows zip, extract to tools/"
    Write-Host ""
    Write-Host "  After extracting to tools/, you do NOT need to re-run this script."
    exit 1
}

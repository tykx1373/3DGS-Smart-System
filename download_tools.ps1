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

function Get-FastestMirror($githubUrl) {
    # Test multiple GitHub mirrors and return the fastest working one
    $mirrors = @(
        "https://gh-proxy.com/https://github.com",
        "https://github.moeyy.xyz/https://github.com",
        "https://ghfast.top/https://github.com"
    )
    $bestUrl = $githubUrl  # fallback to direct
    $bestTime = [int]::MaxValue

    foreach ($m in $mirrors) {
        $testUrl = $githubUrl -replace '^https://github.com', $m
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $out = & curl.exe -sI -L --ssl-no-revoke --connect-timeout 8 --max-time 15 $testUrl 2>$null
            $sw.Stop()
            if ($out -match "Content-Length:\s+(\d+)" -and [int64]$Matches[1] -gt 1000000) {
                if ($sw.ElapsedMilliseconds -lt $bestTime) {
                    $bestTime = $sw.ElapsedMilliseconds
                    $bestUrl = $testUrl
                }
            }
        } catch {
            # mirror failed, try next
        }
    }
    return $bestUrl
}

function Download-File($url, $outPath, $minSize = 1000000) {
    Write-Host "  Downloading: $url"
    Write-Host "  Save to: $outPath"

    # Auto-select fastest mirror (or direct URL)
    Write-Host "  Selecting fastest mirror..."
    $downloadUrl = Get-FastestMirror $url
    if ($downloadUrl -ne $url) {
        Write-Host "  Using mirror: $downloadUrl"
    } else {
        Write-Host "  Using direct URL (no mirror available)"
    }

    # Start curl in background (avoids PowerShell stderr parsing issues)
    $curlArgs = "-L --ssl-no-revoke --retry 3 --retry-delay 5 -o `"$outPath`" `"$downloadUrl`""
    $proc = Start-Process -FilePath "curl.exe" -ArgumentList $curlArgs -NoNewWindow -PassThru -RedirectStandardError "$outPath.curl.log"

    # Show progress by polling file size
    $lastSize = 0
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 3
        if (Test-Path $outPath) {
            $size = (Get-Item $outPath).Length
            $sizeMB = [math]::Round($size / 1MB, 1)
            if ($size -ne $lastSize) {
                Write-Host "  Progress: $sizeMB MB  `r" -NoNewline
                $lastSize = $size
            }
        }
    }
    Write-Host ""  # newline after progress

    $proc.WaitForExit()
    $exitCode = $proc.ExitCode

    # Clean up curl log
    Remove-Item "$outPath.curl.log" -Force -ErrorAction SilentlyContinue

    # Check file size - curl may return non-zero on connection reset even if download completed
    if (Test-Path $outPath) {
        $size = (Get-Item $outPath).Length
        if ($size -ge $minSize) { $exitCode = 0 }
    }

    if ($exitCode -ne 0) {
        Write-Host "  [FAIL] Download failed (curl exit code $exitCode)" -ForegroundColor Red
        Remove-Item $outPath -Force -ErrorAction SilentlyContinue
        return $false
    }

    if (-not (Test-Path $outPath)) {
        Write-Host "  [FAIL] Output file not created" -ForegroundColor Red
        return $false
    }

    $size = (Get-Item $outPath).Length
    $sizeMB = [math]::Round($size / 1MB, 2)
    Write-Host "  Downloaded: $sizeMB MB"
    if ($size -lt $minSize) {
        Write-Host "  [FAIL] File too small ($size bytes), likely an error page" -ForegroundColor Red
        Remove-Item $outPath -Force -ErrorAction SilentlyContinue
        return $false
    }
    return $true
}

function Extract-Zip($zipPath, $destDir) {
    Write-Host "  Extracting to: $destDir"
    # Use tar.exe (ships with Windows 10+) - faster than Expand-Archive
    Push-Location $destDir
    try {
        & tar.exe -xf $zipPath 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) {
            # Fallback to Expand-Archive
            Pop-Location
            Write-Host "  tar failed, trying Expand-Archive..." -ForegroundColor DarkYellow
            Expand-Archive -Path $zipPath -DestinationPath $destDir -Force
            return $true
        }
        Pop-Location
        return $true
    } catch {
        Pop-Location
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

    # Build & install vksplat into vksplat conda env
    Write-Host "Installing vksplat (this compiles C++ extension, may take a few minutes)..."
    $vksplatPy = Join-Path $vksplatDir "vksplat"
    $pipCmd = "pip install -e `"$vksplatPy`" --no-build-isolation"

    # Try to find vksplat conda env python
    $condaPython = $null
    $condaCandidates = @(
        "D:\miniconda3-pbe\envs\vksplat\python.exe",
        "D:\miniconda3\envs\vksplat\python.exe",
        "$env:USERPROFILE\miniconda3\envs\vksplat\python.exe",
        "$env:USERPROFILE\anaconda3\envs\vksplat\python.exe",
        "$env:USERPROFILE\AppData\Local\miniconda3\envs\vksplat\python.exe",
        "$env:USERPROFILE\AppData\Local\anaconda3\envs\vksplat\python.exe",
        "C:\ProgramData\miniconda3\envs\vksplat\python.exe",
        "C:\ProgramData\anaconda3\envs\vksplat\python.exe"
    )
    foreach ($c in $condaCandidates) {
        if (Test-Path $c) { $condaPython = $c; break }
    }

    if ($condaPython) {
        Write-Host "  Using conda env python: $condaPython"
        & $condaPython -m pip install -e $vksplatPy --no-build-isolation 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] vksplat installed successfully" -ForegroundColor Green
        } else {
            Write-Host "[WARN] vksplat install failed. Try manually:" -ForegroundColor Yellow
            Write-Host "       conda activate vksplat"
            Write-Host "       pip install -e tools/vksplat/vksplat --no-build-isolation"
            $failed += "VkSplat-build"
        }
    } else {
        Write-Host "[WARN] vksplat conda env not found. Create it first:" -ForegroundColor Yellow
        Write-Host "       conda create -n vksplat python=3.10 -y"
        Write-Host "       conda activate vksplat"
        Write-Host "       pip install pybind11 setuptools wheel numpy opencv-python tqdm torchmetrics"
        Write-Host "       pip install -e tools/vksplat/vksplat --no-build-isolation"
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
    if (Test-Path $vksplatGit) { Write-Host "     VkSplat: $vksplatDir (source + patch + built)" }
    Write-Host ""
    Write-Host "You can now run: run.bat" -ForegroundColor Cyan
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

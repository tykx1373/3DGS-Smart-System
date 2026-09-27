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
        "https://ghfast.top/https://github.com",
        "https://mirror.ghproxy.com/https://github.com",
        "https://gh.api.99988866.xyz/https://github.com",
        "https://gcore.jsdelivr.net/gh",
        "https://cdn.jsdelivr.net/gh"
    )
    $bestUrl = $githubUrl  # fallback to direct
    $bestTime = [int]::MaxValue

    foreach ($m in $mirrors) {
        # jsdelivr mirrors use a different URL format
        if ($m -match "jsdelivr") {
            # https://github.com/user/repo/releases/download/tag/file -> user/repo@tag/file
            $testUrl = $githubUrl -replace '^https://github.com/([^/]+/[^/]+)/releases/download/([^/]+)/(.+)$', "$m/`$1@`$2/`$3"
        } else {
            $testUrl = $githubUrl -replace '^https://github.com', $m
        }
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

    # Resume support: if partial file exists, continue from where it stopped
    $resumeArg = ""
    if (Test-Path $outPath) {
        $partialSize = (Get-Item $outPath).Length
        if ($partialSize -gt 0 -and $partialSize -lt $minSize) {
            Write-Host "  Resuming from $([math]::Round($partialSize/1MB,1)) MB..."
            $resumeArg = "-C -"
        } elseif ($partialSize -ge $minSize) {
            Write-Host "  [SKIP] File already downloaded completely." -ForegroundColor Yellow
            return $true
        }
    }

    # Start curl with resume support
    $curlArgs = "-L --ssl-no-revoke --retry 5 --retry-delay 3 --connect-timeout 15 --max-time 1800 $resumeArg -o `"$outPath`" `"$downloadUrl`""
    $proc = Start-Process -FilePath "curl.exe" -ArgumentList $curlArgs -NoNewWindow -PassThru -RedirectStandardError "$outPath.curl.log"

    # Show progress by polling file size
    $lastSize = 0
    $stallCount = 0
    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 3
        if (Test-Path $outPath) {
            $size = (Get-Item $outPath).Length
            $sizeMB = [math]::Round($size / 1MB, 1)
            if ($size -ne $lastSize) {
                $speedMBps = if ($lastSize -gt 0) { [math]::Round(($size - $lastSize) / 1MB / 3, 2) } else { 0 }
                $speedStr = if ($speedMBps -gt 0) { " ($speedMBps MB/s)" } else { "" }
                Write-Host "  Progress: $sizeMB MB$speedStr  `r" -NoNewline
                $lastSize = $size
                $stallCount = 0
            } else {
                $stallCount++
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
        $size = if (Test-Path $outPath) { (Get-Item $outPath).Length } else { 0 }
        Write-Host "  [FAIL] Download interrupted. $([math]::Round($size/1MB,1)) MB downloaded." -ForegroundColor Red
        Write-Host "         Re-run this script to resume (supports breakpoint resume)." -ForegroundColor Yellow
        Write-Host "         Or download manually: $url" -ForegroundColor Yellow
        Write-Host "         Put the zip in: $outPath" -ForegroundColor Yellow
        # Keep partial file for resume
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
# COLMAP (choose CUDA or noCUDA based on GPU)
# ----------------------------------------------------------
Write-Section "COLMAP"

function Test-NvidiaGpu {
    try {
        $result = Get-CimInstance -ClassName Win32_VideoController -ErrorAction Stop | Select-Object -ExpandProperty Name
        return ($result -match "NVIDIA|GeForce|RTX|GTX")
    } catch {
        try {
            $result = wmic path win32_VideoController get name 2>$null
            return ($result -match "NVIDIA")
        } catch { return $false }
    }
}

function Install-Colmap($pattern, $targetDirName, $label) {
    $targetDir = Join-Path $toolsDir $targetDirName
    $targetExe = Join-Path $targetDir "COLMAP.bat"

    if (Test-Path $targetExe) {
        Write-Host "[SKIP] COLMAP ($label) already exists: $targetDir" -ForegroundColor Yellow
        return $true
    }

    $release = Get-LatestReleaseAssets "colmap/colmap"
    if (-not $release) { return $false }

    $asset = $release.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
    if (-not $asset) {
        Write-Host "[FAIL] $label asset not found (pattern: $pattern)" -ForegroundColor Red
        return $false
    }

    $assetMB = [math]::Round($asset.size / 1MB, 1)
    Write-Host "Found: $($asset.name) ($assetMB MB)"
    $zipPath = Join-Path $toolsDir $asset.name

    if (-not (Download-File $asset.browser_download_url $zipPath $asset.size)) { return $false }
    if (-not (Extract-Zip $zipPath $toolsDir)) { Remove-Item $zipPath -Force -ErrorAction SilentlyContinue; return $false }
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

    $extracted = Get-ChildItem $toolsDir -Directory | Where-Object { $_.Name -match "colmap" } | Select-Object -First 1
    if ($extracted -and $extracted.FullName -ne $targetDir) {
        if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force }
        Rename-Item $extracted.FullName $targetDir
    }

    if (Test-Path $targetExe) {
        Write-Host "[OK] COLMAP ($label) installed: $targetDir" -ForegroundColor Green
        return $true
    } else {
        Write-Host "[FAIL] COLMAP.bat not found after extraction" -ForegroundColor Red
        return $false
    }
}

$colmapCudaDir = Join-Path $toolsDir "colmap-x64-windows-cuda"
$colmapCudaExe = Join-Path $colmapCudaDir "COLMAP.bat"
$colmapNocudaDir = Join-Path $toolsDir "colmap-x64-windows-nocuda"
$colmapNocudaExe = Join-Path $colmapNocudaDir "COLMAP.bat"

$hasNvidia = Test-NvidiaGpu
if ($hasNvidia) {
    Write-Host "[INFO] NVIDIA GPU detected. CUDA version recommended for faster feature extraction." -ForegroundColor Cyan
    Write-Host "       Choose COLMAP version to download:"
    Write-Host "         1. CUDA version  (recommended, ~360 MB, GPU accelerated)"
    Write-Host "         2. noCUDA version (~200 MB, CPU only, works on all GPUs)"
    Write-Host "         3. Both"
    $choice = Read-Host "Enter 1, 2, or 3 (default: 1)"
    if (-not $choice) { $choice = "1" }

    switch ($choice) {
        "1" { if (-not (Install-Colmap "windows-cuda\.zip$" "colmap-x64-windows-cuda" "CUDA")) { $failed += "COLMAP-CUDA" } }
        "2" { if (-not (Install-Colmap "windows-nocuda\.zip$" "colmap-x64-windows-nocuda" "noCUDA")) { $failed += "COLMAP-noCUDA" } }
        "3" {
            if (-not (Install-Colmap "windows-cuda\.zip$" "colmap-x64-windows-cuda" "CUDA")) { $failed += "COLMAP-CUDA" }
            if (-not (Install-Colmap "windows-nocuda\.zip$" "colmap-x64-windows-nocuda" "noCUDA")) { $failed += "COLMAP-noCUDA" }
        }
        default {
            Write-Host "[WARN] Invalid choice, downloading CUDA version." -ForegroundColor Yellow
            if (-not (Install-Colmap "windows-cuda\.zip$" "colmap-x64-windows-cuda" "CUDA")) { $failed += "COLMAP-CUDA" }
        }
    }
} else {
    Write-Host "[INFO] No NVIDIA GPU detected. Downloading noCUDA version (compatible with all GPUs)." -ForegroundColor Cyan
    if (-not (Install-Colmap "windows-nocuda\.zip$" "colmap-x64-windows-nocuda" "noCUDA")) { $failed += "COLMAP-noCUDA" }
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
# VkSplat (source included in repo, just build & install)
# ----------------------------------------------------------
Write-Section "VkSplat"
$vksplatDir = Join-Path $toolsDir "vksplat"
$vksplatPy = Join-Path $vksplatDir "vksplat"

if (-not (Test-Path (Join-Path $vksplatPy "setup.py"))) {
    Write-Host "[FAIL] VkSplat source not found at $vksplatPy" -ForegroundColor Red
    Write-Host "       Make sure you cloned the repo correctly (source is included)."
    $failed += "VkSplat"
} else {
    Write-Host "[OK] VkSplat source: $vksplatDir" -ForegroundColor Green

    # Build & install vksplat into vksplat conda env
    Write-Host "Installing vksplat (compiles C++ extension, may take a few minutes)..."

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
    Write-Host "     COLMAP (CUDA):   $colmapCudaExe"
    Write-Host "     COLMAP (noCUDA): $colmapNocudaExe"
    $vkgsCheck = Get-ChildItem $toolsDir -Filter "vk_gaussian_splatting.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($vkgsCheck) { Write-Host "     VKGS:   $($vkgsCheck.FullName)" }
    if (Test-Path $vksplatDir) { Write-Host "     VkSplat: $vksplatDir (source + built)" }
    Write-Host ""
    Write-Host "You can now run: run.bat" -ForegroundColor Cyan
    exit 0
} else {
    Write-Host "[FAIL] The following tools failed. Please handle manually:" -ForegroundColor Red
    Write-Host ""
    if ($failed -contains "COLMAP-CUDA" -or $failed -contains "COLMAP-noCUDA") {
        Write-Host "  COLMAP: https://github.com/colmap/colmap/releases"
        if ($failed -contains "COLMAP-CUDA") {
            Write-Host "           CUDA version:  Download COLMAP-x.x.x-windows-cuda.zip -> tools/colmap-x64-windows-cuda/"
        }
        if ($failed -contains "COLMAP-noCUDA") {
            Write-Host "           noCUDA version: Download COLMAP-x.x.x-windows-nocuda.zip -> tools/colmap-x64-windows-nocuda/"
            Write-Host "           (noCUDA works on all GPUs including Intel/AMD integrated)"
        }
        Write-Host ""
    }
    if ($failed -contains "VKGS") {
        Write-Host "  VKGS:   https://github.com/nvpro-samples/vk_gaussian_splatting/releases"
        Write-Host "           Download the latest Windows zip, extract to tools/"
        Write-Host ""
    }
    if ($failed -contains "VkSplat") {
        Write-Host "  VkSplat: Source should be included in the repo at tools/vksplat/"
        Write-Host "           If missing, re-clone the repository."
        Write-Host ""
    }
    Write-Host "  After extracting to tools/, you do NOT need to re-run this script."
    exit 1
}

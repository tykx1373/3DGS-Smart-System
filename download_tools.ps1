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

function Get-MirrorUrls($githubUrl) {
    # Return list of mirror URLs to try in order (direct + mirrors)
    $mirrors = @(
        "https://gh-proxy.com/https://github.com",
        "https://github.moeyy.xyz/https://github.com",
        "https://ghfast.top/https://github.com",
        "https://mirror.ghproxy.com/https://github.com",
        "https://gh.api.99988866.xyz/https://github.com",
        "https://gcore.jsdelivr.net/gh",
        "https://cdn.jsdelivr.net/gh"
    )
    $urls = @()
    # Try mirrors first (faster in China), direct URL as last resort
    foreach ($m in $mirrors) {
        if ($m -match "jsdelivr") {
            $testUrl = $githubUrl -replace '^https://github.com/([^/]+/[^/]+)/releases/download/([^/]+)/(.+)$', "$m/`$1@`$2/`$3"
        } else {
            $testUrl = $githubUrl -replace '^https://github.com', $m
        }
        $urls += $testUrl
    }
    $urls += $githubUrl  # direct URL as fallback
    return $urls
}

function Download-File($url, $outPath, $minSize = 1000000) {
    Write-Host "  Downloading: $url"
    Write-Host "  Save to: $outPath"

    # If already complete, skip
    if (Test-Path $outPath) {
        $existingSize = (Get-Item $outPath).Length
        if ($existingSize -ge $minSize) {
            Write-Host "  [SKIP] File already downloaded completely." -ForegroundColor Yellow
            return $true
        }
    }

    $mirrorUrls = Get-MirrorUrls $url
    Write-Host "  Trying $($mirrorUrls.Count) sources (mirrors + direct)..."

    foreach ($downloadUrl in $mirrorUrls) {
        $label = if ($downloadUrl -eq $url) { "direct" } else { ($downloadUrl -split '/')[2] }
        Write-Host "  Trying: $label"

        # Resume support
        $resumeArg = ""
        if (Test-Path $outPath) {
            $partialSize = (Get-Item $outPath).Length
            if ($partialSize -gt 0 -and $partialSize -lt $minSize) {
                Write-Host "    Resuming from $([math]::Round($partialSize/1MB,1)) MB..."
                $resumeArg = "-C -"
            }
        }

        $curlArgs = "-L --ssl-no-revoke --connect-timeout 10 --max-time 1800 $resumeArg -o `"$outPath`" `"$downloadUrl`""
        $proc = Start-Process -FilePath "curl.exe" -ArgumentList $curlArgs -NoNewWindow -PassThru -RedirectStandardError "$outPath.curl.log"

        # Monitor speed - kill and switch if too slow
        $lastSize = 0
        $slowCount = 0
        $startTime = Get-Date
        while (-not $proc.HasExited) {
            Start-Sleep -Seconds 5
            if (Test-Path $outPath) {
                $size = (Get-Item $outPath).Length
                $sizeMB = [math]::Round($size / 1MB, 1)
                $delta = $size - $lastSize
                $speedMBps = [math]::Round($delta / 1MB / 5, 2)
                $speedStr = if ($speedMBps -gt 0) { " ($speedMBps MB/s)" } else { "" }
                Write-Host "    Progress: $sizeMB MB$speedStr  `r" -NoNewline
                $lastSize = $size

                # If downloaded less than 2MB in last 5s (after 15s warmup), switch mirror
                $elapsed = (Get-Date) - $startTime
                if ($elapsed.TotalSeconds -gt 15 -and $delta -lt 2MB) {
                    $slowCount++
                    if ($slowCount -ge 2) {
                        Write-Host ""
                        Write-Host "    Too slow ($speedMBps MB/s), switching..." -ForegroundColor DarkYellow
                        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                        break
                    }
                } else {
                    $slowCount = 0
                }
            }
        }
        Write-Host ""

        if (-not $proc.HasExited) {
            $proc.WaitForExit()
        }
        $exitCode = $proc.ExitCode
        Remove-Item "$outPath.curl.log" -Force -ErrorAction SilentlyContinue

        # Check if download completed
        if (Test-Path $outPath) {
            $size = (Get-Item $outPath).Length
            if ($size -ge $minSize) {
                $sizeMB = [math]::Round($size / 1MB, 2)
                Write-Host "  [OK] Downloaded: $sizeMB MB via $label" -ForegroundColor Green
                return $true
            }
        }

        # Not complete, try next mirror
        $size = if (Test-Path $outPath) { [math]::Round((Get-Item $outPath).Length / 1MB, 1) } else { 0 }
        Write-Host "    Incomplete ($size MB), trying next source..." -ForegroundColor DarkYellow
    }

    # All mirrors failed
    $size = if (Test-Path $outPath) { [math]::Round((Get-Item $outPath).Length / 1MB, 1) } else { 0 }
    Write-Host "  [FAIL] All sources failed. $size MB downloaded." -ForegroundColor Red
    Write-Host "         Or download manually: $url" -ForegroundColor Yellow
    Write-Host "         Put the zip in: $outPath" -ForegroundColor Yellow
    return $false
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

    # If user manually placed the zip, use it directly (skip download)
    if (Test-Path $zipPath) {
        $existingSize = (Get-Item $zipPath).Length
        if ($existingSize -ge $asset.size * 0.9) {
            Write-Host "[SKIP] Zip already exists: $zipPath ($([math]::Round($existingSize/1MB,1)) MB)" -ForegroundColor Yellow
        } else {
            Write-Host "[WARN] Existing zip too small ($([math]::Round($existingSize/1MB,1)) MB), re-downloading..." -ForegroundColor Yellow
            Remove-Item $zipPath -Force
            if (-not (Download-File $asset.browser_download_url $zipPath $asset.size)) { return $false }
        }
    } else {
        if (-not (Download-File $asset.browser_download_url $zipPath $asset.size)) { return $false }
    }

    if (-not (Extract-Zip $zipPath $toolsDir)) {
        Write-Host "  Keep zip for retry: $zipPath" -ForegroundColor Yellow
        return $false
    }

    # Match extracted dir by pattern (cuda/nocuda) to avoid mismatching
    $extracted = Get-ChildItem $toolsDir -Directory | Where-Object { $_.Name -match $pattern } | Select-Object -First 1
    if (-not $extracted) {
        # Fallback: match any colmap dir that doesn't match the other version
        $otherPattern = if ($pattern -match "cuda") { "nocuda" } else { "cuda" }
        $extracted = Get-ChildItem $toolsDir -Directory | Where-Object { $_.Name -match "colmap" -and $_.Name -notmatch $otherPattern } | Select-Object -First 1
    }

    if ($extracted -and $extracted.FullName -ne $targetDir) {
        if (Test-Path $targetDir) { Remove-Item $targetDir -Recurse -Force }
        Rename-Item $extracted.FullName $targetDir
        Write-Host "  Renamed '$($extracted.Name)' -> '$targetDirName'"
    }

    # Clean up zip after successful extraction
    Remove-Item $zipPath -Force -ErrorAction SilentlyContinue

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

            # Reuse manually placed zip
            $zipOk = $false
            if (Test-Path $zipPath) {
                $existingSize = (Get-Item $zipPath).Length
                if ($existingSize -ge $asset.size * 0.9) {
                    Write-Host "[SKIP] Zip already exists: $zipPath ($([math]::Round($existingSize/1MB,1)) MB)" -ForegroundColor Yellow
                    $zipOk = $true
                } else {
                    Write-Host "[WARN] Existing zip too small, re-downloading..." -ForegroundColor Yellow
                    Remove-Item $zipPath -Force
                }
            }
            if (-not $zipOk) {
                if (Download-File $asset.browser_download_url $zipPath $asset.size) { $zipOk = $true }
            }

            if ($zipOk) {
                if (Extract-Zip $zipPath $toolsDir) {
                    $exe = Get-ChildItem $toolsDir -Filter "vk_gaussian_splatting.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
                    if ($exe) {
                        Write-Host "[OK] VKGS installed: $($exe.FullName)" -ForegroundColor Green
                        Remove-Item $zipPath -Force -ErrorAction SilentlyContinue
                    } else {
                        Write-Host "[FAIL] vk_gaussian_splatting.exe not found after extraction" -ForegroundColor Red
                        Write-Host "  Keep zip for retry: $zipPath" -ForegroundColor Yellow
                        $failed += "VKGS"
                    }
                } else {
                    Write-Host "  Keep zip for retry: $zipPath" -ForegroundColor Yellow
                    $failed += "VKGS"
                }
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

    # Find mamba/conda executable (prefer mamba for speed)
    $mambaExe = $null
    $condaBase = $null

    # Strategy 1: search PATH (Get-Command, no NativeCommandError noise)
    foreach ($cmd in @("mamba", "conda")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) {
            $mambaExe = $found.Source
            $condaBase = Split-Path (Split-Path $found.Source -Parent) -Parent
            break
        }
    }

    # Strategy 2: search registry (conda writes install path to registry)
    if (-not $mambaExe) {
        $regPaths = @(
            "HKCU:\Software\Python\ContinuumAnalytics",
            "HKLM:\Software\Python\ContinuumAnalytics",
            "HKCU:\Software\Python\Conda",
            "HKLM:\Software\Python\Conda"
        )
        foreach ($rp in $regPaths) {
            if (Test-Path $rp) {
                Get-ChildItem $rp -ErrorAction SilentlyContinue | ForEach-Object {
                    $installPath = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).InstallPath
                    if ($installPath -and (Test-Path (Join-Path $installPath "Scripts\mamba.exe"))) {
                        $mambaExe = Join-Path $installPath "Scripts\mamba.exe"
                        $condaBase = $installPath
                    } elseif ($installPath -and (Test-Path (Join-Path $installPath "Scripts\conda.exe"))) {
                        $mambaExe = Join-Path $installPath "Scripts\conda.exe"
                        $condaBase = $installPath
                    }
                }
                if ($mambaExe) { break }
            }
        }
    }

    # Strategy 3: common install paths
    if (-not $mambaExe) {
        $condaBaseCandidates = @(
            "C:\mambaforge", "C:\miniforge3", "C:\miniconda3", "C:\anaconda3",
            "D:\mambaforge", "D:\miniforge3", "D:\miniconda3-pbe", "D:\miniconda3", "D:\anaconda3",
            "$env:USERPROFILE\mambaforge", "$env:USERPROFILE\miniforge3",
            "$env:USERPROFILE\miniconda3", "$env:USERPROFILE\anaconda3",
            "$env:USERPROFILE\AppData\Local\mambaforge",
            "$env:USERPROFILE\AppData\Local\miniforge3",
            "$env:USERPROFILE\AppData\Local\miniconda3",
            "$env:USERPROFILE\AppData\Local\anaconda3",
            "C:\ProgramData\mambaforge", "C:\ProgramData\miniforge3",
            "C:\ProgramData\miniconda3", "C:\ProgramData\anaconda3"
        )
        foreach ($base in $condaBaseCandidates) {
            $mamba = Join-Path $base "Scripts\mamba.exe"
            $conda = Join-Path $base "Scripts\conda.exe"
            if (Test-Path $mamba) { $mambaExe = $mamba; $condaBase = $base; break }
            elseif (Test-Path $conda) { $mambaExe = $conda; $condaBase = $base; break }
        }
    }

    # Project-local env path (preferred - self-contained, predictable)
    $projectEnvPython = Join-Path $PSScriptRoot "env\vksplat\python.exe"

    # Try to find vksplat conda env python
    $condaPython = $null
    # First priority: project-local env
    if (Test-Path $projectEnvPython) { $condaPython = $projectEnvPython }
    # Second: use the detected conda base path
    if (-not $condaPython -and $condaBase) {
        $p = Join-Path $condaBase "envs\vksplat\python.exe"
        if (Test-Path $p) { $condaPython = $p }
    }
    # Fallback: common paths
    if (-not $condaPython) {
        $condaCandidates = @(
            "$env:USERPROFILE\.conda\envs\vksplat\python.exe",
            "C:\mambaforge\envs\vksplat\python.exe",
            "C:\miniforge3\envs\vksplat\python.exe",
            "C:\miniconda3\envs\vksplat\python.exe",
            "C:\anaconda3\envs\vksplat\python.exe",
            "D:\mambaforge\envs\vksplat\python.exe",
            "D:\miniforge3\envs\vksplat\python.exe",
            "D:\miniconda3-pbe\envs\vksplat\python.exe",
            "D:\miniconda3\envs\vksplat\python.exe",
            "D:\anaconda3\envs\vksplat\python.exe",
            "$env:USERPROFILE\mambaforge\envs\vksplat\python.exe",
            "$env:USERPROFILE\miniforge3\envs\vksplat\python.exe",
            "$env:USERPROFILE\miniconda3\envs\vksplat\python.exe",
            "$env:USERPROFILE\anaconda3\envs\vksplat\python.exe",
            "$env:USERPROFILE\AppData\Local\mambaforge\envs\vksplat\python.exe",
            "$env:USERPROFILE\AppData\Local\miniforge3\envs\vksplat\python.exe",
            "$env:USERPROFILE\AppData\Local\miniconda3\envs\vksplat\python.exe",
            "$env:USERPROFILE\AppData\Local\anaconda3\envs\vksplat\python.exe",
            "C:\ProgramData\mambaforge\envs\vksplat\python.exe",
            "C:\ProgramData\miniforge3\envs\vksplat\python.exe",
            "C:\ProgramData\miniconda3\envs\vksplat\python.exe",
            "C:\ProgramData\anaconda3\envs\vksplat\python.exe"
        )
        foreach ($c in $condaCandidates) {
            if (Test-Path $c) { $condaPython = $c; break }
        }
    }

    # If env doesn't exist, create it in project-local env/ directory
    if (-not $condaPython) {
        if ($mambaExe) {
            $managerName = if ($mambaExe -match "mamba") { "mamba" } else { "conda" }

            # Configure conda-forge mirror (Tsinghua) for faster downloads in China
            # Use cmd /c to avoid PowerShell NativeCommandError on stderr
            Write-Host "Configuring conda-forge mirror (Tsinghua)..."
            cmd /c "$mambaExe config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge/ 2>nul"
            cmd /c "$mambaExe config --remove channels defaults 2>nul"
            cmd /c "$mambaExe config --set show_channel_urls yes 2>nul"

            $envPrefix = Join-Path $PSScriptRoot "env\vksplat"
            Write-Host "Creating vksplat environment at env\vksplat (using $managerName)..."
            cmd /c "$mambaExe env create --prefix `"$envPrefix`" -f environment.yaml -y --quiet 2>&1" 2>&1 | ForEach-Object { Write-Host "  $_" }
            # Re-find python after env creation (project-local first)
            if (Test-Path $projectEnvPython) { $condaPython = $projectEnvPython }
            if (-not $condaPython) {
                foreach ($c in $condaCandidates) {
                    if (Test-Path $c) { $condaPython = $c; break }
                }
            }
        } else {
            Write-Host "[WARN] No conda/mamba found. Install Miniforge first:" -ForegroundColor Yellow
            Write-Host "       https://github.com/conda-forge/miniforge"
            $failed += "VkSplat-env"
        }
    }

    if ($condaPython) {
        Write-Host "  Using env python: $condaPython"
        Write-Host "  Installing vksplat (compiles C++ extension, may take a few minutes)..."
        cmd /c "`"$condaPython`" -m pip install -e `"$vksplatPy`" --no-build-isolation 2>&1" 2>&1 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] vksplat installed successfully" -ForegroundColor Green
        } else {
            Write-Host "[WARN] vksplat install failed. Try manually:" -ForegroundColor Yellow
            Write-Host "       pip install -e tools/vksplat/vksplat --no-build-isolation"
            $failed += "VkSplat-build"
        }
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

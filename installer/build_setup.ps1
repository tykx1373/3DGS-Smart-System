<#
.SYNOPSIS
    Build the 3DGS Quick Pipeline setup.exe installer.
.DESCRIPTION
    1) Build the console-less launcher 3DGS-Studio.exe with PyInstaller
       (using the portable Python env)
    2) Stage the launcher at the repo root (Inno Setup picks it up there)
    3) Compile installer\setup.iss with ISCC
    4) Remove the staged copy; output installer\output\3DGS-Studio-Setup-2.0.0.exe

    NOTE: this script must stay ASCII-only without BOM. Windows PowerShell 5.1
    decodes BOM-less .ps1 files as ANSI; any non-ASCII byte would turn into
    mojibake (tests/test_repo_rules.py enforces this).
.PARAMETER SkipLauncherBuild
    Reuse installer\dist\3DGS-Studio.exe instead of rebuilding it.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File installer\build_setup.ps1
#>
[CmdletBinding()]
param(
    [switch]$SkipLauncherBuild
)

$ErrorActionPreference = 'Stop'
$InstallerDir = $PSScriptRoot
$RepoRoot = Resolve-Path (Join-Path $InstallerDir '..')
$PyExe = Join-Path $RepoRoot 'env\vksplat\python.exe'
$StagingExe = Join-Path $RepoRoot '3DGS-Studio.exe'
$BuiltExe = Join-Path $InstallerDir 'dist\3DGS-Studio.exe'
$SetupScript = Join-Path $InstallerDir 'setup.iss'

Write-Host '== [1/4] Environment check ==' -ForegroundColor Cyan
if (-not (Test-Path $PyExe)) { throw "Portable Python not found: $PyExe" }
if (-not (Test-Path $SetupScript)) { throw "Setup script not found: $SetupScript" }

# Locate ISCC (common install locations + PATH)
$isccCandidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 7\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:USERPROFILE '.local\share\InnoSetup7\ISCC.exe')
)
$cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
if ($cmd) { $isccCandidates = @($cmd.Source) + $isccCandidates }
$Iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $Iscc) {
    throw 'Inno Setup compiler ISCC.exe not found. Install Inno Setup 6/7: https://jrsoftware.org/isdl.php'
}
Write-Host "ISCC: $Iscc"

try {
    if ($SkipLauncherBuild) {
        Write-Host '== [2/4] Skipping launcher build (-SkipLauncherBuild) ==' -ForegroundColor Cyan
    } else {
        Write-Host '== [2/4] Building launcher with PyInstaller ==' -ForegroundColor Cyan
        Push-Location $InstallerDir
        try {
            & $PyExe -m PyInstaller --clean --noconfirm launcher.spec
            if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed' }
        } finally {
            Pop-Location
        }
    }
    if (-not (Test-Path $BuiltExe)) { throw "Launcher build output missing: $BuiltExe" }

    Write-Host '== [3/4] Staging launcher at repo root ==' -ForegroundColor Cyan
    Copy-Item $BuiltExe $StagingExe -Force

    Write-Host '== [4/4] Compiling with Inno Setup (~3 GB input, LZMA2, 10-40 min) ==' -ForegroundColor Cyan
    & $Iscc $SetupScript
    if ($LASTEXITCODE -ne 0) { throw "ISCC compilation failed (exit code $LASTEXITCODE)" }
} finally {
    if (Test-Path $StagingExe) {
        Remove-Item $StagingExe -Force
        Write-Host 'Removed staged launcher copy from repo root' -ForegroundColor DarkGray
    }
}

$out = Join-Path $InstallerDir 'output\3DGS-Studio-Setup-2.0.0.exe'
if (Test-Path $out) {
    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host ''
    Write-Host "Build succeeded: $out ($mb MB)" -ForegroundColor Green
} else {
    throw 'Compilation finished but output file is missing'
}

<#
.SYNOPSIS
    构建 3DGS 快速管线 setup.exe 安装包。
.DESCRIPTION
    1) 用便携环境中的 PyInstaller 重新构建无控制台启动器 3DGS-Studio.exe
    2) 把启动器临时放到仓库根（供 Inno Setup 打包）
    3) 调用 ISCC 编译 installer\setup.iss
    4) 清理临时副本，输出 installer\output\3DGS-Studio-Setup-2.0.0.exe
.PARAMETER SkipLauncherBuild
    跳过 PyInstaller 构建，直接使用 installer\dist\3DGS-Studio.exe。
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

Write-Host '== [1/4] 环境检查 ==' -ForegroundColor Cyan
if (-not (Test-Path $PyExe)) { throw "未找到便携 Python：$PyExe" }
if (-not (Test-Path $SetupScript)) { throw "未找到 $SetupScript" }

# 查找 ISCC（常见安装位置 + PATH）
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
    throw '未找到 Inno Setup 编译器 ISCC.exe，请先安装 Inno Setup 6/7：https://jrsoftware.org/isdl.php'
}
Write-Host "ISCC: $Iscc"

try {
    if ($SkipLauncherBuild) {
        Write-Host '== [2/4] 跳过启动器构建（-SkipLauncherBuild）==' -ForegroundColor Cyan
    } else {
        Write-Host '== [2/4] PyInstaller 构建启动器 ==' -ForegroundColor Cyan
        Push-Location $InstallerDir
        try {
            & $PyExe -m PyInstaller --clean --noconfirm launcher.spec
            if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败' }
        } finally {
            Pop-Location
        }
    }
    if (-not (Test-Path $BuiltExe)) { throw "未找到构建产物：$BuiltExe" }

    Write-Host '== [3/4] 暂存启动器到仓库根 ==' -ForegroundColor Cyan
    Copy-Item $BuiltExe $StagingExe -Force

    Write-Host '== [4/4] Inno Setup 编译（3 GB 输入，LZMA2 压缩约需 10-40 分钟）==' -ForegroundColor Cyan
    & $Iscc $SetupScript
    if ($LASTEXITCODE -ne 0) { throw "ISCC 编译失败（退出码 $LASTEXITCODE）" }
} finally {
    if (Test-Path $StagingExe) {
        Remove-Item $StagingExe -Force
        Write-Host '已清理仓库根临时启动器副本' -ForegroundColor DarkGray
    }
}

$out = Join-Path $InstallerDir 'output\3DGS-Studio-Setup-2.0.0.exe'
if (Test-Path $out) {
    $mb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host ''
    Write-Host "构建成功：$out ($mb MB)" -ForegroundColor Green
} else {
    throw '编译结束但未找到输出文件'
}

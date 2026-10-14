# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：构建无控制台单文件启动器 3DGS-Studio.exe。

构建（在仓库根目录执行）：
    env\\vksplat\\python.exe -m PyInstaller --clean --noconfirm installer\\launcher.spec
产物：dist\\launcher\\3DGS-Studio.exe（onefile，约 10 MB）
"""
import os

block_cipher = None

# 版本元数据由 build_setup.ps1 从 version_info.txt 模板生成；
# 手动直接跑 PyInstaller 时该文件不存在，则不带版本资源（不影响功能）
_version_file = 'build_version_info.txt'
if not os.path.exists(_version_file):
    _version_file = None

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 启动器只用标准库，主动排除 PySide6/torch 等大包，保持体积最小
    excludes=['PySide6', 'PySide2', 'PyQt5', 'PyQt6', 'shiboken6',
              'torch', 'torchvision', 'numpy', 'cv2', 'PIL', 'qfluentwidgets'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='3DGS-Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 程序，无黑色控制台窗口
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',         # Fluent 风格应用图标（快捷方式/任务栏显示）
    version=_version_file,  # exe 属性页的版本/产品信息（可为 None）
)

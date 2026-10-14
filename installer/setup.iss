; -*- coding: utf-8 -*-
; 3DGS 快速管线 —— Inno Setup 安装脚本
; 构建：installer\build_setup.ps1（会先用 PyInstaller 生成根目录启动器）
; 或手动：iscc installer\setup.iss（需先把 3DGS-Studio.exe 放到仓库根）

#define MyAppName "3DGS 快速管线"
; 版本号单一来源是 build_setup.ps1 的 $AppVersion（通过 /DMyAppVersion= 传入）；
; 直接用 ISCC 编译时用此处默认值
#ifndef MyAppVersion
  #define MyAppVersion "2.0.0"
#endif
#define MyAppPublisher "3DGS Studio"
#define MyAppExeName "3DGS-Studio.exe"
; 打包源 = 仓库根（iss 在 installer\ 下）
#define SrcRoot "..\"

[Setup]
AppId={{756EB930-5A16-481B-9199-E16CB1ECB64C
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={userappdata}\3DGS-Studio
DefaultGroupName=3DGS 快速管线
DisableProgramGroupPage=yes
LicenseFile=licenses\wizard_license.txt
SetupIconFile=app.ico
; 免管理员：安装到当前用户目录
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=output
OutputBaseFilename=3DGS-Studio-windows-x64-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
AppCopyright=Copyright (C) 2026；自有代码 Apache-2.0，随附第三方开源组件
; 覆盖安装时提示关闭正在运行的程序（不强杀，重启安装器后自动恢复）
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "在桌面创建快捷方式"; GroupDescription: "附加快捷方式："

[Types]
Name: "full"; Description: "完整安装（推荐）"
Name: "compact"; Description: "精简安装（不含示例数据集）"
Name: "custom"; Description: "自定义安装"; Flags: iscustom

[Components]
Name: "samples"; Description: "示例数据集 south-building（约 223 MB，装完可直接跑通完整流程）"; Types: full

[Dirs]
; 用户数据目录：卸载时永不删除
Name: "{app}\workspaces"; Flags: uninsneveruninstall
Name: "{app}\outputs"; Flags: uninsneveruninstall
Name: "{app}\logs"; Flags: uninsneveruninstall

[Files]
; ---- 启动器（build_setup.ps1 构建后复制到仓库根）----
Source: "{#SrcRoot}{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

; ---- 根目录只保留面向用户的文件 ----
; doctor.py 必须保留：GUI「导出诊断包」功能会以子进程方式调用 doctor.py --json；
; run.bat / download_tools.* / environment.yaml / ROADMAP.md 是开发环境脚手架，不分发；
; tests/ docs/ 同为开发产物，不分发。
Source: "{#SrcRoot}doctor.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SrcRoot}LICENSE"; DestDir: "{app}"; Flags: ignoreversion

; ---- 许可证与第三方声明 ----
Source: "licenses\*"; DestDir: "{app}\licenses"; Flags: recursesubdirs createallsubdirs ignoreversion

; ---- 应用代码与工具链 ----
Source: "{#SrcRoot}gui\*"; DestDir: "{app}\gui"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__,*.pyc,*.pyo,quick_gui_config.json"
; tools 裁剪：COLMAP 测试程序/静态库、vksplat 的 C++/slang 源码与内置 web viewer、
; cp311 双版本绑定（便携环境为 cp310）、VKGS 空日志
Source: "{#SrcRoot}tools\*"; DestDir: "{app}\tools"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__,*.pyc,*.pyo,*.pdb,*.lib,*_test.exe,*.log,RUN_TESTS.bat,vksplat\vksplat\src,vksplat\vksplat\slang,vksplat\vksplat\viewer,*.cp311-win_amd64.pyd,log_vk_gaussian_splatting.txt"
Source: "{#SrcRoot}sample\*"; DestDir: "{app}\sample"; Flags: recursesubdirs createallsubdirs ignoreversion; Components: samples

; ---- 便携 conda 环境 ----
; 裁剪策略：
;   1) 全局排除 __pycache__/*.pyc/*.lib/*.pdb（链接库与调试符号运行时不需要）
;   2) 排除 conda/Python 开发物：头文件、conda-meta、Scripts、IDLE、标准库测试
;   3) PySide6 只保留 GUI 实际 import 的 QtCore/QtGui/QtWidgets：
;      去掉 WebEngine（约 250 MB）、Qml/Quick/3D、Multimedia、Pdf 等 DLL，
;      以及对应模块的 56 个 .pyd（其 DLL 已删，留着也是死文件）、非必要插件目录
Source: "{#SrcRoot}env\*"; DestDir: "{app}\env"; Flags: recursesubdirs createallsubdirs ignoreversion; Excludes: "__pycache__,*.pyc,*.pyo,*.lib,*.pdb,vksplat\conda-meta,vksplat\Scripts,vksplat\Tools,vksplat\include,vksplat\libs,vksplat\Library\include,vksplat\Library\share\doc,vksplat\Lib\idlelib,vksplat\Lib\test,vksplat\Lib\site-packages\torch\include,vksplat\Lib\site-packages\PySide6\qml,vksplat\Lib\site-packages\PySide6\resources,vksplat\Lib\site-packages\PySide6\metatypes,vksplat\Lib\site-packages\PySide6\include,vksplat\Lib\site-packages\PySide6\typesystems,vksplat\Lib\site-packages\PySide6\glue,vksplat\Lib\site-packages\PySide6\scripts,vksplat\Lib\site-packages\PySide6\doc,vksplat\Lib\site-packages\PySide6\support,vksplat\Lib\site-packages\PySide6\QtAsyncio,vksplat\Lib\site-packages\PySide6\translations,vksplat\Lib\site-packages\PySide6\Qt6WebEngine*.dll,vksplat\Lib\site-packages\PySide6\Qt6Pdf*.dll,vksplat\Lib\site-packages\PySide6\Qt6Quick*.dll,vksplat\Lib\site-packages\PySide6\Qt6Qml*.dll,vksplat\Lib\site-packages\PySide6\Qt6Quick3D*.dll,vksplat\Lib\site-packages\PySide6\Qt63D*.dll,vksplat\Lib\site-packages\PySide6\Qt6Designer*.dll,vksplat\Lib\site-packages\PySide6\Qt6Charts.dll,vksplat\Lib\site-packages\PySide6\Qt6Graphs*.dll,vksplat\Lib\site-packages\PySide6\Qt6DataVisualization.dll,vksplat\Lib\site-packages\PySide6\Qt6Multimedia*.dll,vksplat\Lib\site-packages\PySide6\Qt6SpatialAudio.dll,vksplat\Lib\site-packages\PySide6\Qt6Bluetooth.dll,vksplat\Lib\site-packages\PySide6\Qt6RemoteObjects.dll,vksplat\Lib\site-packages\PySide6\Qt6DBus.dll,vksplat\Lib\site-packages\PySide6\Qt6Location.dll,vksplat\Lib\site-packages\PySide6\Qt6Nfc.dll,vksplat\Lib\site-packages\PySide6\Qt6Sensors*.dll,vksplat\Lib\site-packages\PySide6\Qt6SerialPort.dll,vksplat\Lib\site-packages\PySide6\Qt6SerialBus.dll,vksplat\Lib\site-packages\PySide6\Qt6Sql.dll,vksplat\Lib\site-packages\PySide6\Qt6Test.dll,vksplat\Lib\site-packages\PySide6\Qt6Help.dll,vksplat\Lib\site-packages\PySide6\Qt6PrintSupport.dll,vksplat\Lib\site-packages\PySide6\Qt6ShaderTools.dll,vksplat\Lib\site-packages\PySide6\Qt6TextToSpeech.dll,vksplat\Lib\site-packages\PySide6\Qt6VirtualKeyboard.dll,vksplat\Lib\site-packages\PySide6\Qt6WebChannel.dll,vksplat\Lib\site-packages\PySide6\Qt6WebSockets.dll,vksplat\Lib\site-packages\PySide6\Qt6WebView*.dll,vksplat\Lib\site-packages\PySide6\Qt6Network*.dll,vksplat\Lib\site-packages\PySide6\Qt6HttpServer.dll,vksplat\Lib\site-packages\PySide6\Qt6JsonRpc.dll,vksplat\Lib\site-packages\PySide6\Qt6LanguageServer*.dll,vksplat\Lib\site-packages\PySide6\Qt6Protobuf*.dll,vksplat\Lib\site-packages\PySide6\Qt6Grpc*.dll,vksplat\Lib\site-packages\PySide6\Qt6UiTools.dll,vksplat\Lib\site-packages\PySide6\Qt6UiPlugin.dll,vksplat\Lib\site-packages\PySide6\Qt6DeviceDiscoverySupport.dll,vksplat\Lib\site-packages\PySide6\Qt6Egl*.dll,vksplat\Lib\site-packages\PySide6\Qt6OpenSsl*.dll,vksplat\Lib\site-packages\PySide6\Qt6Core5Compat.dll,vksplat\Lib\site-packages\PySide6\Qt6Ax*.dll,vksplat\Lib\site-packages\PySide6\Qt3D*.pyd,vksplat\Lib\site-packages\PySide6\QtAxContainer.pyd,vksplat\Lib\site-packages\PySide6\QtBluetooth.pyd,vksplat\Lib\site-packages\PySide6\QtCharts.pyd,vksplat\Lib\site-packages\PySide6\QtConcurrent.pyd,vksplat\Lib\site-packages\PySide6\QtDataVisualization.pyd,vksplat\Lib\site-packages\PySide6\QtDBus.pyd,vksplat\Lib\site-packages\PySide6\QtDesigner.pyd,vksplat\Lib\site-packages\PySide6\QtExampleIcons.pyd,vksplat\Lib\site-packages\PySide6\QtGraphs*.pyd,vksplat\Lib\site-packages\PySide6\QtHelp.pyd,vksplat\Lib\site-packages\PySide6\QtHttpServer.pyd,vksplat\Lib\site-packages\PySide6\QtLocation.pyd,vksplat\Lib\site-packages\PySide6\QtMultimedia*.pyd,vksplat\Lib\site-packages\PySide6\QtNetwork*.pyd,vksplat\Lib\site-packages\PySide6\QtNfc.pyd,vksplat\Lib\site-packages\PySide6\QtOpenGL*.pyd,vksplat\Lib\site-packages\PySide6\QtPdf*.pyd,vksplat\Lib\site-packages\PySide6\QtPositioning.pyd,vksplat\Lib\site-packages\PySide6\QtPrintSupport.pyd,vksplat\Lib\site-packages\PySide6\QtQml*.pyd,vksplat\Lib\site-packages\PySide6\QtQuick*.pyd,vksplat\Lib\site-packages\PySide6\QtRemoteObjects.pyd,vksplat\Lib\site-packages\PySide6\QtScxml.pyd,vksplat\Lib\site-packages\PySide6\QtSensors.pyd,vksplat\Lib\site-packages\PySide6\QtSerial*.pyd,vksplat\Lib\site-packages\PySide6\QtSpatialAudio.pyd,vksplat\Lib\site-packages\PySide6\QtSql.pyd,vksplat\Lib\site-packages\PySide6\QtStateMachine.pyd,vksplat\Lib\site-packages\PySide6\QtSvg*.pyd,vksplat\Lib\site-packages\PySide6\QtTest.pyd,vksplat\Lib\site-packages\PySide6\QtTextToSpeech.pyd,vksplat\Lib\site-packages\PySide6\QtUiTools.pyd,vksplat\Lib\site-packages\PySide6\QtWeb*.pyd,vksplat\Lib\site-packages\PySide6\QtXml.pyd,vksplat\Lib\site-packages\PySide6\plugins\assetimporters,vksplat\Lib\site-packages\PySide6\plugins\canbus,vksplat\Lib\site-packages\PySide6\plugins\designer,vksplat\Lib\site-packages\PySide6\plugins\geometryloaders,vksplat\Lib\site-packages\PySide6\plugins\geoservices,vksplat\Lib\site-packages\PySide6\plugins\multimedia,vksplat\Lib\site-packages\PySide6\plugins\networkinformation,vksplat\Lib\site-packages\PySide6\plugins\position,vksplat\Lib\site-packages\PySide6\plugins\qmltooling,vksplat\Lib\site-packages\PySide6\plugins\renderers,vksplat\Lib\site-packages\PySide6\plugins\renderplugins,vksplat\Lib\site-packages\PySide6\plugins\sceneparsers,vksplat\Lib\site-packages\PySide6\plugins\scxmldatamodel,vksplat\Lib\site-packages\PySide6\plugins\sensors,vksplat\Lib\site-packages\PySide6\plugins\sqldrivers,vksplat\Lib\site-packages\PySide6\plugins\texttospeech,vksplat\Lib\site-packages\PySide6\plugins\tls,vksplat\Lib\site-packages\PySide6\plugins\webview"

; Qt 自带中文翻译（标准对话框用），其余约 49 MB 多语言翻译不打包
Source: "{#SrcRoot}env\vksplat\Lib\site-packages\PySide6\translations\qt_zh_CN.qm"; DestDir: "{app}\env\vksplat\Lib\site-packages\PySide6\translations"; Flags: ignoreversion
Source: "{#SrcRoot}env\vksplat\Lib\site-packages\PySide6\translations\qtbase_zh_CN.qm"; DestDir: "{app}\env\vksplat\Lib\site-packages\PySide6\translations"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Comment: "基于 Vulkan 的轻量化三维高斯重建管线"
Name: "{group}\工作区（照片与项目）"; Filename: "{app}\workspaces"
Name: "{group}\模型输出（outputs）"; Filename: "{app}\outputs"
Name: "{group}\使用说明 README"; Filename: "{app}\README.md"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon; Comment: "基于 Vulkan 的轻量化三维高斯重建管线"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; 覆盖安装旧版本时，清掉早期版本曾分发、现已不再打包的开发脚手架/目录
Type: files; Name: "{app}\run.bat"
Type: files; Name: "{app}\download_tools.bat"
Type: files; Name: "{app}\download_tools.ps1"
Type: files; Name: "{app}\environment.yaml"
Type: files; Name: "{app}\ROADMAP.md"
Type: filesandordirs; Name: "{app}\tests"
Type: filesandordirs; Name: "{app}\docs"

[UninstallDelete]
; 程序目录在运行中会生成 __pycache__ 字节码、.syscheck.json 等清单外文件，
; 卸载时一并清扫；workspaces / outputs / logs 是用户数据，绝不在此列出。
Type: files; Name: "{app}\.syscheck.json"
Type: filesandordirs; Name: "{app}\env"
Type: filesandordirs; Name: "{app}\gui"
Type: filesandordirs; Name: "{app}\tools"
Type: filesandordirs; Name: "{app}\docs"
Type: filesandordirs; Name: "{app}\tests"
Type: filesandordirs; Name: "{app}\sample"
Type: filesandordirs; Name: "{app}\licenses"

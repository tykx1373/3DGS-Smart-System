# 3DGS Smart System — 基于 Vulkan 的三维高斯重建与实时渲染

一套面向轻量硬件的 3D Gaussian Splatting (3DGS) 一站式管线：用一组照片自动重建可旋转、可缩放的 3D 模型。

整条链路**全程基于 Vulkan**，不依赖 CUDA，支持 NVIDIA / AMD / Intel 核显等任意 Vulkan 设备。

```
照片文件夹 → COLMAP 稀疏重建 → VkSplat (Vulkan) 训练 → VKGS 实时渲染查看
```

---

## 目录

- [功能特性](#功能特性)
- [普通用户：下载安装包（无需 Python）](#普通用户下载安装包无需-python)
- [开发者：从源码运行](#开发者从源码运行)
- [系统要求](#系统要求)
- [依赖下载与安装](#依赖下载与安装)
- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [工作流程](#工作流程)
- [质量档位](#质量档位)
- [常见问题](#常见问题)
- [许可证](#许可证)

---

## 功能特性

- **一键式管线** — 选照片 → 自动稀疏重建 → 训练 → 打开查看器，全流程 GUI 操作
- **Vulkan 训练** — 基于 [VkSplat](https://github.com/harry7557558/vksplat)，跨厂商 GPU 加速（NVIDIA / AMD / Intel 核显）
- **双 COLMAP 版本** — CUDA 版（N 卡加速）与无 CUDA 版（纯 CPU，通用）可切换
- **实时渲染** — 基于 [VKGS](https://github.com/nvpro-samples/vk_gaussian_splatting)，生成的 PLY 可直接预览
- **智能 GPU 适配** — 自动检测独显/核显，动态调整高斯数量上限与缓存策略，防止核显 TDR 超时
- **三档质量预设** — 快速（5000 步）/ 标准（15000 步）/ 高质量（30000 步）
- **断点续训** — 每 1000 步自动保存进度；训练中断（手动停止/崩溃/断电）后可从断点继续，不必从头再来
- **实时训练进度** — 全程一根进度条：COLMAP 按「正在定位照片 64/128」逐张推进并给剩余时间，训练阶段显示步数、百分比、当前高斯数量；运行日志默认折叠，需要时展开查看
- **安全停止** — 训练中点击「停止」会保存当前进度后干净退出，不损坏数据
- **统一输出命名** — PLY 文件带参数标识，如 `vksplat_15000steps_standard.ply`
- **分享文件** — 训练完成后自动生成体积小得多的 `.splat`（约 PLY 的 1/7），直接把这个文件发给对方就行；本机 VKGS 也能打开它
- **选完照片就检查** — 挑好文件夹立刻在本地看张数够不够、有没有发虚的照片并点名，不用等几十分钟 COLMAP 才听说照片不行
- **拍得好不好，训练前就说** — 照片定位不达标时，直接列出哪几张没对上并给出补拍办法，不会让你白等几十分钟才发现问题
- **出错就讲两句话** — 失败原因和「现在该怎么办」显示在训练页上，附一键导出诊断包，不用去翻折叠的日志
- **日志系统** — GUI 实时显示 + 文件持久化（`logs/YYYYMMDD.log`，自动轮转）

---

## 普通用户：下载安装包（无需 Python）

不想配置环境的用户，直接到 [Releases 页面](https://github.com/tykx1373/3DGS-Smart-System/releases)
下载 `3DGS-Studio-windows-x64-Setup-<版本>.exe`，双击安装即可——
COLMAP、VkSplat、VKGS 和便携 Python 环境已全部内置，无需自行安装任何东西。

- **免管理员安装**：默认装到 `%AppData%\3DGS-Studio`，可自行更改目录；自动创建开始菜单与桌面快捷方式
- **COLMAP 双版本**：纯 CPU 的 noCUDA 版默认必装（任何显卡通用）；检测到 NVIDIA 显卡时会默认勾选 CUDA 加速版（特征提取更快），不需要可在自定义安装中取消
- **示例数据集（可选组件）**：128 张 south-building 照片（约 65 MB，长边 1600），装完可在 GUI 里一键试跑，用来先确认这台机器能出模型
- **卸载自选数据**：卸载时会询问是否同时删除 workspaces / outputs / logs，默认保留
- **系统要求**：Windows 10/11 (x64)、支持 Vulkan 1.3+ 的显卡（NVIDIA / AMD / Intel 核显均可）、8 GB 以上内存（核显建议 16 GB）
- **验证下载**：Releases 页面会显示安装包的 SHA-256，可在 PowerShell 中用
  `Get-FileHash .\3DGS-Studio-windows-x64-Setup-*.exe -Algorithm SHA256` 核对
- **卸载**：开始菜单或"设置 → 应用"中卸载；卸载向导会询问是否一并删除 `workspaces`（照片项目）、`outputs`（生成的模型）、`logs`（日志），默认保留

> **关于 SmartScreen 提示**：当前安装包尚未购买代码签名证书，首次运行时
> Windows 可能弹出"Windows 已保护你的电脑"。点击"更多信息" → "仍要运行"即可；
> 这是未签名软件的标准提示，不代表存在风险。

---

## 开发者：从源码运行

以下章节面向希望从源码运行、修改代码或重新编译 VkSplat 的开发者，
需要自行准备 Python 环境与第三方工具。

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 (x64) |
| GPU | 任意支持 Vulkan 1.3+ 的显卡（独显或核显均可） |
| 内存 | 8 GB 以上（核显建议 16 GB） |
| Python | 3.9 ~ 3.12（推荐 [Miniforge](https://github.com/conda-forge/miniforge) 管理环境，自带 mamba 加速） |
| 编译器 | 无需安装（已包含预编译 VkSplat `.pyd`）。仅当需重新编译时才需要 MSVC v143+ + Vulkan SDK |

---

## 依赖下载与安装

项目仓库**不包含**第三方工具二进制（体积过大），需按以下步骤获取到 `tools/` 目录。

### 方式一：一键下载脚本（推荐）

运行 `download_tools.bat`，自动完成 COLMAP、VKGS、VkSplat 三个工具的获取：

```batch
download_tools.bat
```

脚本会：
- **COLMAP** — 自动检测显卡，智能选择版本：
  - 有 NVIDIA GPU：提示用户选择 CUDA 版（推荐）/ noCUDA 版 / 两者都装
  - 无 NVIDIA GPU：直接下载 noCUDA 版（兼容所有显卡）
- **VKGS** — 从 GitHub Releases 下载最新 Windows 预编译包，自动解压
- **VkSplat** — 源码 + **预编译 `.pyd`** 已包含在仓库中，自动安装（无需编译，无需 Vulkan SDK / MSVC）
- 已存在的工具会自动跳过
- **任意步骤失败时打印手动下载链接**，按提示操作即可
- 支持**断点续传**：下载中断后重新运行脚本即可继续，不会从头开始
- 完成后提示后续 conda 环境创建与 VkSplat 编译命令

> **下载慢怎么办？** COLMAP 约 360MB，国内从 GitHub 下载可能很慢。脚本会：
> 1. 自动尝试多个 GitHub 镜像，速度太慢自动切换到下一个
> 2. 支持断点续传，切换镜像或中断后重跑会从断点继续
> 3. 也可以用浏览器/IDM/迅雷等手动下载 zip，放到 `tools/` 目录下（保持原文件名），重新运行脚本会自动解压
>
> 若脚本运行失败（网络问题、GitHub 访问受限等），请参考下方"方式二：手动下载"。
>
> GUI 也会自动检测显卡类型，选择对应的 COLMAP 版本运行。

### 方式二：手动下载

#### 1. Vulkan SDK（仅重新编译 VkSplat 时需要）

> **默认无需安装。** 仓库已包含 Python 3.10 和 3.11 的预编译 `vksplat.cp*-win_amd64.pyd`，`download_tools.bat` 会自动使用，无需编译。仅当你修改了 VkSplat C++ 源码或使用其他 Python 版本时，才需要安装 Vulkan SDK + MSVC 重新编译。

如需重新编译，下载并安装 [LunarG Vulkan SDK](https://vulkan.lunarg.com/sdk/home#windows) for Windows。

安装后确认环境变量 `VULKAN_SDK` 指向 SDK 根目录（如 `C:\VulkanSDK\1.3.x.x.x`），VkSplat 的 `setup.py` 会自动查找。

#### 2. COLMAP（稀疏重建）

提供两个版本，按需下载其一或全部：

| 版本 | 适用场景 | 下载地址 |
|------|----------|----------|
| `colmap-x64-windows-cuda` | 有 NVIDIA 显卡，GPU 加速特征提取（**只需 NVIDIA 驱动，无需安装 CUDA Toolkit**） | [COLMAP Releases](https://github.com/colmap/colmap/releases)（选 `COLMAP-x.x.x-windows-cuda.zip`） |
| `colmap-x64-windows-nocuda` | 无 NVIDIA 显卡（AMD/Intel 核显），纯 CPU 运行 | 同上（选 `COLMAP-x.x.x-windows-nocuda.zip`） |

> **注意：** COLMAP CUDA 版是预编译二进制，已静态包含 CUDA runtime，用户**不需要安装 CUDA Toolkit**。整个 3DGS 项目的训练和渲染基于 Vulkan（VkSplat），不依赖 CUDA；仅 COLMAP 的特征提取步骤可选 CUDA 加速。

下载后解压到 `tools/`，目录结构应为：

```
tools/
├── colmap-x64-windows-cuda/
│   └── COLMAP.bat
└── colmap-x64-windows-nocuda/
    └── COLMAP.bat
```

#### 3. VKGS（实时渲染查看器）

从 [nvpro-samples/vk_gaussian_splatting Releases](https://github.com/nvpro-samples/vk_gaussian_splatting/releases) 下载最新 Windows 版 zip，解压到 `tools/` 下：

```
tools/
└── vkgs-2026.x.x-windows-64bits/
    └── vk_gaussian_splatting.exe
```

#### 4. VkSplat（Vulkan 训练后端）

VkSplat 源码已**直接包含在仓库中**（`tools/vksplat/`），包含本地定制修改（旋转矩阵对齐、simple_trainer 调整等），无需 submodule 或 patch。

**预编译版本已包含：** `tools/vksplat/vksplat/` 下提供了 `vksplat.cp310-win_amd64.pyd` 和 `vksplat.cp311-win_amd64.pyd`，分别对应 Python 3.10 和 3.11。`download_tools.bat` 会自动检测匹配的版本并直接使用，**无需安装 Vulkan SDK 或 MSVC**。

使用 [Miniforge](https://github.com/conda-forge/miniforge) 从 `environment.yaml` 创建环境并安装。Miniforge 自带 `mamba` 命令（比 `conda` 快约 10 倍）：

```bash
# 从 environment.yaml 创建环境（mamba 比 conda 快 10 倍）
mamba env create -f environment.yaml

# 激活环境
mamba activate vksplat

# 安装 CPU-only PyTorch + torchmetrics（VkSplat 用 Vulkan 而非 CUDA）
pip install torch torchmetrics --index-url https://download.pytorch.org/whl/cpu --extra-index-url https://pypi.org/simple

# 安装 VkSplat（自动使用预编译 .pyd，无需编译）
# 若需重新编译（修改了 C++ 源码），才需要 Vulkan SDK + MSVC
pip install -e tools/vksplat/vksplat --no-build-isolation
```

> 若使用的 Python 版本与预编译 `.pyd` 不匹配，`pip install -e .` 会尝试编译，此时需要安装 Vulkan SDK + MSVC。
> 安装成功后可在 Python 中 `import vksplat` 验证。
>
> 没有 mamba？用 conda 也一样：`conda env create -f environment.yaml`
>
> 以上步骤 `download_tools.bat` 会自动完成，手动安装仅作参考。

最终 `tools/` 目录结构：

```
tools/
├── colmap-x64-windows-cuda/        # COLMAP CUDA 版
├── colmap-x64-windows-nocuda/      # COLMAP 无 CUDA 版
├── vksplat/                        # VkSplat 源码（已 pip install -e）
│   └── vksplat/
│       ├── setup.py
│       ├── src/
│       └── shader/
└── vkgs-2026.x.x-windows-64bits/   # VKGS 查看器
    └── vk_gaussian_splatting.exe
```

---

## 快速开始

### 启动 GUI

双击根目录下的 `run.bat`，脚本会自动查找 `vksplat` conda 环境的 Python 并启动 GUI。

或手动运行：

```bash
conda activate vksplat
python gui/quick_gui.py
```

### 使用流程

1. **选择照片文件夹** — 点击「浏览…」选择一组照片（建议 30~200 张，绕物体一圈拍摄，重叠 60% 以上）
2. **选择质量档位** — 快速 / 标准 / 高质量（见[质量档位](#质量档位)）
3. **开始生成** — 点击「开始生成 3D 模型」，COLMAP 自动做稀疏重建，VkSplat 训练高斯模型；进度条实时显示步数、剩余时间和高斯数量
4. **查看结果** — 训练完成后自动启动 VKGS 查看器，可旋转/缩放预览 3D 模型

> 训练中途可以点击「停止」安全中断：当前进度会自动保存，再次点击「开始」时 GUI 会询问是否从断点继续。

> 第一次用、或想先确认这台机器跑不跑得动：点照片卡片下方的「手边没合适的照片？用内置示例照片试跑一次」，
> 会用随安装包附带的 128 张 south-building 示例照片完整跑一遍（安装时需勾选「示例数据集」组件；
> 没装该组件时这个按钮不会出现）。

> 首次使用建议在「设置」页确认各工具路径正确，然后点「保存设置」。

---

## 目录结构

```
3DGS/
├── run.bat                     # 一键启动脚本（自动查找 vksplat Python 环境）
├── gui/
│   ├── quick_gui.py            # 主 GUI（纯 PySide6，串联 COLMAP → VkSplat → VKGS）
│   ├── qt_theme.py             # Qt 样式表主题与轻量组件（原创，无第三方 UI 库）
│   ├── pipeline_core.py        # 与界面无关的管线核心（COLMAP/训练/产物收取）
│   ├── detect_gpu.py           # Vulkan 设备检测（独显/核显自动适配）
│   └── quick_gui_config.json   # 工具路径配置（首次保存后生成）
├── tools/             # 第三方工具（需自行下载，见上）
│   ├── colmap-x64-windows-cuda/
│   ├── colmap-x64-windows-nocuda/
│   ├── vksplat/
│   └── vkgs-2026.2.9-windows-64bits/
├── workspaces/                 # 运行时生成：COLMAP 中间结果
├── outputs/                    # 运行时生成：VkSplat 训练输出
├── logs/                       # 运行时生成：日志文件（自动轮转）
├── .gitignore
├── LICENSE                     # Apache-2.0
└── README.md
```

---

## 工作流程

GUI 内部按以下步骤执行：

1. **COLMAP 特征提取** — `feature_extractor`，提取 SIFT 特征点
2. **COLMAP 特征匹配** — `exhaustive_matcher`，两两匹配图片
3. **COLMAP 稀疏重建** — `mapper`，恢复相机位姿与稀疏点云
4. **VkSplat 训练** — 读取 COLMAP 的 `sparse/0/`，用 Vulkan 计算训练高斯模型（MCMC 策略）
5. **VKGS 查看** — 启动 `vk_gaussian_splatting.exe` 加载生成的 PLY

输出 PLY 文件命名：`vksplat_<步数>steps_<质量>.ply`，位于对应工作区根目录。

---

## 质量档位

| 档位 | 训练步数 | 预估耗时 | 适用场景 |
|------|----------|----------|----------|
| 快速 | 5,000 | 2~3 分钟 | 快速预览轮廓，验证流程 |
| 标准 | 15,000 | 8~10 分钟 | 日常使用，推荐 |
| 高质量 | 30,000 | 20 分钟+ | 细节最丰富 |

> 默认使用 MCMC 致密化策略（自动增删高斯点，多数场景质量更好）；
> 小场景（<50 张图）偶发不稳定时，可在高级选项中取消"MCMC 优化"改用 Default 策略。
> 核显会自动降低高斯上限（cap_max = 500,000）并使用 CPU 图像缓存，避免 TDR 超时；独显上限为 1,000,000。

---

## 常见问题

**Q: 启动时提示找不到 Python？**
A: 确保已安装 Miniforge（或 Miniconda/Anaconda）并创建了 `vksplat` 环境。`run.bat` 会自动搜索常见安装路径，也可手动编辑 `run.bat` 指定 Python 路径。

**Q: VkSplat 安装失败？**
A: 仓库已包含 Python 3.10/3.11 的预编译 `.pyd`，`download_tools.bat` 会自动使用，无需编译。若你使用了其他 Python 版本或修改了 C++ 源码需要重新编译，请安装 [Vulkan SDK](https://vulkan.lunarg.com/sdk/home) 和 MSVC（Visual Studio Build Tools，勾选"使用 C++ 的桌面开发"），并设置 `VULKAN_SDK` 环境变量。

**Q: 训练时 GPU 超时（TDR）？**
A: 核显用户请确认 cap_max 已自动设为 500,000；若仍超时，可在高级选项中手动降低高斯上限。

**Q: COLMAP 重建失败？**
A: 检查照片是否有足够重叠（建议 60%+），数量不少于 30 张；模糊或无纹理的图片会导致特征点不足。

**Q: 输出的 PLY 用什么打开？**
A: 训练完成后 GUI 会自动用 VKGS 打开；也可手动用 `vk_gaussian_splatting.exe` 或其他支持 3DGS PLY 的查看器打开。

**Q: 弹出「照片检查结果」，说有几张没对上位置怎么办？**
A: 那是训练前的把关：列出的那几张照片没能算出相机位置，通常是重叠不够或画面发虚。点「去补拍」先按提示补一圈照片再重跑；赶时间也可以点「先训练看看」，会用已经定位成功的照片继续训练。照片全部对上时不会打扰你。

**Q: 提示「COLMAP 没能完成这一步」/「COLMAP 自己崩了」怎么办？**
A: 先直接重跑一次。COLMAP 的失败里有相当一部分是偶发的——实测同一批照片第一次崩在特征提取、第二次注册率 100% 正常出模型。反复失败再考虑照片本身（重叠不足、纹理太少），或在「设置」里把 COLMAP 换成 noCUDA 版重试。

**Q: 怎么把模型发给别人？**
A: 训练完成弹窗里点「准备分享文件」，或在「历史模型」页选中模型后点「发给别人」。程序会在 PLY 旁边准备一个体积小得多的 `.splat`（约 1/7），并打开所在文件夹把它选中——把这个文件发给对方即可。对方用支持 `.splat` 的查看器打开，本软件的「查看 3D 模型」选这个文件也能直接打开。注意分享版是固定光照，观感比本机预览平淡一些，模型本体仍是 `.ply`。

**Q: 训练中断了，进度会丢吗？**
A: 不会。训练每 1000 步自动保存 checkpoint；点击「停止」会保存当前精确进度。再次点击「开始生成」时，GUI 会检测到恢复点并询问是否从断点继续。若上次是异常退出（崩溃/断电），进度回退到最近一次自动保存的整千步。

**Q: 怎么确认我装的是哪个版本？**
A: 看窗口标题栏或左侧品牌区，都带版本号（如 `v2.3.1`）；「导出诊断包」生成的报告里也写着。若怀疑装的是旧构建，可核对安装包 SHA-256 与 Releases 页面是否一致。

**Q: 运行日志在哪里看？**
A: GUI 底部有「运行日志」折叠按钮，点击即可展开实时日志；历史日志按天保存在 `logs/` 目录。

---

## 许可证

本项目采用 **Apache License 2.0**，详见 [LICENSE](LICENSE)。

> **Apache-2.0 核心特点**：允许任意使用、修改、分发（包括商业闭源用途），只需保留版权与许可证声明；自带专利授权条款。衍生作品可选择任意许可证，不强制开源。

### 第三方依赖及许可证

| 组件 | 引入方式 | 用途 | 许可证 |
|------|---------|------|--------|
| [COLMAP](https://github.com/colmap/colmap) | 外部进程调用 | 稀疏重建（SfM/MVS） | BSD-3-Clause |
| [VkSplat](https://github.com/harry7557558/vksplat) | 源码内置（`tools/vksplat/`） | 3DGS 训练后端（Vulkan） | Apache-2.0 |
| [VKGS](https://github.com/nvpro-samples/vk_gaussian_splatting) | 外部进程调用 | 实时渲染查看器 | MIT |
| [PySide6](https://www.qt.io/pyside) | Python 依赖 | GUI 框架（Qt 官方 Python 绑定，仅用原生控件 + 自写 QSS） | LGPLv3 |

> 界面只用 PySide6 原生控件和项目自带的 `gui/qt_theme.py` 样式，不依赖 GPLv3 的第三方 UI 组件库；LGPLv3 以动态链接方式使用，允许闭源分发（保留许可证声明、允许用户替换 Qt 库即可）。

各第三方工具的源代码请前往其各自仓库获取。

**VkSplat 修改声明（Apache-2.0 §4(b) 要求）**：本项目对内置的 VkSplat 源码做了以下修改，均已在文件头部标注：

- `vksplat/simple_trainer.py`：新增 PLY 断点保存/恢复、GUI 进度输出（PROGRESS 行）、STOP 文件安全停止
- `vksplat/src/gs_trainer.cpp`：新增世界坐标系对齐旋转，使 COLMAP 位姿与 OpenSplat 约定一致

VkSplat 原始许可证见 [tools/vksplat/LICENSE](tools/vksplat/LICENSE)。

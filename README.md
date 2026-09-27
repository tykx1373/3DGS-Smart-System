# 3DGS Smart System — 基于 Vulkan 的三维高斯重建与实时渲染

一套面向轻量硬件的 3D Gaussian Splatting (3DGS) 一站式管线：用一组照片自动重建可旋转、可缩放的 3D 模型。

整条链路**全程基于 Vulkan**，不依赖 CUDA，支持 NVIDIA / AMD / Intel 核显等任意 Vulkan 设备。

```
照片文件夹 → COLMAP 稀疏重建 → VkSplat (Vulkan) 训练 → VKGS 实时渲染查看
```

---

## 目录

- [功能特性](#功能特性)
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
- **实时渲染** — 基于 [VKGS](https://github.com/limacv/vk_gaussian_splatting)，生成的 PLY 可直接预览
- **智能 GPU 适配** — 自动检测独显/核显，动态调整高斯数量上限与缓存策略，防止核显 TDR 超时
- **三档质量预设** — 快速（5000 步）/ 标准（15000 步）/ 高质量（30000 步）
- **统一输出命名** — PLY 文件带参数标识，如 `vksplat_15000steps_standard.ply`
- **日志系统** — GUI 实时显示 + 文件持久化（`logs/YYYYMMDD.log`，自动轮转）

---

## 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 / 11 (x64) |
| GPU | 任意支持 Vulkan 1.3+ 的显卡（独显或核显均可） |
| 内存 | 8 GB 以上（核显建议 16 GB） |
| Python | 3.9 ~ 3.12（推荐 Miniconda 管理环境） |
| 编译器 | MSVC v143+（Visual Studio 2022），用于编译 VkSplat 的 pybind11 扩展 |

---

## 依赖下载与安装

项目仓库**不包含**第三方工具二进制（体积过大），需按以下步骤自行下载到 `tools/` 目录。

> 推荐先装好 [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 和 [Vulkan SDK](https://vulkan.lunarg.com/sdk/home)，再依次获取三个工具。

### 1. Vulkan SDK（编译 VkSplat 必需）

下载并安装 [LunarG Vulkan SDK](https://vulkan.lunarg.com/sdk/home#windows) for Windows。

安装后确认环境变量 `VULKAN_SDK` 指向 SDK 根目录（如 `C:\VulkanSDK\1.3.x.x.x`），VkSplat 的 `setup.py` 会自动查找。

### 2. COLMAP（稀疏重建）

提供两个版本，按需下载其一或全部：

| 版本 | 适用场景 | 下载地址 |
|------|----------|----------|
| `colmap-x64-windows-cuda` | 有 NVIDIA 显卡，GPU 加速特征提取 | [COLMAP Releases](https://github.com/colmap/colmap/releases)（选 `COLMAP-x.x.x-windows-cuda.zip`） |
| `colmap-x64-windows-nocuda` | 无 NVIDIA 显卡或不想装 CUDA | 同上（选 `COLMAP-x.x.x-windows-nocuda.zip`） |

下载后解压到 `tools/`，目录结构应为：

```
tools/
├── colmap-x64-windows-cuda/
│   └── COLMAP.bat
└── colmap-x64-windows-nocuda/
    └── COLMAP.bat
```

### 3. VkSplat（Vulkan 训练后端，需编译）

VkSplat 已作为 **Git Submodule** 管理，无需手动 clone。

克隆主仓库时加 `--recursive` 自动拉取：

```bash
git clone --recursive https://github.com/tykx1373/3DGS-Smart-System.git
```

如果已经 clone 但忘了加 `--recursive`，执行：

```bash
git submodule update --init --recursive
```

**应用本地修改补丁**（旋转矩阵对齐、simple_trainer 调整等）：

```batch
apply_vksplat_patch.bat
```

创建 conda 环境并编译安装：

```bash
conda create -n vksplat python=3.10 -y
conda activate vksplat

# 安装编译依赖
pip install pybind11 setuptools wheel numpy opencv-python tqdm torchmetrics

# 编译安装 VkSplat（需要 Vulkan SDK + MSVC）
cd "tools/vksplat/vksplat"
pip install -e . --no-build-isolation
```

> 若 `pip install -e .` 报找不到 Vulkan，请确认 `VULKAN_SDK` 环境变量已设置。
> 编译成功后可在 Python 中 `import vksplat` 验证。

### 4. VKGS（实时渲染查看器）

下载预编译版本：[vk_gaussian_splatting Releases](https://github.com/limacv/vk_gaussian_splatting/releases)

解压到 `tools/vkgs-2026.2.9-windows-64bits/`，确保存在 `vk_gaussian_splatting.exe`。

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
└── vkgs-2026.2.9-windows-64bits/   # VKGS 查看器
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
3. **开始生成** — 点击「开始生成 3D 模型」，COLMAP 自动做稀疏重建，VkSplat 训练高斯模型
4. **查看结果** — 训练完成后自动启动 VKGS 查看器，可旋转/缩放预览 3D 模型

> 首次使用建议在「高级选项」中确认各工具路径正确，然后点「保存路径」。

---

## 目录结构

```
3DGS/
├── run.bat                     # 一键启动脚本（自动查找 vksplat Python 环境）
├── gui/
│   ├── quick_gui.py            # 主 GUI（串联 COLMAP → VkSplat → VKGS）
│   ├── detect_gpu.py           # Vulkan 设备检测（独显/核显自动适配）
│   └── quick_gui_config.json   # 工具路径配置（首次保存后生成）
├── docs/
│   ├── 基于Vulkan的轻量化三维高斯重建与实时渲染系统项目计划书.md
│   └── 日志术语对照表.md
├── tools/             # 第三方工具（需自行下载，见上）
│   ├── colmap-x64-windows-cuda/
│   ├── colmap-x64-windows-nocuda/
│   ├── vksplat/
│   └── vkgs-2026.2.9-windows-64bits/
├── workspaces/                 # 运行时生成：COLMAP 中间结果
├── outputs/                    # 运行时生成：VkSplat 训练输出
├── logs/                       # 运行时生成：日志文件（自动轮转）
├── .gitignore
├── LICENSE                     # AGPL-3.0
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

> 所有档位统一使用 MCMC 致密化策略，确保高斯点充分增长。
> 核显会自动降低高斯上限（cap_max = 500,000）并使用 CPU 图像缓存，避免 TDR 超时；独显上限为 1,000,000。

---

## 常见问题

**Q: 启动时提示找不到 Python？**
A: 确保已安装 Miniconda 并创建了 `vksplat` 环境。`run.bat` 会自动搜索常见安装路径，也可手动编辑 `run.bat` 指定 Python 路径。

**Q: VkSplat 编译失败，提示找不到 Vulkan？**
A: 确认已安装 [Vulkan SDK](https://vulkan.lunarg.com/sdk/home)，且环境变量 `VULKAN_SDK` 指向 SDK 根目录。

**Q: 训练时 GPU 超时（TDR）？**
A: 核显用户请确认 cap_max 已自动设为 500,000；若仍超时，可在高级选项中手动降低高斯上限。

**Q: COLMAP 重建失败？**
A: 检查照片是否有足够重叠（建议 60%+），数量不少于 30 张；模糊或无纹理的图片会导致特征点不足。

**Q: 输出的 PLY 用什么打开？**
A: 训练完成后 GUI 会自动用 VKGS 打开；也可手动用 `vk_gaussian_splatting.exe` 或其他支持 3DGS PLY 的查看器打开。

---

## 许可证

本项目采用 **GNU Affero General Public License v3.0 (AGPL-3.0)**，详见 [LICENSE](LICENSE)。

> **AGPL-3.0 核心要求**：任何使用、修改、分发本项目代码的个人或组织，必须将其衍生作品以 AGPL-3.0 协议开源。即使仅通过网络提供服务（如部署为在线服务），也必须向用户提供完整的源代码。

### 第三方依赖及许可证

本项目通过**外部进程调用**以下开源工具（非代码链接），各组件保留其原始许可证：

| 组件 | 用途 | 许可证 |
|------|------|--------|
| [COLMAP](https://github.com/colmap/colmap) | 稀疏重建（SfM/MVS） | BSD-3-Clause |
| [VkSplat](https://github.com/harry7557558/vksplat) | 3DGS 训练后端（Vulkan） | Apache-2.0 |
| [VKGS](https://github.com/limacv/vk_gaussian_splatting) | 实时渲染查看器 | MIT |

各第三方工具的源代码请前往其各自仓库获取。

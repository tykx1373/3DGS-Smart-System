# 3DGS - 三维高斯泼溅工具

基于 ImGui + GLFW + OpenGL 3.0 的 3D Gaussian Splatting (3DGS) 图形化工具。
支持图片导入、渲染管线、JSON 项目管理与 PLY 点云导出。


## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [构建说明](#构建说明)
- [使用指南](#使用指南)
- [渲染管线](#渲染管线)
- [输出格式](#输出格式)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [许可证](#许可证)

---

## 功能特性

### 已实现

- **图片导入** — 多选导入 JPG / PNG / BMP，自动生成缩略图预览
- **渲染管线** — 后台多线程管线，从图片像素采样生成 3DGS 高斯点云
- **参数调节** — 采样步长、场景缩放、不透明度、高斯尺度实时可调
- **PLY 导出** — 标准 62 属性二进制 PLY (位置/SH/不透明度/尺度/旋转)
- **JSON 项目** — 保存/加载项目元数据与图片列表
- **日志系统** — 实时持久化日志，文件位于 `logs/` 目录
- **主题切换** — 浅色/深色双主题，标题栏一键切换
- **字体缩放** — Ctrl + 滚轮调节，范围 0.5x ~ 3.0x

---

## 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10/11 |
| 编译器 | MSVC v143+ (Visual Studio 2022) |
| C++ 标准 | C++20 |
| 平台 | x64 |

## 构建说明

### 依赖库

项目依赖以下库，已包含在仓库中（仅保留必要的源码和库文件）：

| 库 | 版本 | 用途 |
|----|------|------|
| [Dear ImGui](https://github.com/ocornut/imgui) | 1.92+ | 即时模式 GUI 框架 |
| [GLFW](https://www.glfw.org/) | 3.4 | 窗口管理与输入处理 |
| [stb_image](https://github.com/nothings/stb) | 最新 | 图片解码 |

### 目录布局

```
3DGS/
├── imgui/              # ImGui 源码 (核心 + backends)
├── glfw/               # GLFW 预编译库
│   ├── include/        # 头文件
│   └── lib-vc2022/     # MSVC 2022 静态库 + DLL
└── 3DGS/               # 本项目源码
```

### 方式一：Visual Studio IDE

1. 用 Visual Studio 2022 打开 `3DGS.slnx`
2. 选择 `Debug|x64` 或 `Release|x64` 配置
3. 按 `F5` 或 `Ctrl+F5` 编译运行

### 方式二：命令行 (MSBuild)

```batch
msbuild 3DGS.slnx -p:Configuration=Release -p:Platform=x64
```

编译后可执行文件位于 `bin\x64\Debug\3DGS.exe` (Debug) 或 `bin\x64\Release\3DGS.exe` (Release)。
GLFW 的 DLL (`glfw3.dll`) 会在编译时自动复制到输出目录。

---

## 使用指南

### 基本工作流

1. **导入图片** — 点击「导入图片」选择输入图片 (支持多选)
2. **调整参数** — 在「渲染参数」区调节采样步长、场景缩放等
3. **开始渲染** — 点击「开始渲染」，进度条实时显示处理状态
4. **导出点云** — 渲染完成后点击「导出点云 (PLY)」保存结果
5. **保存项目** — 点击「导出项目 (JSON)」保存项目元数据

### 界面说明

程序采用标题栏 + 侧边栏导航 + 内容区 + 状态栏的专业布局：

| 区域 | 说明 |
|------|------|
| 标题栏 | 应用名/版本 + 主题切换按钮 |
| 侧边栏 | 控制面板 / 日志 / 帮助 三个导航页 |
| 内容区 | 根据导航切换的功能面板 |
| 状态栏 | 就绪状态、渲染进度、图片数、FPS |

### 控制面板

| 分区 | 功能 |
|------|------|
| 项目管理 | 加载项目 (JSON) / 导出项目 (JSON) |
| 工作流程 | 导入图片 / 开始渲染 / 停止渲染 |
| 渲染参数 | 采样步长、场景缩放、不透明度、高斯尺度 |
| 导出 | 导出点云 (PLY) / 清空图片 |
| 图片预览 | 缩略图网格，右键可移除单张 |

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl` + `鼠标滚轮` | 放大/缩小字体 (0.5x ~ 3.0x，步进 5%) |

---

## 渲染管线

渲染管线 (`pipeline.h/.cpp`) 在后台线程运行，不阻塞 UI，可随时停止。

### 处理流程

1. 遍历每张导入图片，按采样步长 (`sampleStep`) 读取像素
2. 跳过近黑像素 (RGB 总和 < 30)
3. 每个采样像素生成一个高斯点 (62 个属性)
4. 像素颜色经 sRGB → 线性 → SH DC 系数转换
5. 多张图片在 Z 轴分层排布，创建深度感
6. 最终打乱点序，使不同图片的点交错分布

### 可调参数

| 参数 | 范围 | 默认值 | 说明 |
|------|------|--------|------|
| 采样步长 | 1-16 像素 | 4 | 越小点越密集 |
| 场景缩放 | 0.5-5.0 | 2.0 | 整体场景大小 |
| 高斯不透明度 | 0.1-1.0 | 0.85 | 点的不透明度 |
| 高斯尺度 | 0.1-1.0 | 0.30 | 点的大小 |

---

## 输出格式

### PLY 点云 (二进制)

渲染完成后导出的 PLY 文件为 `binary_little_endian` 格式，每个顶点包含 62 个属性：

| 属性组 | 字段 | 数量 |
|--------|------|------|
| 位置 | x, y, z | 3 |
| 法线 | nx, ny, nz | 3 |
| SH DC 系数 | f_dc_0, f_dc_1, f_dc_2 | 3 |
| SH 高阶系数 | f_rest_0 ~ f_rest_44 | 45 |
| 不透明度 | opacity | 1 |
| 尺度 | scale_0, scale_1, scale_2 | 3 |
| 旋转 | rot_0, rot_1, rot_2, rot_3 | 4 |

### JSON 项目文件

```json
{
  "version": "1.0",
  "project": {
    "name": "My 3DGS Project",
    "created_time": "2026-07-26T10:00:00",
    "modified_time": "2026-07-26T10:30:00"
  },
  "images": [
    {
      "file_path": "D:\\photos\\image001.jpg",
      "file_name": "image001.jpg",
      "file_size": 2048000,
      "width": 3840,
      "height": 2160,
      "channels": 3
    }
  ],
  "output": {
    "path": "D:\\output\\project.json",
    "ply_path": "D:\\output\\point_cloud.ply",
    "format": "ply"
  },
  "statistics": {
    "total_images": 1,
    "total_file_size": 2048000,
    "total_file_size_formatted": "1 MB"
  }
}
```

---

## 项目结构

```
3DGS/
├── main.cpp                # 程序入口、ImGui/GLFW 初始化与主循环
├── app_state.h             # 全局应用状态 (ImageManager + Pipeline + Config)
├── pipeline.h/.cpp         # 渲染管线 (后台线程、高斯点生成)
├── image_manager.h/.cpp    # 图片管理与缩略图纹理
├── project_io.h/.cpp       # JSON 项目存取 + PLY 点云导出
├── log_system.h/.cpp       # 日志系统 (持久化到文件)
├── file_dialog.h/.cpp      # Win32 文件对话框封装
├── theme.h                 # 浅色/深色主题
├── stb_image.h             # stb_image 单头文件库
├── ui_main_window.h/.cpp   # 主窗口布局 (标题栏/侧边栏/内容区/状态栏)
├── ui_control_panel.h/.cpp # 控制面板
├── ui_log_panel.h/.cpp     # 日志面板
└── ui_help_panel.h/.cpp    # 帮助面板
```

---

## 技术栈

| 技术 | 用途 |
|------|------|
| C++20 | 主开发语言 |
| Dear ImGui 1.92+ | 即时模式 GUI |
| GLFW 3.4 | 窗口管理 |
| OpenGL 3.0 | 渲染后端 |
| stb_image | 图片解码 |
| Win32 API | 文件对话框、Shell 执行 |
| std::thread | 后台渲染管线 |

### 编译选项

- `/utf-8` — MSVC UTF-8 源码编码支持
- `/Zc:char8_t-` — 兼容 C++20 u8 字面量与 ImGui API
- `C++20 (stdcpp20)` — 语言标准

### 后续计划

- **GPU 加速** — 当前渲染在 CPU 上运行，后续计划迁移到 CUDA 或 Vulkan 实现性能提升
  → 详见 [ROADMAP.md](ROADMAP.md)

---

## 许可证

本项目采用 **GNU Affero General Public License v3.0 (AGPL-3.0)**，详见 [LICENSE](LICENSE)。

> **AGPL-3.0 核心要求**：任何使用、修改、分发本项目代码的个人或组织，必须将其衍生作品以 AGPL-3.0 协议开源。即使仅通过网络提供服务（如部署为在线服务），也必须向用户提供完整的源代码。

### 第三方依赖及许可证

本项目依赖以下开源软件，各组件保留其原始许可证：

| 组件 | 用途 | 许可证 |
|------|------|--------|
| [COLMAP](https://github.com/colmap/colmap) | 稀疏重建（SfM/MVS） | BSD-3-Clause |
| [vkSplat](https://github.com/vk-splat/vksplat) | 3DGS 训练后端（Vulkan） | Apache-2.0 |
| [VKGS](https://github.com/limacv/vk_gaussian_splatting) | 实时渲染查看器 | MIT |

> **说明**：本项目通过**外部进程调用**上述工具（非代码链接），因此本项目代码可独立采用 AGPL-3.0 协议。各第三方工具的源代码请前往其各自仓库获取。

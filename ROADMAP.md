# 开发路线图

> 更新：2026-10-14。Vulkan 训练管线（COLMAP → VkSplat → VKGS）全链路打通；
> 第二代纯 PySide6 GUI 与 Windows 安装包已发布（v2.0.0-beta）。
> 以下为后续优化方向，按优先级排序。

## ✅ 已完成

- [x] Vulkan 训练后端集成（VkSplat，源码内置，无需 CUDA）
- [x] COLMAP 稀疏重建（CUDA / noCUDA 双版本自动选择）
- [x] VKGS 实时渲染查看器集成
- [x] 中文 GUI（纯 PySide6 原生控件 + 自写 QSS，Fluent 风格），一键式管线
- [x] 独显 / 核显自动适配（cap_max、图像缓存策略）
- [x] 断点续训（每 1000 步自动保存，停止时精确保存）
- [x] 实时训练进度（步数 / 剩余时间 / 高斯数量）
- [x] 安全停止（STOP 文件优雅退出，不损坏数据）
- [x] MCMC / Default 稠密化策略切换（高级选项勾选）
- [x] 图像 Mask 支持（高级选项选择 mask 文件夹，排除天空/地面等区域）
- [x] 诊断包一键导出（日志 + 环境自检 + 配置打包 zip）
- [x] Windows 安装包（Inno Setup）：免管理员安装、开始菜单/桌面快捷方式、
      便携 conda 环境随包分发、卸载保留 workspaces/outputs/logs
- [x] 启动器版本元数据与版本号单一来源（build_setup.ps1 的 $AppVersion）
- [x] 许可证切换为 Apache-2.0（PySide6/Qt 为 LGPLv3 动态链接，随附声明）

## 🔜 近期计划（高优先级）

### P2：PLY → SPLAT 压缩输出

- 训练完成后可选输出 `.splat` 格式（体积约为 PLY 的 1/10）
- 便于分享与网页查看器（antimatter15/splat 等）直接加载
- 改动量：新增转换函数 ~40 行（纯 Python）

### P3：曝光校正预处理

- COLMAP 之后、训练之前，对训练图做直方图匹配 / gamma 校正
- 解决照片曝光不一致导致的重建色差（VkSplat 原生不支持曝光补偿）
- 改动量：新增预处理步骤 ~50 行

### P5：训练分辨率按显存自适应

- 目前分辨率由质量档位 + 手动选项决定；改为读取显存自动选 images / images_2 / images_4
- 核显 4GB 强制降分辨率，独显 8GB+ 用全分辨率

## 🔭 中期计划

### P6：训练中实时预览

- 接入 VkSplat 自带的 `ViewerServer`（simple_trainer 已有 enable_viewer 选项）
- GUI 训练过程中打开浏览器窗口实时查看渲染效果
- 打包注意：安装脚本当前排除了 `tools/vksplat/vksplat/viewer/`（0.06 MB），
  做此项时需在 installer/setup.iss 的 tools Excludes 中移除该目录

### 分发工程

- [ ] setup.exe / 启动器代码签名（当前未签名，首启会有 SmartScreen 提示）
- [ ] 无 Python / 无显卡开发包的干净机器（或虚拟机）安装实测
- [ ] 发布正式版时把 Release 资源命名统一为
      `3DGS-Studio-windows-x64-Setup-<version>.exe`（构建脚本已按此命名）

## 🧪 远期 / 深度优化（需改 C++ / Shader）

- [ ] SH 系数量化（float32 → fp16/int8），进一步压缩显存
- [ ] 多图批量训练（每步 2~4 张图共享投影与光栅化）
- [ ] 更激进的稠密化策略（LiteGS / Taming 3DGS 移植）
- [ ] AMD 平台 PCIe 传输瓶颈优化（官方已知问题）

## 🚫 明确不做

- 集成 OpenSplat：与零 CUDA 依赖的定位冲突（依赖 libtorch + CUDA/ROCm）
- 多卡训练：目标用户为低端 GPU 场景
- GUI 重写为 C++/ImGui：当前纯 PySide6 足够
- 安装包增量自动更新：全量包 600+ MB 做增量需自建补丁服务，用户量起来前不值得

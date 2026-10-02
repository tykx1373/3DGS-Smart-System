# 开发路线图

> 更新：2026-10-02。Vulkan 训练管线（COLMAP → VkSplat → VKGS）已全链路打通，
> GUI 支持断点续训、实时进度与安全停止。以下为后续优化方向，按优先级排序。

## ✅ 已完成

- [x] Vulkan 训练后端集成（VkSplat，源码内置，无需 CUDA）
- [x] COLMAP 稀疏重建（CUDA / noCUDA 双版本自动选择）
- [x] VKGS 实时渲染查看器集成
- [x] 中文 GUI（customtkinter），一键式管线
- [x] 独显 / 核显自动适配（cap_max、图像缓存策略）
- [x] 断点续训（每 1000 步自动保存，停止时精确保存）
- [x] 实时训练进度（步数 / 剩余时间 / 高斯数量）
- [x] 安全停止（STOP 文件优雅退出，不损坏数据）
- [x] 许可证切换为 Apache-2.0

## 🔜 近期计划（高优先级）

### P1：稠密化策略切换（Default）

- 高级选项中增加 MCMC / Default 下拉切换
- MCMC 在小场景（<50 张图）上偶发不稳定，Default 策略可作为兜底
- 改动量：GUI ~10 行

### P2：PLY → SPLAT 压缩输出

- 训练完成后可选输出 `.splat` 格式（体积约为 PLY 的 1/10）
- 便于分享与网页查看器（antimatter15/splat 等）直接加载
- 改动量：新增转换函数 ~40 行（纯 Python）

### P3：曝光校正预处理

- COLMAP 之后、训练之前，对训练图做直方图匹配 / gamma 校正
- 解决照片曝光不一致导致的重建色差（VkSplat 原生不支持曝光补偿）
- 改动量：新增预处理步骤 ~50 行

## 🔭 中期计划

### P4：图像 Mask 支持

- GUI 增加 mask 文件夹选择，排除天空 / 地面等无效区域
- C++ 层 `DatasetImage` 已有 `mask_path` 字段，需在 GUI 与训练配置中打通

### P5：训练分辨率自适应

- 根据显存大小自动选择 images / images_2 / images_4，而非按质量档位硬编码
- 核显 4GB 强制降分辨率，独显 8GB+ 可用全分辨率

### P6：训练中实时预览

- 接入 VkSplat 自带的 `ViewerServer`（simple_trainer 已有 enable_viewer 选项）
- GUI 训练过程中打开浏览器窗口实时查看渲染效果

## 🧪 远期 / 深度优化（需改 C++ / Shader）

- [ ] SH 系数量化（float32 → fp16/int8），进一步压缩显存
- [ ] 多图批量训练（每步 2~4 张图共享投影与光栅化）
- [ ] 更激进的稠密化策略（LiteGS / Taming 3DGS 移植）
- [ ] AMD 平台 PCIe 传输瓶颈优化（官方已知问题）

## 🚫 明确不做

- 集成 OpenSplat：与零 CUDA 依赖的定位冲突（依赖 libtorch + CUDA/ROCm）
- 多卡训练：目标用户为低端 GPU 场景
- GUI 重写为 C++/ImGui：当前 customtkinter 足够

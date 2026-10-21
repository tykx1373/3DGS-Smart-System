# 开发路线图

> 更新：2026-10-18。Vulkan 训练管线（COLMAP → VkSplat → VKGS）全链路打通；
> 第二代纯 PySide6 GUI 与 Windows 安装包已发布（当前版本 2.3.0）。
> 以下为后续优化方向，按优先级排序。工程侧（CI、安装包、断点续训、诊断包）已较扎实，
> 后续重心放在**训练前的采集质量把关**与**训练后的结果交付**两端。

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
- [x] 采集质量把关（COLMAP 后跑 `model_analyzer`：注册率不达标时列出**没定位上的照片名**、
      给出补拍办法，并弹出「先去补拍 / 先训练看看」的可操作提示；只提醒不拦截）
- [x] 选照片就地预检（挑完文件夹立即在本地算张数与清晰度，结论写在照片卡片下方，
      不用等 COLMAP 跑完才发现照片不行）
- [x] 失败原因卡片（退出码翻译成「原因 / 怎么办」并显示在主界面，附导出诊断包与看日志入口）
- [x] 内置示例照片一键试跑（用随包示例数据完整跑一遍，先确认这台机器能出模型）
- [x] 分享文件入口（训练完成总是自动生成 `.splat`，完成弹窗与历史模型页均可一键准备并定位）
- [x] 全程统一进度条（COLMAP 按「正在定位照片 N/M」逐张推进并给剩余时间，训练按步数，
      两段分别占整条进度的前 30% 与后 70%；mapper 进度取日志里的 `num_reg_frames`）
- [x] 诊断包一键导出（日志 + 环境自检 + 配置打包 zip）
- [x] PLY → SPLAT 压缩导出（`.splat` 体积约为 PLY 的 1/7，可直接拖进
      antimatter15/splat 等网页查看器分享）
- [x] 曝光校正预处理（高级选项勾选，生成训练副本时逐通道直方图匹配
      到中间曝光照片，统一明暗，不动用户原图）
- [x] 训练分辨率按显存自适应（跟随档位时：核显 / 独显 <8GB 自动降至
      1/2 分辨率防显存溢出，手动选择分辨率则完全尊重）
- [x] Windows 安装包（Inno Setup）：免管理员安装、开始菜单/桌面快捷方式、
      便携 conda 环境随包分发、卸载保留 workspaces/outputs/logs
- [x] 启动器版本元数据与版本号单一来源（唯一来源 `gui/app_version.py`，
      `build_setup.ps1` 反过来读它 —— 安装包不分发 `installer/`，写在那里的话
      程序自己看不到版本号）
- [x] 版本号在界面上可见（标题栏 `3DGS 快速管线 v2.3.1`、侧栏品牌区
      `照片 → 3D 模型 · v2.3.1`、启动日志一行、诊断报告首屏字段）
- [x] 安装包瘦身：示例数据集照片由 3072px 重编码到长边 1600（COLMAP 的
      `max_image_size` 默认就是 1600，原图本来也会被缩到这一步，零精度损失），
      223 MB → 65 MB，安装包减小约 158 MB
- [x] 许可证切换为 Apache-2.0（PySide6/Qt 为 LGPLv3 动态链接，随附声明）

## 🔜 近期计划（高优先级）

### P8：无 GUI 批处理模式（headless）

除 `doctor.py` 外全项目没有 argparse 入口，训练必须开着 GUI 点按钮，导致 30000 步的
长任务无法脚本化、无法挂机排队、也无法一次跑多个场景。

- `PipelineCore` 已经通过 Tk-Var 风格的适配对象读取界面状态（见 `quick_gui.py`
  的 Var 适配层），所以 headless 不必重构管线：实现一个同接口的**无界面宿主**，
  从命令行参数 / JSON 填充这些 Var 即可
- 需要自动应答的交互点：`ask_continue()`、`ask_resume()`（checkpoint 询问），
  用 `--yes` / `--resume=auto|new|skip` 之类的开关替代弹窗
- 退出码要可判定（成功 / COLMAP 失败 / 训练失败 / 用户 STOP），便于外部脚本串联
- 入口形态：新增 `gui/pipeline_cli.py`，按现有习惯用路径直接运行
  （`python gui/pipeline_cli.py --images <dir> --preset standard --out <ply>`，
  `gui` 不是 package，不要设计成 `-m` 形式）；再加一个 `run_cli.bat`，
  复用 `run.bat` 里的 Python 探测逻辑，免管理员安装的便携环境同样可用
  —— 解释器扫描列表目前在 `run.bat` 和 `download_tools.ps1` 里各写了一份
  （20 多个候选路径），做 CLI 时顺手抽成一个共享脚本；`installer/launcher.py`
  只用固定的 `env\vksplat\pythonw.exe`，不参与扫描
- GUI 保持默认路径不变，两者共用 `PipelineCore`
- 顺带收益：可以拿真实小数据集在 CI 里跑端到端冒烟测试（目前 CI 只有语法编译和单测）

## 🔭 中期计划

### P6：训练中实时预览

- 接入 VkSplat 自带的 `ViewerServer`（simple_trainer 已有 enable_viewer 选项）
- GUI 训练过程中打开浏览器窗口实时查看渲染效果
- **风险**：`simple_trainer.py` 里 `enable_viewer` 的注释自己就写着
  "can affect resource usage, disable during benchmark"——训练和预览共用同一块 GPU，
  核显上会拖慢训练甚至触发 TDR 超时，与本项目的轻量硬件定位直接冲突。
  因此只在检测到独显时提供，且默认关闭
- 打包注意：安装脚本当前排除了 `tools/vksplat/vksplat/viewer/`（0.06 MB），
  做此项时需在 installer/setup.iss 的 tools Excludes 中移除该目录

### P9：真实尺度标定与裁剪导出

COLMAP 只能恢复到一个未知相似变换，导出的 PLY 没有米制尺度，也带着拍进来的天空和地面——
这两点是用户拿到模型后的第一道墙，也是本工具与「又一个 3DGS demo」拉开差距的地方。

- 两点标定尺度：在查看器或 GUI 里选两个已知实际距离的点，反算统一缩放系数写回模型
- 导出前裁剪：按用户拖的 bbox（或自动剔除不透明度高斯占比过低的远处背景）生成
  裁剪后的 PLY / `.splat`，复用现有 `.splat` 导出链路
- 顺带提供尺寸读数（长宽高，米），供需要量尺寸的用途使用
- 依赖 P8：这类后处理最好先有 headless 入口，避免再往 GUI 里堆按钮

### 分发工程

- [ ] CI 增加安装包构建 job：目前 `.github/workflows/ci.yml` 只有语法编译 + 单测 +
      doctor 冒烟，`setup.exe` 仍需本地手跑 `installer/build_setup.ps1`。
      加 tag 触发的 `windows-latest` job 产出 artifact，并自动写 SHA-256 到 Release 正文
      （README 现在让用户自己核对哈希，这步应该由流水线代劳）
- [x] **仓库改 public**：2026-10-19 已公开。匿名接口实测 `private=false`、
      `releases/latest` 返回 v2.3.2、对下载直链取前 1 KB 得到 206 且魔数是 `MZ`
      （Content-Range 总长与包大小一致），所以 README「到 Releases 页面下载安装包」
      对外部访客已经成立
- [ ] setup.exe / 启动器代码签名（当前未签名，首启会有 SmartScreen 提示；公开之后
      陌生人也会装，这条的优先级比公开前更高）
- [ ] 无 Python / 无显卡开发包的干净机器（或虚拟机）安装实测
- [x] Release 资源统一命名为 `3DGS-Studio-windows-x64-Setup-<version>.exe`
      （构建脚本按此命名，2.1.0 起各版本均已一致；一个 release 只放对应版本的一个包）

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

// app_state.h - 应用程序中心状态容器
//
// 将应用程序状态分为两个逻辑组，以清晰区分关注点，
// 方便协作者理解和上手：
//
//   1. 业务状态 - 核心数据：图片管理器、渲染管线、项目配置和渲染参数。
//      这些与界面外观无关。
//
//   2. UI 状态 (UiState) - 仅界面相关设置：当前标签页、主题、字体缩放、
//      强调色、设置弹窗可见性。仅影响外观。
//
// 用法:
//   state.imageManager.AddImage(...);   // 业务状态
//   state.ui.fontScale = 1.5f;          // UI 状态
//   state.ui.isDarkTheme = true;        // UI 状态
//
#pragma once
#include "image_manager.h"
#include "project_io.h"
#include "pipeline.h"
#include "gpu_info.h"

// ============================================================================
// 延迟操作类型
//
// Win32 文件对话框 (GetOpenFileNameW / GetSaveFileNameW) 是同步阻塞调用。
// 如果在 ImGui 帧内直接调用，对话框关闭后 GLFW 积压的鼠标事件会被 ImGui
// 当作按钮再次点击，导致对话框反复弹出。
//
// 解决方案：按钮点击时仅设置 pendingAction 标志，在 ImGui 帧外
// （主循环中 glfwSwapBuffers 之后）执行文件对话框，返回后清空残留输入事件。
// ============================================================================
enum class PendingAction {
    None,           // 无待处理操作
    LoadProject,    // 加载项目 JSON
    SaveProject,    // 导出项目 JSON
    ImportImages,   // 导入图片
    ExportPly       // 导出点云 PLY
};

// GpuType 枚举定义在 pipeline.h 中（管线配置语义）
// app_state.h 通过 #include "pipeline.h" 获取该类型

// ============================================================================
// UI 状态 - 界面外观与导航（视图层）
//
// 这些字段控制应用程序的外观，而非功能。
// 可通过设置弹窗和 Ctrl+滚轮 调整。
// ============================================================================
struct UiState {
    // 导航
    int   currentTab    = 0;      // 0=控制面板, 1=日志, 2=帮助

    // 外观（在设置弹窗中调整）
    bool  showSettings  = false;  // 设置弹窗打开状态
    bool  isDarkTheme   = false;  // false=浅色主题, true=深色主题
    float fontScale     = 1.3f;   // 字体缩放 (Ctrl+滚轮, 范围 0.5x-3.0x, 步长 5%)
    int   uiDensity     = 1;      // 0=紧凑 1=标准 2=宽松
    float thumbSize     = 96.0f;  // 缩略图基础尺寸 (px, 1.3x 字体时)
    int   accentIndex   = 0;      // 强调色 (0=石板蓝 1=翠绿 2=紫罗兰 3=琥珀 4=玫红)

    // 性能优化（在设置弹窗中调整）
    // 用户选择显卡类型，管线据此选择对应算法路径（当前为空壳）
    GpuType gpuType     = GpuType::HighPerf;  // 默认高性能独显

    // 图片预览交互状态
    int   previewImageIndex = -1; // 放大预览的图片索引 (-1=未打开)
    int   pendingRemoveIndex = -1; // 待确认删除的图片索引 (-1=无)

    // 延迟操作：文件对话框在 ImGui 帧外执行（见 main.cpp 主循环）
    PendingAction pendingAction = PendingAction::None;

    // 弹窗互斥机制：同一时间只允许一个弹出窗口/对话框存在。
    // 当有弹窗打开时，点击其他会弹窗的操作会触发提示而非直接打开。
    // activePopup 记录当前活动弹窗类型：
    //   0=无, 1=设置窗口, 2=导入图片对话框, 3=放大预览, 4=删除确认,
    //   5=加载项目对话框, 6=导出项目对话框, 7=导出点云对话框
    int   activePopup = 0;
    char  popupNotice[128] = {}; // 弹窗互斥提示文字（非空时显示一个提示弹窗）

    // 输入守卫：文件对话框关闭后，GLFW 可能有残留鼠标事件。
    // 设置 inputGuard > 0 后，接下来 N 帧内静默忽略所有用户输入，
    // 让残留事件被安全消化，防止误触发按钮。
    int   inputGuard = 0;
};

// ============================================================================
// AppState - 根应用程序状态（同时持有业务状态和 UI 状态）
// ============================================================================
struct AppState {
    // ---- 业务状态（模型层）----
    ImageManager  imageManager;
    Pipeline      pipeline;
    ProjectConfig projectConfig;

    // 显卡检测信息（启动时由 DetectGpu() 填充）
    GpuInfo       gpuInfo;
    bool          gpuAppliedRecommend = false;  // 是否已应用推荐参数

    // 渲染状态标志
    bool          isRendering   = false;
    bool          renderDone    = false;

    // 管线参数（用户通过控制面板滑块调整）
    int           sampleStep    = 4;      // 像素采样步长 (1=每个像素, 4=每4个像素)
    float         sceneScale    = 2.0f;   // 整体场景缩放系数
    float         baseOpacity   = 0.85f;  // 生成高斯点的基础不透明度
    float         baseScale     = 0.3f;   // 生成高斯点的基础尺度

    // ---- UI 状态（视图层）----
    UiState       ui;

    AppState() {
        projectConfig.createdTime  = ProjectIO::GetCurrentTimeISO8601();
        projectConfig.modifiedTime = projectConfig.createdTime;
    }

    // 便捷方法：后台管线是否仍在运行？
    bool IsPipelineRunning() const { return pipeline.IsRunning(); }
    float GetProgress() const { return pipeline.GetProgress(); }
};

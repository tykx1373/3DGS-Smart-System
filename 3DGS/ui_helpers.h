// ui_helpers.h - 所有面板共享的 ImGui 绘制工具
//
// 集中常见的 UI 辅助函数，这些函数之前在 ui_main_window.cpp、ui_control_panel.cpp、
// ui_log_panel.cpp 和 ui_help_panel.cpp 中存在重复定义：
//   - UIScale():   字体相对缩放系数 (默认 1.3x 字体时为 1.0)
//   - ButtonH():   标准按钮高度，随字体大小缩放
//   - SectionHeader(): 带分隔线的一致的区块标题
//   - Card():      带边框的子窗口，用于包裹一组相关内容
//
// 所有面板都应使用这些函数，而非各自定义。
#pragma once
#include <imgui.h>
#include <cstdio>
#include "app_state.h"
#include "log_system.h"

// ---- 缩放辅助函数 ------------------------------------------------------------

// 字体相对 UI 缩放系数。默认字体缩放 (1.3x) 时返回 1.0。
// 用此系数推导应随字体大小变化的面板尺寸。
inline float UIScale(const AppState& state) {
    return state.ui.fontScale / 1.3f;
}

// 重载：从当前 ImGui 样式推导缩放系数（用于不接收 AppState 的面板，如日志面板）。
inline float UIScale() {
    return ImGui::GetStyle().FontScaleMain / 1.3f;
}

// 标准按钮高度：随字体缩放，但不小于文本框架高度。
// 所有主要操作按钮应使用此函数以保持视觉一致性。
inline float ButtonH(const AppState& state) {
    float h = 44.0f * UIScale(state);
    float minH = ImGui::GetFrameHeight();
    return (h < minH) ? minH : h;
}

// 重载：从当前 ImGui 样式推导。
inline float ButtonH() {
    float h = 44.0f * UIScale();
    float minH = ImGui::GetFrameHeight();
    return (h < minH) ? minH : h;
}

// ---- 弹窗互斥辅助函数 --------------------------------------------------------

// 弹窗互斥检查：如果有弹窗/对话框已打开，设置提示信息并返回 false。
// 用于所有会触发弹窗或文件对话框的按钮点击处理。
// inputGuard 期间（文件对话框刚关闭）静默拦截，不显示提示。
// 调用方式：
//   if (ImGui::Button(u8"导入图片", ...)) {
//       if (CheckPopupMutex(state, u8"导入图片")) {
//           state.ui.pendingAction = PendingAction::ImportImages;
//           state.ui.activePopup = 2;
//       }
//   }
inline bool CheckPopupMutex(AppState& state, const char* actionName) {
    // 输入守卫期间（对话框刚关闭）静默拦截所有操作，不显示提示
    if (state.ui.inputGuard > 0) {
        return false;
    }
    if (state.ui.activePopup != 0) {
        snprintf(state.ui.popupNotice, sizeof(state.ui.popupNotice),
            u8"请先关闭当前打开的窗口\n再进行「%s」操作", actionName);
        return false;
    }
    return true;
}

// ---- 布局辅助函数 ------------------------------------------------------------

// 获取日志级别的显示颜色（用于日志面板和状态指示器）。
inline ImVec4 GetLogLevelColor(LogLevel level) {
    switch (level) {
        case LogLevel::Info:    return ImVec4(0.9f, 0.9f, 0.9f, 1.0f);   // 浅灰
        case LogLevel::Warning: return ImVec4(1.0f, 0.8f, 0.2f, 1.0f);   // 黄色
        case LogLevel::Error:   return ImVec4(1.0f, 0.4f, 0.4f, 1.0f);   // 红色
        default:                return ImVec4(0.9f, 0.9f, 0.9f, 1.0f);
    }
}

// 绘制区块标题：彩色标题文字 + 分隔线 + 间距。
// 所有面板使用此函数以保持区块样式一致。
inline void SectionHeader(const char* title) {
    ImGui::Spacing();
    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.5f, 0.6f, 0.75f, 1.0f), "%s", title);
    ImGui::PopFont();
    ImGui::Separator();
    ImGui::Spacing();
}

// 绘制带边框的卡片：使用 FrameBg 背景色和边框的子窗口，
// 包裹一组相关内容。body lambda 负责绘制卡片内容。
//
// 用法:
//   Card("##MyCard", [&]() {
//       ImGui::Text("内容");
//   });
//
// id 参数应以 "##" 开头以隐藏可见标签
// （调用者在 body 内自行绘制标题，如需要）。
// 添加 NoScrollWithMouse 标志，让卡片不拦截滚轮事件，由父窗口统一处理滚动。
template <typename Body>
inline void Card(const char* id, Body body) {
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild(id, ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY,
                      ImGuiWindowFlags_NoScrollWithMouse);
    ImGui::PopStyleColor();
    body();
    ImGui::EndChild();
    ImGui::Spacing();
}

// 绘制顶部带强调色标题的卡片。
// 标题左侧有 4px 强调色竖条，标题下方有半透明细线分隔。
// 当卡片需要可见标题时使用此变体。
// 添加 NoScrollWithMouse 标志，让卡片不拦截滚轮事件，由父窗口统一处理滚动。
template <typename Body>
inline void CardWithTitle(const char* id, const char* titleText, ImVec4 accentColor, Body body) {
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild(id, ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY,
                      ImGuiWindowFlags_NoScrollWithMouse);
    ImGui::PopStyleColor();

    // 左侧强调色竖条
    float barW = 4.0f;
    float innerSpacing = ImGui::GetStyle().ItemInnerSpacing.x;
    ImVec2 cursor = ImGui::GetCursorScreenPos();
    ImDrawList* dl = ImGui::GetWindowDrawList();
    float lineH = ImGui::GetTextLineHeight();
    float padY = ImGui::GetStyle().FramePadding.y;
    dl->AddRectFilled(
        ImVec2(cursor.x, cursor.y + padY),
        ImVec2(cursor.x + barW, cursor.y + lineH + padY),
        ImGui::ColorConvertFloat4ToU32(accentColor),
        2.0f
    );

    // 标题文字（偏移色条宽度）
    ImGui::SetCursorPosX(ImGui::GetCursorPosX() + barW + innerSpacing);
    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(accentColor, u8"%s", titleText);
    ImGui::PopFont();

    // 标题下方细线 - 横跨整个卡片内容宽度
    ImGui::Spacing();
    float childLeftX = ImGui::GetWindowPos().x + ImGui::GetStyle().WindowPadding.x;
    float childRightX = childLeftX + ImGui::GetWindowWidth() - ImGui::GetStyle().WindowPadding.x * 2.0f;
    float sepY = ImGui::GetCursorScreenPos().y;
    dl->AddLine(
        ImVec2(childLeftX, sepY),
        ImVec2(childRightX, sepY),
        ImGui::ColorConvertFloat4ToU32(ImVec4(accentColor.x, accentColor.y, accentColor.z, 0.30f)),
        1.0f
    );
    ImGui::Dummy(ImVec2(0, 2));

    body();
    ImGui::EndChild();
    ImGui::Spacing();
}

// ---- 强调色按钮样式 --------------------------------------------------------

// 将按钮颜色临时设置为强调色及其悬停/按下变体。
// 与 ImGui::PopStyleColor(3) 配对使用。
inline void PushAccentButtonColors(ImVec4 accent) {
    ImGui::PushStyleColor(ImGuiCol_Button, accent);
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(
        accent.x + 0.12f > 1.0f ? 1.0f : accent.x + 0.12f,
        accent.y + 0.12f > 1.0f ? 1.0f : accent.y + 0.12f,
        accent.z + 0.12f > 1.0f ? 1.0f : accent.z + 0.12f,
        1.0f));
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, ImVec4(
        accent.x * 0.82f,
        accent.y * 0.82f,
        accent.z * 0.82f,
        1.0f));
}

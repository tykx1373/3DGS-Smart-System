// ui_main_window.cpp - 主应用窗口布局
//
// 渲染顶层窗口结构：
//   - 标题栏 (应用名、版本、设置按钮)
//   - 主体 (侧边栏导航 + 内容区域)
//   - 状态栏 (就绪状态、渲染进度、图片数量、FPS)
//
// 设置弹窗 (DrawSettingsPopup) 最后绘制以覆盖在其他内容之上。
// Ctrl+鼠标滚轮调整字体大小（在窗口层级处理）。
//
#include "ui_main_window.h"
#include "ui_helpers.h"
#include "ui_settings.h"
#include "ui_control_panel.h"
#include "ui_log_panel.h"
#include "ui_help_panel.h"
#include "theme.h"
#include "log_system.h"
#include <imgui.h>
#include <cstdio>

// ---- 主窗口 -----------------------------------------------------------------
void DrawMainWindow(AppState& state) {
    // 每帧：保持内边距/间距与字体缩放和密度成比例，
    // 并重新应用强调色（主题会重置它，所以在此恢复）。
    ApplyDynamicGeometry(state.ui.fontScale, state.ui.uiDensity);
    ApplyAccent(state.ui.accentIndex);
    ImGui::GetStyle().FontScaleMain = state.ui.fontScale;

    // 输入守卫：文件对话框关闭后，GLFW 残留的鼠标事件可能在接下来几帧
    // 被 ImGui 处理。守卫期间强制清除所有鼠标输入状态，并递减计数器。
    if (state.ui.inputGuard > 0) {
        ImGuiIO& guardIo = ImGui::GetIO();
        for (int i = 0; i < IM_ARRAYSIZE(guardIo.MouseDown); i++) {
            guardIo.MouseDown[i] = false;
        }
        guardIo.MouseWheel = 0.0f;
        guardIo.MouseWheelH = 0.0f;
        state.ui.inputGuard--;
    }

    ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->Pos);
    ImGui::SetNextWindowSize(viewport->Size);
    ImGuiWindowFlags window_flags = ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoCollapse
        | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove
        | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus;
    ImGui::Begin("3DGS##MainWindow", nullptr, window_flags);

    // Ctrl+鼠标滚轮缩放字体
    ImGuiIO& io = ImGui::GetIO();
    if (io.KeyCtrl && io.MouseWheel != 0.0f) {
        state.ui.fontScale += io.MouseWheel * 0.05f;
        state.ui.fontScale = (state.ui.fontScale < 0.5f) ? 0.5f : ((state.ui.fontScale > 3.0f) ? 3.0f : state.ui.fontScale);
        ImGui::GetStyle().FontScaleMain = state.ui.fontScale;
    }

    const ImGuiStyle& style = ImGui::GetStyle();
    const float pad        = style.WindowPadding.x;
    const float uiS        = UIScale(state);
    const float titleBarH  = 48.0f * uiS;
    const float sidebarW   = 160.0f * uiS;
    const float statusBarH = 28.0f * uiS;
    const float navBtnH    = ButtonH(state);
    const ImVec4 accent    = GetAccentColor(state.ui.accentIndex);

    float availW = ImGui::GetContentRegionAvail().x;
    float availH = ImGui::GetContentRegionAvail().y;
    float bodyH  = availH - titleBarH - statusBarH - style.ItemSpacing.y * 2.0f;

    // ===== 顶部标题栏 =====
    {
        ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_TitleBgActive));
        ImGui::BeginChild("##TitleBar", ImVec2(availW, titleBarH), ImGuiChildFlags_None, ImGuiWindowFlags_NoScrollbar);
        ImGui::PopStyleColor();

        // 应用名 + 版本（垂直居中）
        ImGui::SetCursorPosY(titleBarH / 2.0f - ImGui::GetTextLineHeight() / 2.0f);
        ImGui::TextColored(ImVec4(0.85f, 0.92f, 1.0f, 1.0f), u8"  3DGS");
        ImGui::SameLine();
        ImGui::TextColored(ImVec4(0.6f, 0.7f, 0.8f, 1.0f), u8" 三维高斯泼溅工具  v1.0");

        // 右侧按钮：设置（主题切换在设置弹窗内）
        const char* settingsLabel = u8"设置";
        float setBtnW = ImGui::CalcTextSize(settingsLabel).x + style.FramePadding.x * 3.0f;

        float rightX = availW - pad;
        ImGui::SameLine();
        ImGui::SetCursorPosX(rightX - setBtnW);
        ImGui::SetCursorPosY(titleBarH / 2.0f - ImGui::GetTextLineHeight() / 2.0f - style.FramePadding.y / 2.0f);
        if (ImGui::Button(settingsLabel)) {
            if (CheckPopupMutex(state, u8"打开设置")) {
                state.ui.showSettings = true;
            }
        }
        ImGui::EndChild();
    }

    // ===== 主体：侧边栏 + 内容区域（并排）=====
    {
        // --- 侧边栏 ---
        ImGui::BeginChild("##Sidebar", ImVec2(sidebarW, bodyH), ImGuiChildFlags_Borders);

        const char* navItems[] = { u8" 控制面板", u8" 日志", u8" 帮助" };
        for (int i = 0; i < 3; i++) {
            bool selected = (state.ui.currentTab == i);
            if (selected) {
                ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetColorU32(ImGuiCol_ButtonActive));
                ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImGui::GetColorU32(ImGuiCol_ButtonActive));
            }
            if (ImGui::Button(navItems[i], ImVec2(-1, navBtnH))) {
                state.ui.currentTab = i;
            }
            // 选中状态左侧强调色指示条
            if (selected) {
                ImVec2 btnMin = ImGui::GetItemRectMin();
                ImVec2 btnMax = ImGui::GetItemRectMax();
                ImDrawList* dl = ImGui::GetWindowDrawList();
                dl->AddRectFilled(
                    ImVec2(btnMin.x + 2, btnMin.y + 3),
                    ImVec2(btnMin.x + 5, btnMax.y - 3),
                    ImGui::ColorConvertFloat4ToU32(accent),
                    2.0f
                );
                ImGui::PopStyleColor(2);
            }
            ImGui::Spacing();
        }

        // 侧边栏底部：图片数量
        ImGui::Dummy(ImVec2(0, 10 * uiS));
        ImGui::Separator();
        ImGui::Spacing();
        ImGui::TextDisabled(u8" 导入图片");
        ImGui::Text(u8"   %zu 张", state.imageManager.GetCount());

        if (state.isRendering || state.IsPipelineRunning()) {
            ImGui::Spacing();
            ImGui::Separator();
            ImGui::Spacing();
            ImGui::TextDisabled(u8" 渲染状态");
            ImGui::TextColored(ImVec4(0.4f, 0.8f, 0.4f, 1.0f), u8"   进行中 %.0f%%", state.GetProgress() * 100.0f);
        }

        ImGui::EndChild();

        // --- 内容区域 ---
        ImGui::SameLine(0, 0);
        float contentW = availW - sidebarW - style.ItemSpacing.x;
        ImGui::BeginChild("##Content", ImVec2(contentW, bodyH), ImGuiChildFlags_Borders);

        switch (state.ui.currentTab) {
            case 0: DrawControlPanel(state); break;
            case 1: DrawLogPanel(); break;
            case 2: DrawHelpPanel(); break;
        }

        ImGui::EndChild();
    }

    // ===== 底部状态栏 =====
    {
        ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_TitleBg));
        ImGui::BeginChild("##StatusBar", ImVec2(availW, statusBarH), ImGuiChildFlags_None, ImGuiWindowFlags_NoScrollbar);
        ImGui::PopStyleColor();

        ImGui::SetCursorPosY((statusBarH - ImGui::GetTextLineHeight()) * 0.5f);
        ImGui::TextDisabled(u8"  就绪");
        ImGui::SameLine();
        ImGui::TextDisabled(u8"|");
        ImGui::SameLine();

        if (state.isRendering || state.IsPipelineRunning()) {
            ImGui::TextColored(ImVec4(0.4f, 0.8f, 0.4f, 1.0f), u8" 渲染中 %.0f%%", state.GetProgress() * 100.0f);
        } else {
            ImGui::TextDisabled(u8" 空闲");
        }

        ImGui::SameLine();
        ImGui::TextDisabled(u8"|");
        ImGui::SameLine();
        ImGui::TextDisabled(u8" 图片: %zu", state.imageManager.GetCount());

        // 右侧 FPS
        ImGui::SameLine();
        float fpsW = ImGui::CalcTextSize(u8"60.0 FPS").x + style.WindowPadding.x;
        ImGui::SetCursorPosX(availW - fpsW);
        ImGui::TextDisabled(u8"%.1f FPS", io.Framerate);

        ImGui::EndChild();
    }

    // 弹窗互斥提示（在主窗口上下文内，确保所有按钮触发的提示都能正确弹出）
    // 输入守卫期间不显示提示（残留事件不应产生用户可见反馈）
    if (state.ui.popupNotice[0] != 0 && state.ui.inputGuard <= 0) {
        ImGui::OpenPopup("##PopupNotice");
    }
    if (ImGui::BeginPopupModal("##PopupNotice", nullptr,
            ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoTitleBar)) {
        ImGui::Spacing();
        ImGui::TextUnformatted(state.ui.popupNotice);
        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();
        float bw = 100.0f * UIScale(state);
        if (ImGui::Button(u8"知道了", ImVec2(bw, 0))) {
            state.ui.popupNotice[0] = 0;
            ImGui::CloseCurrentPopup();
        }
        ImGui::EndPopup();
    }

    ImGui::End();

    // 设置窗口（最后绘制以覆盖所有内容）
    DrawSettingsPopup(state);
}

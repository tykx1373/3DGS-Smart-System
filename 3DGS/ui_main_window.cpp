#include "ui_main_window.h"
#include "ui_control_panel.h"
#include "ui_log_panel.h"
#include "ui_help_panel.h"
#include "theme.h"
#include "log_system.h"
#include <imgui.h>

void DrawMainWindow(AppState& state) {
    ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->Pos);
    ImGui::SetNextWindowSize(viewport->Size);
    ImGuiWindowFlags window_flags = ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoCollapse
        | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove
        | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus;
    ImGui::Begin("3DGS##MainWindow", nullptr, window_flags);

    // Ctrl+MouseWheel to zoom font
    ImGuiIO& io = ImGui::GetIO();
    if (io.KeyCtrl && io.MouseWheel != 0.0f) {
        state.fontScale += io.MouseWheel * 0.05f;
        state.fontScale = (state.fontScale < 0.5f) ? 0.5f : ((state.fontScale > 3.0f) ? 3.0f : state.fontScale);
        ImGui::GetStyle().FontScaleMain = state.fontScale;
    }

    const ImGuiStyle& style = ImGui::GetStyle();
    const float pad        = style.WindowPadding.x;
    const float titleBarH  = 48.0f;
    const float sidebarW   = 160.0f;
    const float statusBarH = 28.0f;

    float availW = ImGui::GetContentRegionAvail().x;
    float availH = ImGui::GetContentRegionAvail().y;
    float bodyH  = availH - titleBarH - statusBarH - style.ItemSpacing.y * 2.0f;

    // ===== Top Title Bar =====
    {
        ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_TitleBgActive));
        ImGui::BeginChild("##TitleBar", ImVec2(availW, titleBarH), ImGuiChildFlags_None, ImGuiWindowFlags_NoScrollbar);
        ImGui::PopStyleColor();

        // App name + version (vertically centered)
        ImGui::SetCursorPosY(titleBarH / 2.0f - ImGui::GetTextLineHeight() / 2.0f);
        ImGui::TextColored(ImVec4(0.85f, 0.92f, 1.0f, 1.0f), u8"  3DGS");
        ImGui::SameLine();
        ImGui::TextColored(ImVec4(0.6f, 0.7f, 0.8f, 1.0f), u8" 三维高斯泼溅工具  v1.0");

        // Theme toggle on right side
        const char* themeLabel = state.isDarkTheme ? u8"浅色模式" : u8"深色模式";
        float btnW = ImGui::CalcTextSize(themeLabel).x + style.FramePadding.x * 3.0f;
        ImGui::SameLine();
        ImGui::SetCursorPosX(availW - btnW - pad);
        ImGui::SetCursorPosY(titleBarH / 2.0f - ImGui::GetTextLineHeight() / 2.0f - style.FramePadding.y / 2.0f);
        if (ImGui::Button(themeLabel)) {
            state.isDarkTheme = !state.isDarkTheme;
            if (state.isDarkTheme) {
                ApplyDarkTheme();
                ImGui::GetStyle().FontScaleMain = state.fontScale;
                LogSystem::Info(u8"已切换至深色主题");
            } else {
                ApplyLightTheme();
                ImGui::GetStyle().FontScaleMain = state.fontScale;
                LogSystem::Info(u8"已切换至浅色主题");
            }
        }
        ImGui::EndChild();
    }

    // ===== Body: Sidebar + Content (side by side) =====
    {
        // --- Sidebar ---
        ImGui::BeginChild("##Sidebar", ImVec2(sidebarW, bodyH), ImGuiChildFlags_Borders);

        const char* navItems[] = { u8" 控制面板", u8" 日志", u8" 帮助" };
        for (int i = 0; i < 3; i++) {
            bool selected = (state.currentTab == i);
            if (selected) {
                ImGui::PushStyleColor(ImGuiCol_Button, ImGui::GetColorU32(ImGuiCol_ButtonActive));
                ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImGui::GetColorU32(ImGuiCol_ButtonActive));
            }
            if (ImGui::Button(navItems[i], ImVec2(-1, 44))) {
                state.currentTab = i;
            }
            if (selected) {
                ImGui::PopStyleColor(2);
            }
            ImGui::Spacing();
        }

        // Sidebar footer: image count
        ImGui::Dummy(ImVec2(0, 10));
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

        // --- Content Area ---
        ImGui::SameLine(0, 0);
        float contentW = availW - sidebarW - style.ItemSpacing.x;
        ImGui::BeginChild("##Content", ImVec2(contentW, bodyH), ImGuiChildFlags_Borders);

        switch (state.currentTab) {
            case 0: DrawControlPanel(state); break;
            case 1: DrawLogPanel(); break;
            case 2: DrawHelpPanel(); break;
        }

        ImGui::EndChild();
    }

    // ===== Bottom Status Bar =====
    {
        ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_TitleBg));
        ImGui::BeginChild("##StatusBar", ImVec2(availW, statusBarH), ImGuiChildFlags_None, ImGuiWindowFlags_NoScrollbar);
        ImGui::PopStyleColor();

        ImGui::SetCursorPosY(4);
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

        // FPS on right
        ImGui::SameLine();
        ImGui::SetCursorPosX(availW - 100);
        ImGui::TextDisabled(u8"%.1f FPS", io.Framerate);

        ImGui::EndChild();
    }

    ImGui::End();
}

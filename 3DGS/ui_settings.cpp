// ui_settings.cpp - 设置窗口的实现
//
// 从 ui_main_window.cpp 中抽取。包含可拖动调整大小的独立窗口及外观设置：
// 主题切换、强调色选择、字体大小、界面密度和缩略图大小调整。
//
// 弹窗互斥：设置窗口打开期间 activePopup=1，其他弹窗操作会被拦截并提示。
// 关闭设置窗口时清除 activePopup。
//
#include "ui_settings.h"
#include "ui_helpers.h"
#include "theme.h"
#include "log_system.h"
#include <imgui.h>
#include <string>
#include <cstring>

void DrawSettingsPopup(AppState& state) {
    const ImGuiStyle& style = ImGui::GetStyle();
    const float uiS = UIScale(state);

    // 打开设置时检查互斥
    if (state.ui.showSettings && state.ui.activePopup == 0) {
        state.ui.activePopup = 1; // 1=设置
    }
    // 若被其他弹窗占用，取消打开
    if (state.ui.showSettings && state.ui.activePopup != 1 && state.ui.activePopup != 0) {
        state.ui.showSettings = false;
    }

    if (state.ui.showSettings) {
        // 独立可拖动调整大小的窗口：居中首次出现，允许用户拖拽边缘改变大小
        ImVec2 center = ImGui::GetMainViewport()->GetCenter();
        ImGui::SetNextWindowPos(center, ImGuiCond_Appearing, ImVec2(0.5f, 0.5f));
        // 首次出现时设置初始尺寸
        float initW = 420.0f * uiS;
        float initH = 480.0f * uiS;
        ImGui::SetNextWindowSize(ImVec2(initW, initH), ImGuiCond_Appearing);
        // 设置最小和最大尺寸约束，允许在范围内自由拖动调整
        float minW = 360.0f * uiS;
        float minH = 320.0f * uiS;
        ImVec2 maxSize = ImGui::GetMainViewport()->Size;
        ImGui::SetNextWindowSizeConstraints(
            ImVec2(minW, minH),
            ImVec2(maxSize.x * 0.9f, maxSize.y * 0.9f));

        // 移除 AlwaysAutoResize，允许用户自由拖动调整窗口大小
        if (ImGui::Begin(u8"设置##Settings", &state.ui.showSettings,
                ImGuiWindowFlags_NoCollapse)) {

            // 标题
            ImGui::PushFont(ImGui::GetFont());
            ImGui::TextColored(GetAccentColor(state.ui.accentIndex), u8"  设置");
            ImGui::PopFont();
            ImGui::Separator();
            ImGui::Spacing();

            // ===== 外观卡片：主题 + 强调色 =====
            CardWithTitle("##外观", u8"外观", GetAccentColor(state.ui.accentIndex), [&]() {
                ImGui::TextDisabled(u8"  主题");
                ImGui::Spacing();
                bool light = !state.ui.isDarkTheme;
                bool dark  = state.ui.isDarkTheme;
                if (ImGui::Checkbox(u8"  浅色模式", &light)) {
                    if (light && state.ui.isDarkTheme) {
                        state.ui.isDarkTheme = false;
                        ApplyLightTheme();
                        LogSystem::Info(u8"已切换至浅色主题");
                    }
                }
                ImGui::SameLine();
                if (ImGui::Checkbox(u8"  深色模式", &dark)) {
                    if (dark && !state.ui.isDarkTheme) {
                        state.ui.isDarkTheme = true;
                        ApplyDarkTheme();
                        LogSystem::Info(u8"已切换至深色主题");
                    }
                }

                ImGui::Spacing();
                ImGui::Separator();
                ImGui::Spacing();

                ImGui::TextDisabled(u8"  强调色");
                ImGui::Spacing();
                // 颜色色块按钮
                float swatch = 36.0f * uiS;
                for (int i = 0; i < 5; i++) {
                    if (i > 0) ImGui::SameLine();
                    ImGui::PushID(i);
                    ImVec4 col = GetAccentColor(i);
                    bool sel = (state.ui.accentIndex == i);
                    if (sel) {
                        ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(col.x, col.y, col.z, 1.0f));
                        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(col.x, col.y, col.z, 1.0f));
                        ImGui::PushStyleColor(ImGuiCol_ButtonActive, ImVec4(col.x, col.y, col.z, 1.0f));
                    } else {
                        ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(col.x, col.y, col.z, 0.55f));
                        ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(col.x, col.y, col.z, 0.85f));
                        ImGui::PushStyleColor(ImGuiCol_ButtonActive, ImVec4(col.x, col.y, col.z, 1.0f));
                    }
                    if (ImGui::Button(u8"##swatch", ImVec2(swatch, swatch))) {
                        state.ui.accentIndex = i;
                        LogSystem::Info((std::string(u8"强调色: ") + GetAccentName(i)).c_str());
                    }
                    ImGui::PopStyleColor(3);
                    if (ImGui::IsItemHovered()) {
                        ImGui::BeginTooltip();
                        ImGui::TextUnformatted(GetAccentName(i));
                        ImGui::EndTooltip();
                    }
                    ImGui::PopID();
                }
                ImGui::SameLine();
                ImGui::TextDisabled(u8"  当前: %s", GetAccentName(state.ui.accentIndex));
            });

            // ===== 字体与布局卡片：字体大小 + 密度 =====
            CardWithTitle("##字体与布局", u8"字体与布局", GetAccentColor(state.ui.accentIndex), [&]() {
                ImGui::TextDisabled(u8"  字体大小");
                ImGui::SetNextItemWidth(-1);
                if (ImGui::SliderFloat(u8"##FontSize", &state.ui.fontScale, 0.5f, 3.0f, u8"%.2fx")) {
                    ImGui::GetStyle().FontScaleMain = state.ui.fontScale;
                }
                SliderWheelFloat(&state.ui.fontScale, 0.5f, 3.0f);
                ImGui::GetStyle().FontScaleMain = state.ui.fontScale;
                ImGui::SameLine();
                if (ImGui::Button(u8"重置")) {
                    state.ui.fontScale = 1.3f;
                    ImGui::GetStyle().FontScaleMain = state.ui.fontScale;
                }

                ImGui::Spacing();
                ImGui::Separator();
                ImGui::Spacing();

                ImGui::TextDisabled(u8"  界面密度");
                ImGui::Spacing();
                const char* densityLabels[] = { u8"紧凑", u8"标准", u8"宽松" };
                for (int i = 0; i < 3; i++) {
                    if (i > 0) ImGui::SameLine();
                    ImGui::PushID(i + 100);
                    if (ImGui::RadioButton(densityLabels[i], state.ui.uiDensity == i)) {
                        state.ui.uiDensity = i;
                    }
                    ImGui::PopID();
                }
            });

            // ===== 图片预览卡片：缩略图大小 =====
            CardWithTitle("##图片预览", u8"图片预览", GetAccentColor(state.ui.accentIndex), [&]() {
                ImGui::TextDisabled(u8"  缩略图大小");
                ImGui::SetNextItemWidth(-1);
                ImGui::SliderFloat(u8"##ThumbSize", &state.ui.thumbSize, 64.0f, 192.0f, u8"%.0f px");
                SliderWheelFloat(&state.ui.thumbSize, 64.0f, 192.0f);
            });

            // ===== 操作按钮 =====
            ImGui::Spacing();
            float btnH = ButtonH(state);
            float halfW = (ImGui::GetContentRegionAvail().x - style.ItemSpacing.x) / 2.0f;
            if (ImGui::Button(u8"恢复默认", ImVec2(halfW, btnH))) {
                state.ui.fontScale   = 1.3f;
                state.ui.uiDensity   = 1;
                state.ui.thumbSize   = 96.0f;
                state.ui.accentIndex = 0;
                state.ui.isDarkTheme = false;
                ApplyLightTheme();
                ImGui::GetStyle().FontScaleMain = state.ui.fontScale;
                LogSystem::Info(u8"已恢复默认界面设置");
            }
            ImGui::SameLine();
            if (ImGui::Button(u8"关闭", ImVec2(halfW, btnH))) {
                state.ui.showSettings = false;
            }

            ImGui::End();
        }

        // 窗口关闭后清除活动弹窗标志
        if (!state.ui.showSettings && state.ui.activePopup == 1) {
            state.ui.activePopup = 0;
        }
    }
}

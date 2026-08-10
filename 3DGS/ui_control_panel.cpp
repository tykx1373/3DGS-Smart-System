// ui_control_panel.cpp - 控制面板：项目管理、工作流程、导出
//
// 主交互面板，包含：
//   - 项目管理 (加载/导出 JSON)
//   - 工作流程 (导入图片、开始/停止渲染、进度显示)
//   - 显卡优化 (自动检测 + 手动选择 + 应用推荐)
//   - 渲染参数 (采样步长、场景缩放、不透明度、高斯尺度)
//   - 导出 (PLY 点云)
//   - 图片预览网格 (缩略图：点击放大、右上角×删除带确认)
//
// 布局原则：
//   - 每个功能区块用 CardWithTitle 包裹，视觉层次清晰
//   - 语义相关按钮纵向排列（而非随意并排）
//   - 参数滑块紧凑排列，标签与控件在一行
//   - 所有尺寸随字体缩放，保持比例协调
//
#include "ui_control_panel.h"
#include "ui_helpers.h"
#include "string_utils.h"
#include "gpu_info.h"
#include "file_dialog.h"
#include "project_io.h"
#include "log_system.h"
#include "theme.h"
#include <imgui.h>
#include <algorithm>
#include <cstdio>

// 紧凑参数行：标签 + 滑块在同一行
static void ParamSliderInt(AppState& state, const char* label, int* v, int min, int max, const char* fmt) {
    char labelBuf[64];
    snprintf(labelBuf, sizeof(labelBuf), "%s:", label);
    float labelW = ImGui::CalcTextSize(labelBuf).x + ImGui::GetStyle().ItemInnerSpacing.x;
    float avail = ImGui::GetContentRegionAvail().x;
    ImGui::Text("%s", labelBuf);
    ImGui::SameLine();
    ImGui::SetNextItemWidth(avail - labelW);
    ImGui::SliderInt(fmt, v, min, max);
    SliderWheelInt(v, min, max);
}

static void ParamSliderFloat(AppState& state, const char* label, float* v, float min, float max, const char* fmt) {
    char labelBuf[64];
    snprintf(labelBuf, sizeof(labelBuf), "%s:", label);
    float labelW = ImGui::CalcTextSize(labelBuf).x + ImGui::GetStyle().ItemInnerSpacing.x;
    float avail = ImGui::GetContentRegionAvail().x;
    ImGui::Text("%s", labelBuf);
    ImGui::SameLine();
    ImGui::SetNextItemWidth(avail - labelW);
    ImGui::SliderFloat(fmt, v, min, max, fmt);
    SliderWheelFloat(v, min, max);
}

void DrawControlPanel(AppState& state) {
    const ImGuiStyle& style = ImGui::GetStyle();
    float panelW = ImGui::GetContentRegionAvail().x;
    float btnH = ButtonH(state);
    float uiS  = UIScale(state);
    ImVec4 accent = GetAccentColor(state.ui.accentIndex);

    // ===== 项目管理卡片 =====
    CardWithTitle("##Proj", u8"项目管理", accent, [&]() {
        float halfW = (ImGui::GetContentRegionAvail().x - style.ItemSpacing.x) * 0.5f;
        if (ImGui::Button(u8"加载项目", ImVec2(halfW, btnH))) {
            if (CheckPopupMutex(state, u8"加载项目")) {
                state.ui.pendingAction = PendingAction::LoadProject;
                state.ui.activePopup = 5;
            }
        }
        ImGui::SameLine();
        if (ImGui::Button(u8"导出项目 (JSON)", ImVec2(halfW, btnH))) {
            if (CheckPopupMutex(state, u8"导出项目")) {
                state.ui.pendingAction = PendingAction::SaveProject;
                state.ui.activePopup = 6;
            }
        }
    });

    // ===== 工作流程卡片 =====
    CardWithTitle("##Workflow", u8"工作流程", accent, [&]() {
        float fullW = ImGui::GetContentRegionAvail().x;

        // 导入图片（全宽，主操作 - 强调色）
        PushAccentButtonColors(accent);
        if (ImGui::Button(u8"导入图片", ImVec2(fullW, btnH))) {
            if (CheckPopupMutex(state, u8"导入图片")) {
                state.ui.pendingAction = PendingAction::ImportImages;
                state.ui.activePopup = 2;
            }
        }
        ImGui::PopStyleColor(3);

        // 渲染按钮（全宽，根据状态切换）
        bool pipelineRunning = state.pipeline.IsRunning();
        if (pipelineRunning) {
            // 停止渲染 - 警示红色
            ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.85f, 0.30f, 0.30f, 1.00f));
            ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(0.95f, 0.40f, 0.40f, 1.00f));
            ImGui::PushStyleColor(ImGuiCol_ButtonActive, ImVec4(0.70f, 0.22f, 0.22f, 1.00f));
            if (ImGui::Button(u8"停止渲染", ImVec2(fullW, btnH))) {
                if (CheckPopupMutex(state, u8"停止渲染")) {
                    state.pipeline.Stop();
                    LogSystem::Info(u8"渲染已停止");
                }
            }
            ImGui::PopStyleColor(3);
        } else {
            // 开始渲染 - 强调色
            PushAccentButtonColors(accent);
            if (ImGui::Button(u8"开始渲染", ImVec2(fullW, btnH))) {
                if (CheckPopupMutex(state, u8"开始渲染")) {
                    const auto& images = state.imageManager.GetImages();
                    if (images.empty()) {
                        LogSystem::Warn(u8"请先导入图片");
                    } else {
                        PipelineConfig cfg;
                        cfg.sampleStep  = state.sampleStep;
                        cfg.sceneScale  = state.sceneScale;
                        cfg.baseOpacity = state.baseOpacity;
                        cfg.baseScale   = state.baseScale;
                        cfg.gpuType     = state.ui.gpuType;
                        cfg.verbose     = true;
                        if (state.pipeline.Start(images, cfg)) {
                            state.isRendering = true;
                            state.renderDone = false;
                            LogSystem::Info(u8"渲染已开始");
                        }
                    }
                }
            }
            ImGui::PopStyleColor(3);
        }

        // 渲染进度
        if (pipelineRunning) {
            float progress = state.pipeline.GetProgress();
            ImGui::Spacing();
            ImGui::ProgressBar(progress, ImVec2(fullW, 0), "");
            ImGui::Text(u8"%.1f%%  %s", progress * 100.0f, state.pipeline.GetStatus().c_str());
        } else if (state.pipeline.IsFinished()) {
            if (!state.renderDone) {
                state.renderDone = true;
                state.isRendering = false;
            }
            const auto& result = state.pipeline.GetResult();
            if (result.completed) {
                ImGui::Spacing();
                ImGui::TextColored(ImVec4(0.3f, 0.7f, 0.3f, 1.0f),
                    u8"完成: %zu 个高斯点", result.points.size());
            }
        }
    });

    // ===== 显卡优化卡片 =====
    CardWithTitle("##Gpu", u8"显卡优化", accent, [&]() {
        // 检测到的显卡信息
        if (state.gpuInfo.detected) {
            // 显卡名称限制在卡片宽度内自动换行
            ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x);
            ImGui::TextColored(ImVec4(0.5f, 0.75f, 0.95f, 1.0f), u8"%s",
                state.gpuInfo.shortName.c_str());
            ImGui::PopTextWrapPos();
            if (state.gpuInfo.vramMB > 0) {
                ImGui::TextDisabled(u8"显存: %d MB", state.gpuInfo.vramMB);
            }
            ImGui::TextDisabled(u8"检测分类: %s", GetGpuTypeName(state.gpuInfo.type));
            ImGui::TextWrapped(u8"%s", GetGpuAlgoDesc(state.gpuInfo.type));
        } else {
            ImGui::TextDisabled(u8"未检测到显卡信息");
        }

        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();

        // 手动选择（紧凑排列）
        ImGui::TextDisabled(u8"渲染方案");
        const char* gpuLabels[] = { u8"高性能独显", u8"低功耗独显", u8"核显" };
        int gpuIdx = (int)state.ui.gpuType;
        for (int i = 0; i < 3; i++) {
            if (i > 0) ImGui::SameLine();
            ImGui::PushID(i + 300);
            bool isRec = (state.gpuInfo.detected && (int)state.gpuInfo.type == i);
            if (ImGui::RadioButton(gpuLabels[i], gpuIdx == i)) {
                state.ui.gpuType = (GpuType)i;
                LogSystem::Info((std::string(u8"渲染方案切换: ") + gpuLabels[i]).c_str());
            }
            ImGui::PopID();
            if (isRec) {
                ImGui::SameLine(0, 1);
                ImGui::TextColored(ImVec4(0.3f, 0.8f, 0.3f, 1.0f), u8"*");
            }
        }

        // 应用推荐按钮
        if (state.gpuInfo.detected) {
            ImGui::Spacing();
            float fullW = ImGui::GetContentRegionAvail().x;
            if (ImGui::Button(u8"应用推荐参数", ImVec2(fullW, btnH))) {
                state.sampleStep = state.gpuInfo.recSampleStep;
                state.sceneScale = state.gpuInfo.recSceneScale;
                state.baseScale  = state.gpuInfo.recBaseScale;
                state.ui.gpuType = state.gpuInfo.type;
                state.gpuAppliedRecommend = true;
                LogSystem::Info(u8"已应用推荐参数");
            }
            if (ImGui::IsItemHovered()) {
                ImGui::BeginTooltip();
                ImGui::Text(u8"采样步长 %d  |  场景缩放 %.1f  |  高斯尺度 %.2f",
                    state.gpuInfo.recSampleStep, state.gpuInfo.recSceneScale, state.gpuInfo.recBaseScale);
                ImGui::EndTooltip();
            }
        }
    });

    // ===== 渲染参数卡片 =====
    CardWithTitle("##Params", u8"渲染参数", accent, [&]() {
        ParamSliderInt(state, u8"采样步长", &state.sampleStep, 1, 16, u8"##SampleStep");
        ParamSliderFloat(state, u8"场景缩放", &state.sceneScale, 0.5f, 5.0f, u8"%.1f##SceneScale");
        ParamSliderFloat(state, u8"不透明度", &state.baseOpacity, 0.1f, 1.0f, u8"%.2f##Opacity");
        ParamSliderFloat(state, u8"高斯尺度", &state.baseScale, 0.1f, 1.0f, u8"%.2f##Scale");
    });

    // ===== 导出卡片 =====
    CardWithTitle("##Export", u8"导出", accent, [&]() {
        float fullW = ImGui::GetContentRegionAvail().x;
        bool hasResult = state.pipeline.IsFinished() &&
                         state.pipeline.GetResult().completed &&
                         !state.pipeline.GetResult().points.empty();

        if (!hasResult) {
            ImGui::BeginDisabled();
            ImGui::Button(u8"导出点云 (PLY)", ImVec2(fullW, btnH));
            ImGui::EndDisabled();
            if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
                ImGui::BeginTooltip();
                ImGui::TextUnformatted(u8"请先完成渲染");
                ImGui::EndTooltip();
            }
        } else {
            PushAccentButtonColors(accent);
            if (ImGui::Button(u8"导出点云 (PLY)", ImVec2(fullW, btnH))) {
                if (CheckPopupMutex(state, u8"导出点云")) {
                    state.ui.pendingAction = PendingAction::ExportPly;
                    state.ui.activePopup = 7;
                }
            }
            ImGui::PopStyleColor(3);
        }

        // 输出路径提示（限制在卡片宽度内换行）
        if (!state.projectConfig.outputPath.empty() || !state.projectConfig.plyOutputPath.empty()) {
            ImGui::Spacing();
            ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x);
            if (!state.projectConfig.outputPath.empty()) {
                ImGui::TextDisabled(u8"JSON: %s", state.projectConfig.outputPath.c_str());
            }
            if (!state.projectConfig.plyOutputPath.empty()) {
                ImGui::TextDisabled(u8"PLY:  %s", state.projectConfig.plyOutputPath.c_str());
            }
            ImGui::PopTextWrapPos();
        }
    });

    // ===== 图片预览卡片 =====
    const auto& images = state.imageManager.GetImages();
    if (!images.empty()) {
        CardWithTitle("##Preview", u8"图片预览", accent, [&]() {
            float fullW = ImGui::GetContentRegionAvail().x;

            // 统计栏 + 清空按钮
            size_t totalSize = 0;
            for (const auto& img : images) totalSize += img.fileSize;
            ImGui::TextDisabled(u8"共 %zu 张  |  %s", images.size(),
                StringUtils::FormatFileSize(totalSize).c_str());
            ImGui::SameLine();
            float clearW = ImGui::CalcTextSize(u8"清空").x + style.FramePadding.x * 3;
            ImGui::SetCursorPosX(fullW - clearW);
            if (ImGui::Button(u8"清空")) {
                if (CheckPopupMutex(state, u8"清空图片")) {
                    state.imageManager.ClearAll();
                    state.renderDone = false;
                    state.pipeline.Reset();
                    LogSystem::Info(u8"已清空所有图片和渲染结果");
                }
            }
            ImGui::Spacing();

            // 缩略图网格
            ImGui::BeginChild("##ImageGrid", ImVec2(0, 0), ImGuiChildFlags_Borders);

            float thumbSize = state.ui.thumbSize * uiS;
            float spacing = style.ItemSpacing.x;
            int cols = (int)((ImGui::GetContentRegionAvail().x + spacing) / (thumbSize + spacing));
            if (cols < 1) cols = 1;

            if (ImGui::BeginTable("ThumbGrid", cols)) {
                for (size_t i = 0; i < images.size(); ++i) {
                    ImGui::TableNextColumn();
                    const auto& img = images[i];
                    ImGui::PushID((int)i);

                    // 缩略图绘制
                    ImVec2 thumbPos;
                    ImVec2 thumbBox(thumbSize, thumbSize);
                    float thumbActualH = thumbSize;
                    if (img.textureLoaded) {
                        float aspect = (img.width > 0 && img.height > 0)
                            ? (float)img.height / (float)img.width : 1.0f;
                        thumbActualH = thumbSize * aspect;
                        if (thumbActualH > thumbSize) thumbActualH = thumbSize;
                        thumbPos = ImGui::GetCursorScreenPos();
                        ImGui::Image(ImTextureRef((ImTextureID)(uint64_t)img.textureId),
                            ImVec2(thumbSize, thumbActualH));
                    } else {
                        thumbPos = ImGui::GetCursorScreenPos();
                        ImGui::Dummy(thumbBox);
                    }

                    // 屏幕矩形用于 hover 检测
                    ImVec2 thumbMin = thumbPos;
                    ImVec2 thumbMax(thumbPos.x + thumbSize, thumbPos.y + thumbActualH);

                    // 悬停提示
                    ImGuiIO& io = ImGui::GetIO();
                    bool mouseOverThumb = io.MousePos.x >= thumbMin.x && io.MousePos.x < thumbMax.x
                                       && io.MousePos.y >= thumbMin.y && io.MousePos.y < thumbMax.y;
                    if (mouseOverThumb) {
                        ImGui::BeginTooltip();
                        ImGui::Text("%s", img.fileName.c_str());
                        ImGui::Text(u8"%dx%d  %s", img.width, img.height,
                            StringUtils::FormatFileSize(img.fileSize).c_str());
                        ImGui::EndTooltip();
                    }

                    // 右上角 × 删除按钮
                    float btnSize = std::max(16.0f, thumbSize * 0.18f);
                    ImVec2 xBtnPos(thumbPos.x + thumbSize - btnSize, thumbPos.y);
                    ImVec2 xBtnMin = xBtnPos;
                    ImVec2 xBtnMax(xBtnPos.x + btnSize, xBtnPos.y + btnSize);
                    bool mouseOverXBtn = io.MousePos.x >= xBtnMin.x && io.MousePos.x < xBtnMax.x
                                      && io.MousePos.y >= xBtnMin.y && io.MousePos.y < xBtnMax.y;

                    ImGui::SetCursorScreenPos(xBtnPos);
                    ImGui::PushStyleColor(ImGuiCol_Button, ImVec4(0.8f, 0.2f, 0.2f, 0.85f));
                    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ImVec4(1.0f, 0.3f, 0.3f, 1.0f));
                    ImGui::PushStyleColor(ImGuiCol_ButtonActive, ImVec4(0.7f, 0.1f, 0.1f, 1.0f));
                    ImGui::PushStyleVar(ImGuiStyleVar_FrameRounding, btnSize * 0.5f);
                    ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(0, 0));
                    char btnLabel[16];
                    snprintf(btnLabel, sizeof(btnLabel), "x##del%d", (int)i);
                    if (ImGui::Button(btnLabel, ImVec2(btnSize, btnSize)) && state.ui.inputGuard <= 0) {
                        if (state.ui.activePopup != 0 && state.ui.activePopup != 3) {
                            snprintf(state.ui.popupNotice, sizeof(state.ui.popupNotice),
                                u8"请先关闭当前打开的窗口\n再进行「删除图片」操作");
                        } else if (state.ui.activePopup == 3) {
                            ImGui::CloseCurrentPopup();
                            state.ui.previewImageIndex = -1;
                            state.ui.pendingRemoveIndex = (int)i;
                            state.ui.activePopup = 4;
                        } else {
                            state.ui.pendingRemoveIndex = (int)i;
                            state.ui.activePopup = 4;
                        }
                    }
                    ImGui::PopStyleVar(2);
                    ImGui::PopStyleColor(3);

                    // 点击放大
                    if (mouseOverThumb && !mouseOverXBtn && ImGui::IsMouseClicked(ImGuiMouseButton_Left)
                            && state.ui.inputGuard <= 0) {
                        if (CheckPopupMutex(state, u8"查看图片放大")) {
                            state.ui.previewImageIndex = (int)i;
                            state.ui.activePopup = 3;
                        }
                    }

                    ImGui::SetCursorScreenPos(ImVec2(thumbPos.x, thumbPos.y + thumbSize + style.ItemSpacing.y));
                    ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + thumbSize);
                    ImGui::TextDisabled("%s", img.fileName.c_str());
                    ImGui::PopTextWrapPos();

                    ImGui::PopID();
                }
                ImGui::EndTable();
            }

            // 弹窗打开请求（PushID 外部）
            if (state.ui.activePopup == 3 && !ImGui::IsPopupOpen("ImagePreview")) {
                ImGui::OpenPopup("ImagePreview");
            }
            if (state.ui.activePopup == 4 && !ImGui::IsPopupOpen("ConfirmRemove")) {
                ImGui::OpenPopup("ConfirmRemove");
            }

            // 删除确认弹窗
            if (ImGui::BeginPopupModal("ConfirmRemove", nullptr,
                    ImGuiWindowFlags_AlwaysAutoResize | ImGuiWindowFlags_NoTitleBar)) {
                int idx = state.ui.pendingRemoveIndex;
                if (idx >= 0 && idx < (int)images.size()) {
                    const auto& target = images[idx];
                    ImGui::Text(u8"确定要删除这张图片吗？");
                    ImGui::Spacing();
                    if (target.textureLoaded) {
                        float pv = 120.0f * uiS;
                        ImGui::Image(ImTextureRef((ImTextureID)(uint64_t)target.textureId),
                            ImVec2(pv, pv));
                    }
                    ImGui::Text(u8"%s", target.fileName.c_str());
                    ImGui::Spacing();
                    ImGui::Separator();
                    ImGui::Spacing();
                    float bw = 100.0f * uiS;
                    if (ImGui::Button(u8"确认删除", ImVec2(bw, 0))) {
                        state.imageManager.RemoveImage((size_t)idx);
                        state.renderDone = false;
                        state.ui.pendingRemoveIndex = -1;
                        state.ui.activePopup = 0;
                        ImGui::CloseCurrentPopup();
                    }
                    ImGui::SameLine();
                    if (ImGui::Button(u8"取消", ImVec2(bw, 0))) {
                        state.ui.pendingRemoveIndex = -1;
                        state.ui.activePopup = 0;
                        ImGui::CloseCurrentPopup();
                    }
                } else {
                    state.ui.pendingRemoveIndex = -1;
                    state.ui.activePopup = 0;
                    ImGui::CloseCurrentPopup();
                }
                ImGui::EndPopup();
            }

            // 放大预览弹窗
            if (ImGui::BeginPopupModal("ImagePreview", nullptr,
                    ImGuiWindowFlags_AlwaysAutoResize)) {
                int idx = state.ui.previewImageIndex;
                if (idx >= 0 && idx < (int)images.size()) {
                    const auto& target = images[idx];
                    ImGui::Text("%s", target.fileName.c_str());
                    ImGui::SameLine();
                    ImGui::TextDisabled(u8"%dx%d", target.width, target.height);
                    ImGui::Separator();
                    ImGui::Spacing();

                    ImVec2 display = ImGui::GetMainViewport()->Size;
                    float maxW = display.x * 0.7f;
                    float maxH = display.y * 0.7f;
                    float w = (float)target.width;
                    float h = (float)target.height;
                    if (w > maxW) { h = h * (maxW / w); w = maxW; }
                    if (h > maxH) { w = w * (maxH / h); h = maxH; }

                    if (target.textureLoaded) {
                        ImGui::Image(ImTextureRef((ImTextureID)(uint64_t)target.textureId),
                            ImVec2(w, h));
                    }

                    ImGui::Spacing();
                    ImGui::Separator();
                    ImGui::Spacing();
                    float bw = 100.0f * uiS;
                    if (ImGui::Button(u8"删除这张", ImVec2(bw, 0))) {
                        state.ui.pendingRemoveIndex = idx;
                        state.ui.previewImageIndex = -1;
                        state.ui.activePopup = 4;
                        ImGui::CloseCurrentPopup();
                    }
                    ImGui::SameLine();
                    ImGui::Dummy(ImVec2(0, 0));
                    ImGui::SameLine();
                    if (ImGui::Button(u8"关闭", ImVec2(bw, 0)) || ImGui::IsKeyPressed(ImGuiKey_Escape)) {
                        state.ui.previewImageIndex = -1;
                        state.ui.activePopup = 0;
                        ImGui::CloseCurrentPopup();
                    }
                } else {
                    state.ui.previewImageIndex = -1;
                    state.ui.activePopup = 0;
                    ImGui::CloseCurrentPopup();
                }
                ImGui::EndPopup();
            }

            ImGui::EndChild();
        });
    }
}

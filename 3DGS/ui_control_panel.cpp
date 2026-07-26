#include "ui_control_panel.h"
#include "file_dialog.h"
#include "project_io.h"
#include "log_system.h"
#include <imgui.h>

// Helper: draw a section card with title
static void SectionHeader(const char* title) {
    ImGui::Spacing();
    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.5f, 0.6f, 0.75f, 1.0f), "%s", title);
    ImGui::PopFont();
    ImGui::Separator();
    ImGui::Spacing();
}

void DrawControlPanel(AppState& state) {
    const ImGuiStyle& style = ImGui::GetStyle();
    float panelW = ImGui::GetContentRegionAvail().x;
    float btnW = (panelW - style.ItemSpacing.x) / 2.0f;

    // ===== Project Section =====
    SectionHeader(u8"项目管理");

    if (ImGui::Button(u8"加载项目", ImVec2(btnW, 40))) {
        std::string path = FileDialog::OpenProjectFile();
        if (!path.empty()) {
            ProjectIO::LoadProject(path, state.projectConfig, state.imageManager);
            state.renderDone = false;
        } else {
            LogSystem::Info(u8"已取消加载项目");
        }
    }
    ImGui::SameLine();
    if (ImGui::Button(u8"导出项目 (JSON)", ImVec2(btnW, 40))) {
        std::string savePath = FileDialog::SaveFile();
        if (!savePath.empty()) {
            state.projectConfig.outputPath = savePath;
            state.projectConfig.modifiedTime = ProjectIO::GetCurrentTimeISO8601();
            ProjectIO::SaveProject(savePath, state.projectConfig, state.imageManager.GetImages());
        } else {
            LogSystem::Info(u8"已取消保存");
        }
    }

    // ===== Workflow Section =====
    SectionHeader(u8"工作流程");

    // Import + Render side by side
    if (ImGui::Button(u8"导入图片", ImVec2(btnW, 44))) {
        auto files = FileDialog::OpenFiles();
        if (!files.empty()) {
            state.imageManager.AddImages(files);
            state.projectConfig.modifiedTime = ProjectIO::GetCurrentTimeISO8601();
            state.renderDone = false;
        } else {
            LogSystem::Info(u8"未选择图片");
        }
    }
    ImGui::SameLine();

    // Render button: starts pipeline if images exist and pipeline not running
    bool pipelineRunning = state.pipeline.IsRunning();
    if (pipelineRunning) {
        if (ImGui::Button(u8"停止渲染", ImVec2(btnW, 44))) {
            state.pipeline.Stop();
            LogSystem::Info(u8"渲染已停止");
        }
    } else {
        if (ImGui::Button(u8"开始渲染", ImVec2(btnW, 44))) {
            const auto& images = state.imageManager.GetImages();
            if (images.empty()) {
                LogSystem::Warn(u8"请先导入图片");
            } else {
                PipelineConfig cfg;
                cfg.sampleStep    = state.sampleStep;
                cfg.sceneScale    = state.sceneScale;
                cfg.baseOpacity   = state.baseOpacity;
                cfg.baseScale     = state.baseScale;
                cfg.verbose       = true;
                if (state.pipeline.Start(images, cfg)) {
                    state.isRendering = true;
                    state.renderDone = false;
                    LogSystem::Info(u8"渲染已开始");
                }
            }
        }
    }

    // Render progress (live from pipeline)
    if (pipelineRunning) {
        float progress = state.pipeline.GetProgress();
        ImGui::Spacing();
        ImGui::ProgressBar(progress, ImVec2(-1, 0), "");
        ImGui::Text(u8"渲染进度: %.1f%%  %s",
                    progress * 100.0f, state.pipeline.GetStatus().c_str());
    } else if (state.pipeline.IsFinished()) {
        ImGui::Spacing();
        if (!state.renderDone) {
            state.renderDone = true;
            state.isRendering = false;
        }
        const auto& result = state.pipeline.GetResult();
        if (result.completed) {
            ImGui::TextColored(ImVec4(0.3f, 0.7f, 0.3f, 1.0f),
                u8"渲染完成: %zu 个高斯点", result.points.size());
        }
    }

    // ===== Pipeline Settings Section =====
    SectionHeader(u8"渲染参数");

    ImGui::TextDisabled(u8"采样步长 (越小点越密集)");
    ImGui::SetNextItemWidth(-1);
    ImGui::SliderInt(u8"##SampleStep", &state.sampleStep, 1, 16, u8"%d 像素");

    ImGui::Spacing();
    ImGui::TextDisabled(u8"场景缩放");
    ImGui::SetNextItemWidth(-1);
    ImGui::SliderFloat(u8"##SceneScale", &state.sceneScale, 0.5f, 5.0f, u8"%.1f");

    ImGui::Spacing();
    ImGui::TextDisabled(u8"高斯不透明度");
    ImGui::SetNextItemWidth(-1);
    ImGui::SliderFloat(u8"##Opacity", &state.baseOpacity, 0.1f, 1.0f, u8"%.2f");

    ImGui::Spacing();
    ImGui::TextDisabled(u8"高斯尺度");
    ImGui::SetNextItemWidth(-1);
    ImGui::SliderFloat(u8"##Scale", &state.baseScale, 0.1f, 1.0f, u8"%.2f");

    // ===== Export Section =====
    SectionHeader(u8"导出");

    bool hasRenderResult = state.pipeline.IsFinished() &&
                           state.pipeline.GetResult().completed &&
                           !state.pipeline.GetResult().points.empty();

    if (!hasRenderResult) {
        // No render result available - disable export with hint
        ImGui::BeginDisabled();
        ImGui::Button(u8"导出点云 (PLY)", ImVec2(btnW, 44));
        ImGui::EndDisabled();
        if (ImGui::IsItemHovered(ImGuiHoveredFlags_AllowWhenDisabled)) {
            ImGui::BeginTooltip();
            ImGui::Text(u8"请先完成渲染");
            ImGui::EndTooltip();
        }
    } else {
        if (ImGui::Button(u8"导出点云 (PLY)", ImVec2(btnW, 44))) {
            std::string savePath = FileDialog::SavePlyFile();
            if (!savePath.empty()) {
                state.projectConfig.plyOutputPath = savePath;
                ProjectIO::SavePly(savePath, state.pipeline.GetResult());
            } else {
                LogSystem::Info(u8"已取消保存 PLY");
            }
        }
    }
    ImGui::SameLine();
    if (ImGui::Button(u8"清空图片", ImVec2(btnW, 44))) {
        state.imageManager.ClearAll();
        state.renderDone = false;
        state.pipeline.Reset();
        LogSystem::Info(u8"已清空所有图片和渲染结果");
    }

    // Output paths
    if (!state.projectConfig.outputPath.empty() || !state.projectConfig.plyOutputPath.empty()) {
        ImGui::Spacing();
        if (!state.projectConfig.outputPath.empty()) {
            ImGui::TextDisabled(u8"  JSON: %s", state.projectConfig.outputPath.c_str());
        }
        if (!state.projectConfig.plyOutputPath.empty()) {
            ImGui::TextDisabled(u8"  PLY:  %s", state.projectConfig.plyOutputPath.c_str());
        }
    }

    // ===== Image Preview Section =====
    const auto& images = state.imageManager.GetImages();
    if (!images.empty()) {
        SectionHeader(u8"图片预览");

        // Stats bar
        size_t totalSize = 0;
        for (const auto& img : images) totalSize += img.fileSize;
        ImGui::TextDisabled(u8"共 %zu 张 | 总计 %s", images.size(), ProjectIO::FormatFileSize(totalSize).c_str());
        ImGui::Spacing();

        ImGui::BeginChild("##ImageGrid", ImVec2(0, 0), ImGuiChildFlags_Borders);

        float thumbSize = 96.0f;
        float spacing = style.ItemSpacing.x;
        int cols = (int)((ImGui::GetContentRegionAvail().x + spacing) / (thumbSize + spacing));
        if (cols < 1) cols = 1;

        if (ImGui::BeginTable("ThumbGrid", cols)) {
            for (size_t i = 0; i < images.size(); ++i) {
                ImGui::TableNextColumn();
                const auto& img = images[i];
                ImGui::PushID((int)i);

                if (img.textureLoaded) {
                    float aspect = (img.height > 0) ? (float)img.height / (float)img.width : 1.0f;
                    float thumbH = thumbSize * aspect;
                    if (thumbH > thumbSize) thumbH = thumbSize;
                    ImGui::Image(ImTextureRef((ImTextureID)(uint64_t)img.textureId),
                        ImVec2(thumbSize, thumbH));
                } else {
                    ImGui::Dummy(ImVec2(thumbSize, thumbSize));
                }

                if (ImGui::IsItemHovered()) {
                    ImGui::BeginTooltip();
                    ImGui::Text("%s", img.fileName.c_str());
                    ImGui::Text(u8"分辨率: %dx%d  大小: %s", img.width, img.height,
                        ProjectIO::FormatFileSize(img.fileSize).c_str());
                    ImGui::Text(u8"路径: %s", img.filePath.c_str());
                    ImGui::EndTooltip();
                }

                if (ImGui::IsItemHovered() && ImGui::IsMouseClicked(ImGuiMouseButton_Right)) {
                    ImGui::OpenPopup("RemoveMenu");
                }
                if (ImGui::BeginPopup("RemoveMenu")) {
                    if (ImGui::MenuItem(u8"移除该图片")) {
                        state.imageManager.RemoveImage(i);
                        state.renderDone = false;
                    }
                    ImGui::EndPopup();
                }

                ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + thumbSize);
                ImGui::TextDisabled("%s", img.fileName.c_str());
                ImGui::PopTextWrapPos();

                ImGui::PopID();
            }
            ImGui::EndTable();
        }
        ImGui::EndChild();
    }
}

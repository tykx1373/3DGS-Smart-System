#include "ui_help_panel.h"
#include <imgui.h>

// Helper: draw a section card with title (consistent with other panels)
static void SectionHeader(const char* title) {
    ImGui::Spacing();
    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.5f, 0.6f, 0.75f, 1.0f), "%s", title);
    ImGui::PopFont();
    ImGui::Separator();
    ImGui::Spacing();
}

void DrawHelpPanel() {
    const ImGuiStyle& style = ImGui::GetStyle();

    // ===== About Section =====
    SectionHeader(u8"关于");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##AboutCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.4f, 0.6f, 0.85f, 1.0f), u8"  3DGS - 三维高斯泼溅工具");
    ImGui::PopFont();
    ImGui::TextDisabled(u8"  版本 1.0");
    ImGui::Spacing();
    ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x - style.WindowPadding.x);
    ImGui::TextWrapped(
        u8"  用于 3D Gaussian Splatting 工作流的图形化工具，支持图片导入、"
        u8"渲染处理、项目元数据 (JSON) 和点云 (PLY) 导出。"
    );
    ImGui::PopTextWrapPos();
    ImGui::EndChild();

    // ===== Quick Start Section =====
    SectionHeader(u8"快速入门");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##QuickStartCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    const char* steps[] = {
        u8"1.  导入图片    点击「导入图片」选择输入图片 (JPG/PNG/BMP)",
        u8"2.  查看预览    在缩略图预览区域查看已导入的图片",
        u8"3.  移除图片    右键点击缩略图可以移除该图片",
        u8"4.  开始渲染    点击「开始渲染」启动渲染 (当前为模拟)",
        u8"5.  导出结果    点击「导出项目 (JSON)」或「导出点云 (PLY)」"
    };
    for (const char* s : steps) {
        ImGui::Text(u8"  %s", s);
    }
    ImGui::EndChild();

    // ===== Shortcuts Section =====
    SectionHeader(u8"快捷键");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##ShortcutCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    ImGui::TextDisabled(u8"  Ctrl + 鼠标滚轮");
    ImGui::SameLine(0, style.ItemSpacing.x * 2);
    ImGui::Text(u8"放大/缩小字体 (范围 0.5x - 3.0x，步长 5%%)");

    ImGui::EndChild();

    // ===== Supported Formats Section =====
    SectionHeader(u8"支持的图片格式");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##FormatCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    const char* formats[] = {
        u8"JPEG    (.jpg, .jpeg)",
        u8"PNG     (.png)",
        u8"BMP     (.bmp)",
        u8"其他 stb_image 支持的格式"
    };
    for (const char* f : formats) {
        ImGui::Text(u8"  %s", f);
    }
    ImGui::EndChild();

    // ===== Output Formats Section =====
    SectionHeader(u8"输出格式说明");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##OutputCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.4f, 0.6f, 0.85f, 1.0f), u8"  项目信息 (JSON)");
    ImGui::PopFont();
    ImGui::TextWrapped(
        u8"  包含项目元数据、导入图片列表 (含尺寸信息) 和统计数据。\n"
        u8"  字段: 版本号、项目名称、时间戳、图片信息、输出配置、统计信息。"
    );

    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();

    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.4f, 0.6f, 0.85f, 1.0f), u8"  点云 (PLY)");
    ImGui::PopFont();
    ImGui::TextWrapped(
        u8"  3DGS 高斯点云数据，包含 62 个属性 (位置、协方差、SH 系数、不透明度)。\n"
        u8"  渲染管线实现完成后将填充实际数据。"
    );
    ImGui::EndChild();

    // ===== Log System Section =====
    SectionHeader(u8"日志系统");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##LogCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    ImGui::TextWrapped(
        u8"  日志文件位于程序同目录下的 logs/ 文件夹中，\n"
        u8"  命名格式为 3dgs_YYYY-MM-DD_HH-MM-SS.log。\n\n"
        u8"  级别说明:"
    );
    ImGui::TextColored(ImVec4(0.4f, 0.7f, 1.0f, 1.0f), u8"    INFO     ");
    ImGui::SameLine(); ImGui::TextDisabled(u8"常规信息");
    ImGui::TextColored(ImVec4(1.0f, 0.8f, 0.2f, 1.0f), u8"    WARN     ");
    ImGui::SameLine(); ImGui::TextDisabled(u8"警告信息");
    ImGui::TextColored(ImVec4(1.0f, 0.4f, 0.4f, 1.0f), u8"    ERROR    ");
    ImGui::SameLine(); ImGui::TextDisabled(u8"错误信息");

    ImGui::EndChild();

    // ===== Technical Info =====
    SectionHeader(u8"技术信息");

    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##TechCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    ImGui::TextDisabled(u8"  GUI 框架");
    ImGui::SameLine(0, style.ItemSpacing.x * 2);
    ImGui::Text(u8"Dear ImGui + GLFW + OpenGL 3.0");

    ImGui::TextDisabled(u8"  图片解码");
    ImGui::SameLine(0, style.ItemSpacing.x * 2);
    ImGui::Text(u8"stb_image");

    ImGui::TextDisabled(u8"  编译环境");
    ImGui::SameLine(0, style.ItemSpacing.x * 2);
    ImGui::Text(u8"Visual Studio 2022 (MSVC v145, C++20)");

    ImGui::EndChild();
}

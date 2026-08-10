// ui_help_panel.cpp - 帮助面板：关于、快速入门、快捷键、格式说明
//
// 以一系列卡片形式展示静态信息内容：
//   - 关于：应用名称、版本、描述
//   - 快速入门：分步使用指南
//   - 快捷键：键盘快捷键 (Ctrl+滚轮缩放字体)
//   - 支持的格式：输入图片格式
//   - 输出格式：JSON 和 PLY 导出说明
//   - 日志系统：日志文件位置和级别说明
//   - 技术信息：GUI 框架、图片解码器、编译环境
//
// 所有内容包裹在一个带滚动条的子窗口中，这样鼠标悬停在文字上
// 也能正常滚动（之前内容直接铺在面板里，鼠标在文字上时滚轮无效）。
#include "ui_help_panel.h"
#include "ui_helpers.h"
#include <imgui.h>

void DrawHelpPanel() {
    const ImGuiStyle& style = ImGui::GetStyle();
    const ImVec4 accentColor(0.4f, 0.6f, 0.85f, 1.0f);

    // 用带滚动条的子窗口包裹所有内容，使鼠标悬停在文字上也能滚动。
    // 子窗口填满内容区域，高度设为 0 表示自动占满剩余空间。
    ImGui::BeginChild("##HelpScroll", ImVec2(0, 0), ImGuiChildFlags_None, 0);

    // ===== 关于区块 =====
    SectionHeader(u8"关于");

    Card("##AboutCard", [&]() {
        ImGui::PushFont(ImGui::GetFont());
        ImGui::TextColored(accentColor, u8"  3DGS - 三维高斯泼溅工具");
        ImGui::PopFont();
        ImGui::TextDisabled(u8"  版本 1.0");
        ImGui::Spacing();
        ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x - style.WindowPadding.x);
        ImGui::TextWrapped(
            u8"  用于 3D Gaussian Splatting 工作流的图形化工具，支持图片导入、"
            u8"渲染处理、项目元数据 (JSON) 和点云 (PLY) 导出。"
        );
        ImGui::PopTextWrapPos();
    });

    // ===== 快速入门区块 =====
    SectionHeader(u8"快速入门");

    Card("##QuickStartCard", [&]() {
        const char* steps[] = {
            u8"1.  导入图片    点击「导入图片」选择输入图片 (JPG/PNG/BMP)",
            u8"2.  查看预览    在缩略图预览区域查看已导入的图片",
            u8"3.  放大/删除   点击缩略图放大查看；点右上角 × 删除该图片",
            u8"4.  开始渲染    点击「开始渲染」启动渲染管线",
            u8"5.  导出结果    点击「导出项目 (JSON)」或「导出点云 (PLY)」"
        };
        for (const char* s : steps) {
            ImGui::Text(u8"  %s", s);
        }
    });

    // ===== 快捷键区块 =====
    SectionHeader(u8"快捷键");

    Card("##ShortcutCard", [&]() {
        ImGui::TextDisabled(u8"  Ctrl + 鼠标滚轮");
        ImGui::SameLine(0, style.ItemSpacing.x * 2);
        ImGui::Text(u8"放大/缩小字体 (范围 0.5x - 3.0x，步长 5%%)");
    });

    // ===== 支持的图片格式区块 =====
    SectionHeader(u8"支持的图片格式");

    Card("##FormatCard", [&]() {
        const char* formats[] = {
            u8"JPEG    (.jpg, .jpeg)",
            u8"PNG     (.png)",
            u8"BMP     (.bmp)",
            u8"其他 stb_image 支持的格式"
        };
        for (const char* f : formats) {
            ImGui::Text(u8"  %s", f);
        }
    });

    // ===== 输出格式说明区块 =====
    SectionHeader(u8"输出格式说明");

    Card("##OutputCard", [&]() {
        ImGui::PushFont(ImGui::GetFont());
        ImGui::TextColored(accentColor, u8"  项目信息 (JSON)");
        ImGui::PopFont();
        ImGui::TextWrapped(
            u8"  包含项目元数据、导入图片列表 (含尺寸信息) 和统计数据。\n"
            u8"  字段: 版本号、项目名称、时间戳、图片信息、输出配置、统计信息。"
        );

        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();

        ImGui::PushFont(ImGui::GetFont());
        ImGui::TextColored(accentColor, u8"  点云 (PLY)");
        ImGui::PopFont();
        ImGui::TextWrapped(
            u8"  3DGS 高斯点云数据，包含 62 个属性 (位置、协方差、SH 系数、不透明度)。\n"
            u8"  渲染管线实现完成后将填充实际数据。"
        );
    });

    // ===== 日志系统区块 =====
    SectionHeader(u8"日志系统");

    Card("##LogCard", [&]() {
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
    });

    // ===== 技术信息区块 =====
    SectionHeader(u8"技术信息");

    Card("##TechCard", [&]() {
        ImGui::TextDisabled(u8"  GUI 框架");
        ImGui::SameLine(0, style.ItemSpacing.x * 2);
        ImGui::Text(u8"Dear ImGui + GLFW + OpenGL 3.0");

        ImGui::TextDisabled(u8"  图片解码");
        ImGui::SameLine(0, style.ItemSpacing.x * 2);
        ImGui::Text(u8"stb_image");

        ImGui::TextDisabled(u8"  编译环境");
        ImGui::SameLine(0, style.ItemSpacing.x * 2);
        ImGui::Text(u8"Visual Studio 2022 (MSVC v145, C++20)");
    });

    ImGui::EndChild();
}

// ui_log_panel.cpp - 日志面板：日志文件信息、统计和打开按钮
//
// 显示当前日志文件的信息和本会话统计。
// "打开日志文件"按钮使用系统默认编辑器打开日志文件。
//
// 注意：本面板不接收 AppState；通过 UIScale() / ButtonH() 重载
// 从当前 ImGui 样式推导字体缩放。
//
#include "ui_log_panel.h"
#include "ui_helpers.h"
#include "string_utils.h"
#include "log_system.h"
#include <imgui.h>
#include <windows.h>
#include <shellapi.h>
#include <filesystem>

// 辅助函数：获取日志文件大小的格式化字符串
static std::string GetLogFileSizeStr(const std::string& path) {
    if (path.empty()) return u8"未知";
    try {
        if (std::filesystem::exists(path)) {
            return StringUtils::FormatFileSize(std::filesystem::file_size(path));
        }
    } catch (...) {}
    return u8"未知";
}

void DrawLogPanel() {
    const ImGuiStyle& style = ImGui::GetStyle();
    float btnH = ButtonH();

    std::string logPath = LogSystem::GetLogFilePath();

    // ===== 日志文件信息区块 =====
    SectionHeader(u8"日志文件");

    if (logPath.empty()) {
        ImGui::TextColored(ImVec4(1.0f, 0.5f, 0.3f, 1.0f), u8"  日志文件尚未初始化");
        return;
    }

    // 带边框背景的信息卡片
    Card("##LogInfoCard", [&]() {
        // 文件名（突出显示）
        ImGui::TextDisabled(u8"  文件名");
        ImGui::PushFont(ImGui::GetFont());
        ImGui::Text(u8"  %s", StringUtils::GetFileName(logPath).c_str());
        ImGui::PopFont();

        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();

        // 所在目录
        ImGui::TextDisabled(u8"  所在目录");
        ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x - style.WindowPadding.x);
        ImGui::TextWrapped(u8"  %s", StringUtils::GetDirectory(logPath).c_str());
        ImGui::PopTextWrapPos();

        ImGui::Spacing();
        ImGui::Separator();
        ImGui::Spacing();

        // 文件大小 + 条目数，两列显示
        float halfW = (ImGui::GetContentRegionAvail().x - style.ItemSpacing.x) / 2.0f;

        ImGui::BeginGroup();
        ImGui::TextDisabled(u8"  文件大小");
        ImGui::Text(u8"  %s", GetLogFileSizeStr(logPath).c_str());
        ImGui::EndGroup();

        ImGui::SameLine(halfW + style.WindowPadding.x);

        ImGui::BeginGroup();
        const auto& entries = LogSystem::GetEntries();
        ImGui::TextDisabled(u8"  本会话记录");
        ImGui::Text(u8"  %zu 条", entries.size());
        ImGui::EndGroup();
    });

    // ===== 操作区块 =====
    SectionHeader(u8"操作");

    // 打开日志文件按钮（全宽，突出显示）
    if (ImGui::Button(u8"打开日志文件", ImVec2(-1, btnH))) {
        int len = MultiByteToWideChar(CP_UTF8, 0, logPath.c_str(), (int)logPath.size(), nullptr, 0);
        std::wstring wPath(len, 0);
        MultiByteToWideChar(CP_UTF8, 0, logPath.c_str(), (int)logPath.size(), &wPath[0], len);
        ShellExecuteW(nullptr, L"open", wPath.c_str(), nullptr, nullptr, SW_SHOWNORMAL);
        LogSystem::Info(u8"已打开日志文件");
    }

    if (ImGui::IsItemHovered()) {
        ImGui::BeginTooltip();
        ImGui::Text(u8"使用系统默认程序打开当前日志文件");
        ImGui::EndTooltip();
    }

    // ===== 本会话统计 =====
    const auto& entries = LogSystem::GetEntries();
    if (!entries.empty()) {
        SectionHeader(u8"本会话统计");

        // 按级别计数
        size_t infoCnt = 0, warnCnt = 0, errCnt = 0;
        for (const auto& e : entries) {
            switch (e.level) {
                case LogLevel::Info:    infoCnt++; break;
                case LogLevel::Warning: warnCnt++; break;
                case LogLevel::Error:   errCnt++; break;
            }
        }

        // 三列统计
        float thirdW = (ImGui::GetContentRegionAvail().x - style.ItemSpacing.x * 2) / 3.0f;

        ImGui::BeginGroup();
        ImGui::TextDisabled(u8"  信息");
        ImGui::TextColored(ImVec4(0.4f, 0.7f, 1.0f, 1.0f), u8"  %zu", infoCnt);
        ImGui::EndGroup();

        ImGui::SameLine(thirdW + style.WindowPadding.x);

        ImGui::BeginGroup();
        ImGui::TextDisabled(u8"  警告");
        ImGui::TextColored(ImVec4(1.0f, 0.8f, 0.2f, 1.0f), u8"  %zu", warnCnt);
        ImGui::EndGroup();

        ImGui::SameLine((thirdW + style.WindowPadding.x) * 2);

        ImGui::BeginGroup();
        ImGui::TextDisabled(u8"  错误");
        ImGui::TextColored(ImVec4(1.0f, 0.4f, 0.4f, 1.0f), u8"  %zu", errCnt);
        ImGui::EndGroup();
    }

    // ===== 说明区块 =====
    SectionHeader(u8"说明");

    ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x - style.WindowPadding.x);
    ImGui::TextWrapped(
        u8"日志文件以追加模式写入，每次启动程序会创建新的日志文件。\n"
        u8"文件位于程序同目录下的 logs/ 文件夹中，命名格式为 3dgs_YYYY-MM-DD_HH-MM-SS.log。\n"
        u8"日志记录格式: [HH:MM:SS][级别] 消息"
    );
    ImGui::PopTextWrapPos();
}

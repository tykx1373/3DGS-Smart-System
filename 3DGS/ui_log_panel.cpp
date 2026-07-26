#include "ui_log_panel.h"
#include "log_system.h"
#include <imgui.h>
#include <windows.h>
#include <shellapi.h>
#include <filesystem>

// Helper: draw a section card with title (consistent with control panel)
static void SectionHeader(const char* title) {
    ImGui::Spacing();
    ImGui::PushFont(ImGui::GetFont());
    ImGui::TextColored(ImVec4(0.5f, 0.6f, 0.75f, 1.0f), "%s", title);
    ImGui::PopFont();
    ImGui::Separator();
    ImGui::Spacing();
}

// Extract filename from full path
static std::string GetFileName(const std::string& path) {
    size_t pos = path.find_last_of("\\/");
    return (pos == std::string::npos) ? path : path.substr(pos + 1);
}

// Extract directory from full path
static std::string GetDirectory(const std::string& path) {
    size_t pos = path.find_last_of("\\/");
    return (pos == std::string::npos) ? "" : path.substr(0, pos);
}

// Get log file size in bytes
static std::string GetLogFileSizeStr(const std::string& path) {
    if (path.empty()) return u8"未知";
    try {
        if (std::filesystem::exists(path)) {
            auto size = std::filesystem::file_size(path);
            if (size < 1024) return std::to_string(size) + u8" B";
            if (size < 1024 * 1024) return std::to_string(size / 1024) + u8" KB";
            return std::to_string(size / (1024 * 1024)) + u8" MB";
        }
    } catch (...) {}
    return u8"未知";
}

void DrawLogPanel() {
    const ImGuiStyle& style = ImGui::GetStyle();

    std::string logPath = LogSystem::GetLogFilePath();

    // ===== Log File Info Section =====
    SectionHeader(u8"日志文件");

    if (logPath.empty()) {
        ImGui::TextColored(ImVec4(1.0f, 0.5f, 0.3f, 1.0f), u8"  日志文件尚未初始化");
        return;
    }

    // Info card with bordered background
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetColorU32(ImGuiCol_FrameBg));
    ImGui::BeginChild("##LogInfoCard", ImVec2(0, 0), ImGuiChildFlags_Borders | ImGuiChildFlags_AutoResizeY);
    ImGui::PopStyleColor();

    // File name (prominent)
    ImGui::TextDisabled(u8"  文件名");
    ImGui::PushFont(ImGui::GetFont());
    ImGui::Text(u8"  %s", GetFileName(logPath).c_str());
    ImGui::PopFont();

    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();

    // Directory
    ImGui::TextDisabled(u8"  所在目录");
    ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x - style.WindowPadding.x);
    ImGui::TextWrapped(u8"  %s", GetDirectory(logPath).c_str());
    ImGui::PopTextWrapPos();

    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();

    // File size + entry count in two columns
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

    ImGui::EndChild();

    // ===== Action Section =====
    SectionHeader(u8"操作");

    // Open log file button (full width, prominent)
    if (ImGui::Button(u8"打开日志文件", ImVec2(-1, 44))) {
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

    // ===== Session Statistics =====
    if (!entries.empty()) {
        SectionHeader(u8"本会话统计");

        // Count by level
        size_t infoCnt = 0, warnCnt = 0, errCnt = 0;
        for (const auto& e : entries) {
            switch (e.level) {
                case LogLevel::Info:    infoCnt++; break;
                case LogLevel::Warning: warnCnt++; break;
                case LogLevel::Error:   errCnt++; break;
            }
        }

        // Three-column stats
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

    // ===== Description Section =====
    SectionHeader(u8"说明");

    ImGui::PushTextWrapPos(ImGui::GetCursorPos().x + ImGui::GetContentRegionAvail().x - style.WindowPadding.x);
    ImGui::TextWrapped(
        u8"日志文件以追加模式写入，每次启动程序会创建新的日志文件。\n"
        u8"文件位于程序同目录下的 logs/ 文件夹中，命名格式为 3dgs_YYYY-MM-DD_HH-MM-SS.log。\n"
        u8"日志记录格式: [HH:MM:SS][级别] 消息"
    );
    ImGui::PopTextWrapPos();
}

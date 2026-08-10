// log_system.h - 线程安全的日志系统，支持文件输出
//
// 提供分级日志 (Info / Warning / Error)，双重输出：
//   1. 内存中的日志条目列表（用于 UI 显示）
//   2. 文件输出（追加模式，每次写入后刷新）
//
// 日志文件创建在 <exe_dir>/logs/ 目录下，命名规则：
//   3dgs_YYYY-MM-DD_HH-MM-SS.log
//
// 每行日志格式: [HH:MM:SS][级别] 消息
//
// 本模块不依赖 ImGui 或任何 UI 库。日志级别的颜色映射
// 在 UI 层处理（见 ui_helpers.h）。
#pragma once
#include <string>
#include <vector>
#include <fstream>

// 日志严重级别，按严重程度递增排列。
enum class LogLevel {
    Info,
    Warning,
    Error
};

// 单条内存日志条目，用于 UI 显示。
struct LogEntry {
    std::string message;
    std::string timestamp;   // "HH:MM:SS"
    LogLevel    level;
};

class LogSystem {
public:
    // 初始化日志文件（创建 logs/ 目录并打开文件流）。
    // 必须在启动时、任何日志记录之前调用一次。
    static void Init();

    // 按指定级别记录消息。线程安全。
    static void Info(const std::string& msg);
    static void Warn(const std::string& msg);
    static void Error(const std::string& msg);

    // 获取所有内存中的日志条目（用于 UI 显示）。
    static const std::vector<LogEntry>& GetEntries();

    // 清除内存中的条目（不影响日志文件）。
    static void Clear();

    // 获取当前日志文件路径（用于"打开日志文件"按钮）。
    static std::string GetLogFilePath();

private:
    // 将格式化的行写入日志文件。
    static void WriteToFile(const std::string& levelStr, const std::string& msg);

    static std::vector<LogEntry> s_Entries;
    static std::ofstream         s_LogFile;
    static std::string           s_LogFilePath;
};

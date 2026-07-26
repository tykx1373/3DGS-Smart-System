#pragma once
#include <string>
#include <vector>
#include <fstream>
#include <imgui.h>

enum class LogLevel {
    Info,
    Warning,
    Error
};

struct LogEntry {
    std::string message;
    std::string timestamp;   // "HH:MM:SS"
    LogLevel   level;
};

class LogSystem {
public:
    // Initialize log file (create logs/ directory and open file stream)
    static void Init();

    static void Info(const std::string& msg);
    static void Warn(const std::string& msg);
    static void Error(const std::string& msg);

    static const std::vector<LogEntry>& GetEntries();
    static void Clear();

    static ImVec4 GetLevelColor(LogLevel level);

    // Get the current log file path
    static std::string GetLogFilePath();

private:
    static void WriteToFile(const std::string& levelStr, const std::string& msg);

    static std::vector<LogEntry> s_Entries;
    static std::ofstream         s_LogFile;
    static std::string           s_LogFilePath;
};

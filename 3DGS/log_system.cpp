// log_system.cpp - 线程安全日志系统的实现
//
// 公共 API 和设计说明见 log_system.h。
#include "log_system.h"
#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <filesystem>
#include <windows.h>

std::vector<LogEntry> LogSystem::s_Entries;
std::ofstream         LogSystem::s_LogFile;
std::string           LogSystem::s_LogFilePath;

static std::string GetExeDir() {
    wchar_t buffer[MAX_PATH];
    DWORD len = GetModuleFileNameW(nullptr, buffer, MAX_PATH);
    if (len == 0) return "";
    std::wstring wPath(buffer, len);
    size_t pos = wPath.find_last_of(L"\\/");
    if (pos == std::wstring::npos) return "";
    std::wstring wDir = wPath.substr(0, pos);
    int n = WideCharToMultiByte(CP_UTF8, 0, wDir.c_str(), (int)wDir.size(), nullptr, 0, nullptr, nullptr);
    std::string dir(n, 0);
    WideCharToMultiByte(CP_UTF8, 0, wDir.c_str(), (int)wDir.size(), &dir[0], n, nullptr, nullptr);
    return dir;
}

static std::string GetCurrentTimestamp() {
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    struct tm tm_buf;
    localtime_s(&tm_buf, &time_t);

    std::ostringstream oss;
    oss << std::put_time(&tm_buf, "%H:%M:%S");
    return oss.str();
}

static std::string GetLogFileName() {
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    struct tm tm_buf;
    localtime_s(&tm_buf, &time_t);

    std::ostringstream oss;
    oss << std::put_time(&tm_buf, "%Y-%m-%d_%H-%M-%S");
    return "3dgs_" + oss.str() + ".log";
}

void LogSystem::Init() {
    std::string exeDir = GetExeDir();
    if (exeDir.empty()) exeDir = ".";

    std::string logDir = exeDir + "\\logs";
    std::filesystem::create_directories(logDir);

    s_LogFilePath = logDir + "\\" + GetLogFileName();
    s_LogFile.open(s_LogFilePath, std::ios::out | std::ios::app);

    if (s_LogFile.is_open()) {
        s_LogFile << "========================================" << std::endl;
        s_LogFile << "  3DGS Log Started: " << GetCurrentTimestamp() << std::endl;
        s_LogFile << "========================================" << std::endl;
        s_LogFile.flush();
    }
}

void LogSystem::WriteToFile(const std::string& levelStr, const std::string& msg) {
    if (s_LogFile.is_open()) {
        s_LogFile << "[" << GetCurrentTimestamp() << "][" << levelStr << "] " << msg << std::endl;
        s_LogFile.flush();
    }
}

void LogSystem::Info(const std::string& msg) {
    s_Entries.push_back({msg, GetCurrentTimestamp(), LogLevel::Info});
    WriteToFile("INFO", msg);
}

void LogSystem::Warn(const std::string& msg) {
    s_Entries.push_back({msg, GetCurrentTimestamp(), LogLevel::Warning});
    WriteToFile("WARN", msg);
}

void LogSystem::Error(const std::string& msg) {
    s_Entries.push_back({msg, GetCurrentTimestamp(), LogLevel::Error});
    WriteToFile("ERROR", msg);
}

const std::vector<LogEntry>& LogSystem::GetEntries() {
    return s_Entries;
}

void LogSystem::Clear() {
    s_Entries.clear();
}

std::string LogSystem::GetLogFilePath() {
    return s_LogFilePath;
}

// string_utils.h - 通用字符串与路径格式化工具
//
// 集中处理路径/文件名提取和文件大小格式化函数，
// 这些函数此前在 ui_log_panel.cpp、ui_control_panel.cpp 和 project_io.cpp
// 中存在重复实现。
#pragma once
#include <string>
#include <cstdint>

namespace StringUtils {

// 从完整路径中提取文件名（含扩展名）。
// "C:\dir\file.txt" -> "file.txt"
inline std::string GetFileName(const std::string& path) {
    size_t pos = path.find_last_of("\\/");
    return (pos == std::string::npos) ? path : path.substr(pos + 1);
}

// 从完整路径中提取目录（不含末尾分隔符）。
// "C:\dir\file.txt" -> "C:\dir"
inline std::string GetDirectory(const std::string& path) {
    size_t pos = path.find_last_of("\\/");
    return (pos == std::string::npos) ? "" : path.substr(0, pos);
}

// 将字节数格式化为易读的字符串 (B / KB / MB / GB)。
// 示例: 512 -> "512 B", 1536 -> "1 KB", 1048576 -> "1 MB"
inline std::string FormatFileSize(uint64_t bytes) {
    if (bytes < 1024) return std::to_string(bytes) + " B";
    if (bytes < 1024ULL * 1024) return std::to_string(bytes / 1024) + " KB";
    if (bytes < 1024ULL * 1024 * 1024) return std::to_string(bytes / (1024 * 1024)) + " MB";
    return std::to_string(bytes / (1024ULL * 1024 * 1024)) + " GB";
}

// 去除字符串首尾的空白字符。
inline std::string Trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

} // namespace StringUtils

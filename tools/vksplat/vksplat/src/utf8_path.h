#pragma once

#include <cstdio>
#include <cstring>
#include <filesystem>
#include <string>

// Python hands VkSplat file paths as UTF-8 bytes: pybind11 always encodes a
// Python str -> std::string as UTF-8, regardless of the OS locale.
//
// MSVC's *narrow* std::ifstream / std::fopen resolve such a byte string through
// the ANSI codepage. On a system whose ACP is not UTF-8 (e.g. 936/GBK on Chinese
// Windows) any non-ASCII path - say a project folder named "科研立项" - is
// misdecoded and the file cannot be opened ("Failed to open file").
//
// std::filesystem::u8path() decodes the string as UTF-8 and returns a path that
// the fstream / FILE overloads open through the wide (UTF-16) Win32 APIs, so the
// path is correct on every system locale.
namespace vksplat_util {

inline std::filesystem::path utf8Path(const std::string& utf8) {
    return std::filesystem::u8path(utf8);
}

// fopen() equivalent that is safe for non-ASCII paths.
// `mode` is a narrow ASCII string such as "wb".
inline FILE* openFile(const std::string& utf8, const char* mode) {
#ifdef _WIN32
    std::wstring wmode(mode, mode + std::strlen(mode));
    return _wfopen(utf8Path(utf8).wstring().c_str(), wmode.c_str());
#else
    return std::fopen(utf8.c_str(), mode);
#endif
}

}  // namespace vksplat_util
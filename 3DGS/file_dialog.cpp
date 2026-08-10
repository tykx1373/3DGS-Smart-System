// file_dialog.cpp - Windows 文件对话框封装的实现
//
// 公共 API 见 file_dialog.h。
// 使用 GetOpenFileNameW / GetSaveFileNameW，内部进行 UTF-16 转换。
//
#include "file_dialog.h"
#include <windows.h>
#include <commdlg.h>
#include <shlwapi.h>
#include <string>

#pragma comment(lib, "comdlg32.lib")
#pragma comment(lib, "shlwapi.lib")

// 静态成员初始化：默认无父窗口
NativeWindowHandle FileDialog::s_ownerWindow = nullptr;

// 设置父窗口句柄，使文件对话框成为模态对话框
void FileDialog::SetOwnerWindow(NativeWindowHandle handle) {
    s_ownerWindow = handle;
}

// 辅助函数：窄字符 (UTF-8) 转宽字符 (UTF-16)
static std::wstring Utf8ToWide(const std::string& str) {
    if (str.empty()) return {};
    int len = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), nullptr, 0);
    std::wstring wstr(len, 0);
    MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), &wstr[0], len);
    return wstr;
}

// 辅助函数：宽字符 (UTF-16) 转窄字符 (UTF-8)
static std::string WideToUtf8(const std::wstring& wstr) {
    if (wstr.empty()) return {};
    int len = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), nullptr, 0, nullptr, nullptr);
    std::string str(len, 0);
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), &str[0], len, nullptr, nullptr);
    return str;
}

std::vector<std::string> FileDialog::OpenFiles(
    const std::string& title,
    const std::string& filterDesc,
    const std::string& filterExt)
{
    std::vector<std::string> result;

    // 构建宽字符过滤字符串："图片文件\0*.jpg;*.png\0所有文件\0*.*\0\0"
    std::wstring wFilter = Utf8ToWide(filterDesc) + L'\0' + Utf8ToWide(filterExt) + L'\0' + L"All Files\0*.*\0";

    // 多选缓冲区（宽字符，最大 32768 字符）
    wchar_t buffer[32768] = {};
    buffer[0] = L'\0';

    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner   = (HWND)s_ownerWindow;
    ofn.lpstrFilter = wFilter.c_str();
    ofn.nFilterIndex = 1;
    ofn.lpstrFile   = buffer;
    ofn.nMaxFile    = sizeof(buffer) / sizeof(wchar_t);
    ofn.lpstrTitle  = Utf8ToWide(title).c_str();
    ofn.Flags       = OFN_ALLOWMULTISELECT | OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;

    if (GetOpenFileNameW(&ofn)) {
        // 解析多选结果
        // buffer[0] = 目录路径（多选时），然后 \0 文件1 \0 文件2 \0 ... \0
        std::wstring dirPath = buffer;
        wchar_t* p = buffer + dirPath.size() + 1;

        if (*p == L'\0') {
            // 单选：buffer 即为完整路径
            result.push_back(WideToUtf8(dirPath));
        } else {
            // 多选
            while (*p != L'\0') {
                std::wstring fullPath = dirPath + L"\\" + std::wstring(p);
                result.push_back(WideToUtf8(fullPath));
                p += wcslen(p) + 1;
            }
        }
    }

    return result;
}

std::string FileDialog::OpenProjectFile(
    const std::string& title,
    const std::string& filterDesc,
    const std::string& filterExt)
{
    std::wstring wFilter = Utf8ToWide(filterDesc) + L'\0' + Utf8ToWide(filterExt) + L'\0' + L"All Files\0*.*\0";

    wchar_t buffer[MAX_PATH] = {};

    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner   = (HWND)s_ownerWindow;
    ofn.lpstrFilter = wFilter.c_str();
    ofn.nFilterIndex = 1;
    ofn.lpstrFile   = buffer;
    ofn.nMaxFile    = MAX_PATH;
    ofn.lpstrTitle  = Utf8ToWide(title).c_str();
    ofn.Flags       = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;

    if (GetOpenFileNameW(&ofn)) {
        return WideToUtf8(std::wstring(buffer));
    }

    return "";
}

std::string FileDialog::SaveFile(
    const std::string& title,
    const std::string& defaultName,
    const std::string& filterDesc,
    const std::string& filterExt)
{
    std::wstring wFilter = Utf8ToWide(filterDesc) + L'\0' + Utf8ToWide(filterExt) + L'\0' + L"All Files\0*.*\0";

    wchar_t buffer[MAX_PATH] = {};
    std::wstring wDefault = Utf8ToWide(defaultName);
    wcsncpy_s(buffer, wDefault.c_str(), _TRUNCATE);

    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner   = (HWND)s_ownerWindow;
    ofn.lpstrFilter = wFilter.c_str();
    ofn.nFilterIndex = 1;
    ofn.lpstrFile   = buffer;
    ofn.nMaxFile    = MAX_PATH;
    ofn.lpstrTitle  = Utf8ToWide(title).c_str();
    ofn.Flags       = OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR;
    ofn.lpstrDefExt = L"json";

    if (GetSaveFileNameW(&ofn)) {
        return WideToUtf8(std::wstring(buffer));
    }

    return "";
}

std::string FileDialog::SavePlyFile(
    const std::string& title,
    const std::string& defaultName,
    const std::string& filterDesc,
    const std::string& filterExt)
{
    std::wstring wFilter = Utf8ToWide(filterDesc) + L'\0' + Utf8ToWide(filterExt) + L'\0' + L"All Files\0*.*\0";

    wchar_t buffer[MAX_PATH] = {};
    std::wstring wDefault = Utf8ToWide(defaultName);
    wcsncpy_s(buffer, wDefault.c_str(), _TRUNCATE);

    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner   = (HWND)s_ownerWindow;
    ofn.lpstrFilter = wFilter.c_str();
    ofn.nFilterIndex = 1;
    ofn.lpstrFile   = buffer;
    ofn.nMaxFile    = MAX_PATH;
    ofn.lpstrTitle  = Utf8ToWide(title).c_str();
    ofn.Flags       = OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR;
    ofn.lpstrDefExt = L"ply";

    if (GetSaveFileNameW(&ofn)) {
        return WideToUtf8(std::wstring(buffer));
    }

    return "";
}

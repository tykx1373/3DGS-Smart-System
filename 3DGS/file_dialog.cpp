#include "file_dialog.h"
#include <windows.h>
#include <commdlg.h>
#include <shlwapi.h>
#include <string>

#pragma comment(lib, "comdlg32.lib")
#pragma comment(lib, "shlwapi.lib")

// Helper: narrow (UTF-8) to wide (UTF-16)
static std::wstring Utf8ToWide(const std::string& str) {
    if (str.empty()) return {};
    int len = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), nullptr, 0);
    std::wstring wstr(len, 0);
    MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), &wstr[0], len);
    return wstr;
}

// Helper: wide (UTF-16) to narrow (UTF-8)
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

    // Build wide filter string: "图片文件\0*.jpg;*.png\0所有文件\0*.*\0\0"
    std::wstring wFilter = Utf8ToWide(filterDesc) + L'\0' + Utf8ToWide(filterExt) + L'\0' + L"All Files\0*.*\0";

    // Multi-select buffer for wide char (32768 chars max)
    wchar_t buffer[32768] = {};
    buffer[0] = L'\0';

    OPENFILENAMEW ofn = {};
    ofn.lStructSize = sizeof(ofn);
    ofn.hwndOwner   = nullptr;
    ofn.lpstrFilter = wFilter.c_str();
    ofn.nFilterIndex = 1;
    ofn.lpstrFile   = buffer;
    ofn.nMaxFile    = sizeof(buffer) / sizeof(wchar_t);
    ofn.lpstrTitle  = Utf8ToWide(title).c_str();
    ofn.Flags       = OFN_ALLOWMULTISELECT | OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;

    if (GetOpenFileNameW(&ofn)) {
        // Parse multi-select result
        // buffer[0] = directory path (if multi), then \0 file1 \0 file2 \0 ... \0
        std::wstring dirPath = buffer;
        wchar_t* p = buffer + dirPath.size() + 1;

        if (*p == L'\0') {
            // Single selection: buffer is the full path
            result.push_back(WideToUtf8(dirPath));
        } else {
            // Multi selection
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
    ofn.hwndOwner   = nullptr;
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
    ofn.hwndOwner   = nullptr;
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
    ofn.hwndOwner   = nullptr;
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

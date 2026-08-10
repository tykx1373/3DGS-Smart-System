// file_dialog.h - Windows 文件对话框封装
//
// 使用 Win32 通用对话框 API (GetOpenFileNameW / GetSaveFileNameW)
// 提供打开和保存文件的静态方法。
//
// 所有字符串参数和返回值均使用 UTF-8 编码。
// 内部在与 Win32 宽字符 API 交互时进行 UTF-16 转换。
//
// 方法:
//   OpenFiles()        - 多选图片文件对话框 (JPG/PNG/BMP)
//   OpenProjectFile()  - 单选 JSON 项目文件对话框
//   SaveFile()         - JSON 项目文件保存对话框
//   SavePlyFile()      - PLY 点云文件保存对话框
//
#pragma once
#include <string>
#include <vector>

// 平台原生窗口句柄（Win32 下为 HWND）
#ifdef _WIN32
struct HWND__;
using NativeWindowHandle = HWND__*;
#else
using NativeWindowHandle = void*;
#endif

class FileDialog {
public:
    // 设置父窗口句柄。设置后，文件对话框将成为该窗口的模态对话框：
    // 操作系统会禁用父窗口的所有输入，对话框始终显示在父窗口之上，
    // 用户无法在对话框关闭前操作父窗口。
    // 必须在调用 Open*/Save* 方法之前调用。
    static void SetOwnerWindow(NativeWindowHandle handle);

    // 打开文件对话框，支持多选图片文件。
    // 返回选中的文件路径列表（取消则为空）。
    static std::vector<std::string> OpenFiles(
        const std::string& title = u8"选择图片",
        const std::string& filterDesc = u8"图片文件",
        const std::string& filterExt = "*.jpg;*.jpeg;*.png;*.bmp"
    );

    // 打开单个 JSON 项目文件。
    // 返回选中的文件路径（取消则为空）。
    static std::string OpenProjectFile(
        const std::string& title = u8"加载项目",
        const std::string& filterDesc = u8"JSON 项目文件",
        const std::string& filterExt = "*.json"
    );

    // JSON 项目文件保存对话框。
    // 返回选择的保存路径（取消则为空）。
    static std::string SaveFile(
        const std::string& title = u8"保存项目",
        const std::string& defaultName = "project.json",
        const std::string& filterDesc = u8"JSON 文件",
        const std::string& filterExt = "*.json"
    );

    // PLY 点云文件保存对话框。
    // 返回选择的保存路径（取消则为空）。
    static std::string SavePlyFile(
        const std::string& title = u8"导出点云",
        const std::string& defaultName = "point_cloud.ply",
        const std::string& filterDesc = u8"PLY 文件",
        const std::string& filterExt = "*.ply"
    );

private:
    static NativeWindowHandle s_ownerWindow;
};

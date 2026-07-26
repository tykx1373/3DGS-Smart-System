#pragma once
#include <string>
#include <vector>

class FileDialog {
public:
    // Open file dialog, supports multi-select
    static std::vector<std::string> OpenFiles(
        const std::string& title = u8"选择图片",
        const std::string& filterDesc = u8"图片文件",
        const std::string& filterExt = "*.jpg;*.jpeg;*.png;*.bmp"
    );

    // Open single JSON project file
    static std::string OpenProjectFile(
        const std::string& title = u8"加载项目",
        const std::string& filterDesc = u8"JSON 项目文件",
        const std::string& filterExt = "*.json"
    );

    // Save file dialog
    static std::string SaveFile(
        const std::string& title = u8"保存项目",
        const std::string& defaultName = "project.json",
        const std::string& filterDesc = u8"JSON 文件",
        const std::string& filterExt = "*.json"
    );

    // Save PLY file dialog
    static std::string SavePlyFile(
        const std::string& title = u8"导出点云",
        const std::string& defaultName = "point_cloud.ply",
        const std::string& filterDesc = u8"PLY 文件",
        const std::string& filterExt = "*.ply"
    );
};

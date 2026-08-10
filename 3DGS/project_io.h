// project_io.h - 项目文件 I/O 与 PLY 导出
//
// 处理两种导出格式：
//   1. JSON 项目文件 - 元数据、图片列表、统计信息
//   2. PLY 点云文件 - 二进制 3DGS 格式，包含 62 个顶点属性
//
// JSON 格式:
//   {
//     "version": "1.0",
//     "project": { "name", "created_time", "modified_time" },
//     "images":  [ { "file_path", "file_name", "file_size", "width", "height", "channels" } ],
//     "output":  { "path", "ply_path", "format" },
//     "statistics": { "total_images", "total_file_size", "total_file_size_formatted" }
//   }
//
// PLY 格式:
//   binary_little_endian，每个顶点 62 个 float 属性:
//   x, y, z, nx, ny, nz, f_dc_0..2, f_rest_0..44, opacity, scale_0..2, rot_0..3
//
#pragma once
#include <string>
#include <vector>
#include "image_manager.h"
#include "pipeline.h"

// 存储在 JSON 文件中的项目元数据。
struct ProjectConfig {
    std::string projectName     = "My 3DGS Project";
    std::string createdTime;           // ISO 8601 格式
    std::string modifiedTime;          // ISO 8601 格式
    std::string outputPath       = ""; // 上次 JSON 导出路径
    std::string plyOutputPath    = ""; // 上次 PLY 导出路径
    std::string outputFormat     = "ply";
};

class ProjectIO {
public:
    // 将项目元数据导出为 JSON。
    // 成功返回 true，文件打开失败返回 false。
    static bool SaveProject(
        const std::string& filePath,
        const ProjectConfig& config,
        const std::vector<ImageEntry>& images
    );

    // 从 JSON 加载项目元数据。
    // 将图片列表恢复到提供的 ImageManager 中。
    // 成功返回 true，文件打开或解析失败返回 false。
    static bool LoadProject(
        const std::string& filePath,
        ProjectConfig& config,
        ImageManager& imageManager
    );

    // 将 3DGS 点云导出为二进制 PLY，包含真实高斯点数据。
    // 成功返回 true，文件打开失败返回 false。
    static bool SavePly(const std::string& filePath, const RenderResult& result);

    // 旧版占位 PLY 导出（0 个顶点，仅头部）。
    // 在无渲染结果但需要 PLY 结构时使用。
    static bool SavePlyPlaceholder(const std::string& filePath);

    // 获取当前时间的 ISO 8601 格式 (如 "2026-07-26T15:30:00")。
    static std::string GetCurrentTimeISO8601();

    // 将字节数格式化为易读的字符串 (如 "1.5 MB")。
    // 委托给 StringUtils::FormatFileSize 以保持一致性。
    static std::string FormatFileSize(size_t bytes);

private:
    // JSON 字符串转义/反转义 (处理 " \ \n \r \t)。
    static std::string JsonEscape(const std::string& raw);
    static std::string JsonUnescape(const std::string& raw);

    // 从 JSON 中提取键对应的字符串值：查找 "key" : "value"。
    // 简单解析器 - 不处理嵌套对象或数组。
    static std::string ExtractJsonString(const std::string& json, const std::string& key);
};

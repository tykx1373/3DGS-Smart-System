// project_io.cpp - 项目文件 I/O 与 PLY 导出的实现
//
// 公共 API 和格式规范见 project_io.h。
//
#include "project_io.h"
#include "string_utils.h"
#include "log_system.h"
#include <fstream>
#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <algorithm>
#include <cstring>

// ============================================================================
// 私有 JSON 辅助函数
// ============================================================================

std::string ProjectIO::JsonEscape(const std::string& raw) {
    std::string result;
    result.reserve(raw.size() + 16);
    for (char c : raw) {
        switch (c) {
            case '"':  result += "\\\""; break;
            case '\\': result += "\\\\";  break;
            case '\n': result += "\\n";   break;
            case '\r': result += "\\r";   break;
            case '\t': result += "\\t";   break;
            default:   result += c;        break;
        }
    }
    return result;
}

std::string ProjectIO::JsonUnescape(const std::string& raw) {
    std::string result;
    result.reserve(raw.size());
    for (size_t i = 0; i < raw.size(); ++i) {
        if (raw[i] == '\\' && i + 1 < raw.size()) {
            char next = raw[i + 1];
            switch (next) {
                case '"':  result += '"';  ++i; break;
                case '\\': result += '\\'; ++i; break;
                case 'n':  result += '\n'; ++i; break;
                case 'r':  result += '\r'; ++i; break;
                case 't':  result += '\t'; ++i; break;
                default:   result += raw[i]; break;
            }
        } else {
            result += raw[i];
        }
    }
    return result;
}

// 简单的 JSON 字符串提取器：查找 "key" : "value" 并返回 value。
// 不处理嵌套对象或数组 - 对本项目的扁平 JSON 结构足够。
std::string ProjectIO::ExtractJsonString(const std::string& json, const std::string& key) {
    std::string searchKey = "\"" + key + "\"";
    size_t pos = json.find(searchKey);
    if (pos == std::string::npos) return "";
    pos = json.find(':', pos + searchKey.size());
    if (pos == std::string::npos) return "";
    pos = json.find('"', pos + 1);
    if (pos == std::string::npos) return "";
    size_t start = pos + 1;
    size_t end = start;
    while (end < json.size() && json[end] != '"') {
        if (json[end] == '\\' && end + 1 < json.size()) ++end;
        ++end;
    }
    return JsonUnescape(json.substr(start, end - start));
}

// ============================================================================
// 公共工具方法
// ============================================================================

std::string ProjectIO::FormatFileSize(size_t bytes) {
    return StringUtils::FormatFileSize(static_cast<uint64_t>(bytes));
}

std::string ProjectIO::GetCurrentTimeISO8601() {
    auto now = std::chrono::system_clock::now();
    auto time_t = std::chrono::system_clock::to_time_t(now);
    struct tm tm_buf;
    localtime_s(&tm_buf, &time_t);

    std::ostringstream oss;
    oss << std::put_time(&tm_buf, "%Y-%m-%dT%H:%M:%S");
    return oss.str();
}

// ============================================================================
// JSON 项目保存/加载
// ============================================================================

bool ProjectIO::SaveProject(
    const std::string& filePath,
    const ProjectConfig& config,
    const std::vector<ImageEntry>& images)
{
    std::ofstream ofs(filePath);
    if (!ofs.is_open()) {
        LogSystem::Error(u8"无法打开文件进行写入: " + filePath);
        return false;
    }

    // 计算总大小用于统计
    size_t totalSize = 0;
    for (const auto& img : images) totalSize += img.fileSize;

    ofs << "{\n";
    ofs << "  \"version\": \"1.0\",\n";

    // 项目信息
    ofs << "  \"project\": {\n";
    ofs << "    \"name\": \"" << JsonEscape(config.projectName) << "\",\n";
    ofs << "    \"created_time\": \"" << config.createdTime << "\",\n";
    ofs << "    \"modified_time\": \"" << config.modifiedTime << "\"\n";
    ofs << "  },\n";

    // 图片数组
    ofs << "  \"images\": [\n";
    for (size_t i = 0; i < images.size(); i++) {
        const auto& img = images[i];
        ofs << "    {\n";
        ofs << "      \"file_path\": \"" << JsonEscape(img.filePath) << "\",\n";
        ofs << "      \"file_name\": \"" << JsonEscape(img.fileName) << "\",\n";
        ofs << "      \"file_size\": " << img.fileSize << ",\n";
        ofs << "      \"width\": " << img.width << ",\n";
        ofs << "      \"height\": " << img.height << ",\n";
        ofs << "      \"channels\": " << img.channels << "\n";
        ofs << "    }" << (i + 1 < images.size() ? "," : "") << "\n";
    }
    ofs << "  ],\n";

    // 输出配置
    ofs << "  \"output\": {\n";
    ofs << "    \"path\": \"" << JsonEscape(config.outputPath) << "\",\n";
    ofs << "    \"ply_path\": \"" << JsonEscape(config.plyOutputPath) << "\",\n";
    ofs << "    \"format\": \"" << JsonEscape(config.outputFormat) << "\"\n";
    ofs << "  },\n";

    // 统计信息
    ofs << "  \"statistics\": {\n";
    ofs << "    \"total_images\": " << images.size() << ",\n";
    ofs << "    \"total_file_size\": " << totalSize << ",\n";
    ofs << "    \"total_file_size_formatted\": \"" << FormatFileSize(totalSize) << "\"\n";
    ofs << "  }\n";

    ofs << "}\n";
    ofs.close();

    LogSystem::Info(u8"项目已保存至: " + filePath);
    return true;
}

bool ProjectIO::LoadProject(
    const std::string& filePath,
    ProjectConfig& config,
    ImageManager& imageManager)
{
    std::ifstream ifs(filePath);
    if (!ifs.is_open()) {
        LogSystem::Error(u8"无法打开项目文件: " + filePath);
        return false;
    }

    // 将整个文件读入字符串
    std::stringstream ss;
    ss << ifs.rdbuf();
    std::string json = ss.str();
    ifs.close();

    // 提取项目元数据
    config.projectName  = ExtractJsonString(json, "name");
    config.createdTime  = ExtractJsonString(json, "created_time");
    config.modifiedTime = ExtractJsonString(json, "modified_time");
    config.outputPath   = ExtractJsonString(json, "path");
    config.plyOutputPath = ExtractJsonString(json, "ply_path");
    config.outputFormat  = ExtractJsonString(json, "format");

    if (config.projectName.empty()) {
        config.projectName = "Loaded Project";
    }

    // 从 images 数组中提取所有 file_path 值
    imageManager.ClearAll();
    size_t searchPos = json.find("\"images\"");
    if (searchPos == std::string::npos) {
        LogSystem::Warn(u8"项目文件中未找到图片列表");
        LogSystem::Info(u8"项目已加载: " + config.projectName);
        return true;
    }

    size_t arrayStart = json.find('[', searchPos);
    size_t arrayEnd   = json.find(']', arrayStart);
    if (arrayStart == std::string::npos || arrayEnd == std::string::npos) {
        LogSystem::Warn(u8"项目文件图片列表格式错误");
        return false;
    }

    // 在 images 数组中查找所有 "file_path": "..." 出现的位置
    int loadedCount = 0;
    size_t pos = arrayStart;
    while (pos < arrayEnd) {
        std::string path = ExtractJsonString(json.substr(pos, arrayEnd - pos), "file_path");
        if (path.empty()) break;
        imageManager.AddImage(path);
        loadedCount++;
        // 移过本次出现位置
        size_t next = json.find("\"file_path\"", pos);
        if (next == std::string::npos) break;
        pos = next + 11;
    }

    LogSystem::Info(u8"项目已加载: " + config.projectName + u8" (" +
                    std::to_string(loadedCount) + u8" 张图片)");
    return true;
}

// ============================================================================
// PLY 导出
// ============================================================================

bool ProjectIO::SavePly(const std::string& filePath, const RenderResult& result) {
    std::ofstream ofs(filePath, std::ios::binary);
    if (!ofs.is_open()) {
        LogSystem::Error(u8"无法打开 PLY 文件进行写入: " + filePath);
        return false;
    }

    size_t vertexCount = result.points.size();

    // PLY 头部 - binary_little_endian 格式
    // 标准 3DGS PLY: 62 个属性 (位置、法线、SH、不透明度、尺度、旋转)
    ofs << "ply\n";
    ofs << "format binary_little_endian 1.0\n";
    ofs << "comment 3DGS generated by 3DGS Tool v1.0\n";
    ofs << "comment source_images: " << result.imageCount << "\n";
    ofs << "comment source_resolution: " << result.sourceWidth << "x" << result.sourceHeight << "\n";
    ofs << "element vertex " << vertexCount << "\n";
    ofs << "property float x\n";
    ofs << "property float y\n";
    ofs << "property float z\n";
    ofs << "property float nx\n";
    ofs << "property float ny\n";
    ofs << "property float nz\n";
    ofs << "property float f_dc_0\n";
    ofs << "property float f_dc_1\n";
    ofs << "property float f_dc_2\n";
    // 45 个 SH rest 系数
    for (int i = 0; i < 45; ++i) {
        ofs << "property float f_rest_" << i << "\n";
    }
    ofs << "property float opacity\n";
    ofs << "property float scale_0\n";
    ofs << "property float scale_1\n";
    ofs << "property float scale_2\n";
    ofs << "property float rot_0\n";
    ofs << "property float rot_1\n";
    ofs << "property float rot_2\n";
    ofs << "property float rot_3\n";
    ofs << "end_header\n";

    // 写入二进制顶点数据。
    // 每个 GaussianPoint 恰好 62 个 float = 248 字节，按 PLY
    // 属性顺序写入（与结构体字段顺序一致）。
    for (const auto& p : result.points) {
        // 位置 (3 个 float)
        ofs.write(reinterpret_cast<const char*>(&p.x), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.y), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.z), sizeof(float));
        // 法线 (3 个 float)
        ofs.write(reinterpret_cast<const char*>(&p.nx), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.ny), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.nz), sizeof(float));
        // SH DC (3 个 float)
        ofs.write(reinterpret_cast<const char*>(&p.f_dc_0), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.f_dc_1), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.f_dc_2), sizeof(float));
        // SH rest (45 个 float)
        ofs.write(reinterpret_cast<const char*>(p.f_rest), sizeof(float) * 45);
        // 不透明度 (1 个 float)
        ofs.write(reinterpret_cast<const char*>(&p.opacity), sizeof(float));
        // 尺度 (3 个 float)
        ofs.write(reinterpret_cast<const char*>(&p.scale_0), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.scale_1), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.scale_2), sizeof(float));
        // 旋转 (4 个 float)
        ofs.write(reinterpret_cast<const char*>(&p.rot_0), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.rot_1), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.rot_2), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.rot_3), sizeof(float));
    }
    ofs.close();

    LogSystem::Info(u8"PLY 文件已保存至: " + filePath);
    LogSystem::Info(u8"  顶点数: " + std::to_string(vertexCount));
    LogSystem::Info(u8"  文件大小: " + FormatFileSize(vertexCount * 62 * sizeof(float)));
    return true;
}

bool ProjectIO::SavePlyPlaceholder(const std::string& filePath) {
    std::ofstream ofs(filePath, std::ios::binary);
    if (!ofs.is_open()) {
        LogSystem::Error(u8"无法打开 PLY 文件进行写入: " + filePath);
        return false;
    }

    ofs << "ply\n";
    ofs << "format binary_little_endian 1.0\n";
    ofs << "comment 3DGS placeholder (no render data)\n";
    ofs << "element vertex 0\n";
    ofs << "property float x\n";
    ofs << "property float y\n";
    ofs << "property float z\n";
    ofs << "property float nx\n";
    ofs << "property float ny\n";
    ofs << "property float nz\n";
    ofs << "property float f_dc_0\n";
    ofs << "property float f_dc_1\n";
    ofs << "property float f_dc_2\n";
    for (int i = 0; i < 45; ++i) {
        ofs << "property float f_rest_" << i << "\n";
    }
    ofs << "property float opacity\n";
    ofs << "property float scale_0\n";
    ofs << "property float scale_1\n";
    ofs << "property float scale_2\n";
    ofs << "property float rot_0\n";
    ofs << "property float rot_1\n";
    ofs << "property float rot_2\n";
    ofs << "property float rot_3\n";
    ofs << "end_header\n";
    ofs.close();

    LogSystem::Info(u8"PLY 占位文件已保存至: " + filePath);
    LogSystem::Warn(u8"当前为占位文件，包含 0 个顶点 (未运行渲染)");
    return true;
}

#include "project_io.h"
#include "log_system.h"
#include <fstream>
#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <algorithm>
#include <cstring>

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

std::string ProjectIO::Trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

std::string ProjectIO::ExtractJsonString(const std::string& json, const std::string& key) {
    // Simple JSON string extractor: find "key" : "value"
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

std::string ProjectIO::FormatFileSize(size_t bytes) {
    if (bytes < 1024) return std::to_string(bytes) + " B";
    if (bytes < 1024 * 1024) return std::to_string(bytes / 1024) + " KB";
    if (bytes < (size_t)1024 * 1024 * 1024) return std::to_string(bytes / (1024 * 1024)) + " MB";
    return std::to_string(bytes / ((size_t)1024 * 1024 * 1024)) + " GB";
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

    // Calculate total size
    size_t totalSize = 0;
    for (const auto& img : images) totalSize += img.fileSize;

    ofs << "{\n";
    ofs << "  \"version\": \"1.0\",\n";

    // Project info
    ofs << "  \"project\": {\n";
    ofs << "    \"name\": \"" << JsonEscape(config.projectName) << "\",\n";
    ofs << "    \"created_time\": \"" << config.createdTime << "\",\n";
    ofs << "    \"modified_time\": \"" << config.modifiedTime << "\"\n";
    ofs << "  },\n";

    // Images array
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

    // Output config
    ofs << "  \"output\": {\n";
    ofs << "    \"path\": \"" << JsonEscape(config.outputPath) << "\",\n";
    ofs << "    \"ply_path\": \"" << JsonEscape(config.plyOutputPath) << "\",\n";
    ofs << "    \"format\": \"" << JsonEscape(config.outputFormat) << "\"\n";
    ofs << "  },\n";

    // Statistics
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

    // Read entire file
    std::stringstream ss;
    ss << ifs.rdbuf();
    std::string json = ss.str();
    ifs.close();

    // Extract project metadata
    config.projectName  = ExtractJsonString(json, "name");
    config.createdTime  = ExtractJsonString(json, "created_time");
    config.modifiedTime = ExtractJsonString(json, "modified_time");
    config.outputPath   = ExtractJsonString(json, "path");
    config.plyOutputPath = ExtractJsonString(json, "ply_path");
    config.outputFormat  = ExtractJsonString(json, "format");

    if (config.projectName.empty()) {
        config.projectName = "Loaded Project";
    }

    // Extract all file_path values from images array
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

    // Find all "file_path": "..." occurrences within the images array
    int loadedCount = 0;
    size_t pos = arrayStart;
    while (pos < arrayEnd) {
        std::string path = ExtractJsonString(json.substr(pos, arrayEnd - pos), "file_path");
        if (path.empty()) break;
        imageManager.AddImage(path);
        loadedCount++;
        // Move past this occurrence
        size_t next = json.find("\"file_path\"", pos);
        if (next == std::string::npos) break;
        pos = next + 11;
    }

    LogSystem::Info(u8"项目已加载: " + config.projectName + u8" (" +
                    std::to_string(loadedCount) + u8" 张图片)");
    return true;
}

bool ProjectIO::SavePly(const std::string& filePath, const RenderResult& result) {
    std::ofstream ofs(filePath, std::ios::binary);
    if (!ofs.is_open()) {
        LogSystem::Error(u8"无法打开 PLY 文件进行写入: " + filePath);
        return false;
    }

    size_t vertexCount = result.points.size();

    // PLY header - binary_little_endian format
    // Standard 3DGS PLY: 62 attributes (position, normal, SH, opacity, scale, rotation)
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
    // 45 SH rest coefficients
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

    // Write binary vertex data
    // Each GaussianPoint is exactly 62 floats = 248 bytes
    for (const auto& p : result.points) {
        // Position (3 floats)
        ofs.write(reinterpret_cast<const char*>(&p.x), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.y), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.z), sizeof(float));
        // Normal (3 floats)
        ofs.write(reinterpret_cast<const char*>(&p.nx), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.ny), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.nz), sizeof(float));
        // SH DC (3 floats)
        ofs.write(reinterpret_cast<const char*>(&p.f_dc_0), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.f_dc_1), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.f_dc_2), sizeof(float));
        // SH rest (45 floats)
        ofs.write(reinterpret_cast<const char*>(p.f_rest), sizeof(float) * 45);
        // Opacity (1 float)
        ofs.write(reinterpret_cast<const char*>(&p.opacity), sizeof(float));
        // Scale (3 floats)
        ofs.write(reinterpret_cast<const char*>(&p.scale_0), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.scale_1), sizeof(float));
        ofs.write(reinterpret_cast<const char*>(&p.scale_2), sizeof(float));
        // Rotation (4 floats)
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

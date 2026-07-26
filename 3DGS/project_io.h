#pragma once
#include <string>
#include <vector>
#include "image_manager.h"
#include "pipeline.h"

struct ProjectConfig {
    std::string projectName     = "My 3DGS Project";
    std::string createdTime;
    std::string modifiedTime;
    std::string outputPath       = "";
    std::string plyOutputPath    = "";
    std::string outputFormat     = "ply";
};

class ProjectIO {
public:
    // Export project metadata as JSON
    static bool SaveProject(
        const std::string& filePath,
        const ProjectConfig& config,
        const std::vector<ImageEntry>& images
    );

    // Load project metadata from JSON (restores image list to ImageManager)
    static bool LoadProject(
        const std::string& filePath,
        ProjectConfig& config,
        ImageManager& imageManager
    );

    // Export 3DGS point cloud as PLY with real Gaussian point data
    static bool SavePly(const std::string& filePath, const RenderResult& result);

    // Legacy placeholder PLY export (0 vertices)
    static bool SavePlyPlaceholder(const std::string& filePath);

    static std::string GetCurrentTimeISO8601();
    static std::string FormatFileSize(size_t bytes);

private:
    static std::string JsonEscape(const std::string& raw);
    static std::string JsonUnescape(const std::string& raw);
    static std::string Trim(const std::string& s);
    static std::string ExtractJsonString(const std::string& json, const std::string& key);
};

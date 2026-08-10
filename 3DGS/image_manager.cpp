// image_manager.cpp - 图片加载与纹理管理的实现
//
// 公共 API 和线程安全说明见 image_manager.h。
//
// 缩略图创建流程:
//   1. 用 stb_image 解码图片（全分辨率）
//   2. 将最长边缩小到最大 512px（最近邻采样）
//   3. 转换为 RGBA 格式
//   4. 上传为 OpenGL 纹理（线性过滤，边缘钳制）
//

// 启用 stb_image 的 Windows UTF-8 路径支持。
// 必须在 #include "stb_image.h" 之前定义，否则中文路径无法正确加载。
#define STBI_WINDOWS_UTF8
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

// 在 OpenGL 之前包含 Windows 头文件，以避免 APIENTRY 冲突。
// 同时取消 LoadImage 宏定义，避免与 ImageManager::LoadImage 冲突。
#include <windows.h>
#undef LoadImage
#include <GL/gl.h>

#ifndef GL_CLAMP_TO_EDGE
#define GL_CLAMP_TO_EDGE 0x812F
#endif

#include "image_manager.h"
#include "log_system.h"

// 缩略图纹理的最大尺寸（最长边）。
// 更大的图片会缩小到此尺寸以实现高效的 UI 渲染。
static constexpr int MAX_THUMBNAIL_SIZE = 512;

void ImageManager::AddImage(const std::string& filePath) {
    // 去重：如果已导入则跳过
    for (const auto& img : m_Images) {
        if (img.filePath == filePath) {
            LogSystem::Warn(u8"图片已导入: " + filePath);
            return;
        }
    }

    ImageEntry entry;
    entry.filePath = filePath;
    // 使用 u8path 正确处理 UTF-8 编码的路径（中文路径等）
    auto p = std::filesystem::u8path(filePath);
    entry.fileName = p.filename().string();
    entry.fileExt  = p.extension().string();

    try {
        entry.fileSize = std::filesystem::file_size(p);
    } catch (const std::exception& e) {
        LogSystem::Warn(u8"无法获取文件大小: " + entry.fileName + " (" + e.what() + ")");
        entry.fileSize = 0;
    }

    if (LoadImage(entry)) {
        m_Images.push_back(std::move(entry));
        LogSystem::Info(u8"已导入: " + m_Images.back().fileName +
            " (" + std::to_string(m_Images.back().width) + "x" + std::to_string(m_Images.back().height) + ")");
    } else {
        LogSystem::Error(u8"图片加载失败: " + entry.fileName);
    }
}

void ImageManager::AddImages(const std::vector<std::string>& filePaths) {
    for (const auto& path : filePaths) {
        AddImage(path);
    }
}

void ImageManager::RemoveImage(size_t index) {
    if (index >= m_Images.size()) return;
    if (m_Images[index].textureLoaded) {
        glDeleteTextures(1, &m_Images[index].textureId);
    }
    std::string name = m_Images[index].fileName;
    m_Images.erase(m_Images.begin() + index);
    LogSystem::Info(u8"已移除: " + name);
}

void ImageManager::ClearAll() {
    ReleaseTextures();
    m_Images.clear();
    LogSystem::Info(u8"已清空所有图片");
}

const std::vector<ImageEntry>& ImageManager::GetImages() const {
    return m_Images;
}

size_t ImageManager::GetCount() const {
    return m_Images.size();
}

void ImageManager::ReleaseTextures() {
    for (auto& img : m_Images) {
        if (img.textureLoaded) {
            glDeleteTextures(1, &img.textureId);
            img.textureLoaded = false;
        }
    }
}

ImageManager::~ImageManager() {
    ReleaseTextures();
}

bool ImageManager::LoadImage(ImageEntry& entry) {
    int w, h, ch;
    unsigned char* data = stbi_load(entry.filePath.c_str(), &w, &h, &ch, 0);
    if (!data) {
        LogSystem::Error(u8"加载失败: " + entry.fileName + " (" + stbi_failure_reason() + ")");
        return false;
    }

    entry.width    = w;
    entry.height   = h;
    entry.channels = ch;

    // 将最长边缩小到最大 512px 以便上传纹理
    int texW = w, texH = h;
    if (w > MAX_THUMBNAIL_SIZE || h > MAX_THUMBNAIL_SIZE) {
        float scale = (float)MAX_THUMBNAIL_SIZE / (float)(w > h ? w : h);
        texW = (int)(w * scale);
        texH = (int)(h * scale);
    }

    // 最近邻采样缩小到 RGBA
    unsigned char* rgba = (unsigned char*)malloc(texW * texH * 4);
    if (!rgba) {
        stbi_image_free(data);
        LogSystem::Error(u8"内存不足，无法加载: " + entry.fileName);
        return false;
    }

    for (int y = 0; y < texH; y++) {
        for (int x = 0; x < texW; x++) {
            int srcX = (int)(x * (float)w / texW);
            int srcY = (int)(y * (float)h / texH);
            srcX = (srcX < w) ? srcX : w - 1;
            srcY = (srcY < h) ? srcY : h - 1;
            int si = (srcY * w + srcX) * ch;
            int di = (y * texW + x) * 4;
            rgba[di + 0] = data[si + 0];
            rgba[di + 1] = data[si + 1];
            rgba[di + 2] = data[si + 2];
            rgba[di + 3] = (ch >= 4) ? data[si + 3] : 255;
        }
    }
    stbi_image_free(data);

    // 上传到 OpenGL
    GLuint texId;
    glGenTextures(1, &texId);
    glBindTexture(GL_TEXTURE_2D, texId);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, texW, texH, 0, GL_RGBA, GL_UNSIGNED_BYTE, rgba);
    glBindTexture(GL_TEXTURE_2D, 0);
    free(rgba);

    entry.textureId = texId;
    entry.textureLoaded = true;
    return true;
}
